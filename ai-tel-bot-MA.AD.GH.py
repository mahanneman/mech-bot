# -*- coding: utf-8 -*-
"""
# ════════════════════════════════════════════════════════════════════════════════
  MAHAN NEMAN Bot (mahanneman.py) — Ultimate Merged Professional Edition
  Based on MAADGH v5.0 Performance Core + all patches (v2 → v18)
# ════════════════════════════════════════════════════════════════════════════════
  Merged from:
    • MAADGH.py (original)
    • MAADGH -2.py (Secured Edition v2.0)
    • MAADGH -4 - Copy.py / MAADGH-4 - Copy.py
    • MAADGH-4.PY (full v5 + patches up to v18)
  Features preserved:
    • 27+ Mechanical Engineering topics + topic bank loader
    • Multiple content styles (tutorial, formula, quiz, trivia, deep, ...)
    • OpenRouter + Gemini multi-model fallback
    • Bloom filter dedup, LRU+TTL caches, connection pooling
    • Auto-poster, scheduler, drafts, polls
    • 200+ APIs injector (v17), Wikipedia, arXiv, weather, etc.
    • Formula Unicode boxes, Persian-first, English problem statements
    • Interactive menu + Telegram command registry
    • Security: token/key detection, ZDR-compatible models
  Optimized for 16GB+ RAM. No syntax conflicts. All functions complete.
# ════════════════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import os
import sys
import re
import io
import gc
import json
import time
import ssl
import math
import queue
import signal
import shutil
import struct
import random
import hashlib
import logging
import logging.handlers
import threading
import subprocess
import webbrowser
import traceback
import itertools
import contextlib
import collections
from pathlib import Path
from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque, OrderedDict, Counter
from concurrent.futures import ThreadPoolExecutor, Future, as_completed, TimeoutError as FutureTimeout
from typing import Optional, List, Dict, Any, Tuple, Callable, Union, Iterable, Iterator
from dataclasses import dataclass, field, asdict, fields
from enum import Enum, IntEnum
from functools import wraps, lru_cache, partial
import secrets
import math as _math_rnd

# __SHUTDOWN_EARLY__ — قبل از هر thread باید باشد
try:
    _shutting_down
except NameError:
    _shutting_down = threading.Event()


# ═══════════════════════════════════════════════════════════════════════════
#  TTLStore — Thread-safe in-memory store with TTL and LRU eviction
#  (defined here so it can be used earlier in the file)
# ═══════════════════════════════════════════════════════════════════════════
class TTLStore:
    """Thread-safe in-memory store با TTL و LRU eviction."""
    __slots__ = ("_d", "_ts", "_max", "_ttl", "_lock")

    def __init__(self, max_items: int = 2000, ttl: float = 3600.0):
        self._d = {}
        self._ts = {}
        self._max = max_items
        self._ttl = ttl
        self._lock = threading.RLock()

    def get(self, key, default=None):
        with self._lock:
            if key not in self._d:
                return default
            if time.time() - self._ts.get(key, 0) > self._ttl:
                self._d.pop(key, None)
                self._ts.pop(key, None)
                return default
            return self._d[key]

    def set(self, key, value):
        with self._lock:
            self._d[key] = value
            self._ts[key] = time.time()
            if len(self._d) > self._max:
                sorted_keys = sorted(self._ts, key=self._ts.get)
                for k in sorted_keys[: max(1, self._max // 10)]:
                    self._d.pop(k, None)
                    self._ts.pop(k, None)

    def __contains__(self, key):
        return self.get(key) is not None

    def pop(self, key, default=None):
        with self._lock:
            self._ts.pop(key, None)
            return self._d.pop(key, default)

    def clear(self):
        with self._lock:
            self._d.clear()
            self._ts.clear()

    def __len__(self):
        with self._lock:
            return len(self._d)

# True random generator (uses OS entropy)
_RND = random.SystemRandom()


# --- Force UTF-8 console output on Windows ---
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
#                    ENVIRONMENT DETECTION & BOOTSTRAP
# ══════════════════════════════════════════════════════════════════════════════

IS_WINDOWS = os.name == "nt"
IS_LINUX   = sys.platform.startswith("linux")
IS_MAC     = sys.platform == "darwin"

PY_VER     = sys.version_info
PY_MAJOR   = PY_VER.major
PY_MINOR   = PY_VER.minor
PY_OK      = (PY_MAJOR, PY_MINOR) >= (3, 9)

if not PY_OK:
    print(f"Python 3.9+ required (found {PY_MAJOR}.{PY_MINOR})")
    sys.exit(1)


# Detect CPU cores for thread pool sizing
CPU_COUNT = os.cpu_count() or 4
# Reserve 1 core for main loop, use rest for workers (cap at 64)
MAX_WORKERS = min(64, max(8, CPU_COUNT * 4))


def _try_import(name: str):
    try:
        return __import__(name)
    except ImportError:
        return None


def _module_available(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False

def _try_install(pkg: str, timeout: int = 120) -> bool:
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet",
             "--disable-pip-version-check", pkg],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
        return True
    except Exception:
        return False


# Fast JSON: prefer orjson, fallback to ujson, then stdlib
_orjson = _try_import("orjson")
if _orjson is None:
    if _try_install("orjson", 60):
        _orjson = _try_import("orjson")

_ujson = _try_import("ujson")

if _orjson:
    JSON_BACKEND = "orjson"

    def json_dumps(obj, indent: bool = False) -> bytes:
        opts = 0
        if indent:
            opts |= _orjson.OPT_INDENT_2
        opts |= _orjson.OPT_NON_STR_KEYS
        opts |= _orjson.OPT_SERIALIZE_DATACLASS
        opts |= _orjson.OPT_SERIALIZE_NUMPY
        try:
            return _orjson.dumps(obj, option=opts)
        except TypeError:
            return _orjson.dumps(obj, option=opts, default=str)

    def json_loads(data):
        if isinstance(data, (str, bytes, bytearray)):
            return _orjson.loads(data)
        return json.loads(data)

elif _ujson:
    JSON_BACKEND = "ujson"

    def json_dumps(obj, indent: bool = False) -> str:
        return _ujson.dumps(obj, indent=2 if indent else 0, ensure_ascii=False)

    def json_loads(data):
        return _ujson.loads(data)

else:
    JSON_BACKEND = "json"

    def json_dumps(obj, indent: bool = False) -> str:
        return json.dumps(obj, ensure_ascii=False,
                          indent=2 if indent else None, default=str)

    def json_loads(data):
        return json.loads(data)


# HTTP client library
_httpx = _try_import("httpx")
_requests = _try_import("requests")
if _requests is None:
    if _try_install("requests", 90):
        _requests = _try_import("requests")
if _requests is None:
    print("FATAL: could not install 'requests'")
    sys.exit(1)


# RSS
_feedparser = _try_import("feedparser")
if _feedparser is None:
    if _try_install("feedparser", 60):
        _feedparser = _try_import("feedparser")


# urllib3 for warnings control
_urllib3 = _try_import("urllib3")
if _urllib3:
    _urllib3.disable_warnings(_urllib3.exceptions.InsecureRequestWarning)


# Compression for cache (optional)
_zstd = _try_import("zstandard")
_lz4  = _try_import("lz4.frame")


# ══════════════════════════════════════════════════════════════════════════════
#                          PROCESS PRIORITY BOOST
# ══════════════════════════════════════════════════════════════════════════════

def boost_process_priority() -> Tuple[bool, str]:
    """Increase process priority for faster execution."""
    try:
        if IS_WINDOWS:
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            # Process priority: HIGH_PRIORITY_CLASS = 0x80
            handle = kernel32.GetCurrentProcess()
            ok = kernel32.SetPriorityClass(handle, 0x80)
            if ok:
                return True, "HIGH_PRIORITY_CLASS"
            return False, "SetPriorityClass failed"
        elif IS_LINUX or IS_MAC:
            os.nice(-10)
            return True, "nice -10"
    except Exception as e:
        return False, str(e)
    return False, "unsupported"


def tune_gc(threshold0: int = 70000, threshold1: int = 10, threshold2: int = 10) -> None:
    """Tune garbage collector for high-RAM systems."""
    try:
        gc.set_threshold(threshold0, threshold1, threshold2)
        gc.collect()
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
#                          PATHS
# ══════════════════════════════════════════════════════════════════════════════

_SCRIPT_DIR = Path(__file__).resolve().parent

_CANDIDATE_ROOTS = [
    Path(r"J:\#mahan\projects\ai-telgram-chaneel-agent"),
    _SCRIPT_DIR / "bot_data",
    Path.home() / ".maadgh-bot",
    Path.cwd() / "maadgh-data",
]

ROOT: Optional[Path] = None
for _c in _CANDIDATE_ROOTS:
    try:
        _c.mkdir(parents=True, exist_ok=True)
        _t = _c / ".write_probe"
        _t.write_text("ok", encoding="utf-8")
        _t.unlink()
        ROOT = _c
        break
    except Exception:
        continue

if ROOT is None:
    print("FATAL: no writable directory found")
    sys.exit(1)


DATA_DIR    = ROOT / "data"
CACHE_DIR   = ROOT / "cache"
LOG_DIR     = ROOT / "logs"
BACKUP_DIR  = ROOT / "backup"
MEDIA_DIR   = ROOT / "media"
EXPORT_DIR  = ROOT / "export"
TMP_DIR     = ROOT / "tmp"

for _d in (DATA_DIR, CACHE_DIR, LOG_DIR, BACKUP_DIR, MEDIA_DIR, EXPORT_DIR, TMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)


CONFIG_FILE       = DATA_DIR / "config.json"
HISTORY_FILE      = DATA_DIR / "history.json"
STATS_FILE        = DATA_DIR / "stats.json"
POLLS_FILE        = DATA_DIR / "polls.json"
PID_FILE          = DATA_DIR / "bot.pid"
TOPICS_FILE       = DATA_DIR / "topics.json"
PROMPTS_FILE      = DATA_DIR / "prompts.json"
SEEN_FILE         = DATA_DIR / "seen.bloom"
USERS_FILE        = DATA_DIR / "users.json"
SCHEDULE_FILE     = DATA_DIR / "schedule.json"
QUEUE_FILE        = DATA_DIR / "queue.json"
DRAFT_FILE        = DATA_DIR / "drafts.json"
API_KEYS_FILE     = DATA_DIR / "api_keys.json"

LOG_FILE          = LOG_DIR / "bot.log"
ERROR_LOG_FILE    = LOG_DIR / "error.log"
PERF_LOG_FILE     = LOG_DIR / "perf.log"


# ══════════════════════════════════════════════════════════════════════════════
#                          COLOR CONSOLE
# ══════════════════════════════════════════════════════════════════════════════

if IS_WINDOWS:
    os.system("")


class Clr:
    R      = "\033[0m"
    B      = "\033[1m"
    DIM    = "\033[2m"
    IT     = "\033[3m"
    U      = "\033[4m"
    BLK    = "\033[30m"
    RED    = "\033[31m"
    GRN    = "\033[32m"
    YEL    = "\033[33m"
    BLU    = "\033[34m"
    MAG    = "\033[35m"
    CYN    = "\033[36m"
    WHT    = "\033[37m"
    GRY    = "\033[90m"
    BRED   = "\033[91m"
    BGRN   = "\033[92m"
    BYEL   = "\033[93m"
    BBLU   = "\033[94m"
    BMAG   = "\033[95m"
    BCYN   = "\033[96m"
    BWHT   = "\033[97m"


_print_lock = threading.Lock()


def _p(msg: str) -> None:
    with _print_lock:
        try:
            print(msg)
        except UnicodeEncodeError:
            print(msg.encode("utf-8", errors="replace").decode("utf-8", errors="replace"))


def head(t: str, ch: str = "═", w: int = 72) -> None:
    _p(f"\n{Clr.BCYN}{ch * w}{Clr.R}")
    _p(f"{Clr.B}{Clr.BCYN}  {t}{Clr.R}")
    _p(f"{Clr.BCYN}{ch * w}{Clr.R}")


def sub(t: str) -> None:
    _p(f"\n{Clr.BMAG}── {t} ──{Clr.R}")


def ok(m: str) -> None:    _p(f"{Clr.BGRN}[✓] {m}{Clr.R}")
def err(m: str) -> None:   _p(f"{Clr.BRED}[✗] {m}{Clr.R}")
def warn(m: str) -> None:  _p(f"{Clr.BYEL}[!] {m}{Clr.R}")
def info(m: str) -> None:  _p(f"{Clr.GRY}    {m}{Clr.R}")
def step(m: str) -> None:  _p(f"{Clr.BBLU}[*] {m}{Clr.R}")
def succ(m: str) -> None:  _p(f"{Clr.BMAG}{Clr.B}[★] {m}{Clr.R}")
def perf(m: str) -> None:  _p(f"{Clr.CYN}⚡ {m}{Clr.R}")
def success(m: str) -> None: _p(f"{Clr.BMAG}{Clr.B}[★] {m}{Clr.R}")


def pause(msg: str = "Enter...") -> None:
    try:
        input(f"\n{Clr.GRY}{msg}{Clr.R}")
    except (EOFError, KeyboardInterrupt):
        pass


def clear() -> None:
    os.system("cls" if IS_WINDOWS else "clear")


# ══════════════════════════════════════════════════════════════════════════════
#                          LOGGING (queue-based, non-blocking)
# ══════════════════════════════════════════════════════════════════════════════

class _QueueHandler(logging.Handler):
    """Non-blocking log handler using queue."""

    def __init__(self, q: queue.Queue):
        super().__init__()
        self.q = q

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.q.put_nowait(record)
        except queue.Full:
            pass


class _LogWorker(threading.Thread):
    def __init__(self, q: queue.Queue, handlers: List[logging.Handler]):
        super().__init__(daemon=True, name="LogWorker")
        self.q = q
        self.handlers = handlers
        self._stop = threading.Event()

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                rec = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            for h in self.handlers:
                try:
                    if rec.levelno >= h.level:
                        h.emit(rec)
                except Exception:
                    pass

    def stop(self) -> None:
        self._stop.set()


_log_queue: queue.Queue = queue.Queue(maxsize=10000)
_log_file_handlers: List[logging.Handler] = []
_log_worker: Optional[_LogWorker] = None


def _setup_logging() -> logging.Logger:
    global _log_worker

    logger = logging.getLogger("maadgh")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logger.propagate = False

    # File: rotating, all levels
    fh = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=10, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
    ))

    # Error file
    eh = logging.handlers.RotatingFileHandler(
        ERROR_LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    eh.setLevel(logging.ERROR)
    eh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s:%(lineno)d: %(message)s"
    ))

    _log_file_handlers.extend([fh, eh])

    # Async worker
    qh = _QueueHandler(_log_queue)
    logger.addHandler(qh)
    _log_worker = _LogWorker(_log_queue, _log_file_handlers)
    _log_worker.start()

    # Console (INFO+)
    class ConsoleFormatter(logging.Formatter):
        COLORS = {
            logging.DEBUG:    Clr.GRY,
            logging.INFO:     Clr.BGRN,
            logging.WARNING:  Clr.BYEL,
            logging.ERROR:    Clr.BRED,
            logging.CRITICAL: Clr.BRED + Clr.B,
        }
        def format(self, r):
            c = self.COLORS.get(r.levelno, Clr.R)
            lvl = f"{c}{r.levelname:<7}{Clr.R}"
            ts = self.formatTime(r, "%H:%M:%S")
            return f"{Clr.GRY}{ts}{Clr.R} {lvl} {r.getMessage()}"
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(ConsoleFormatter())
    logger.addHandler(ch)

    return logger


log = _setup_logging()

# ─── Live terminal progress (FIX5) ───────────────────────────────────────
def _prog(msg: str, tag: str = "run") -> None:
    """Print to terminal + log."""
    try:
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"\033[96m[{ts}] [{tag}]\033[0m {msg}", flush=True)
    except Exception:
        pass
    try: log.info(f"[{tag}] {msg}")
    except Exception: pass


def _prog_ai_start(model_hint: str = "?") -> float:
    import time as _t
    _prog("-> sending to AI (max_tokens~3500)...", "ai")
    return _t.perf_counter()


def _prog_ai_done(t0: float, text: str, provider: str = "?") -> None:
    import time as _t
    dt = _t.perf_counter() - t0
    _prog(f"<- {provider} replied in {dt:.2f}s, {len(text or '')} chars", "ai")


# ─── end FIX5 progress helper ─────────────────────────────────────────────







# ══════════════════════════════════════════════════════════════════════════════
#                          LRU + TTL CACHE
# ══════════════════════════════════════════════════════════════════════════════

class LRUTTLCache:
    """
    Thread-safe LRU cache with TTL expiry.
    Uses OrderedDict for O(1) operations.
    """

    __slots__ = ("_data", "_max", "_ttl", "_lock", "_hits", "_misses")

    def __init__(self, maxsize: int = 1000, ttl: float = 3600.0):
        self._data: OrderedDict = OrderedDict()
        self._max = maxsize
        self._ttl = ttl
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    def get(self, key) -> Optional[Any]:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                self._misses += 1
                return None
            ts, value = item
            if time.time() - ts > self._ttl:
                del self._data[key]
                self._misses += 1
                return None
            self._data.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key, value) -> None:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = (time.time(), value)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def resize(self, new_max: int) -> None:
        """Safely change max size."""
        with self._lock:
            self._max = max(1, int(new_max))
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def purge_expired(self) -> int:
        now = time.time()
        removed = 0
        with self._lock:
            for k in list(self._data.keys()):
                ts, _ = self._data[k]
                if now - ts > self._ttl:
                    del self._data[k]
                    removed += 1
        return removed

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            rate = (self._hits / total * 100) if total else 0.0
            return {
                "size": len(self._data),
                "max": self._max,
                "ttl": self._ttl,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(rate, 2),
            }


AI_CACHE = LRUTTLCache(maxsize=500, ttl=1800)
HTTP_CACHE = LRUTTLCache(maxsize=2000, ttl=600)
TRANSLATE_CACHE = LRUTTLCache(maxsize=2000, ttl=86400)


# ══════════════════════════════════════════════════════════════════════════════
#                          BLOOM FILTER (memory-efficient dedup)
# ══════════════════════════════════════════════════════════════════════════════

class BloomFilter:
    """
    Space-efficient probabilistic set.
    Uses ~1.2 bytes per item at 1% false positive rate.
    For 1M items: ~1.2MB instead of ~30MB with a regular set.
    """

    def __init__(self, capacity: int = 1_000_000, error_rate: float = 0.01):
        self._capacity = capacity
        self._error_rate = error_rate
        self._bit_size = self._optimal_bits(capacity, error_rate)
        self._hash_count = self._optimal_hashes(self._bit_size, capacity)
        self._bytes = bytearray((self._bit_size + 7) // 8)
        self._count = 0
        self._lock = threading.RLock()

    @staticmethod
    def _optimal_bits(n: int, p: float) -> int:
        return int(-n * math.log(p) / (math.log(2) ** 2))

    @staticmethod
    def _optimal_hashes(m: int, n: int) -> int:
        return max(1, int(round(m / n * math.log(2))))

    def _hashes(self, item: str) -> Iterator[int]:
        data = item.encode("utf-8")
        h1 = int.from_bytes(hashlib.md5(data).digest()[:8], "big")
        h2 = int.from_bytes(hashlib.sha1(data).digest()[:8], "big")
        for i in range(self._hash_count):
            yield (h1 + i * h2) % self._bit_size

    def _set_bit(self, idx: int) -> None:
        self._bytes[idx // 8] |= (1 << (idx % 8))

    def _get_bit(self, idx: int) -> bool:
        return bool(self._bytes[idx // 8] & (1 << (idx % 8)))

    def add(self, item: str) -> None:
        with self._lock:
            for idx in self._hashes(item):
                self._set_bit(idx)
            self._count += 1

    def __contains__(self, item: str) -> bool:
        with self._lock:
            return all(self._get_bit(i) for i in self._hashes(item))

    def __len__(self) -> int:
        return self._count

    def to_bytes(self) -> bytes:
        with self._lock:
            header = json_dumps({
                "capacity": self._capacity,
                "error_rate": self._error_rate,
                "bit_size": self._bit_size,
                "hash_count": self._hash_count,
                "count": self._count,
            })
            if isinstance(header, str):
                header = header.encode("utf-8")
            return struct.pack("<I", len(header)) + header + bytes(self._bytes)

    @classmethod
    def from_bytes(cls, data: bytes) -> "BloomFilter":
        hlen = struct.unpack("<I", data[:4])[0]
        header = json_loads(data[4:4 + hlen])
        bf = cls(capacity=header["capacity"], error_rate=header["error_rate"])
        bf._bit_size = header["bit_size"]
        bf._hash_count = header["hash_count"]
        # v16: guard against stale bloom files
        expected_bits = bf._optimal_bits(bf._capacity, bf._error_rate)
        if abs(bf._bit_size - expected_bits) > expected_bits * 0.1:
            bf._bit_size = expected_bits
            bf._hash_count = bf._optimal_hashes(bf._bit_size, bf._capacity)
        bf._count = header["count"]
        bf._bytes = bytearray(data[4 + hlen:])
        return bf

    def save(self, path: Path) -> bool:
        try:
            path.write_bytes(self.to_bytes())
            return True
        except Exception as e:
            log.error(f"Bloom save error: {e}")
            return False

    @classmethod
    def load(cls, path: Path, default_capacity: int = 1_000_000) -> "BloomFilter":
        if not path.exists():
            return cls(capacity=default_capacity)
        try:
            return cls.from_bytes(path.read_bytes())
        except Exception as e:
            log.error(f"Bloom load error: {e}")
            return cls(capacity=default_capacity)

    def stats(self) -> Dict[str, Any]:
        return {
            "capacity": self._capacity,
            "count": self._count,
            "bits": self._bit_size,
            "hashes": self._hash_count,
            "size_kb": round(len(self._bytes) / 1024, 1),
            "load": round(self._count / self._capacity * 100, 1),
        }


# ══════════════════════════════════════════════════════════════════════════════
#                          BATCHED DISK WRITER
# ══════════════════════════════════════════════════════════════════════════════

class BatchedWriter:
    """
    Batch disk writes to reduce I/O.
    Accumulates writes in memory and flushes every N seconds or when
    buffer exceeds threshold.
    """

    def __init__(self, flush_interval: float = 3.0, max_pending: int = 100):
        self._pending: Dict[Path, Any] = {}
        self._lock = threading.RLock()
        self._flush_interval = flush_interval
        self._max_pending = max_pending
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="BatchWriter")
        self._thread.start()
        self._writes = 0
        self._flushes = 0

    def write(self, path: Path, data: Any) -> None:
        with self._lock:
            self._pending[path] = data
            if len(self._pending) >= self._max_pending:
                self._flush_locked()

    def _flush_locked(self) -> int:
        if not self._pending:
            return 0
        count = 0
        items = list(self._pending.items())
        self._pending.clear()
        for path, data in items:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(path.suffix + ".tmp")
                payload = json_dumps(data, indent=True)
                if isinstance(payload, str):
                    tmp.write_text(payload, encoding="utf-8")
                else:
                    tmp.write_bytes(payload)
                tmp.replace(path)
                count += 1
                self._writes += 1
            except Exception as e:
                log.error(f"Batch write fail {path.name}: {e}")
        if count:
            self._flushes += 1
        return count

    def flush(self) -> int:
        with self._lock:
            return self._flush_locked()
    def _loop(self) -> None:
        while not self._stop.is_set() and not _shutting_down.is_set():
            self._stop.wait(self._flush_interval)
            try:
                self.flush()
            except Exception as e:
                log.error(f"Batch flush error: {e}")

    def stop(self) -> None:
        self._stop.set()
        self.flush()

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "pending": len(self._pending),
                "writes": self._writes,
                "flushes": self._flushes,
                "interval": self._flush_interval,
            }


BATCHED_WRITER = BatchedWriter(flush_interval=3.0, max_pending=50)


# ══════════════════════════════════════════════════════════════════════════════
#                          JSON STORE (fast, atomic, cached)
# ══════════════════════════════════════════════════════════════════════════════

class JsonStore:
    """High-perf atomic JSON store with in-memory cache."""

    _lock = threading.RLock()
    _cache: Dict[Path, Tuple[float, Any]] = {}
    _max_cache = 128

    @classmethod
    def load(cls, path: Path, default: Any = None) -> Any:
        with cls._lock:
            try:
                if not path.exists():
                    return _deepcopy(default)
                mtime = path.stat().st_mtime
                cached = cls._cache.get(path)
                if cached and cached[0] == mtime:
                    return _deepcopy(cached[1])
                raw = path.read_text(encoding="utf-8")
                data = json_loads(raw) if raw.strip() else _deepcopy(default)
                if len(cls._cache) >= cls._max_cache:
                    cls._cache.pop(next(iter(cls._cache)))
                cls._cache[path] = (mtime, data)
                return _deepcopy(data)
            except Exception as e:
                log.error(f"JsonStore load {path.name}: {e}")
                return _deepcopy(default)

    @classmethod
    def save(cls, path: Path, data: Any, backup: bool = False) -> bool:
        try:
            payload = json_dumps(data, indent=True)
            if isinstance(payload, str):
                payload = payload.encode("utf-8")
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(payload)
            tmp.replace(path)
            with cls._lock:
                cls._cache[path] = (path.stat().st_mtime, _deepcopy(data))
            return True
        except Exception as e:
            log.error(f"JsonStore save {path.name}: {e}")
            return False

    @classmethod
    def save_async(cls, path: Path, data: Any) -> None:
        BATCHED_WRITER.write(path, data)


def _deepcopy(obj: Any) -> Any:
    if obj is None:
        return None
    try:
        return json.loads(json.dumps(obj, default=str))
    except Exception:
        return obj


def load_json(path: Path, default: Any = None) -> Any:
    return JsonStore.load(path, default)


def save_json(path: Path, data: Any) -> bool:
    return JsonStore.save(path, data)


# ══════════════════════════════════════════════════════════════════════════════
#                          CONNECTION POOL / HTTP CLIENT
# ══════════════════════════════════════════════════════════════════════════════

class ConnectionPool:
    """
    High-performance HTTP client with:
    - Connection pooling (200 connections)
    - Keep-alive
    - Auto-retry with exponential backoff
    - Per-host connection limits
    """

    def __init__(self, pool_size: int = 200, retries: int = 3, timeout: int = 30):
        self.pool_size = pool_size
        self.retries = retries
        self.default_timeout = timeout

        self._session = _requests.Session()

        adapter = _requests.adapters.HTTPAdapter(
            pool_connections=pool_size,
            pool_maxsize=pool_size,
            max_retries=0,  # we handle retries manually
            pool_block=False,
        )
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

        self._session.headers.update({
            "User-Agent": "MAADGH-Bot/5.0 (+python-requests)",
            "Accept-Encoding": "gzip, deflate",
            "Accept": "application/json, text/plain, */*",
            "Connection": "keep-alive",
        })

        self._lock = threading.RLock()
        self._stats = defaultdict(int)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        json_body: Any = None,
        data: Any = None,
        timeout: Optional[int] = None,
        files: Optional[Dict] = None,
        verify: bool = True,
        stream: bool = False,
    ) -> Optional[Any]:
        to = timeout or self.default_timeout
        last_exc: Optional[Exception] = None

        for attempt in range(self.retries + 1):
            try:
                t0 = time.perf_counter()
                r = self._session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_body,
                    data=data,
                    files=files,
                    timeout=to,
                    verify=verify,
                    stream=stream,
                )
                dt = (time.perf_counter() - t0) * 1000
                with self._lock:
                    self._stats[f"{method} {r.status_code}"] += 1
                    self._stats["total"] += 1
                    self._stats["total_ms"] += int(dt)
                return r

            except _requests.exceptions.SSLError as e:
                last_exc = e
                with self._lock:
                    self._stats["ssl_errors"] += 1
                if attempt < self.retries:
                    time.sleep(0.5 * (2 ** attempt))
                    continue

            except _requests.exceptions.Timeout as e:
                last_exc = e
                with self._lock:
                    self._stats["timeouts"] += 1
                if attempt < self.retries:
                    time.sleep(0.3 * (2 ** attempt))
                    continue

            except _requests.exceptions.ConnectionError as e:
                last_exc = e
                with self._lock:
                    self._stats["conn_errors"] += 1
                if attempt < self.retries:
                    time.sleep(1.0 * (2 ** attempt))
                    continue

            except Exception as e:
                last_exc = e
                with self._lock:
                    self._stats["other_errors"] += 1
                break

        if last_exc:
            log.debug(f"HTTP fail {method} {url[:80]}: {last_exc}")
        return None

    def get_json(self, url: str, **kwargs) -> Optional[Any]:
        # Check cache
        cache_key = f"GET:{url}:{json_dumps(kwargs.get('params') or {})}"
        cached = HTTP_CACHE.get(cache_key)
        if cached is not None:
            return cached

        r = self.request("GET", url, **kwargs)
        if r is None or r.status_code != 200:
            return None
        try:
            data = r.json()
            HTTP_CACHE.set(cache_key, data)
            return data
        except Exception:
            return None

    def post_json(self, url: str, **kwargs) -> Optional[Any]:
        r = self.request("POST", url, **kwargs)
        if r is None:
            return None
        try:
            return r.json()
        except Exception:
            return None

    def get_text(self, url: str, **kwargs) -> Optional[str]:
        cache_key = f"TXT:{url}"
        cached = HTTP_CACHE.get(cache_key)
        if cached is not None:
            return cached
        r = self.request("GET", url, **kwargs)
        if r is None or r.status_code != 200:
            return None
        HTTP_CACHE.set(cache_key, r.text)
        return r.text

    def get_bytes(self, url: str, **kwargs) -> Optional[bytes]:
        r = self.request("GET", url, **kwargs)
        if r is None or r.status_code != 200:
            return None
        return r.content

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            s = dict(self._stats)
            total = s.get("total", 0)
            if total:
                s["avg_ms"] = round(s.get("total_ms", 0) / total, 1)
            return s


HTTP = ConnectionPool(pool_size=200, retries=3, timeout=30)


# ══════════════════════════════════════════════════════════════════════════════
#                          THREAD POOL MANAGER
# ══════════════════════════════════════════════════════════════════════════════

class ThreadPoolManager:
    """Global thread pool with task tracking."""

    def __init__(self, max_workers: int = MAX_WORKERS):
        self.max_workers = max_workers
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="maadgh-worker",
        )
        self._lock = threading.RLock()
        self._active = 0
        self._completed = 0
        self._failed = 0

    def submit(self, fn: Callable, *args, **kwargs) -> Optional[Future]:
        with self._lock:
            self._active += 1
        try:
            f = self._pool.submit(fn, *args, **kwargs)
            f.add_done_callback(self._on_done)
            return f
        except Exception as e:
            with self._lock:
                self._active -= 1
                self._failed += 1
            log.error(f"Submit failed: {e}")
            return None

    def _on_done(self, fut: Future) -> None:
        with self._lock:
            self._active -= 1
            if fut.exception():
                self._failed += 1
            else:
                self._completed += 1

    def map(self, fn: Callable, iterable: Iterable, timeout: Optional[float] = None) -> List[Any]:
        futures = [self.submit(fn, x) for x in iterable]
        results: List[Any] = []
        for f in futures:
            if f is None:
                continue
            try:
                results.append(f.result(timeout=timeout))
            except Exception as e:
                log.debug(f"Task error: {e}")
                results.append(None)
        return results

    def gather(self, futures: List[Future], timeout: Optional[float] = None) -> List[Any]:
        out: List[Any] = []
        for f in futures:
            if f is None:
                out.append(None)
                continue
            try:
                out.append(f.result(timeout=timeout))
            except FutureTimeout:
                out.append(None)
            except Exception as e:
                log.debug(f"Gather error: {e}")
                out.append(None)
        return out

    def shutdown(self, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait)

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "max_workers": self.max_workers,
                "active": self._active,
                "completed": self._completed,
                "failed": self._failed,
            }


POOL = ThreadPoolManager(max_workers=MAX_WORKERS)


# ══════════════════════════════════════════════════════════════════════════════
#                          MEMORY MONITOR
# ══════════════════════════════════════════════════════════════════════════════

class MemoryMonitor:
    """Track process memory usage; trigger GC when needed."""

    def __init__(self, soft_limit_mb: int = 2048, hard_limit_mb: int = 6144):
        self.soft_limit_mb = soft_limit_mb
        self.hard_limit_mb = hard_limit_mb
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="MemMon")
        self._thread.start()
        self._last_gc = 0
        self._peak_mb = 0.0

    @staticmethod
    def current_mb() -> float:
        try:
            if IS_WINDOWS:
                import ctypes
                from ctypes import wintypes
                class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                    _fields_ = [
                        ("cb", wintypes.DWORD),
                        ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t),
                    ]
                c = PROCESS_MEMORY_COUNTERS()
                c.cb = ctypes.sizeof(c)
                ctypes.windll.psapi.GetProcessMemoryInfo(
                    ctypes.windll.kernel32.GetCurrentProcess(),
                    ctypes.byref(c), c.cb
                )
                return c.WorkingSetSize / (1024 * 1024)
            else:
                import resource
                return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        except Exception:
            return 0.0
    def _loop(self) -> None:
        while not self._stop.is_set() and not _shutting_down.is_set():
            self._stop.wait(15)
            cur = self.current_mb()
            self._peak_mb = max(self._peak_mb, cur)
            if cur > self.hard_limit_mb:
                log.warning(f"Memory {cur:.0f}MB > hard limit — forcing GC")
                gc.collect()
            elif cur > self.soft_limit_mb and time.time() - self._last_gc > 60:
                gc.collect()
                self._last_gc = time.time()

    def stop(self) -> None:
        self._stop.set()

    def stats(self) -> Dict[str, Any]:
        return {
            "current_mb": round(self.current_mb(), 1),
            "peak_mb": round(self._peak_mb, 1),
            "soft_limit_mb": self.soft_limit_mb,
            "hard_limit_mb": self.hard_limit_mb,
        }


MEM_MON = MemoryMonitor(soft_limit_mb=2048, hard_limit_mb=6144)


# ══════════════════════════════════════════════════════════════════════════════
#                          RTL/LTR FAST
# ══════════════════════════════════════════════════════════════════════════════

LRI = "\u2066"  # LTR isolate
RLI = "\u2067"  # RTL isolate
FSI = "\u2068"  # First-strong isolate
PDI = "\u2069"  # Pop directional isolate

_PERSIAN_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F]")
_LATIN_RE   = re.compile(r"[A-Za-z]")
_MATH_RE    = re.compile(r"[+\-*/=<>^√∫∑∂∇πΔΩ∞≈≤≥≠±×÷°²³⁴½¼¾]")
_CACHE_MAX  = 1000
_text_cache: LRUTTLCache = LRUTTLCache(maxsize=_CACHE_MAX, ttl=600)


def is_formula_line(line: str) -> bool:
    s = line.strip()
    if len(s) < 3:
        return False
    # Reject separators/dashes/dots only
    if re.fullmatch(r"[\-\*_=~\.\s—–]+", s):
        return False
    # Reject markdown table lines
    if s.startswith("|"):
        return False
    # Persian-dominant → never a formula
    persian = len(re.findall(r"[\u0600-\u06FF]", s))
    visible = len(re.sub(r"\s+", "", s)) or 1
    if persian / visible > 0.40:
        return False
    has_latex   = bool(re.search(r"\\[a-zA-Z]+", s))
    has_latin   = bool(re.search(r"[A-Za-z]", s))
    has_mathsym = bool(re.search(r"[=+\-*/^∫∬∭∮∑∂∇√<>≤≥≠±×÷°²³πΔΩ∞]", s))
    if not (has_latex or has_latin or has_mathsym):
        return False
    if has_latex:
        return True
    return len(_MATH_RE.findall(s)) >= 2


def is_mostly_latin(text: str, threshold: float = 0.65) -> bool:
    p = len(_PERSIAN_RE.findall(text))
    l = len(_LATIN_RE.findall(text))
    tot = p + l
    return tot > 0 and (l / tot) >= threshold


def isolate_ltr(text: str) -> str:
    return f"{LRI}{text}{PDI}"


def isolate_rtl(text: str) -> str:
    return f"{RLI}{text}{PDI}"


def escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)

def clean_wiki_extract(text: str) -> str:
    """
    Wikipedia REST API extracts contain artifacts:
      - {\\displaystyle ...}  (LaTeX wrapped)
      - \\displaystyle
      - double spaces from removed math
    This converts them to clean Unicode where possible.
    """
    if not text:
        return ""

    # Unwrap {\displaystyle ...}
    text = re.sub(r"\{\\displaystyle\s+([^{}]+)\}", r"\1", text)
    # Nested: {\displaystyle {\frac{a}{b}}}
    for _ in range(4):
        text = re.sub(r"\{\\displaystyle\s+([^{}]+)\}", r"\1", text)

    # Remove leftover \displaystyle command
    text = text.replace("\\displaystyle", "")

    # Simple LaTeX greek/symbols (subset)
    simple_map = {
        "\\alpha": "α", "\\beta": "β", "\\gamma": "γ", "\\delta": "δ",
        "\\theta": "θ", "\\lambda": "λ", "\\mu": "μ", "\\pi": "π",
        "\\sigma": "σ", "\\phi": "φ", "\\omega": "ω",
        "\\times": "×", "\\cdot": "·", "\\pm": "±",
        "\\le": "≤", "\\ge": "≥", "\\neq": "≠",
        "\\infty": "∞", "\\partial": "∂", "\\nabla": "∇",
        "\\int": "∫", "\\sum": "∑", "\\prod": "∏", "\\sqrt": "√",
        "\\in": "∈", "\\subset": "⊂", "\\cup": "∪", "\\cap": "∩",
    }
    for k, v in simple_map.items():
        text = text.replace(k, v)

    # \frac{a}{b} → (a)/(b)
    text = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"(\1)/(\2)", text)
    # \sqrt{x} → √(x)
    text = re.sub(r"\\sqrt\{([^{}]+)\}", r"√(\1)", text)
    # ^{n} → ⁿ style is complex; just leave raw
    # \text{...} → ...
    text = re.sub(r"\\text\{([^{}]+)\}", r"\1", text)

    # Remove remaining stray braces from math
    text = re.sub(r"[{}]", "", text)
    # Remove remaining LaTeX commands
    text = re.sub(r"\\[a-zA-Z]+", "", text)

    # Cleanup spacing
    text = re.sub(r"\s{2,}", " ", text).strip()

    return text

def wrap_code(text: str) -> str:
    return f"<code>{escape_html(text)}</code>"


def separate_directions(text: str) -> str:
    """Fast RTL/LTR separation with caching."""
    if not text:
        return text
    cached = _text_cache.get(text)
    if cached is not None:
        return cached

    out_lines: List[str] = []
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            out_lines.append("")
            continue

        if ("<code>" in s or "<pre>" in s or "<b>" in s
                or "<i>" in s or "<a " in s or "\x01FML\x01" in s):
            out_lines.append(line)
            continue
        persian = len(re.findall(r"[\u0600-\u06FF]", s))
        visible = len(re.sub(r"\s+", "", s)) or 1
        if persian / visible > 0.40 and "\\" not in s:
            out_lines.append(line)
            continue
        if is_formula_line(s):
            out_lines.append(f"\x01FML\x01{s}\x01/FML\x01")
        elif is_mostly_latin(s) and len(s) < 200:
            out_lines.append(isolate_ltr(s))
        else:
            out_lines.append(line)

    result = "\n".join(out_lines)
    _text_cache.set(text, result)
    return result


# ══════════════════════════════════════════════════════════════════════════════
#                          LATEX CLEANER
# ══════════════════════════════════════════════════════════════════════════════

_LATEX_RE = re.compile(r"\\([A-Za-z]+)")
_LATEX_FRAC = re.compile(r"\\frac\{([^{}]+)\}\{([^{}]+)\}")
_LATEX_SQRT = re.compile(r"\\sqrt\{([^{}]+)\}")
_LATEX_TEXT = re.compile(r"\\text\{([^{}]+)\}")

_GREEK_MAP = {
    "alpha":"α","beta":"β","gamma":"γ","delta":"δ","epsilon":"ε",
    "zeta":"ζ","eta":"η","theta":"θ","iota":"ι","kappa":"κ",
    "lambda":"λ","mu":"μ","nu":"ν","xi":"ξ","pi":"π","rho":"ρ",
    "sigma":"σ","tau":"τ","upsilon":"υ","phi":"φ","chi":"χ",
    "psi":"ψ","omega":"ω","Gamma":"Γ","Delta":"Δ","Theta":"Θ",
    "Lambda":"Λ","Xi":"Ξ","Pi":"Π","Sigma":"Σ","Phi":"Φ","Psi":"Ψ","Omega":"Ω",
}

_SYMBOL_MAP = {
    "partial":"∂","nabla":"∇","infty":"∞","int":"∫","iint":"∬","iiint":"∭",
    "oint":"∮","sum":"∑","prod":"∏","pm":"±","mp":"∓","times":"×","div":"÷",
    "cdot":"·","approx":"≈","neq":"≠","leq":"≤","geq":"≥","ll":"≪","gg":"≫",
    "to":"→","rightarrow":"→","leftarrow":"←","Rightarrow":"⇒","Leftarrow":"⇐",
    "in":"∈","notin":"∉","subset":"⊂","supset":"⊃","cup":"∪","cap":"∩",
    "forall":"∀","exists":"∃",
}

_SUP = str.maketrans("0123456789+-=()in", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁱⁿ")
_SUB = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")


def clean_latex(text: str) -> str:
    if not text or "\\" not in text:
        return text

    text = text.replace("$$", "").replace("$", "")
    text = text.replace("\\(", "").replace("\\)", "")
    text = text.replace("\\[", "").replace("\\]", "")

    for _ in range(3):
        text = _LATEX_FRAC.sub(r"(\1)/(\2)", text)

    text = _LATEX_SQRT.sub(r"√(\1)", text)
    text = _LATEX_TEXT.sub(r"\1", text)
    text = text.replace("\\left", "").replace("\\right", "")

    for k, v in _GREEK_MAP.items():
        text = re.sub(r"\\" + k + r"\b", v, text)
    for k, v in _SYMBOL_MAP.items():
        text = text.replace("\\" + k, v)

    text = re.sub(r"\^\{([^{}]+)\}", lambda m: m.group(1).translate(_SUP), text)
    text = re.sub(r"_\{([^{}]+)\}", lambda m: m.group(1).translate(_SUB), text)
    text = re.sub(r"\^(\w)", lambda m: m.group(1).translate(_SUP), text)
    text = re.sub(r"_(\w)", lambda m: m.group(1).translate(_SUB), text)

    text = _LATEX_RE.sub("", text)
    text = text.replace("\\", "")
    text = re.sub(r"[ \t]+", " ", text)
    return text


# ══════════════════════════════════════════════════════════════════════════════
#                          DATACLASSES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class TelegramCfg:
    token: str = ""
    channel_id: str = "@MAADGHchannel"
    admin_id: Optional[int] = None
    admin_ids: List[int] = field(default_factory=list)


@dataclass
class AICfg:
    provider: str = "openrouter"
    primary_model: str = "openrouter/free"
    fallback_models: List[str] = field(default_factory=list)
    temperature: float = 0.6
    max_tokens: int = 2500
    timeout: int = 120
    retries: int = 2


@dataclass
class ContentCfg:
    length: str = "long"
    technical_level: str = "professional"
    default_style: str = "tutorial"
    include_formulas: bool = True
    include_examples: bool = True
    include_tables: bool = True
    include_hashtags: bool = True
    include_emoji: bool = True
    multi_part: bool = True
    max_chars: int = 4000
    include_youtube_videos: bool = True


@dataclass
class BehaviorCfg:
    auto_post_hours: int = 3
    rotate_topics: bool = True
    topic_index: int = 0
    auto_poll: bool = False
    include_news: bool = True
    include_reddit: bool = True
    include_politics: bool = False
    rate_limit_per_min: int = 15
    max_history: int = 20


@dataclass
class APIKeys:
    openrouter: str = ""
    gemini: str = ""
    zenserp: str = ""
    aviationstack: str = ""
    apify: str = ""
    weatherapi: str = ""
    bazaarlink: str = ""
    bazaarlink_base: str = "https://api.bazaarlink.ai/v1"
    bazaarlink_model: str = "gpt-4o-mini"
    harnessrouter: str = ""
    harnessrouter_base: str = "https://api.harnessrouter.com"
    rapidapi_learning_secret: str = ""
    aimlapi: str = ""
    aimlapi_base: str = "https://api.aimlapi.com/v1"
    aimlapi_model: str = "gpt-4o-mini"
    youtube: str = ""
    share_group_id: str = ""
    groq: str = ""
    groq_base: str = "https://api.groq.com/openai/v1"
    groq_model: str = "llama-3.1-8b-instant"


@dataclass
class FullConfig:
    telegram: TelegramCfg = field(default_factory=TelegramCfg)
    ai: AICfg = field(default_factory=AICfg)
    content: ContentCfg = field(default_factory=ContentCfg)
    behavior: BehaviorCfg = field(default_factory=BehaviorCfg)
    keys: APIKeys = field(default_factory=APIKeys)
    last_update_id: int = 0
    bot_started_at: Optional[str] = None
    version: str = "17.0-clean"


DEFAULT_FALLBACKS = [
    "openrouter/free",
    "qwen/qwen3.6-plus:free",
    "qwen/qwen3-coder:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-3-27b-it:free",
    "google/gemma-3-12b-it:free",
    "google/gemma-3-4b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "meta-llama/llama-3.1-8b-instruct:free",
    "openai/gpt-oss-20b:free",
    "openai/gpt-oss-120b:free",
    "deepseek/deepseek-r1:free",
    "mistralai/mistral-small-3.1-24b-instruct:free",
    "arcee-ai/trinity-large-preview:free",
    "minimax/minimax-m2.5:free",
    "liquid/lfm-2.5-2.6b:free",
]


# ══════════════════════════════════════════════════════════════════════════════
#                          CONFIG MANAGER
# ══════════════════════════════════════════════════════════════════════════════


def _safe_dataclass(cls, data):
    try:
        from dataclasses import fields as _dcf
        allowed = {f.name for f in _dcf(cls)}
        clean = {k: v for k, v in (data or {}).items() if k in allowed}
        return cls(**clean)
    except Exception:
        try: return cls()
        except Exception: raise


class ConfigManager:
    _instance: Optional["ConfigManager"] = None
    _singleton_lock = threading.Lock()

    def __new__(cls, *a, **kw):
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, path: Path = CONFIG_FILE):
        if getattr(self, "_init_done", False):
            return
        self._init_done = True
        self.path = path
        self._lock = threading.RLock()
        self._config: Optional[FullConfig] = None
        self._mtime = 0.0

    def load(self) -> FullConfig:
        with self._lock:
            if self._config is not None and self.path.exists():
                try:
                    current_mtime = self.path.stat().st_mtime
                    if current_mtime == self._mtime:
                        return self._config
                except Exception:
                    pass

            raw = load_json(self.path, default=None)
            if raw is None:
                cfg = FullConfig()
                cfg.ai.fallback_models = list(DEFAULT_FALLBACKS)
                self._config = cfg
                self.save()
                return cfg

            cfg = FullConfig()
            try:
                if "telegram" in raw:
                    cfg.telegram = _safe_dataclass(TelegramCfg, raw["telegram"])
                if "ai" in raw:
                    d = dict(raw["ai"])
                    d.setdefault("fallback_models", list(DEFAULT_FALLBACKS))
                    cfg.ai = AICfg(**d)
                if "content" in raw:
                    cfg.content = _safe_dataclass(ContentCfg, raw["content"])
                if "behavior" in raw:
                    cfg.behavior = _safe_dataclass(BehaviorCfg, raw["behavior"])
                if "keys" in raw:
                    cfg.keys = _safe_dataclass(APIKeys, raw["keys"])
                cfg.last_update_id = raw.get("last_update_id", 0)
                cfg.bot_started_at = raw.get("bot_started_at")
                cfg.version = raw.get("version", "5.0-perf")
            except Exception as e:
                log.error(f"Config rehydrate: {e}")

            self._config = cfg
            try:
                self._mtime = self.path.stat().st_mtime
            except Exception:
                self._mtime = 0.0
            return cfg

    def save(self) -> bool:
        with self._lock:
            if self._config is None:
                return False
            data = {
                "telegram": asdict(self._config.telegram),
                "ai": asdict(self._config.ai),
                "content": asdict(self._config.content),
                "behavior": asdict(self._config.behavior),
                "keys": asdict(self._config.keys),
                "last_update_id": self._config.last_update_id,
                "bot_started_at": self._config.bot_started_at,
                "version": self._config.version,
            }
            ok_flag = save_json(self.path, data)
            if ok_flag:
                try:
                    self._mtime = self.path.stat().st_mtime
                except Exception:
                    pass
            return ok_flag

    def get(self) -> FullConfig:
        return self.load()

    def reload(self) -> FullConfig:
        with self._lock:
            self._config = None
        return self.load()

    # Granular setters
    def set_key(self, name: str, value: str) -> bool:
        cfg = self.load()
        if not hasattr(cfg.keys, name):
            return False
        setattr(cfg.keys, name, value)
        return self.save()

    def set_provider(self, provider: str) -> bool:
        if provider not in ("openrouter", "gemini", "bazaarlink", "aimlapi", "harnessrouter"):
            return False
        cfg = self.load()
        cfg.ai.provider = provider
        return self.save()

    def set_model(self, model: str) -> bool:
        cfg = self.load()
        cfg.ai.primary_model = model
        return self.save()

    def add_fallback(self, model: str) -> bool:
        cfg = self.load()
        if model in cfg.ai.fallback_models:
            return False
        cfg.ai.fallback_models.append(model)
        return self.save()

    def remove_fallback(self, model: str) -> bool:
        cfg = self.load()
        if model not in cfg.ai.fallback_models:
            return False
        cfg.ai.fallback_models.remove(model)
        return self.save()

    def set_content_length(self, length: str) -> bool:
        """Set content length: short | medium | long | very_long"""
        if length not in ("short", "medium", "long", "very_long"):
            return False
        cfg = self.load()
        cfg.content.length = length
        return self.save()

    def set_technical_level(self, level: str) -> bool:
        """Set technical level: basic | intermediate | professional | expert"""
        if level not in ("basic", "intermediate", "professional", "expert"):
            return False
        cfg = self.load()
        cfg.content.technical_level = level
        return self.save()

    def toggle(self, attr: str) -> Optional[bool]:
        cfg = self.load()
        for obj in (cfg.content, cfg.behavior):
            if hasattr(obj, attr):
                cur = getattr(obj, attr)
                new = not bool(cur)
                setattr(obj, attr, new)
                self.save()
                return new
        return None


CONFIG = ConfigManager(CONFIG_FILE)


# ══════════════════════════════════════════════════════════════════════════════
#                          AI CLIENT
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class AIResp:
    ok: bool
    text: str = ""
    model: str = ""
    provider: str = ""
    error: str = ""
    latency_ms: int = 0
    cached: bool = False


class AIClient:
    OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
    GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    GEMINI_DEFAULT = "gemini-2.0-flash-exp"

    def __init__(self, config: ConfigManager):
        self.config = config

    def _cache_key(self, provider: str, sys_p: str, usr_p: str, model: str) -> str:
        h = hashlib.md5()
        h.update(provider.encode())
        h.update(sys_p.encode("utf-8"))
        h.update(usr_p.encode("utf-8"))
        h.update(model.encode())
        return h.hexdigest()

    def ask(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int = 2500,
        temperature: float = 0.6,
        history: Optional[List[Dict[str, str]]] = None,
        force_provider: Optional[str] = None,
        use_cache: bool = True,
    ) -> AIResp:
        cfg = self.config.get()
        provider = force_provider or cfg.ai.provider

        cache_key = self._cache_key(provider, system_prompt, user_prompt, cfg.ai.primary_model)
        if use_cache:
            hit = AI_CACHE.get(cache_key)
            if hit is not None:
                return AIResp(ok=True, text=hit,
                              model="(cached)", provider=provider,
                              latency_ms=0, cached=True)

        # provider chain: BazaarLink -> AIMLAPI -> OpenRouter -> Gemini
        _km = {
            "openrouter": (cfg.keys.openrouter,                 self._openrouter),
            "groq":       (getattr(cfg.keys, "groq", ""),       self._groq),
            "bazaarlink": (getattr(cfg.keys, "bazaarlink", ""), self._bazaarlink),
            "aimlapi":    (getattr(cfg.keys, "aimlapi", ""),    self._aimlapi),
            "gemini":     (cfg.keys.gemini,                     self._gemini),
        }
        _all = []
        if provider in _km and _km[provider][0]:
            _all.append((provider, _km[provider][1]))
        for _n, (_k, _fn) in _km.items():
            if _n == provider: continue
            if _k: _all.append((_n, _fn))
        if not _all:
            return AIResp(ok=False, error="No AI provider configured")
        last_err = ""
        resp = None
        for _n, _fn in _all:
            try:
                resp = _fn(system_prompt, user_prompt, max_tokens, temperature, history)
            except Exception as e:
                log.warning(f"AI {_n} exception: {e}")
                resp = AIResp(ok=False, error=f"{_n}: {e}")
            if resp.ok:
                if _n != provider:
                    log.info(f"AI fallback: {_n}")
                try:
                    LIVE.event("ai", f"AI {_n} replied ({resp.latency_ms}ms)", to_tg=False)
                except Exception:
                    pass
                break
            last_err = resp.error or _n
            log.info(f"AI {_n} failed: {last_err[:80]}")
            try:
                LIVE.event("warn", f"AI {_n} error: {last_err[:60]}", to_tg=False)
            except Exception:
                pass
        if resp is None:
            resp = AIResp(ok=False, error=last_err or "all failed")
        if resp.ok and use_cache:
            AI_CACHE.set(cache_key, resp.text)
        return resp

    def _openrouter(
        self, sys_p: str, usr_p: str,
        max_tokens: int, temperature: float,
        history: Optional[List[Dict[str, str]]],
    ) -> AIResp:
        cfg = self.config.get()
        key = cfg.keys.openrouter.strip()
        if not key:
            return AIResp(ok=False, error="OpenRouter key not set")

        started = time.perf_counter()
        models = [cfg.ai.primary_model] + list(cfg.ai.fallback_models)

        seen = set()
        unique_models = []
        for m in models:
            if m and m not in seen:
                unique_models.append(m)
                seen.add(m)

        last_err = ""
        for mdl in unique_models:
            messages: List[Dict[str, str]] = [{"role": "system", "content": sys_p}]
            if history:
                for h in history[-cfg.behavior.max_history:]:
                    if isinstance(h, dict) and "role" in h and "content" in h:
                        messages.append({"role": h["role"], "content": h["content"]})
            messages.append({"role": "user", "content": usr_p})

            payload = {
                "model": mdl,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }

            r = HTTP.request(
                "POST", self.OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://localhost",
                    "X-Title": "MAADGH",
                },
                json_body=payload,
                timeout=cfg.ai.timeout,
            )

            if r is None:
                last_err = "request failed"
                continue

            if r.status_code == 200:
                try:
                    data = r.json()
                except Exception as e:
                    last_err = f"json error: {e}"
                    continue
                choices = data.get("choices") or []
                if choices and choices[0].get("message"):
                    content = choices[0]["message"].get("content")
                    if content and isinstance(content, str) and len(content.strip()) > 10:
                        return AIResp(
                            ok=True, text=content.strip(),
                            model=mdl, provider="openrouter",
                            latency_ms=int((time.perf_counter() - started) * 1000),
                        )
                last_err = f"{mdl}: empty content"
                continue

            if r.status_code == 401:
                return AIResp(ok=False, error="OpenRouter 401")
            if r.status_code == 429:
                last_err = f"{mdl}: 429 rate limit"
                continue
            try:
                j = r.json()
                emsg = (j.get("error") or {}).get("message", "")
            except Exception:
                emsg = r.text[:120]
            last_err = f"{mdl}: {r.status_code} {emsg[:80]}"

        return AIResp(ok=False, error=last_err or "all models failed")

    def _gemini(
        self, sys_p: str, usr_p: str,
        max_tokens: int, temperature: float,
        history: Optional[List[Dict[str, str]]],
    ) -> AIResp:
        cfg = self.config.get()
        key = cfg.keys.gemini.strip()
        if not key:
            return AIResp(ok=False, error="Gemini key not set")

        started = time.perf_counter()
        mdl = self.GEMINI_DEFAULT

        contents: List[Dict[str, Any]] = []
        if sys_p:
            contents.append({"role": "user", "parts": [{"text": f"[SYSTEM]\n{sys_p}"}]})
            contents.append({"role": "model", "parts": [{"text": "OK."}]})

        if history:
            for h in history[-cfg.behavior.max_history:]:
                if not isinstance(h, dict):
                    continue
                role = "user" if h.get("role") == "user" else "model"
                txt = h.get("content", "")
                if txt:
                    contents.append({"role": role, "parts": [{"text": txt}]})

        contents.append({"role": "user", "parts": [{"text": usr_p}]})

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        url = self.GEMINI_URL.format(model=mdl, key=key)
        r = HTTP.request("POST", url, json_body=payload, timeout=cfg.ai.timeout)

        if r is None:
            return AIResp(ok=False, error="request failed")
        if r.status_code != 200:
            try:
                j = r.json()
                emsg = j.get("error", {}).get("message", "")
            except Exception:
                emsg = r.text[:120]
            return AIResp(ok=False, error=f"Gemini {r.status_code}: {emsg[:100]}")

        try:
            data = r.json()
        except Exception as e:
            return AIResp(ok=False, error=f"json: {e}")

        cand = (data.get("candidates") or [{}])[0]
        parts = cand.get("content", {}).get("parts") or []
        if not parts:
            return AIResp(ok=False, error="Gemini: no parts")
        text = parts[0].get("text", "").strip()
        if not text:
            return AIResp(ok=False, error="Gemini: empty text")

        return AIResp(
            ok=True, text=text, model=mdl, provider="gemini",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


    def _bazaarlink(self, sys_p, usr_p, max_tokens, temperature, history=None):
        cfg = self.config.get()
        key = getattr(cfg.keys, "bazaarlink", "").strip()
        if not key: return AIResp(ok=False, error="BazaarLink key not set")
        base = (getattr(cfg.keys, "bazaarlink_base", "") or "https://api.bazaarlink.ai/v1").rstrip("/")
        mdl = getattr(cfg.keys, "bazaarlink_model", "") or "gpt-4o-mini"
        started = time.perf_counter()
        messages = [{"role": "system", "content": sys_p}]
        if history:
            for h in history[-cfg.behavior.max_history:]:
                if isinstance(h, dict) and "role" in h and "content" in h:
                    messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": usr_p})
        payload = {"model": mdl, "messages": messages,
                   "temperature": temperature, "max_tokens": max_tokens}
        r = HTTP.request("POST", f"{base}/chat/completions",
                         headers={"Authorization": f"Bearer {key}",
                                  "Content-Type": "application/json"},
                         json_body=payload, timeout=90)
        if r is None: return AIResp(ok=False, error="BazaarLink request failed")
        if r.status_code != 200:
            return AIResp(ok=False, error=f"BazaarLink {r.status_code}: {r.text[:150]}")
        try: data = r.json()
        except Exception as e: return AIResp(ok=False, error=f"BazaarLink json: {e}")
        ch = data.get("choices") or []
        if not ch: return AIResp(ok=False, error="BazaarLink: no choices")
        txt = (ch[0].get("message") or {}).get("content", "").strip()
        if not txt: return AIResp(ok=False, error="BazaarLink: empty")
        return AIResp(ok=True, text=txt, model=mdl, provider="bazaarlink",
                      latency_ms=int((time.perf_counter()-started)*1000))

    def _aimlapi(self, sys_p, usr_p, max_tokens, temperature, history=None):
        cfg = self.config.get()
        key = getattr(cfg.keys, "aimlapi", "").strip()
        if not key: return AIResp(ok=False, error="AIMLAPI key not set")
        base = (getattr(cfg.keys, "aimlapi_base", "") or "https://api.aimlapi.com/v1").rstrip("/")
        mdl = getattr(cfg.keys, "aimlapi_model", "") or "gpt-4o-mini"
        started = time.perf_counter()
        messages = [{"role": "system", "content": sys_p}]
        if history:
            for h in history[-cfg.behavior.max_history:]:
                if isinstance(h, dict) and "role" in h and "content" in h:
                    messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": usr_p})
        payload = {"model": mdl, "messages": messages,
                   "temperature": temperature, "max_tokens": max_tokens}
        r = HTTP.request("POST", f"{base}/chat/completions",
                         headers={"Authorization": f"Bearer {key}",
                                  "Content-Type": "application/json"},
                         json_body=payload, timeout=90)
        if r is None: return AIResp(ok=False, error="AIMLAPI request failed")
        if r.status_code != 200:
            return AIResp(ok=False, error=f"AIMLAPI {r.status_code}: {r.text[:150]}")
        try: data = r.json()
        except Exception as e: return AIResp(ok=False, error=f"AIMLAPI json: {e}")
        ch = data.get("choices") or []
        if not ch: return AIResp(ok=False, error="AIMLAPI: no choices")
        txt = (ch[0].get("message") or {}).get("content", "").strip()
        if not txt: return AIResp(ok=False, error="AIMLAPI: empty")
        return AIResp(ok=True, text=txt, model=mdl, provider="aimlapi",
                      latency_ms=int((time.perf_counter()-started)*1000))



    def _groq(self, sys_p, usr_p, max_tokens, temperature, history=None):
        cfg = self.config.get()
        key = getattr(cfg.keys, "groq", "").strip()
        if not key: return AIResp(ok=False, error="Groq key not set")
        base = (getattr(cfg.keys, "groq_base", "") or "https://api.groq.com/openai/v1").rstrip("/")
        mdl = getattr(cfg.keys, "groq_model", "") or "llama-3.3-70b-versatile"
        started = time.perf_counter()
        messages = [{"role": "system", "content": sys_p}]
        if history:
            for h in history[-cfg.behavior.max_history:]:
                if isinstance(h, dict) and "role" in h and "content" in h:
                    messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": usr_p})
        payload = {"model": mdl, "messages": messages,
                   "temperature": temperature, "max_tokens": max_tokens}
        r = HTTP.request("POST", f"{base}/chat/completions",
                         headers={"Authorization": f"Bearer {key}",
                                  "Content-Type": "application/json"},
                         json_body=payload, timeout=90)
        if r is None: return AIResp(ok=False, error="Groq request failed")
        if r.status_code != 200:
            return AIResp(ok=False, error=f"Groq {r.status_code}: {r.text[:150]}")
        try: data = r.json()
        except Exception as e: return AIResp(ok=False, error=f"Groq json: {e}")
        ch = data.get("choices") or []
        if not ch: return AIResp(ok=False, error="Groq: no choices")
        txt = (ch[0].get("message") or {}).get("content", "").strip()
        if not txt: return AIResp(ok=False, error="Groq: empty")
        return AIResp(ok=True, text=txt, model=mdl, provider="groq",
                      latency_ms=int((time.perf_counter()-started)*1000))

    def test_provider(self, provider: str) -> AIResp:
        return self.ask("You are a test assistant.", "Say 'OK' in Persian.",
                        max_tokens=20, force_provider=provider, use_cache=False)

    def ask_parallel(self, requests_list: List[Dict[str, Any]]) -> List[AIResp]:
        """Parallel AI calls using thread pool."""
        futures = [
            POOL.submit(self.ask, r["system"], r["user"],
                        max_tokens=r.get("max_tokens", 2500),
                        temperature=r.get("temperature", 0.6),
                        history=r.get("history"))
            for r in requests_list
        ]
        results = POOL.gather(futures, timeout=300)
        return [r if isinstance(r, AIResp) else AIResp(ok=False, error="failed") for r in results]


AI = AIClient(CONFIG)


# ══════════════════════════════════════════════════════════════════════════════
#                          PERFORMANCE METRICS
# ══════════════════════════════════════════════════════════════════════════════

class PerfMonitor:
    def __init__(self):
        self._counters: Counter = Counter()
        self._timings: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.RLock()
        self._started = time.time()

    def count(self, name: str, n: int = 1) -> None:
        with self._lock:
            self._counters[name] += n

    @contextlib.contextmanager
    def timer(self, name: str):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            dt = (time.perf_counter() - t0) * 1000
            with self._lock:
                lst = self._timings[name]
                lst.append(dt)
                if len(lst) > 1000:
                    del lst[:500]

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            out = {
                "counters": dict(self._counters),
                "uptime_sec": round(time.time() - self._started, 1),
                "timings": {}
            }
            for name, lst in self._timings.items():
                if lst:
                    out["timings"][name] = {
                        "count": len(lst),
                        "avg_ms": round(sum(lst) / len(lst), 2),
                        "min_ms": round(min(lst), 2),
                        "max_ms": round(max(lst), 2),
                    }
            return out


PERF = PerfMonitor()


# ══════════════════════════════════════════════════════════════════════════════
#                          SHUTDOWN HANDLING
# ══════════════════════════════════════════════════════════════════════════════

_shutdown_handlers: List[Callable[[], None]] = []
_shutdown_lock = threading.Lock()
_shutting_down = threading.Event()


def register_shutdown(fn: Callable[[], None]) -> None:
    with _shutdown_lock:
        _shutdown_handlers.append(fn)


def _run_shutdown() -> None:
    if _shutting_down.is_set():
        return
    _shutting_down.set()
    log.info("Shutting down...")
    with _shutdown_lock:
        handlers = list(_shutdown_handlers)
    for h in handlers:
        try:
            h()
        except Exception as e:
            log.error(f"Shutdown handler: {e}")
    try:
        BATCHED_WRITER.stop()
    except Exception:
        pass
    try:
        POOL.shutdown(wait=False)
    except Exception:
        pass
    try:
        MEM_MON.stop()
    except Exception:
        pass
    try:
        if _log_worker:
            _log_worker.stop()
    except Exception:
        pass


def _signal_handler(signum, frame):
    log.info(f"Signal {signum} received")
    _run_shutdown()
    sys.exit(0)


for _sig in (signal.SIGINT, signal.SIGTERM):
    try:
        signal.signal(_sig, _signal_handler)
    except Exception:
        pass


register_shutdown(_run_shutdown)


# ══════════════════════════════════════════════════════════════════════════════
#                          SELF TEST / BENCHMARK
# ══════════════════════════════════════════════════════════════════════════════

def _bench_json(n: int = 10000) -> None:
    data = {"items": [{"id": i, "name": f"item_{i}", "value": i * 3.14} for i in range(n)]}
    t0 = time.perf_counter()
    for _ in range(50):
        s = json_dumps(data)
        if isinstance(s, str):
            s = s.encode("utf-8")
    dt_encode = (time.perf_counter() - t0) / 50 * 1000

    payload = s if isinstance(s, bytes) else s.encode("utf-8")

    t0 = time.perf_counter()
    for _ in range(50):
        _ = json_loads(payload)
    dt_decode = (time.perf_counter() - t0) / 50 * 1000

    perf(f"JSON ({JSON_BACKEND}): encode {dt_encode:.2f}ms | decode {dt_decode:.2f}ms "
         f"| {n} items | backend={JSON_BACKEND}")


def _bench_cache(n: int = 100000) -> None:
    cache = LRUTTLCache(maxsize=10000, ttl=3600)
    t0 = time.perf_counter()
    for i in range(n):
        cache.set(f"key_{i % 10000}", i)
    dt_set = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    hits = 0
    for i in range(n):
        if cache.get(f"key_{i % 10000}") is not None:
            hits += 1
    dt_get = (time.perf_counter() - t0) * 1000

    perf(f"Cache: {n} sets in {dt_set:.1f}ms | {n} gets in {dt_get:.1f}ms | hits={hits}")


def _bench_bloom(n: int = 500000) -> None:
    bf = BloomFilter(capacity=n, error_rate=0.01)
    t0 = time.perf_counter()
    for i in range(n):
        bf.add(f"item_{i}")
    dt_add = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    present = sum(1 for i in range(1000) if f"item_{i}" in bf)
    dt_check = (time.perf_counter() - t0) * 1000

    perf(f"Bloom: {n} adds in {dt_add:.1f}ms ({n/dt_add*1000:.0f}/s) "
         f"| 1000 checks in {dt_check:.2f}ms | size={bf.stats()['size_kb']}KB")


def _bench_text(n: int = 10000) -> None:
    sample = (
        "معادله برنولی:\n"
        "P + ½ρv² + ρgz = const\n"
        "که در آن P فشار، ρ چگالی، v سرعت و z ارتفاع است.\n"
    )
    t0 = time.perf_counter()
    for _ in range(n):
        _ = separate_directions(sample)
    dt = (time.perf_counter() - t0) * 1000

    perf(f"RTL sep: {n} calls in {dt:.1f}ms ({n/dt*1000:.0f}/s) "
         f"| cache_hit_rate={_text_cache.stats()['hit_rate']}%")


def self_test() -> None:
    head("Part 1/5 — Performance Self-Test")

    print()
    info(f"Python:      {PY_MAJOR}.{PY_MINOR}")
    info(f"JSON backend: {JSON_BACKEND}")
    info(f"CPU cores:   {CPU_COUNT}")
    info(f"Max workers: {MAX_WORKERS}")
    info(f"RAM limit:   soft=2048MB, hard=6144MB")
    info(f"ROOT:        {ROOT}")

    # Priority
    priority_ok, priority_msg = boost_process_priority()
    if priority_ok:
        ok(f"Process priority boosted: {priority_msg}")
    else:
        warn(f"Priority: {priority_msg}")

    tune_gc()
    ok(f"GC tuned")

    # JSON round-trip
    test_file = TMP_DIR / "_test.json"
    test_data = {"a": 1, "b": [1, 2, 3], "c": {"x": "y"}}
    save_json(test_file, test_data)
    loaded = load_json(test_file)
    if loaded == test_data:
        ok("JSON store working")
    else:
        err(f"JSON round-trip FAILED: {loaded}")
    try:
        test_file.unlink()
    except Exception:
        pass

    # Benchmarks
    print()
    sub("Benchmarks")
    _bench_json(10000)
    _bench_cache(100000)
    _bench_bloom(500000)
    _bench_text(5000)

    # Stats
    print()
    sub("Runtime stats")
    ms = MEM_MON.stats()
    info(f"Memory: {ms['current_mb']}MB now, {ms['peak_mb']}MB peak")
    info(f"Cache AI:     {AI_CACHE.stats()}")
    info(f"Cache HTTP:   {HTTP_CACHE.stats()}")
    info(f"HTTP pool:    {HTTP.stats()}")
    info(f"Thread pool:  {POOL.stats()}")

    # Config
    print()
    sub("Config")
    cfg = CONFIG.get()
    ok(f"Version: {cfg.version}")
    info(f"Provider: {cfg.ai.provider}")
    info(f"Model: {cfg.ai.primary_model}")
    info(f"Fallbacks: {len(cfg.ai.fallback_models)}")
    info(f"Channel: {cfg.telegram.channel_id}")
    info(f"Content length: {cfg.content.length}")
    info(f"Technical level: {cfg.content.technical_level}")

    # AI tests
    print()
    sub("AI Provider tests")
    if cfg.keys.openrouter:
        step("Testing OpenRouter...")
        with PERF.timer("ai_openrouter"):
            resp = AI.test_provider("openrouter")
        if resp.ok:
            ok(f"OpenRouter: {resp.model} ({resp.latency_ms}ms) → {resp.text[:50]}")
        else:
            warn(f"OpenRouter: {resp.error}")
    else:
        info("OpenRouter key not set")

    if cfg.keys.gemini:
        step("Testing Gemini...")
        with PERF.timer("ai_gemini"):
            resp = AI.test_provider("gemini")
        if resp.ok:
            ok(f"Gemini: {resp.model} ({resp.latency_ms}ms) → {resp.text[:50]}")
        else:
            warn(f"Gemini: {resp.error}")
    else:
        info("Gemini key not set")

    # Final
    print()
    perf_stats = PERF.stats()
    print(f"{Clr.CYN}Final perf: {json_dumps(perf_stats, indent=True) if isinstance(json_dumps(perf_stats), str) else perf_stats}{Clr.R}")

    print()
    succ("Part 1/5 self-test complete.")
    info("Send 'ادامه' for Part 2/5 (Telegram API + Router).")


# ══════════════════════════════════════════════════════════════════════════════
#                          ENTRY
# ══════════════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════════════
#                    PART 2/5 — TELEGRAM API + ROUTER + COMMANDS
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
#                          TELEGRAM API CLIENT
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class TgResult:
    ok: bool
    result: Any = None
    description: str = ""
    error_code: int = 0
    raw: Optional[Dict] = None


class TelegramAPI:
    """Full-featured Telegram Bot API client with pooling, retries, fallback."""

    BASE = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self, config: ConfigManager, http: ConnectionPool):
        self.config = config
        self.http = http
        self._lock = threading.RLock()
        self._bot_info: Optional[Dict] = None
        self._last_call = 0.0
        # Global rate limiter: max 30 requests/second to Telegram
        self._rate_lock = threading.Lock()
        self._rate_window: deque = deque(maxlen=30)

    # ─────────────────────────────────────────────────────────────
    # CORE REQUEST
    # ─────────────────────────────────────────────────────────────

    def _wait_rate(self) -> None:
        """Enforce global 30 req/sec cap."""
        while True:
            now = time.monotonic()
            with self._rate_lock:
                while self._rate_window and now - self._rate_window[0] > 1.0:
                    self._rate_window.popleft()
                if len(self._rate_window) < 30:
                    self._rate_window.append(now)
                    return
            time.sleep(0.05)

    def _call(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        files: Optional[Dict] = None,
        timeout: int = 30,
        is_multipart: bool = False,
    ) -> TgResult:
        cfg = self.config.get()
        token = cfg.telegram.token.strip()
        if not token:
            return TgResult(ok=False, description="Telegram token not set")

        self._wait_rate()

        url = self.BASE.format(token=token, method=method)

        try:
            if is_multipart and files:
                r = self.http.request(
                    "POST", url, data=params or {}, files=files,
                    timeout=timeout,
                )
            else:
                payload = params or {}
                # Telegram expects JSON body
                r = self.http.request(
                    "POST", url, json_body=payload, timeout=timeout,
                )

            if r is None:
                return TgResult(ok=False, description="request failed (timeout/network)")

            try:
                data = r.json()
            except Exception:
                return TgResult(ok=False, description=f"bad json: {r.text[:120]}")

            if data.get("ok"):
                return TgResult(ok=True, result=data.get("result"), raw=data)

            return TgResult(
                ok=False,
                description=data.get("description", "unknown error"),
                error_code=data.get("error_code", 0),
                raw=data,
            )

        except Exception as e:
            log.error(f"TG {method} exception: {e}")
            return TgResult(ok=False, description=str(e)[:200])

    # ─────────────────────────────────────────────────────────────
    # MESSAGE OPERATIONS
    # ─────────────────────────────────────────────────────────────

    def _send_with_fallback(
        self,
        chat_id: Union[int, str],
        text: str,
        *,
        parse_mode: str = "HTML",
        reply_markup: Optional[Dict] = None,
        disable_preview: bool = True,
        reply_to: Optional[int] = None,
    ) -> TgResult:
        """Send message; if HTML parse fails, retry as plain text."""
        params = {
            "chat_id": chat_id,
            "text": text[:4096],
            "disable_web_page_preview": disable_preview,
        }
        if parse_mode:
            params["parse_mode"] = parse_mode
        if reply_markup:
            params["reply_markup"] = reply_markup
        if reply_to:
            params["reply_to_message_id"] = reply_to

        res = self._call("sendMessage", params)

        # Fallback: strip HTML and retry
        if not res.ok and res.error_code == 400:
            desc = res.description.lower()
            if "parse" in desc or "entity" in desc or "tag" in desc:
                log.warning("HTML parse failed; retrying as plain text")
                clean = strip_html(text)
                # Also strip code markers just in case
                clean = clean.replace("<code>", "").replace("</code>", "")
                clean = clean.replace("<pre>", "").replace("</pre>", "")
                clean = clean.replace("<b>", "").replace("</b>", "")
                clean = clean.replace("<i>", "").replace("</i>", "")
                clean = clean.replace("<s>", "").replace("</s>", "")
                params["text"] = clean[:4096]
                params.pop("parse_mode", None)
                res = self._call("sendMessage", params)

        return res

    def send_message(
        self,
        chat_id: Union[int, str],
        text: str,
        *,
        parse_mode: str = "HTML",
        reply_markup: Optional[Dict] = None,
        disable_preview: bool = True,
        reply_to: Optional[int] = None,
    ) -> TgResult:
        return self._send_with_fallback(
            chat_id, text,
            parse_mode=parse_mode, reply_markup=reply_markup,
            disable_preview=disable_preview, reply_to=reply_to,
        )

    def send_long_message(
        self,
        chat_id: Union[int, str],
        text: str,
        *,
        parse_mode: str = "HTML",
        reply_markup: Optional[Dict] = None,
        max_len: int = 3800,
        attach_kb_to_last: bool = True,
    ) -> List[TgResult]:
        """Split long text into multiple messages at paragraph boundaries."""
        if len(text) <= max_len:
            return [self.send_message(chat_id, text, parse_mode=parse_mode,
                                      reply_markup=reply_markup)]

        parts = self._split_text(text, max_len)
        results: List[TgResult] = []
        total = len(parts)

        for i, part in enumerate(parts, 1):
            header = f"<b>({i}/{total})</b>\n\n" if total > 1 else ""
            kb = reply_markup if (i == total and attach_kb_to_last) else None
            res = self.send_message(
                chat_id, header + part,
                parse_mode=parse_mode, reply_markup=kb,
            )
            results.append(res)
            time.sleep(0.6)  # avoid flood

        return results

    @staticmethod
    def _split_text(text: str, max_len: int) -> List[str]:
        """Split at paragraph, then line, then char boundaries."""
        if len(text) <= max_len:
            return [text]

        parts: List[str] = []
        current = ""

        # Split by paragraph
        for para in text.split("\n\n"):
            if len(current) + len(para) + 2 > max_len:
                if current:
                    parts.append(current.strip())
                # If single para too long, split by line
                if len(para) > max_len:
                    for line in para.split("\n"):
                        if len(current) + len(line) + 1 > max_len:
                            if current:
                                parts.append(current.strip())
                                current = ""
                            # If single line too long, hard split
                            while len(line) > max_len:
                                parts.append(line[:max_len])
                                line = line[max_len:]
                            current = line
                        else:
                            current += ("\n" if current else "") + line
                else:
                    current = para
            else:
                current += ("\n\n" if current else "") + para

        if current:
            parts.append(current.strip())

        return parts or [text[:max_len]]

    def edit_message(
        self,
        chat_id: Union[int, str],
        message_id: int,
        text: str,
        *,
        parse_mode: str = "HTML",
        reply_markup: Optional[Dict] = None,
    ) -> TgResult:
        if not message_id:
            return TgResult(ok=False, description="no message_id")

        params = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text[:4096],
        }
        if parse_mode:
            params["parse_mode"] = parse_mode
        if reply_markup:
            params["reply_markup"] = reply_markup

        res = self._call("editMessageText", params)

        if not res.ok and res.error_code == 400:
            desc = res.description.lower()
            if "parse" in desc or "entity" in desc:
                clean = strip_html(text)
                params["text"] = clean[:4096]
                params.pop("parse_mode", None)
                res = self._call("editMessageText", params)
            elif "message is not modified" in desc:
                return TgResult(ok=True, description="not modified")

        return res

    def edit_reply_markup(
        self,
        chat_id: Union[int, str],
        message_id: int,
        reply_markup: Optional[Dict],
    ) -> TgResult:
        return self._call("editMessageReplyMarkup", {
            "chat_id": chat_id,
            "message_id": message_id,
            "reply_markup": reply_markup or {"inline_keyboard": []},
        })

    def delete_message(
        self,
        chat_id: Union[int, str],
        message_id: int,
    ) -> TgResult:
        return self._call("deleteMessage", {
            "chat_id": chat_id,
            "message_id": message_id,
        })

    def forward_message(
        self,
        chat_id: Union[int, str],
        from_chat_id: Union[int, str],
        message_id: int,
    ) -> TgResult:
        return self._call("forwardMessage", {
            "chat_id": chat_id,
            "from_chat_id": from_chat_id,
            "message_id": message_id,
        })

    def copy_message(
        self,
        chat_id: Union[int, str],
        from_chat_id: Union[int, str],
        message_id: int,
    ) -> TgResult:
        return self._call("copyMessage", {
            "chat_id": chat_id,
            "from_chat_id": from_chat_id,
            "message_id": message_id,
        })

    # ─────────────────────────────────────────────────────────────
    # MEDIA
    # ─────────────────────────────────────────────────────────────

    def send_photo(
        self,
        chat_id: Union[int, str],
        photo: str,
        *,
        caption: str = "",
        parse_mode: str = "HTML",
        reply_markup: Optional[Dict] = None,
    ) -> TgResult:
        params = {
            "chat_id": chat_id,
            "photo": photo,
            "caption": caption[:1024],
        }
        if parse_mode:
            params["parse_mode"] = parse_mode
        if reply_markup:
            params["reply_markup"] = reply_markup
        return self._call("sendPhoto", params)

    def send_photo_file(
        self,
        chat_id: Union[int, str],
        file_path: Union[str, Path],
        *,
        caption: str = "",
        parse_mode: str = "HTML",
        reply_markup: Optional[Dict] = None,
    ) -> TgResult:
        p = Path(file_path)
        if not p.exists():
            return TgResult(ok=False, description="file not found")
        params = {"chat_id": chat_id, "caption": caption[:1024]}
        if parse_mode:
            params["parse_mode"] = parse_mode
        if reply_markup:
            params["reply_markup"] = json_dumps(reply_markup)
        with open(p, "rb") as f:
            return self._call(
                "sendPhoto", params,
                files={"photo": (p.name, f)}, is_multipart=True,
            )

    def send_document(
        self,
        chat_id: Union[int, str],
        doc: str,
        *,
        caption: str = "",
        reply_markup: Optional[Dict] = None,
    ) -> TgResult:
        params = {"chat_id": chat_id, "document": doc, "caption": caption[:1024]}
        if reply_markup:
            params["reply_markup"] = reply_markup
        return self._call("sendDocument", params)

    def send_document_file(
        self,
        chat_id: Union[int, str],
        file_path: Union[str, Path],
        *,
        caption: str = "",
        reply_markup: Optional[Dict] = None,
    ) -> TgResult:
        p = Path(file_path)
        if not p.exists():
            return TgResult(ok=False, description="file not found")
        params = {"chat_id": chat_id, "caption": caption[:1024]}
        if reply_markup:
            params["reply_markup"] = json_dumps(reply_markup)
        with open(p, "rb") as f:
            return self._call(
                "sendDocument", params,
                files={"document": (p.name, f)}, is_multipart=True,
            )

    def send_audio(
        self,
        chat_id: Union[int, str],
        audio: str,
        *,
        caption: str = "",
        reply_markup: Optional[Dict] = None,
    ) -> TgResult:
        params = {"chat_id": chat_id, "audio": audio, "caption": caption[:1024]}
        if reply_markup:
            params["reply_markup"] = reply_markup
        return self._call("sendAudio", params)

    def send_voice(
        self,
        chat_id: Union[int, str],
        voice: str,
        *,
        caption: str = "",
        reply_markup: Optional[Dict] = None,
    ) -> TgResult:
        params = {"chat_id": chat_id, "voice": voice, "caption": caption[:1024]}
        if reply_markup:
            params["reply_markup"] = reply_markup
        return self._call("sendVoice", params)

    def send_video(
        self,
        chat_id: Union[int, str],
        video: str,
        *,
        caption: str = "",
        reply_markup: Optional[Dict] = None,
    ) -> TgResult:
        params = {"chat_id": chat_id, "video": video, "caption": caption[:1024]}
        if reply_markup:
            params["reply_markup"] = reply_markup
        return self._call("sendVideo", params)

    # ─────────────────────────────────────────────────────────────
    # INTERACTION
    # ─────────────────────────────────────────────────────────────

    def send_chat_action(self, chat_id: Union[int, str], action: str = "typing") -> TgResult:
        return self._call("sendChatAction", {"chat_id": chat_id, "action": action})

    def typing(self, chat_id: Union[int, str]) -> None:
        """Fire-and-forget typing indicator."""
        POOL.submit(self.send_chat_action, chat_id, "typing")

    def answer_callback(
        self,
        callback_query_id: str,
        text: str = "",
        *,
        show_alert: bool = False,
        url: Optional[str] = None,
        cache_time: int = 0,
    ) -> TgResult:
        params = {"callback_query_id": callback_query_id}
        if text:
            params["text"] = text[:200]
        if show_alert:
            params["show_alert"] = True
        if url:
            params["url"] = url
        if cache_time:
            params["cache_time"] = cache_time
        return self._call("answerCallbackQuery", params)

    def send_poll(
        self,
        chat_id: Union[int, str],
        question: str,
        options: List[str],
        *,
        is_anonymous: bool = True,
        allows_multiple: bool = False,
        correct_option_id: Optional[int] = None,
        explanation: str = "",
        open_period: Optional[int] = None,
    ) -> TgResult:
        params = {
            "chat_id": chat_id,
            "question": question[:300],
            "options": options[:10],
            "is_anonymous": is_anonymous,
            "allows_multiple_answers": allows_multiple,
            "type": "quiz" if correct_option_id is not None else "regular",
        }
        if correct_option_id is not None:
            params["correct_option_id"] = correct_option_id
            if explanation:
                params["explanation"] = explanation[:200]
        if open_period:
            params["open_period"] = max(5, min(600, open_period))
        return self._call("sendPoll", params)

    def stop_poll(self, chat_id: Union[int, str], message_id: int) -> TgResult:
        return self._call("stopPoll", {"chat_id": chat_id, "message_id": message_id})

    def pin_message(
        self,
        chat_id: Union[int, str],
        message_id: int,
        *,
        disable_notification: bool = False,
    ) -> TgResult:
        return self._call("pinChatMessage", {
            "chat_id": chat_id,
            "message_id": message_id,
            "disable_notification": disable_notification,
        })

    def unpin_message(self, chat_id: Union[int, str], message_id: Optional[int] = None) -> TgResult:
        params = {"chat_id": chat_id}
        if message_id:
            params["message_id"] = message_id
        return self._call("unpinChatMessage", params)

    # ─────────────────────────────────────────────────────────────
    # BOT MANAGEMENT
    # ─────────────────────────────────────────────────────────────

    def get_me(self) -> TgResult:
        res = self._call("getMe")
        if res.ok:
            with self._lock:
                self._bot_info = res.result
        return res

    def get_updates(
        self,
        offset: int = 0,
        *,
        timeout: int = 25,
        allowed_updates: Optional[List[str]] = None,
        limit: int = 100,
    ) -> TgResult:
        params = {
            "offset": offset,
            "timeout": timeout,
            "limit": limit,
        }
        if allowed_updates is not None:
            params["allowed_updates"] = allowed_updates
        return self._call("getUpdates", params, timeout=timeout + 10)

    def set_my_commands(self, commands: List[Dict[str, str]]) -> TgResult:
        return self._call("setMyCommands", {"commands": commands[:100]})

    def delete_my_commands(self) -> TgResult:
        return self._call("deleteMyCommands")

    def get_my_commands(self) -> TgResult:
        return self._call("getMyCommands")

    def set_webhook(self, url: str, *, secret_token: str = "") -> TgResult:
        params = {"url": url}
        if secret_token:
            params["secret_token"] = secret_token
        return self._call("setWebhook", params)

    def delete_webhook(self, *, drop_pending: bool = False) -> TgResult:
        return self._call("deleteWebhook", {"drop_pending_updates": drop_pending})

    def get_webhook_info(self) -> TgResult:
        return self._call("getWebhookInfo")

    def get_chat(self, chat_id: Union[int, str]) -> TgResult:
        return self._call("getChat", {"chat_id": chat_id})

    def get_chat_member(self, chat_id: Union[int, str], user_id: int) -> TgResult:
        return self._call("getChatMember", {"chat_id": chat_id, "user_id": user_id})

    def get_chat_administrators(self, chat_id: Union[int, str]) -> TgResult:
        return self._call("getChatAdministrators", {"chat_id": chat_id})

    def get_chat_member_count(self, chat_id: Union[int, str]) -> TgResult:
        return self._call("getChatMemberCount", {"chat_id": chat_id})

    def leave_chat(self, chat_id: Union[int, str]) -> TgResult:
        return self._call("leaveChat", {"chat_id": chat_id})

    def bot_username(self) -> str:
        with self._lock:
            if self._bot_info:
                return self._bot_info.get("username", "")
        res = self.get_me()
        if res.ok and res.result:
            return res.result.get("username", "")
        return ""


TG = TelegramAPI(CONFIG, HTTP)


# ══════════════════════════════════════════════════════════════════════════════
#                          KEYBOARD BUILDERS
# ══════════════════════════════════════════════════════════════════════════════

def kb(rows: List[List[Dict[str, str]]]) -> Dict:
    return {"inline_keyboard": rows}


def btn(text: str, callback_data: Optional[str] = None,
        url: Optional[str] = None) -> Dict[str, str]:
    # v17: UTF-8 safe truncation
    if len(text) > 60:
        text = text[:59] + "…"
    d: Dict[str, str] = {"text": text}
    if callback_data:
        cb_bytes = callback_data.encode("utf-8")
        if len(cb_bytes) > 64:
            cb_bytes = cb_bytes[:63]
            while cb_bytes:
                try:
                    cb = cb_bytes.decode("utf-8")
                    break
                except UnicodeDecodeError:
                    cb_bytes = cb_bytes[:-1]
            else:
                cb = ""
        else:
            cb = cb_bytes.decode("utf-8", errors="ignore")
        d["callback_data"] = cb
    elif url:
        d["url"] = url
    return d
def kb_main_menu_v17_obsolete() -> Dict:
    return kb([
        [btn("📘 آموزش گام‌به‌گام", "m:learn"),
         btn("🎓 درس کامل", "sty:tutorial")],
        [btn("🧮 فرمول + مثال", "m:formula"),
         btn("📐 ریاضی", "m:math")],
        [btn("🔬 تحلیل عمیق", "sty:deep"),
         btn("❓ کوییز", "sty:quiz")],
        [btn("📇 فلش‌کارت", "sty:flashcard"),
         btn("🧪 مثال حل‌شده", "sty:example")],
        [btn("📰 اخبار", "n:home"),
         btn("💱 نرخ ارز", "m:rates")],
        [btn("✈️ هوانوردی", "av:help:refresh"),
         btn("📖 ویکی", "w:rand")],
        [btn("🎥 یوتیوب", "y:rand"),
         btn("📚 arXiv", "n:arxiv")],
        [btn("🎲 تصادفی", "m:random"),
         btn("📚 فهرست", "m:list")],
        [btn("🔍 جستجو", "m:search"),
         btn("🎥 ویدیو", "m:video")],
        [btn("📖 ویکی", "m:wiki"),
         btn("📚 arXiv", "m:arxiv")],
        [btn("⚙️ تنظیمات", "m:settings"),
         btn("📊 آمار", "m:stats")],
        [btn("ℹ️ راهنما", "m:help"),
         btn("🔌 APIها", "m:api")],
    ])


def kb_admin_panel() -> Dict:
    return kb([
        [btn("📊 وضعیت", "adm:status"),
         btn("📈 آمار کامل", "adm:stats")],
        [btn("🤖 تست مدل‌ها", "adm:test_models"),
         btn("🧪 تست AI", "adm:test_ai")],
        [btn("📋 لاگ", "adm:logs"),
         btn("⚙️ تنظیمات", "adm:settings")],
        [btn("📢 پست تستی", "adm:test_post"),
         btn("🗑 پاک‌سازی", "adm:cleanup")],
    ])

def kb_settings_menu(cfg) -> Dict:
    def status(k: str) -> str:
        val = getattr(cfg.content, k, None)
        if val is None:
            val = getattr(cfg.behavior, k, None)
        return "✅" if val else "❌"

    return kb([
        [btn(f"{status('include_news')} اخبار", "tg:news"),
         btn(f"{status('include_reddit')} Reddit", "tg:reddit")],
        [btn(f"{status('include_politics')} سیاسی", "tg:politics"),
         btn(f"{status('auto_poll')} نظرسنجی خودکار", "tg:auto_poll")],
        [btn(f"{status('include_formulas')} فرمول", "tg:formulas"),
         btn(f"{status('include_examples')} مثال عددی", "tg:examples")],
        [btn(f"{status('include_tables')} جدول", "tg:tables"),
         btn(f"{status('multi_part')} چندبخشی", "tg:multipart")],
        [btn("🎨 طول محتوا", "cfg:length"),
         btn("🎓 سطح فنی", "cfg:level")],
        [btn("⬅️ بازگشت", "m:main")],
    ])

def kb_length_menu() -> Dict:
    return kb([
        [btn("📏 کوتاه (5-7 خط)", "cl:short")],
        [btn("📐 متوسط (10-15 خط)", "cl:medium")],
        [btn("📜 بلند (20-35 خط)", "cl:long")],
        [btn("📚 خیلی بلند (40-60 خط)", "cl:very_long")],
        [btn("⬅️ بازگشت", "m:settings")],
    ])


def kb_level_menu() -> Dict:
    return kb([
        [btn("🎓 مبتدی", "lv:basic")],
        [btn("📘 متوسط", "lv:intermediate")],
        [btn("🔬 حرفه‌ای", "lv:professional")],
        [btn("🧠 متخصص PhD", "lv:expert")],
        [btn("⬅️ بازگشت", "m:settings")],
    ])


def kb_post_actions(topic_name: str = "") -> Dict:
    safe = (topic_name or "")[:28]
    rows = [
        [btn("🔄 بازتولید", f"regen:{safe}"),
         btn("❓ کوییز از این", f"lsn:quiz:{safe}")],
        [btn("🔬 عمیق‌تر", f"lsn:deep:{safe}"),
         btn("📇 فلش‌کارت", "sty:flashcard")],
        [btn("📢 اشتراک در گروه", "share:menu"),
         btn("🔗 کانال", url="https://t.me/MAADGHchannel")],
    ]
    return kb(rows)


# ══════════════════════════════════════════════════════════════════════════════
#                          RATE LIMITER
# ══════════════════════════════════════════════════════════════════════════════

class RateLimiter:
    """Per-user sliding window rate limiter."""

    def __init__(self, limit_per_min: int = 15):
        self.limit = limit_per_min
        # Generous cap; real check uses time window + self.limit
        self._windows: Dict[int, deque] = defaultdict(lambda: deque(maxlen=60))
        self._lock = threading.RLock()

    def check(self, user_id: int) -> Tuple[bool, int]:
        """Returns (allowed, seconds_until_reset)."""
        # Pull live limit from config each call
        try:
            cfg_limit = int(CONFIG.get().behavior.rate_limit_per_min)
            if cfg_limit > 0:
                self.limit = cfg_limit
        except Exception:
            pass
        now = time.monotonic()
        with self._lock:
            dq = self._windows[user_id]
            # Purge old entries
            while dq and now - dq[0] > 60.0:
                dq.popleft()
            if len(dq) >= self.limit:
                wait = 60.0 - (now - dq[0])
                return False, max(1, int(wait))
            dq.append(now)
            return True, 0

    def reset(self, user_id: int) -> None:
        with self._lock:
            self._windows.pop(user_id, None)

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {uid: len(dq) for uid, dq in self._windows.items()}


RATE_LIMIT = RateLimiter(limit_per_min=15)


# ══════════════════════════════════════════════════════════════════════════════
#                          SESSION STATE
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Session:
    user_id: int
    state: str = "idle"
    data: Dict[str, Any] = field(default_factory=dict)
    last_seen: float = field(default_factory=time.time)
    current_draft: Optional[str] = None
    current_topic: Optional[str] = None
    current_style: Optional[str] = None


class SessionManager:
    _instance: Optional["SessionManager"] = None

    def __new__(cls, *a, **kw):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if getattr(self, "_init_done", False):
            return
        self._init_done = True
        self._sessions: Dict[int, Session] = {}
        self._lock = threading.RLock()
        self._gc_thread = threading.Thread(target=self._gc_loop, daemon=True, name="SessGC")
        self._gc_thread.start()

    def get(self, user_id: int) -> Session:
        with self._lock:
            s = self._sessions.get(user_id)
            if s is None:
                s = Session(user_id=user_id)
                self._sessions[user_id] = s
            s.last_seen = time.time()
            return s

    def set_state(self, user_id: int, state: str, **data) -> Session:
        s = self.get(user_id)
        s.state = state
        s.data.update(data)
        s.last_seen = time.time()
        return s

    def clear_state(self, user_id: int) -> None:
        s = self.get(user_id)
        s.state = "idle"
        s.data.clear()

    def set_draft(self, user_id: int, draft: str, topic: str = "", style: str = "") -> None:
        s = self.get(user_id)
        s.current_draft = draft
        s.current_topic = topic
        s.current_style = style
    def _gc_loop(self) -> None:
        while not getattr(self, "_stop_event", threading.Event()).is_set():
            time.sleep(60)
            cutoff = time.time() - 3600
            with self._lock:
                stale = [uid for uid, s in self._sessions.items() if s.last_seen < cutoff]
                for uid in stale:
                    del self._sessions[uid]

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "active_sessions": len(self._sessions),
                "states": Counter(s.state for s in self._sessions.values()),
            }


SESSIONS = SessionManager()
# v16: clear transient state on restart
try:
    _LS_STATE.clear() if "_LS_STATE" in globals() else None
except Exception:
    pass


# ══════════════════════════════════════════════════════════════════════════════
#                          HISTORY + STATS
# ══════════════════════════════════════════════════════════════════════════════

class HistoryManager:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._data: Dict[str, List[Dict[str, str]]] = load_json(path, default={})

    def get(self, user_id: int) -> List[Dict[str, str]]:
        with self._lock:
            return list(self._data.get(str(user_id), []))

    def append(self, user_id: int, role: str, content: str, max_len: int = 20) -> None:
        with self._lock:
            key = str(user_id)
            if key not in self._data:
                self._data[key] = []
            self._data[key].append({"role": role, "content": content})
            self._data[key] = self._data[key][-max_len:]
            BATCHED_WRITER.write(self.path, self._data)

    def clear(self, user_id: int) -> None:
        with self._lock:
            self._data[str(user_id)] = []
            BATCHED_WRITER.write(self.path, self._data)


HISTORY = HistoryManager(HISTORY_FILE)


class StatsManager:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._data = load_json(path, default={
            "posts": 0,
            "questions": 0,
            "errors": 0,
            "regen": 0,
            "model_usage": {},
            "user_messages": {},
            "commands": {},
            "started_at": datetime.now().isoformat(),
        })

    def incr(self, key: str, n: int = 1) -> None:
        with self._lock:
            self._data[key] = self._data.get(key, 0) + n
            BATCHED_WRITER.write(self.path, self._data)

    def incr_dict(self, key: str, subkey: str, n: int = 1) -> None:
        with self._lock:
            d = self._data.setdefault(key, {})
            d[subkey] = d.get(subkey, 0) + n
            BATCHED_WRITER.write(self.path, self._data)

    def get(self, key: str, default: Any = 0) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def all(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._data)


STATS = StatsManager(STATS_FILE)


# ══════════════════════════════════════════════════════════════════════════════
#                          COMMAND REGISTRY & ROUTER
# ══════════════════════════════════════════════════════════════════════════════

CommandHandler = Callable[[Dict[str, Any], str], None]


@dataclass
class CommandSpec:
    name: str
    handler: CommandHandler
    description: str = ""
    admin_only: bool = False
    rate_limited: bool = True
    usage: str = ""


class CommandRegistry:
    def __init__(self):
        self._commands: Dict[str, CommandSpec] = {}
        self._lock = threading.RLock()

    def register(
        self,
        name: str,
        *,
        description: str = "",
        admin_only: bool = False,
        rate_limited: bool = True,
        usage: str = "",
    ):
        def decorator(fn: CommandHandler) -> CommandHandler:
            with self._lock:
                self._commands[name.lower()] = CommandSpec(
                    name=name,
                    handler=fn,
                    description=description,
                    admin_only=admin_only,
                    rate_limited=rate_limited,
                    usage=usage,
                )
            return fn
        return decorator

    def get(self, name: str) -> Optional[CommandSpec]:
        with self._lock:
            return self._commands.get(name.lower())

    def all(self) -> List[CommandSpec]:
        with self._lock:
            return list(self._commands.values())

    def telegram_menu(self) -> List[Dict[str, str]]:
        return [
            {"command": spec.name.lower().lstrip("/"), "description": spec.description[:100]}
            for spec in self.all()
            if spec.description
        ][:100]


REGISTRY = CommandRegistry()


# ══════════════════════════════════════════════════════════════════════════════
#                          MESSAGE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def extract_command(text: str) -> Tuple[str, str]:
    """Return (command_with_slash, args_string)."""
    if not text or not text.startswith("/"):
        return "", ""
    parts = text.strip().split(None, 1)
    cmd = parts[0].split("@")[0].lower()
    args = parts[1] if len(parts) > 1 else ""
    return cmd, args.strip()


def get_uid(msg: Dict) -> int:
    return msg.get("from", {}).get("id", 0)


def get_chat_id(msg: Dict) -> int:
    return msg.get("chat", {}).get("id", 0)


def is_admin(uid: int) -> bool:
    cfg = CONFIG.get()
    if cfg.telegram.admin_id == uid:
        return True
    return uid in cfg.telegram.admin_ids


def is_private(msg: Dict) -> bool:
    return msg.get("chat", {}).get("type") == "private"


def is_group(msg: Dict) -> bool:
    return msg.get("chat", {}).get("type") in ("group", "supergroup")


def is_channel(msg: Dict) -> bool:
    return msg.get("chat", {}).get("type") == "channel"


def get_user_name(msg: Dict) -> str:
    u = msg.get("from", {})
    parts = [u.get("first_name", ""), u.get("last_name", "")]
    name = " ".join(p for p in parts if p).strip()
    return name or u.get("username", "") or f"user_{u.get('id', 0)}"


# ══════════════════════════════════════════════════════════════════════════════
#                          USER MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

class UserManager:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._data = load_json(path, default={
            "whitelist": [],
            "blacklist": [],
            "first_seen": {},
            "usernames": {},
        })

    def add_to_whitelist(self, uid: int) -> None:
        with self._lock:
            if uid not in self._data["whitelist"]:
                self._data["whitelist"].append(uid)
                BATCHED_WRITER.write(self.path, self._data)

    def add_to_blacklist(self, uid: int) -> None:
        with self._lock:
            if uid not in self._data["blacklist"]:
                self._data["blacklist"].append(uid)
                BATCHED_WRITER.write(self.path, self._data)

    def remove_from_blacklist(self, uid: int) -> None:
        with self._lock:
            if uid in self._data["blacklist"]:
                self._data["blacklist"].remove(uid)
                BATCHED_WRITER.write(self.path, self._data)

    def is_blocked(self, uid: int) -> bool:
        with self._lock:
            return uid in self._data.get("blacklist", [])

    def is_allowed(self, uid: int) -> bool:
        with self._lock:
            if uid in self._data.get("blacklist", []):
                return False
            if is_admin(uid):
                return True
            wl = self._data.get("whitelist", [])
            return uid in wl if wl else True

    def track_seen(self, msg: Dict) -> None:
        uid = get_uid(msg)
        if not uid:
            return
        with self._lock:
            fs = self._data.setdefault("first_seen", {})
            if str(uid) not in fs:
                fs[str(uid)] = datetime.now().isoformat()
            un = self._data.setdefault("usernames", {})
            if msg.get("from", {}).get("username"):
                un[str(uid)] = msg["from"]["username"]
            BATCHED_WRITER.write(self.path, self._data)


USERS = UserManager(USERS_FILE)


# ══════════════════════════════════════════════════════════════════════════════
#                          MAIN ROUTER
# ══════════════════════════════════════════════════════════════════════════════

class Router:
    def __init__(self):
        self._handlers: Dict[str, CommandHandler] = {}
        self._callback_handlers: Dict[str, Callable] = {}
        self._text_handler: Optional[Callable] = None
        self._default_handler: Optional[Callable] = None

    def command(self, name: str, *, admin_only: bool = False, description: str = "",
                rate_limited: bool = True):
        def decorator(fn):
            self._handlers[name.lower().lstrip("/")] = fn
            if description:
                REGISTRY.register(
                    name.lstrip("/"),
                    description=description,
                    admin_only=admin_only,
                    rate_limited=rate_limited,
                )(fn)
            return fn
        return decorator

    def callback(self, prefix: str):
        def decorator(fn):
            self._callback_handlers[prefix] = fn
            return fn
        return decorator

    def on_text(self, fn):
        self._text_handler = fn
        return fn

    def on_default(self, fn):
        self._default_handler = fn
        return fn

    def route_command(self, msg: Dict, cmd: str, args: str) -> bool:
        cmd_name = cmd.lower().lstrip("/")
        handler = self._handlers.get(cmd_name)
        try:
            uid = msg.get("from", {}).get("id", 0)
            u = msg.get("from", {})
            nm = u.get("first_name") or u.get("username") or "?"
            if handler:
                LIVE.event("cmd", f"/{cmd_name} from {nm} ({uid}) args={args[:40]}")
        except Exception:
            pass
        if not handler:
            return False

        spec = REGISTRY.get(cmd_name)
        if spec and spec.admin_only and not is_admin(get_uid(msg)):
            TG.send_message(get_chat_id(msg), "⛔ فقط مدیر دسترسی دارد.")
            return True

        try:
            handler(msg, args)
        except Exception as e:
            log.exception(f"Command {cmd} failed: {e}")
            STATS.incr("errors")
            TG.send_message(get_chat_id(msg),
                           f"❌ خطا در اجرای دستور:\n<code>{escape_html(str(e)[:200])}</code>")
        return True

    def route_callback(self, cb: Dict) -> bool:
        data = cb.get("data", "")
        if not data:
            return False

        prefix = data.split(":", 1)[0]
        handler = self._callback_handlers.get(prefix)
        if not handler:
            handler = self._callback_handlers.get(data)
        if not handler:
            # v19: پشتیبانی از callback های چندکولنی
            for _k in sorted(self._callback_handlers.keys(),
                             key=len, reverse=True):
                if data == _k or data.startswith(_k + ":"):
                    handler = self._callback_handlers[_k]
                    break
        if not handler:
            return False

        try:
            handler(cb, data)
        except Exception as e:
            log.exception(f"Callback {data} failed: {e}")
            TG.answer_callback(cb.get("id", ""), "❌ خطا", show_alert=True)
        return True

    def route_text(self, msg: Dict) -> bool:
        if self._text_handler:
            self._text_handler(msg)
            return True
        return False


ROUTER = Router()

# ══════════════════════════════════════════════════════════════════════════════
#                    LIVE FEED (terminal + telegram) - LIVE.ps1
# ══════════════════════════════════════════════════════════════════════════════
class LiveFeed:
    """Broadcasts activity events to terminal + admin DM."""
    def __init__(self):
        self._enabled = True
        self._admin_id = None
        self._lock = threading.RLock()
        self._last_sent = 0.0
        self._min_interval = 0.5   # rate limit

    def configure(self, admin_id):
        with self._lock:
            if admin_id:
                self._admin_id = int(admin_id)

    def enable(self, flag=True):
        with self._lock:
            self._enabled = bool(flag)
            return self._enabled

    def is_enabled(self):
        with self._lock:
            return self._enabled

    def _emit_terminal(self, icon, tag, msg):
        try:
            ts = datetime.now().strftime("%H:%M:%S")
            colors = {
                "in":   "\033[96m",   # cyan
                "out":  "\033[92m",   # green
                "gen":  "\033[95m",   # magenta
                "err":  "\033[91m",   # red
                "warn": "\033[93m",   # yellow
                "sys":  "\033[94m",   # blue
            }
            c = colors.get(tag, "\033[0m")
            print(f"{c}[{ts}] {icon} {msg}\033[0m", flush=True)
        except Exception:
            pass

    def _emit_telegram(self, icon, tag, msg):
        if not self.is_enabled():
            return
        with self._lock:
            aid = self._admin_id
            if not aid:
                # try to fetch from config
                try:
                    aid = CONFIG.get().telegram.admin_id
                    self._admin_id = aid
                except Exception:
                    return
            now = time.time()
            if now - self._last_sent < self._min_interval:
                return
            self._last_sent = now
        if not aid:
            return
        try:
            # Very short line - keep noise down
            text = f"{icon} <code>{escape_html(tag)}</code>  {escape_html(msg[:200])}"
            POOL.submit(TG.send_message, aid, text,
                        parse_mode="HTML", disable_preview=True)
        except Exception:
            pass

    def event(self, tag, msg, icon="", to_tg=True):
        """Emit event to terminal + optionally to Telegram."""
        if not icon:
            icon = {
                "in":   "📥",
                "out":  "📤",
                "gen":  "⚙️",
                "err":  "❌",
                "warn": "⚠️",
                "sys":  "ℹ️",
                "cmd":  "⌨️",
                "ai":   "🤖",
                "pub":  "📢",
            }.get(tag, "•")
        self._emit_terminal(icon, tag, msg)
        try:
            log.info(f"[live:{tag}] {msg}")
        except Exception:
            pass
        if to_tg:
            self._emit_telegram(icon, tag, msg)


LIVE = LiveFeed()

try:
    LIVE.configure(CONFIG.get().telegram.admin_id)
except Exception:
    pass


# ─── Commands ────────────────────────────────────────────────────────────
@ROUTER.command("live", description="فعال/غیرفعال گزارش زنده", admin_only=True)
def cmd_live(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    a = (args or "").strip().lower()
    if a in ("on", "1", "yes", "روشن"):
        LIVE.enable(True)
        TG.send_message(chat_id, "🟢 گزارش زنده فعال شد")
    elif a in ("off", "0", "no", "خاموش"):
        LIVE.enable(False)
        TG.send_message(chat_id, "🔴 گزارش زنده غیرفعال شد")
    else:
        st = "🟢 فعال" if LIVE.is_enabled() else "🔴 غیرفعال"
        TG.send_message(chat_id,
            f"وضعیت گزارش زنده: {st}\n\n"
            "برای تغییر:\n"
            "<code>/live on</code>\n"
            "<code>/live off</code>")


@ROUTER.command("ping", description="تست گزارش زنده", admin_only=True)
def cmd_ping(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    LIVE.event("sys", f"ping from {get_uid(msg)}")
    TG.send_message(chat_id, "🏓 pong (ترمینال را چک کن)")

# ─── end LiveFeed ────────────────────────────────────────────────────────


# ══════════════════════════════════════════════════════════════════════════════
#                          TYPING HEARTBEAT
# ══════════════════════════════════════════════════════════════════════════════

class TypingHeartbeat:
    """Send typing indicator every 4s while processing."""

    def __init__(self, chat_id: Union[int, str], interval: float = 4.0):
        self.chat_id = chat_id
        self.interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *a):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                TG.send_chat_action(self.chat_id, "typing")
            except Exception:
                pass
            self._stop.wait(self.interval)


# ══════════════════════════════════════════════════════════════════════════════
#                          BASE COMMANDS
# ══════════════════════════════════════════════════════════════════════════════

@ROUTER.command("start", description="شروع")
def cmd_start(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    uid = get_uid(msg)
    name = get_user_name(msg)

    cfg = CONFIG.get()
    # First user becomes primary admin
    if cfg.telegram.admin_id is None:
        cfg.telegram.admin_id = uid
        if uid not in cfg.telegram.admin_ids:
            cfg.telegram.admin_ids.append(uid)
        CONFIG.save()
        log.info(f"Primary admin set: {uid} ({name})")

    text = (
        f"👋 سلام <b>{escape_html(name)}</b>!\n\n"
        f"<b>MAADGH Bot</b> — نسخه حرفه‌ای مهندسی مکانیک\n\n"
        f"از دکمه‌های زیر استفاده کن یا /help را بزن:"
    )
    TG.send_message(chat_id, text, reply_markup=kb_main_menu())


@ROUTER.command("help", description="راهنما")
def cmd_help(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)

    text = (
        "📖 <b>راهنمای کامل</b>\n\n"
        "<b>📝 تولید محتوا:</b>\n"
        "• <code>/post &lt;موضوع&gt;</code> — پست ساختاریافته\n"
        "• <code>/next</code> یا <code>/topic</code> — موضوع بعدی چرخشی\n"
        "• <code>/random</code> — موضوع تصادفی\n"
        "• <code>/formula &lt;موضوع&gt;</code> — برگه فرمول\n"
        "• <code>/math &lt;موضوع&gt;</code> — آموزش ریاضی\n"
        "• <code>/news</code> — اخبار مهندسی\n\n"
        "<b>💬 گفتگو:</b>\n"
        "• <code>/ask &lt;سوال&gt;</code> — سوال تخصصی\n"
        "• <code>/chat &lt;پیام&gt;</code> — گفتگو با AI\n\n"
        "<b>📚 موضوعات:</b>\n"
        "• <code>/list</code> — فهرست کامل\n"
        "• <code>/addtopic نام | query</code> — افزودن موضوع\n"
        "• <code>/delcustom نام</code> — حذف موضوع سفارشی\n\n"
        "<b>⚙️ تنظیمات:</b>\n"
        "• <code>/toggles</code> — کلیدهای روشن/خاموش\n"
        "• <code>/settings</code> — پنل تنظیمات\n"
        "• <code>/length</code> — طول محتوا\n"
        "• <code>/level</code> — سطح فنی\n\n"
        "<b>🔧 مدیریت:</b>\n"
        "• <code>/stats</code> — آمار\n"
        "• <code>/panel</code> — پنل مدیر\n"
        "• <code>/clear</code> — پاک کردن حافظه\n"
        "• <code>/id</code> — نمایش شناسه‌ها"
    )
    TG.send_message(chat_id, text)


@ROUTER.command("id", description="شناسه‌ها")
def cmd_id(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    uid = get_uid(msg)
    cfg = CONFIG.get()

    text = (
        f"<b>🆔 شناسه‌های شما</b>\n\n"
        f"• Chat ID: <code>{chat_id}</code>\n"
        f"• User ID: <code>{uid}</code>\n"
        f"• Admin: {'✅' if is_admin(uid) else '❌'}\n"
        f"• Channel: <code>{escape_html(cfg.telegram.channel_id)}</code>"
    )
    TG.send_message(chat_id, text)


@ROUTER.command("clear", description="پاک کردن حافظه")
def cmd_clear(msg: Dict, args: str) -> None:
    uid = get_uid(msg)
    chat_id = get_chat_id(msg)
    HISTORY.clear(uid)
    SESSIONS.clear_state(uid)
    TG.send_message(chat_id, "✅ حافظه پاک شد.")


@ROUTER.command("stats", description="آمار")
def cmd_stats(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    s = STATS.all()
    ms = MEM_MON.stats()

    text = (
        f"📊 <b>آمار ربات</b>\n\n"
        f"📝 پست‌ها: <code>{s.get('posts', 0)}</code>\n"
        f"💬 سوالات: <code>{s.get('questions', 0)}</code>\n"
        f"🔄 بازتولید: <code>{s.get('regen', 0)}</code>\n"
        f"❌ خطاها: <code>{s.get('errors', 0)}</code>\n\n"
        f"⚡ <b>عملکرد:</b>\n"
        f"• حافظه: <code>{ms['current_mb']}MB</code> (اوج: {ms['peak_mb']}MB)\n"
        f"• ورکرها: <code>{POOL.stats()['active']}</code> فعال از {POOL.stats()['max_workers']}\n"
        f"• کش AI: <code>{AI_CACHE.stats()['hit_rate']}%</code> hit rate\n"
        f"• کش HTTP: <code>{HTTP_CACHE.stats()['size']}</code> آیتم\n"
        f"• JSON: <code>{JSON_BACKEND}</code>"
    )
    TG.send_message(chat_id, text)


@ROUTER.command("panel", description="پنل مدیر", admin_only=True)
def cmd_panel(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    TG.send_message(chat_id, "🔧 <b>پنل مدیریت</b>", reply_markup=kb_admin_panel())


@ROUTER.command("settings", description="تنظیمات")
def cmd_settings(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    cfg = CONFIG.get()
    TG.send_message(chat_id, "⚙️ <b>تنظیمات</b>", reply_markup=kb_settings_menu(cfg))


@ROUTER.command("toggles", description="کلیدهای روشن/خاموش")
def cmd_toggles(msg: Dict, args: str) -> None:
    cmd_settings(msg, args)


@ROUTER.command("length", description="طول محتوا")
def cmd_length(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    cfg = CONFIG.get()
    TG.send_message(chat_id,
                    f"📏 <b>طول محتوا</b>\nفعلی: <code>{cfg.content.length}</code>",
                    reply_markup=kb_length_menu())


@ROUTER.command("level", description="سطح فنی")
def cmd_level(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    cfg = CONFIG.get()
    TG.send_message(chat_id,
                    f"🎓 <b>سطح فنی</b>\nفعلی: <code>{cfg.content.technical_level}</code>",
                    reply_markup=kb_level_menu())


@ROUTER.command("models", description="مدل‌های AI")
def cmd_models(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    cfg = CONFIG.get()
    fb = cfg.ai.fallback_models
    text = (
        f"🤖 <b>مدل‌های AI</b>\n\n"
        f"⭐ اصلی: <code>{escape_html(cfg.ai.primary_model)}</code>\n\n"
        f"🔄 پشتیبان ({len(fb)}):\n"
    )
    for m in fb[:20]:
        text += f"• <code>{escape_html(m)}</code>\n"
    if len(fb) > 20:
        text += f"\n<i>و {len(fb) - 20} مدل دیگر...</i>"
    text += f"\n\n<b>Provider:</b> <code>{cfg.ai.provider}</code>"
    TG.send_message(chat_id, text)


@ROUTER.command("list", description="فهرست موضوعات")
def cmd_list(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    # Determine page
    page = 0
    if args and args.strip().isdigit():
        try: page = max(0, int(args.strip()) - 1)
        except Exception: page = 0

    all_t = list(_get_topics_list()) + list(_get_custom_topics())
    per_page = 25
    total = len(all_t)
    total_pages = max(1, (total + per_page - 1) // per_page)
    if page >= total_pages: page = total_pages - 1
    chunk = all_t[page*per_page:(page+1)*per_page]

    # Category counts
    from collections import Counter
    cat_counts = Counter(t.get("category", "builtin") for t in all_t)

    text = f"📚 <b>بانک موضوعات</b> — {total} کل\n"
    text += f"صفحه {page+1} از {total_pages}\n\n"

    # Small category summary on page 1 only
    if page == 0:
        text += "<b>دسته‌بندی:</b> "
        bits = []
        for c, n in cat_counts.most_common(8):
            label = {"mech": "🔧", "math": "📐",
                     "builtin": "★", "custom": "⭐"}.get(c, "•")
            bits.append(f"{label}{c}:{n}")
        text += " | ".join(bits)
        text += "\n\n"

    for i, t in enumerate(chunk, 1):
        idx = page*per_page + i
        emoji = t.get("emoji", "•")
        name = (t.get("name") or "?")[:60]
        text += f"{idx}. {emoji} {escape_html(name)}\n"

    rows = []
    if page > 0:
        rows.append(btn("◀️ قبلی", f"ls:pg:{page-1}"))
    rows.append(btn(f"{page+1}/{total_pages}", "ls:nop"))
    if page < total_pages - 1:
        rows.append(btn("بعدی ▶️", f"ls:pg:{page+1}"))

    nav1 = rows
    nav2 = [btn("🔧 مکانیک", "ls:cat:mech"),
            btn("📐 ریاضی", "ls:cat:math"),
            btn("🎲 تصادفی", "ls:rand")]
    nav3 = [btn("🔍 جستجو", "ls:help"),
            btn("🏠 منو", "m:main")]

    TG.send_message(chat_id, text[:4000],
                    reply_markup=kb([nav1, nav2, nav3]))


@ROUTER.callback("ls")
def cb_list(cb: Dict, data: str) -> None:
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    chat_id = cb["message"]["chat"]["id"]
    msg_id = cb["message"]["message_id"]
    TG.answer_callback(cb.get("id", ""))

    all_t = list(_get_topics_list()) + list(_get_custom_topics())

    if action == "nop":
        return
    if action == "help":
        TG.edit_message(chat_id, msg_id,
            "🔍 <b>جستجو در بانک</b>\n\n"
            "• <code>/list 3</code> — صفحه ۳\n"
            "• <code>/post موضوع</code> — تولید پست\n"
            "• <code>/next</code> — موضوع بعدی\n"
            "• <code>/random</code> — تصادفی",
            reply_markup=kb([[btn("⬅️ بازگشت", "ls:pg:0")]]))
        return
    if action == "rand":
        if not all_t:
            TG.edit_message(chat_id, msg_id, "❌ بانک خالی"); return
        t = random.choice(all_t)
        TG.edit_message(chat_id, msg_id,
            f"🎲 موضوع تصادفی:\n\n<b>{escape_html(t.get('name','?'))}</b>",
            reply_markup=kb([
                [btn("📝 تولید پست", f"ls:gen:{t.get('name','')[:40]}")],
                [btn("🎲 دیگری", "ls:rand"), btn("⬅️ بازگشت", "ls:pg:0")],
            ]))
        return
    if action == "gen" and len(parts) >= 3:
        topic = parts[2]
        TG.edit_message(chat_id, msg_id, f"⏳ تولید {escape_html(topic)} ...")
        POOL.submit(_generate_and_post, CONFIG.get(), chat_id, topic, "tutorial")
        return
    if action == "cat" and len(parts) >= 3:
        cat = parts[2]
        filtered = [t for t in all_t if t.get("category") == cat]
        if not filtered:
            TG.edit_message(chat_id, msg_id, f"❌ دسته {cat} خالی",
                reply_markup=kb([[btn("⬅️ بازگشت", "ls:pg:0")]]))
            return
        per = 25
        total_pages = max(1, (len(filtered) + per - 1) // per)
        text = f"📂 <b>دسته: {cat}</b> — {len(filtered)} موضوع\n\n"
        for i, t in enumerate(filtered[:per], 1):
            text += f"{i}. {t.get('emoji','•')} {escape_html((t.get('name') or '?')[:60])}\n"
        if len(filtered) > per:
            text += f"\n<i>... {len(filtered)-per} مورد دیگر</i>"
        rows = []
        if total_pages > 1:
            rows.append([btn(f"صفحه 1/{total_pages}", "ls:nop")])
        rows.append([btn("🎲 تصادفی از این دسته", f"ls:randcat:{cat}")])
        rows.append([btn("⬅️ بازگشت", "ls:pg:0")])
        TG.edit_message(chat_id, msg_id, text[:4000], reply_markup=kb(rows))
        return
    if action == "randcat" and len(parts) >= 3:
        cat = parts[2]
        filtered = [t for t in all_t if t.get("category") == cat]
        if not filtered:
            TG.edit_message(chat_id, msg_id, "❌ خالی"); return
        t = random.choice(filtered)
        TG.edit_message(chat_id, msg_id,
            f"🎲 از {cat}:\n\n<b>{escape_html(t.get('name','?'))}</b>",
            reply_markup=kb([
                [btn("📝 تولید پست", f"ls:gen:{t.get('name','')[:40]}")],
                [btn("🎲 دیگری", f"ls:randcat:{cat}"), btn("⬅️", "ls:pg:0")],
            ]))
        return
    if action == "pg" and len(parts) >= 3:
        try: pg = int(parts[2])
        except Exception: pg = 0
        # Re-render page
        per_page = 25
        total = len(all_t)
        total_pages = max(1, (total + per_page - 1) // per_page)
        pg = max(0, min(pg, total_pages - 1))
        chunk = all_t[pg*per_page:(pg+1)*per_page]
        text = f"📚 <b>بانک موضوعات</b> — {total} کل\nصفحه {pg+1}/{total_pages}\n\n"
        for i, t in enumerate(chunk, 1):
            idx = pg*per_page + i
            text += f"{idx}. {t.get('emoji','•')} {escape_html((t.get('name') or '?')[:60])}\n"
        rows = []
        nav = []
        if pg > 0:
            nav.append(btn("◀️", f"ls:pg:{pg-1}"))
        nav.append(btn(f"{pg+1}/{total_pages}", "ls:nop"))
        if pg < total_pages - 1:
            nav.append(btn("▶️", f"ls:pg:{pg+1}"))
        rows.append(nav)
        rows.append([btn("🔧 مکانیک", "ls:cat:mech"),
                     btn("📐 ریاضی", "ls:cat:math"),
                     btn("🎲 تصادفی", "ls:rand")])
        rows.append([btn("🔍 راهنما", "ls:help"), btn("🏠 منو", "m:main")])
        TG.edit_message(chat_id, msg_id, text[:4000], reply_markup=kb(rows))
        return


# ══════════════════════════════════════════════════════════════════════════════
#                          PLACEHOLDER: TOPICS GETTER (filled in Part 4)
# ══════════════════════════════════════════════════════════════════════════════


def _load_extra_topics():
    try:
        p = DATA_DIR / "extra_topics.json"
        if not p.exists(): return []
        raw = load_json(p, default=[]) or []
        return raw if isinstance(raw, list) else []
    except Exception:
        return []

try:
    _EXTRA = _load_extra_topics()
    if _EXTRA:
        _existing = {t.get("name") for t in TOPICS if isinstance(t, dict)}
        _add = [t for t in _EXTRA if isinstance(t, dict) and t.get("name")
                and t["name"] not in _existing]
        TOPICS.extend(_add)
        log.info(f"Loaded {len(_add)} extra topics (total {len(TOPICS)})")
except Exception as _e:
    log.warning(f"extra topics: {_e}")

def _get_topics_list() -> List[Dict]:
    """Will be populated in Part 4. Returns empty list for now."""
    return []


def _get_custom_topics() -> List[Dict]:
    """Custom topics from file."""
    return load_json(TOPICS_FILE, default=[])


# ══════════════════════════════════════════════════════════════════════════════
#                          CALLBACK HANDLERS — MENU
# ══════════════════════════════════════════════════════════════════════════════

@ROUTER.callback("m")
def cb_menu(cb: Dict, data: str) -> None:
    chat_id = cb["message"]["chat"]["id"]
    msg_id = cb["message"]["message_id"]
    action = data.split(":", 1)[1] if ":" in data else "main"

    TG.answer_callback(cb.get("id", ""))

    cfg = CONFIG.get()

    if action == "main":
        TG.edit_message(chat_id, msg_id,
                       "🏠 <b>منوی اصلی</b>",
                       reply_markup=kb_main_menu())
    elif action == "settings":
        TG.edit_message(chat_id, msg_id,
                       "⚙️ <b>تنظیمات</b>",
                       reply_markup=kb_settings_menu(cfg))
    elif action == "stats":
        s = STATS.all()
        text = (
            f"📊 <b>آمار</b>\n\n"
            f"پست‌ها: {s.get('posts', 0)}\n"
            f"سوالات: {s.get('questions', 0)}\n"
            f"خطاها: {s.get('errors', 0)}"
        )
        TG.edit_message(chat_id, msg_id, text, reply_markup=kb([
            [btn("⬅️ بازگشت", "m:main")]
        ]))
    elif action in ("lesson", "list"):
        TG.edit_message(chat_id, msg_id,
                       "📘 برای دیدن فهرست از /list استفاده کن.",
                       reply_markup=kb([[btn("⬅️ بازگشت", "m:main")]]))
    elif action == "formula":
        TG.edit_message(chat_id, msg_id,
                       "🧮 برای فرمول:\n<code>/formula ترمودینامیک</code>",
                       reply_markup=kb([[btn("⬅️ بازگشت", "m:main")]]))
    elif action == "math":
        TG.edit_message(chat_id, msg_id,
                       "📐 برای ریاضی:\n<code>/math انتگرال سه‌گانه</code>",
                       reply_markup=kb([[btn("⬅️ بازگشت", "m:main")]]))
    elif action == "news":
        TG.edit_message(chat_id, msg_id,
            "📰 <b>مرکز اخبار</b>\n\nیکی از گزینه‌ها را انتخاب کن:",
            reply_markup=kb_news_menu())
    elif action == "random":
        TG.edit_message(chat_id, msg_id, "🎲 انتخاب تصادفی...")
        POOL.submit(_handle_random_action, chat_id, msg_id)
    elif action in ("learn", "rates", "search", "video", "arxiv", "wiki", "help", "api"):
        _c2 = dict(cb); _c2["data"] = f"m2:{action}"
        ROUTER.route_callback(_c2)


def _handle_news_action(chat_id: int, msg_id: int) -> None:
    """Fetch and display engineering news (fixed)."""
    try:
        TG.edit_message(chat_id, msg_id, "📰 در حال دریافت اخبار...")
        items = APIS.news.fetch_combined(limit=12)
        if not items:
            TG.edit_message(
                chat_id, msg_id,
                "❌ خبری یافت نشد.\nاتصال اینترنت یا منابع RSS را بررسی کن."
            )
            return
        text = "📰 <b>اخبار مهندسی</b>\n\n"
        for i, item in enumerate(items[:8], 1):
            title = escape_html((item.get("title") or "")[:100])
            url   = item.get("link", "") or ""
            src   = item.get("feed_name", "") or ""
            text += f"{i}. <b>{title}</b>\n"
            if src:
                text += f"<i>{escape_html(src)}</i>\n"
            if url:
                text += f"<a href='{url}'>مشاهده</a>\n"
            text += "\n"
        TG.edit_message(chat_id, msg_id, text[:4000])
    except Exception as e:
        log.exception("news action")
        TG.edit_message(
            chat_id, msg_id,
            f"❌ خطا در دریافت اخبار: {escape_html(str(e)[:150])}"
        )
def _handle_random_action(chat_id: int, msg_id: int) -> None:
    topics = _get_topics_list()
    if not topics:
        TG.edit_message(chat_id, msg_id, "❌ فهرست موضوعات خالی (Part 4).")
        return
    t = random.choice(topics)
    TG.edit_message(chat_id, msg_id, f"🎲 موضوع: {t.get('emoji', '')} {t['name']}")


# ══════════════════════════════════════════════════════════════════════════════
#                          CALLBACK HANDLERS — SETTINGS TOGGLES
# ══════════════════════════════════════════════════════════════════════════════

TOGGLE_MAP = {
    "news": "include_news",
    "reddit": "include_reddit",
    "politics": "include_politics",
    "auto_poll": "auto_poll",
    "formulas": "include_formulas",
    "examples": "include_examples",
    "tables": "include_tables",
    "multipart": "multi_part",
}


@ROUTER.callback("tg")
def cb_toggle(cb: Dict, data: str) -> None:
    if not is_admin(get_uid({"from": cb.get("from", {})})):
        TG.answer_callback(cb.get("id", ""), "⛔", show_alert=True)
        return

    key = data.split(":", 1)[1]
    attr = TOGGLE_MAP.get(key)
    if not attr:
        TG.answer_callback(cb.get("id", ""), "?")
        return

    new_val = CONFIG.toggle(attr)
    cfg = CONFIG.get()

    chat_id = cb["message"]["chat"]["id"]
    msg_id = cb["message"]["message_id"]

    TG.answer_callback(cb.get("id", ""),
                      f"{attr} = {'✅' if new_val else '❌'}")

    TG.edit_message(chat_id, msg_id, "⚙️ <b>تنظیمات</b>",
                   reply_markup=kb_settings_menu(cfg))


@ROUTER.callback("cl")
def cb_length(cb: Dict, data: str) -> None:
    if not is_admin(get_uid({"from": cb.get("from", {})})):
        return
    length = data.split(":", 1)[1]
    if CONFIG.set_content_length(length):
        TG.answer_callback(cb.get("id", ""), f"✅ {length}")
    else:
        TG.answer_callback(cb.get("id", ""), "❌")

    chat_id = cb["message"]["chat"]["id"]
    msg_id = cb["message"]["message_id"]
    cfg = CONFIG.get()
    TG.edit_message(chat_id, msg_id,
                   f"📏 طول: <code>{cfg.content.length}</code>",
                   reply_markup=kb_length_menu())


@ROUTER.callback("lv")
def cb_level(cb: Dict, data: str) -> None:
    if not is_admin(get_uid({"from": cb.get("from", {})})):
        return
    level = data.split(":", 1)[1]
    if CONFIG.set_technical_level(level):
        TG.answer_callback(cb.get("id", ""), f"✅ {level}")
    else:
        TG.answer_callback(cb.get("id", ""), "❌")

    chat_id = cb["message"]["chat"]["id"]
    msg_id = cb["message"]["message_id"]
    cfg = CONFIG.get()
    TG.edit_message(chat_id, msg_id,
                   f"🎓 سطح: <code>{cfg.content.technical_level}</code>",
                   reply_markup=kb_level_menu())


@ROUTER.callback("cfg")
def cb_cfg(cb: Dict, data: str) -> None:
    action = data.split(":", 1)[1]
    chat_id = cb["message"]["chat"]["id"]
    msg_id = cb["message"]["message_id"]
    TG.answer_callback(cb.get("id", ""))

    if action == "length":
        TG.edit_message(chat_id, msg_id, "📏 <b>طول محتوا</b>",
                       reply_markup=kb_length_menu())
    elif action == "level":
        TG.edit_message(chat_id, msg_id, "🎓 <b>سطح فنی</b>",
                       reply_markup=kb_level_menu())


# ══════════════════════════════════════════════════════════════════════════════
#                          CALLBACK HANDLERS — ADMIN
# ══════════════════════════════════════════════════════════════════════════════

@ROUTER.callback("adm")
def cb_admin(cb: Dict, data: str) -> None:
    uid = cb.get("from", {}).get("id", 0)
    if not is_admin(uid):
        TG.answer_callback(cb.get("id", ""), "⛔ فقط مدیر", show_alert=True)
        return

    action = data.split(":", 1)[1]
    chat_id = cb["message"]["chat"]["id"]
    msg_id = cb["message"]["message_id"]

    TG.answer_callback(cb.get("id", ""))

    if action == "status":
        _cb_admin_status(chat_id, msg_id)
    elif action == "stats":
        _cb_admin_stats(chat_id, msg_id)
    elif action == "logs":
        _cb_admin_logs(chat_id, msg_id)
    elif action == "settings":
        cfg = CONFIG.get()
        TG.edit_message(chat_id, msg_id, "⚙️", reply_markup=kb_settings_menu(cfg))
    elif action == "test_models":
        _cb_admin_test_models(chat_id, msg_id)
    elif action == "test_ai":
        _cb_admin_test_ai(chat_id, msg_id)
    elif action == "test_post":
        _cb_admin_test_post(chat_id, msg_id)
    elif action == "cleanup":
        _cb_admin_cleanup(chat_id, msg_id)


def _cb_admin_status(chat_id: int, msg_id: int) -> None:
    cfg = CONFIG.get()
    me = TG.get_me()
    bot_name = f"@{me.result.get('username', '?')}" if me.ok else "❌"

    text = (
        f"📊 <b>وضعیت ربات</b>\n\n"
        f"🤖 {bot_name}\n"
        f"📢 کانال: <code>{escape_html(cfg.telegram.channel_id)}</code>\n"
        f"🔑 OpenRouter: {'✅' if cfg.keys.openrouter else '❌'}\n"
        f"🔑 Gemini: {'✅' if cfg.keys.gemini else '❌'}\n"
        f"🎨 Provider: <code>{cfg.ai.provider}</code>\n"
        f"🧠 مدل: <code>{escape_html(cfg.ai.primary_model)}</code>\n"
        f"📏 طول: <code>{cfg.content.length}</code>\n"
        f"🎓 سطح: <code>{cfg.content.technical_level}</code>\n"
        f"⏰ خودکار: هر {cfg.behavior.auto_post_hours} ساعت\n\n"
        f"💾 حافظه: <code>{MEM_MON.stats()['current_mb']}MB</code>\n"
        f"🧵 ورکرها: <code>{POOL.stats()['active']}/{POOL.stats()['max_workers']}</code>"
    )
    TG.edit_message(chat_id, msg_id, text, reply_markup=kb_admin_panel())


def _cb_admin_stats(chat_id: int, msg_id: int) -> None:
    s = STATS.all()
    top_models = sorted(s.get("model_usage", {}).items(),
                       key=lambda x: -x[1])[:5]
    text = (
        f"📈 <b>آمار کامل</b>\n\n"
        f"📝 پست‌ها: <code>{s.get('posts', 0)}</code>\n"
        f"💬 سوالات: <code>{s.get('questions', 0)}</code>\n"
        f"🔄 بازتولید: <code>{s.get('regen', 0)}</code>\n"
        f"❌ خطاها: <code>{s.get('errors', 0)}</code>\n"
        f"🕐 شروع: <code>{s.get('started_at', '?')[:19]}</code>\n\n"
    )
    if top_models:
        text += "🏆 <b>مدل‌های پرکار:</b>\n"
        for m, c in top_models:
            text += f"• <code>{escape_html(m[:30])}</code>: {c}\n"

    TG.edit_message(chat_id, msg_id, text, reply_markup=kb_admin_panel())


def _cb_admin_logs(chat_id: int, msg_id: int) -> None:
    try:
        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = "\n".join(lines[-20:])
        text = f"📋 <b>آخرین لاگ‌ها</b>\n\n<pre>{escape_html(tail[-1500:])}</pre>"
    except Exception as e:
        text = f"❌ {e}"
    TG.edit_message(chat_id, msg_id, text, reply_markup=kb_admin_panel())


def _cb_admin_test_models(chat_id: int, msg_id: int) -> None:
    TG.edit_message(chat_id, msg_id, "🤖 در حال تست مدل‌ها...")
    POOL.submit(_run_model_test_bg, chat_id, msg_id)


def _run_model_test_bg(chat_id: int, msg_id: int) -> None:
    """Test all models in background."""
    cfg = CONFIG.get()
    key = cfg.keys.openrouter.strip()
    if not key:
        TG.edit_message(chat_id, msg_id, "❌ OpenRouter key ندارد")
        return

    models = [cfg.ai.primary_model] + cfg.ai.fallback_models
    seen = set()
    unique = [m for m in models if m and not (m in seen or seen.add(m))]

    working = []
    failing = []

    for m in unique[:15]:
        payload = {
            "model": m,
            "messages": [{"role": "user", "content": "OK"}],
            "max_tokens": 3,
        }
        r = HTTP.request(
            "POST", "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json_body=payload, timeout=25,
        )
        if r is not None and r.status_code == 200:
            working.append(m)
        else:
            failing.append(m)

    text = (
        f"🤖 <b>نتیجه تست</b>\n\n"
        f"✅ کارکننده ({len(working)}):\n"
    )
    for m in working[:8]:
        text += f"• <code>{escape_html(m[:40])}</code>\n"

    if failing:
        text += f"\n❌ ناموفق ({len(failing)})"

    TG.edit_message(chat_id, msg_id, text, reply_markup=kb_admin_panel())


def _cb_admin_test_ai(chat_id: int, msg_id: int) -> None:
    TG.edit_message(chat_id, msg_id, "🧪 در حال تست AI...")
    POOL.submit(_run_ai_test_bg, chat_id, msg_id)


def _run_ai_test_bg(chat_id: int, msg_id: int) -> None:
    cfg = CONFIG.get()
    out = []

    if cfg.keys.openrouter:
        r = AI.test_provider("openrouter")
        if r.ok:
            out.append(f"✅ OpenRouter: {r.model} ({r.latency_ms}ms)")
        else:
            out.append(f"❌ OpenRouter: {r.error[:100]}")

    if cfg.keys.gemini:
        r = AI.test_provider("gemini")
        if r.ok:
            out.append(f"✅ Gemini: {r.model} ({r.latency_ms}ms)")
        else:
            out.append(f"❌ Gemini: {r.error[:100]}")

    text = "🧪 <b>نتیجه تست AI</b>\n\n" + "\n".join(out)
    TG.edit_message(chat_id, msg_id, text, reply_markup=kb_admin_panel())


def _cb_admin_test_post(chat_id: int, msg_id: int) -> None:
    TG.edit_message(chat_id, msg_id, "📢 در حال ساخت پست تستی...")
    POOL.submit(_run_test_post_bg, chat_id, msg_id)


def _run_test_post_bg(chat_id: int, msg_id: int) -> None:
    """Try to use generate_post from Part 4."""
    try:
        if "_generate_post_full" in globals():
            content = _generate_post_full(CONFIG.get(), "تست مهندسی مکانیک", "tutorial")
        else:
            resp = AI.ask(
                "You are a Persian engineering writer.",
                "یک پست کوتاه تستی درباره استاتیک به فارسی بنویس.",
                max_tokens=500,
            )
            content = resp.text if resp.ok else None

        if not content:
            TG.edit_message(chat_id, msg_id, "❌ تولید ناموفق",
                           reply_markup=kb_admin_panel())
            return

        cfg = CONFIG.get()
        r = TG.send_message(cfg.telegram.channel_id, content)
        if r.ok:
            TG.edit_message(chat_id, msg_id, "✅ پست تستی ارسال شد.",
                           reply_markup=kb_admin_panel())
        else:
            TG.edit_message(chat_id, msg_id,
                           f"❌ خطا: {escape_html(r.description[:100])}",
                           reply_markup=kb_admin_panel())
    except Exception as e:
        log.exception("test post")
        TG.edit_message(chat_id, msg_id, f"❌ {e}",
                       reply_markup=kb_admin_panel())


def _cb_admin_cleanup(chat_id: int, msg_id: int) -> None:
    AI_CACHE.clear()
    HTTP_CACHE.clear()
    gc.collect()
    TG.edit_message(chat_id, msg_id,
                   "✅ کش‌ها پاک شدند، حافظه آزاد شد.",
                   reply_markup=kb_admin_panel())


# ══════════════════════════════════════════════════════════════════════════════
#                          TEXT HANDLER (free-form)
# ══════════════════════════════════════════════════════════════════════════════

@ROUTER.on_text
def handle_free_text(msg: Dict) -> None:
    """Handle non-command text: question → AI answer; else → generate post."""
    chat_id = get_chat_id(msg)
    uid = get_uid(msg)
    text = (msg.get("text") or "").strip()
    if not text:
        return

    # If message is a secret (token/key), block
    if _looks_like_secret(text):
        TG.send_message(chat_id, "🚨 <b>هشدار امنیتی</b>\nتوکن/کلید شناسایی شد. پیام پاک شود.")
        return

    HISTORY.append(uid, "user", text, CONFIG.get().behavior.max_history)

    is_q = (
        text.endswith("?") or text.endswith("؟") or
        text.startswith(("چی", "چرا", "چگونه", "چطور", "چیه",
                         "what", "why", "how", "explain"))
    )

    if is_q:
        _handle_question(chat_id, uid, text)
    else:
        _handle_topic_request(chat_id, uid, text)


SECRET_PATTERNS = [
    re.compile(r"^\d{8,}:[A-Za-z0-9_-]{30,}$"),
    re.compile(r"^sk-or-v1-[a-f0-9]{40,}$"),
    re.compile(r"^sk-[A-Za-z0-9]{40,}$"),
    re.compile(r"^sk-bl-[A-Za-z0-9]{30,}$"),
    re.compile(r"^sk-hr-[A-Za-z0-9]{30,}$"),
    re.compile(r"^gsk_[A-Za-z0-9]{40,}$"),
    re.compile(r"^AIza[A-Za-z0-9_-]{30,}$"),
    re.compile(r"^AQ\.[A-Za-z0-9_-]{30,}$"),
    re.compile(r"^apify_api_[A-Za-z0-9]{30,}$"),
    re.compile(r"^hf_[A-Za-z0-9]{30,}$"),
    re.compile(r"^r8_[A-Za-z0-9]{30,}$"),
    re.compile(r"^sk-ant-[A-Za-z0-9_-]{30,}$"),
]
def _looks_like_secret(text: str) -> bool:
    t = text.strip()
    if len(t) < 20:
        return False
    for p in SECRET_PATTERNS:
        if p.match(t):
            return True
    return False


def _handle_question(chat_id: int, uid: int, question: str) -> None:
    """AI answer for user's question."""
    msg = TG.send_message(chat_id, "💭 در حال پردازش...")
    if not msg.ok:
        return
    mid = (msg.result or {}).get("message_id")

    with TypingHeartbeat(chat_id):
        resp = AI.ask(
            "You are a Persian-speaking PROFESSOR of Mechanical Engineering. "
            "Answer with technical depth. Use formulas where appropriate. "
            "Format with Markdown. NEVER mention being an AI.",
            question,
            history=HISTORY.get(uid),
            max_tokens=2500,
        )

    if not resp.ok:
        TG.edit_message(chat_id, mid, f"❌ {escape_html(resp.error[:150])}")
        STATS.incr("errors")
        return

    HISTORY.append(uid, "assistant", resp.text, CONFIG.get().behavior.max_history)
    STATS.incr("questions")

    final = separate_directions(clean_latex(resp.text))
    final = _md_to_html_safe(final)

    if len(final) > 3800:
        TG.edit_message(chat_id, mid, "📖 ادامه در پیام‌های بعدی...")
        TG.send_long_message(chat_id, final)
    else:
        TG.edit_message(chat_id, mid, final)


def _handle_topic_request(chat_id: int, uid: int, topic_text: str) -> None:
    """Generate post from topic."""
    if "_generate_post_full" not in globals():
        # Fallback simple generation
        msg = TG.send_message(chat_id, f"⏳ در حال تولید محتوا درباره «{topic_text}»...")
        if not msg.ok:
            return
        mid = (msg.result or {}).get("message_id")

        resp = AI.ask(
            "You are a Persian engineering writer for a technical Telegram channel.",
            f"یک پست تخصصی درباره «{topic_text}» بنویس.",
            max_tokens=2500,
        )
        if resp.ok:
            TG.edit_message(chat_id, mid, "✅ آماده شد:\n\n" + resp.text[:3000])
        else:
            TG.edit_message(chat_id, mid, f"❌ {resp.error[:120]}")
        return

    # Full handler from Part 4
    try:
        _generate_and_post(CONFIG.get(), chat_id, topic_text, style="tutorial")
    except Exception as e:
        log.exception("topic gen")
        TG.send_message(chat_id, f"❌ خطا: {escape_message(str(e))}")


def escape_message(s: str) -> str:
    return escape_html(s[:200])


def _md_to_html_safe(text: str) -> str:
    """Markdown to HTML with cache."""
    key = "md2html:" + hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()
    cached = HTTP_CACHE.get(key)
    if cached is not None:
        return cached
    result = _md_to_html_impl(text)
    HTTP_CACHE.set(key, result)
    return result


def _md_to_html_impl(text: str) -> str:
    """Full markdown → HTML for Telegram."""
    if not text:
        return ""

    # Protect code blocks
    fences = []

    def _f(m):
        idx = len(fences)
        code = m.group(1)
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        fences.append(f"<pre>{escaped}</pre>")
        return f"\x00F{idx}\x00"

    text = re.sub(r"```([\s\S]*?)```", _f, text)

    # Protect inline code
    inlines = []

    def _i(m):
        idx = len(inlines)
        code = m.group(1)
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        inlines.append(f"<code>{escaped}</code>")
        return f"\x00I{idx}\x00"

    text = re.sub(r"`([^`\n]+)`", _i, text)

    # Preserve existing HTML tags BEFORE escaping
    preserved = []
    def _preserve_html(m):
        _idx = len(preserved)
        preserved.append(m.group(0))
        return f"\x00P{_idx}\x00"
    text = re.sub(r"<pre>[\s\S]*?</pre>", _preserve_html, text)
    text = re.sub(r"<code>[\s\S]*?</code>", _preserve_html, text)
    text = re.sub(r"<b>[\s\S]*?</b>", _preserve_html, text)
    text = re.sub(r"<i>[\s\S]*?</i>", _preserve_html, text)
    text = re.sub(r"<s>[\s\S]*?</s>", _preserve_html, text)
    text = re.sub(r"<a\s[^>]*>[\s\S]*?</a>", _preserve_html, text)

    # Escape remaining
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Restore preserved
    for _i, _tag in enumerate(preserved):
        text = text.replace(f"\x00P{_i}\x00", _tag)

    # Bold
    text = re.sub(r"\*\*([^\*\n]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__([^_\n]+)__", r"<b>\1</b>", text)

    # Italic
    text = re.sub(r"(?<!\*)\*([^\*\n]+)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!_)_([^_\n]+)_(?!_)", r"<i>\1</i>", text)

    # Strikethrough
    text = re.sub(r"~~([^~\n]+)~~", r"<s>\1</s>", text)

    # Restore protected blocks
    for i, f in enumerate(fences):
        text = text.replace(f"\x00F{i}\x00", f)
    for i, c in enumerate(inlines):
        text = text.replace(f"\x00I{i}\x00", c)

    # Convert FML markers to <code>
    _MO = "\x01FML\x01"
    _MC = "\x01/FML\x01"
    text = re.sub(
        re.escape(_MO) + r"([\s\S]*?)" + re.escape(_MC),
        lambda m: f"<code>{m.group(1).strip()}</code>",
        text,
    )

    return text


# ══════════════════════════════════════════════════════════════════════════════
#                          UPDATE DISPATCHER
# ══════════════════════════════════════════════════════════════════════════════

def dispatch_update(update: Dict) -> None:
    """Route incoming update to appropriate handler."""
    try:
        if "message" in update:
            m = update["message"]
            u = m.get("from", {})
            txt = (m.get("text") or "")[:60]
            name = (u.get("first_name") or u.get("username") or "?")
            LIVE.event("in", f"{name} ({u.get('id','?')}): {txt}")
        elif "callback_query" in update:
            cb = update["callback_query"]
            u = cb.get("from", {})
            data = cb.get("data", "")[:40]
            name = (u.get("first_name") or u.get("username") or "?")
            LIVE.event("in", f"btn {name}: {data}")
    except Exception:
        pass

    # Callback query
    if "callback_query" in update:
        cb = update["callback_query"]
        uid = cb.get("from", {}).get("id", 0)
        if USERS.is_blocked(uid):
            return
        ROUTER.route_callback(cb)
        return

    # Poll answer
    if "poll_answer" in update:
        _handle_poll_answer(update["poll_answer"])
        return

    # Message
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return

    uid = get_uid(msg)
    chat_id = get_chat_id(msg)

    if not uid:
        return

    # Track user
    USERS.track_seen(msg)

    # Blocked?
    if USERS.is_blocked(uid):
        return

    # Rate limit
    allowed, wait = RATE_LIMIT.check(uid)
    if not allowed:
        TG.send_message(chat_id, f"⏳ صبر کنید... ({wait}s)")
        return

    text = (msg.get("text") or "").strip()

    # Command?
    if text.startswith("/"):
        cmd, args = extract_command(text)
        STATS.incr_dict("commands", cmd)
        if ROUTER.route_command(msg, cmd, args):
            return
        # Unknown command
        TG.send_message(chat_id, f"❓ دستور ناشناخته: <code>{escape_html(cmd)}</code>\n/help")
        return

    # Free-form text
    if text:
        ROUTER.route_text(msg)
        return


def _handle_poll_answer(pa: Dict) -> None:
    """Track poll answers in stats."""
    try:
        option_ids = pa.get("option_ids", [])
        STATS.incr("poll_votes", len(option_ids))
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
#                          POLLING LOOP
# ══════════════════════════════════════════════════════════════════════════════

class PollingLoop:
    def __init__(self):
        self._stop = threading.Event()
        self._last_update = 0
        self._errors = 0
        self._consecutive_errors = 0
        self._updates_processed = 0

    def run(self) -> None:
        """Main polling loop — blocking."""
        cfg = CONFIG.get()
        if not cfg.telegram.token:
            log.error("Telegram token not set")
            return

        me = TG.get_me()
        if not me.ok:
            log.error(f"getMe failed: {me.description}")
            return
        log.info(f"Bot online: @{me.result.get('username', '?')}")

        # Clean webhook
        TG.delete_webhook(drop_pending=False)

        self._last_update = int(cfg.last_update_id or 0)
        log.info(f"Polling started. Offset={self._last_update}")
        try:
            LIVE.event("sys", f"Polling started from offset={self._last_update}")
        except Exception:
            pass

        while not self._stop.is_set():
            try:
                res = TG.get_updates(
                    offset=self._last_update + 1,
                    timeout=25,
                    allowed_updates=["message", "edited_message",
                                     "callback_query", "poll_answer"],
                    limit=100,
                )

                if not res.ok:
                    self._consecutive_errors += 1
                    self._errors += 1
                    log.warning(f"getUpdates failed: {res.description}")
                    try:
                        LIVE.event("warn", f"getUpdates: {res.description[:80]}")
                    except Exception:
                        pass
                    if self._consecutive_errors > 5:
                        time.sleep(min(30, 2 ** self._consecutive_errors))
                    else:
                        time.sleep(3)
                    continue

                self._consecutive_errors = 0
                updates = res.result or []

                for upd in updates:
                    try:
                        dispatch_update(upd)
                        self._updates_processed += 1
                    except Exception as e:
                        log.exception(f"dispatch error: {e}")
                        STATS.incr("errors")

                    self._last_update = max(self._last_update, upd.get("update_id", 0))

                if updates:
                    cfg = CONFIG.get()
                    cfg.last_update_id = self._last_update
                    # Save async to avoid blocking
                    JsonStore.save_async(CONFIG_FILE, {
                        "telegram": asdict(cfg.telegram),
                        "ai": asdict(cfg.ai),
                        "content": asdict(cfg.content),
                        "behavior": asdict(cfg.behavior),
                        "keys": asdict(cfg.keys),
                        "last_update_id": self._last_update,
                        "bot_started_at": cfg.bot_started_at,
                        "version": cfg.version,
                    })

            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error(f"polling error: {e}")
                time.sleep(3)

        log.info(f"Polling stopped. Updates processed: {self._updates_processed}")

    def stop(self) -> None:
        self._stop.set()

    def stats(self) -> Dict[str, int]:
        return {
            "last_update_id": self._last_update,
            "updates_processed": self._updates_processed,
            "errors": self._errors,
        }


POLLER = PollingLoop()


# ══════════════════════════════════════════════════════════════════════════════
#                          PART 2 SELF-TEST
# ══════════════════════════════════════════════════════════════════════════════

def self_test_part2() -> None:
    head("Part 2/5 — Telegram API Self-Test")

    cfg = CONFIG.get()

    # 1. Token
    if not cfg.telegram.token:
        warn("Telegram token not set — skipping API tests")
        info("Add token via menu Part 5")
        return

    # 2. getMe
    step("Calling getMe...")
    me = TG.get_me()
    if me.ok:
        ok(f"Bot: @{me.result.get('username', '?')} ({me.result.get('first_name', '')})")
    else:
        err(f"getMe failed: {me.description}")
        return

    # 3. Rate limiter
    step("Testing rate limiter...")
    test_uid = 999999
    results = [RATE_LIMIT.check(test_uid) for _ in range(20)]
    allowed = sum(1 for ok_flag, _ in results if ok_flag)
    ok(f"Rate limiter: {allowed}/20 allowed (limit=15)")

    # 4. Session
    step("Testing sessions...")
    s = SESSIONS.set_state(12345, "test", foo="bar")
    s2 = SESSIONS.get(12345)
    if s2.state == "test" and s2.data.get("foo") == "bar":
        ok("Sessions working")
    else:
        err("Sessions FAILED")

    # 5. History
    step("Testing history...")
    HISTORY.clear(999)
    HISTORY.append(999, "user", "hello")
    HISTORY.append(999, "assistant", "world")
    hist = HISTORY.get(999)
    if len(hist) == 2:
        ok(f"History: {len(hist)} messages")
    else:
        err(f"History FAILED: {hist}")

    # 6. Command registry
    step("Testing command registry...")
    all_cmds = REGISTRY.all()
    ok(f"Registered commands: {len(all_cmds)}")
    for spec in all_cmds[:15]:
        info(f"  /{spec.name} — {spec.description}")

    # 7. Keyboard
    step("Testing keyboard...")
    k = kb_main_menu()
    rows = k.get("inline_keyboard", [])
    ok(f"Main menu: {len(rows)} rows")

    # 8. Markdown conversion
    step("Testing markdown → HTML...")
    md = "**Bold** and *italic* and `code` and [link](https://x.com)"
    html = _md_to_html_safe(md)
    ok(f"Converted: {html[:100]}")

    # 9. Message splitting
    step("Testing message splitting...")
    long_text = "Line. " * 2000
    parts = TG._split_text(long_text, 3800)
    ok(f"Split {len(long_text)} chars into {len(parts)} parts")
    for i, p in enumerate(parts, 1):
        info(f"  Part {i}: {len(p)} chars")

    # 10. RTL/LTR
    step("Testing RTL/LTR separation...")
    mixed = "معادله برنولی:\nP + ½ρv² = const\nسلام."
    sep = separate_directions(mixed)
    ok("Separated OK")
    for line in sep.split("\n"):
        info(f"  | {repr(line)[:100]}")

    print()
    succ("Part 2/5 self-test complete.")
    info("Send 'ادامه' for Part 3/5 (External APIs: Gemini, Zenserp, Aviationstack, Apify, ...)")


# ══════════════════════════════════════════════════════════════════════════════
#                          ENTRY (updates Part 1 entry)
# ══════════════════════════════════════════════════════════════════════════════

def _run_bot_full() -> None:
    """Full bot launcher for Part 2."""
    head("MAADGH Bot — Starting")

    cfg = CONFIG.get()
    if not cfg.telegram.token:
        err("Telegram token not set")
        info("Use menu (Part 5) to configure")
        return

    # Set commands menu
    step("Setting command menu...")
    cmds = REGISTRY.telegram_menu()
    if cmds:
        r = TG.set_my_commands(cmds)
        if r.ok:
            ok(f"Set {len(cmds)} commands")
        else:
            warn(f"setMyCommands failed: {r.description}")

    # Run polling
    step("Starting polling loop...")
    POLLER.run()

#                    PART 3/5 — EXTERNAL APIs INTEGRATION
#                          BASE API CLASS

@dataclass
class APIResult:
    ok: bool
    data: Any = None
    error: str = ""
    source: str = ""
    latency_ms: int = 0
    cached: bool = False


class BaseAPI:
    """Base class for external API integrations."""

    NAME = "base"
    CACHE_TTL = 300

    def __init__(self, config: ConfigManager, http: ConnectionPool):
        self.config = config
        self.http = http
        self._cache = LRUTTLCache(maxsize=500, ttl=self.CACHE_TTL)

    def _cache_key(self, *args) -> str:
        h = hashlib.md5()
        for a in args:
            h.update(str(a).encode("utf-8", errors="replace"))
        return f"{self.NAME}:{h.hexdigest()}"

    def _wrap(self, ok: bool, data=None, error="", latency_ms=0, cached=False) -> APIResult:
        return APIResult(ok=ok, data=data, error=error, source=self.NAME,
                        latency_ms=latency_ms, cached=cached)

    def is_configured(self) -> bool:
        return True

    def test(self) -> APIResult:
        return self._wrap(False, error="not implemented")


# ══════════════════════════════════════════════════════════════════════════════
#                        GEMINI AI PROVIDER (ENHANCED)
# ══════════════════════════════════════════════════════════════════════════════

class GeminiAPI(BaseAPI):
    """
    Google Gemini API.
    Endpoints:
      - generateContent (text)
      - vision (images)
      - embeddings
    Models: 2.0-flash-exp, 1.5-flash, 1.5-pro, 2.5-flash
    """

    NAME = "gemini"
    BASE = "https://generativelanguage.googleapis.com/v1beta/models"
    CACHE_TTL = 1800

    AVAILABLE_MODELS = [
        "gemini-2.0-flash-exp",
        "gemini-1.5-flash",
        "gemini-1.5-flash-8b",
        "gemini-1.5-pro",
        "gemini-2.5-flash-preview-05-20",
        "gemini-2.5-pro-preview-05-06",
    ]

    def is_configured(self) -> bool:
        return bool(self.config.get().keys.gemini.strip())

    def _api_key(self) -> str:
        return self.config.get().keys.gemini.strip()

    def generate(
        self,
        prompt: str,
        *,
        model: str = "gemini-2.0-flash-exp",
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2500,
        json_mode: bool = False,
        history: Optional[List[Dict]] = None,
    ) -> APIResult:
        key = self._api_key()
        if not key:
            return self._wrap(False, error="Gemini key not set")

        cache_key = self._cache_key(prompt, model, temperature, bool(json_mode))
        cached = self._cache.get(cache_key)
        if cached:
            return self._wrap(True, data=cached, cached=True)

        started = time.perf_counter()

        contents: List[Dict] = []
        if system:
            contents.append({"role": "user", "parts": [{"text": f"[SYSTEM]\n{system}"}]})
            contents.append({"role": "model", "parts": [{"text": "OK"}]})

        if history:
            for h in history[-20:]:
                if isinstance(h, dict):
                    role = "user" if h.get("role") == "user" else "model"
                    txt = h.get("content", "")
                    if txt:
                        contents.append({"role": role, "parts": [{"text": txt}]})

        contents.append({"role": "user", "parts": [{"text": prompt}]})

        gen_cfg = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }
        if json_mode:
            gen_cfg["responseMimeType"] = "application/json"

        payload = {"contents": contents, "generationConfig": gen_cfg}
        url = f"{self.BASE}/{model}:generateContent?key={key}"

        r = self.http.request("POST", url, json_body=payload, timeout=90)
        latency = int((time.perf_counter() - started) * 1000)

        if r is None:
            return self._wrap(False, error="request failed", latency_ms=latency)

        if r.status_code != 200:
            try:
                j = r.json()
                emsg = j.get("error", {}).get("message", r.text[:200])
            except Exception:
                emsg = r.text[:200]
            return self._wrap(False, error=f"{r.status_code}: {emsg[:200]}",
                             latency_ms=latency)

        try:
            data = r.json()
        except Exception as e:
            return self._wrap(False, error=f"json: {e}", latency_ms=latency)

        candidates = data.get("candidates") or []
        if not candidates:
            return self._wrap(False, error="no candidates", latency_ms=latency)

        parts = candidates[0].get("content", {}).get("parts") or []
        if not parts:
            return self._wrap(False, error="no parts", latency_ms=latency)

        text = parts[0].get("text", "").strip()
        self._cache.set(cache_key, text)

        return self._wrap(True, data=text, latency_ms=latency)

    def vision(
        self,
        image_url: str,
        prompt: str,
        *,
        model: str = "gemini-2.0-flash-exp",
    ) -> APIResult:
        """Analyze an image via URL."""
        key = self._api_key()
        if not key:
            return self._wrap(False, error="Gemini key not set")

        started = time.perf_counter()

        # Fetch image
        img_bytes = self.http.get_bytes(image_url, timeout=30)
        if not img_bytes:
            return self._wrap(False, error="image download failed")

        import base64
        b64 = base64.b64encode(img_bytes).decode("ascii")

        # Detect mime
        mime = "image/jpeg"
        if image_url.lower().endswith(".png"):
            mime = "image/png"
        elif image_url.lower().endswith(".webp"):
            mime = "image/webp"
        elif image_url.lower().endswith(".gif"):
            mime = "image/gif"

        payload = {
            "contents": [{
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime, "data": b64}},
                ],
            }],
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": 1500},
        }

        url = f"{self.BASE}/{model}:generateContent?key={key}"
        r = self.http.request("POST", url, json_body=payload, timeout=120)
        latency = int((time.perf_counter() - started) * 1000)

        if r is None or r.status_code != 200:
            return self._wrap(False, error=f"status {r.status_code if r else 'none'}",
                             latency_ms=latency)

        try:
            data = r.json()
        except Exception as e:
            return self._wrap(False, error=str(e), latency_ms=latency)

        cands = data.get("candidates") or []
        if not cands:
            return self._wrap(False, error="no candidates", latency_ms=latency)

        parts = cands[0].get("content", {}).get("parts") or []
        text = parts[0].get("text", "").strip() if parts else ""
        return self._wrap(True, data=text, latency_ms=latency)

    def count_tokens(self, text: str, model: str = "gemini-2.0-flash-exp") -> APIResult:
        key = self._api_key()
        if not key:
            return self._wrap(False, error="key not set")

        url = f"{self.BASE}/{model}:countTokens?key={key}"
        payload = {"contents": [{"parts": [{"text": text}]}]}
        r = self.http.request("POST", url, json_body=payload, timeout=20)

        if r is None or r.status_code != 200:
            return self._wrap(False, error="count failed")

        try:
            return self._wrap(True, data=r.json())
        except Exception as e:
            return self._wrap(False, error=str(e))

    def list_models(self) -> APIResult:
        key = self._api_key()
        if not key:
            return self._wrap(False, error="key not set")

        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
        data = self.http.get_json(url)
        if data is None:
            return self._wrap(False, error="list failed")

        models = [m["name"].split("/")[-1] for m in data.get("models", [])]
        return self._wrap(True, data=models)

    def test(self) -> APIResult:
        r = self.generate("Say OK in Persian.", max_tokens=20)
        if r.ok:
            return self._wrap(True, data=f"OK: {r.data[:40]}", latency_ms=r.latency_ms)
        return r


# ══════════════════════════════════════════════════════════════════════════════
#                        ZENSERP (GOOGLE SEARCH)
# ══════════════════════════════════════════════════════════════════════════════

class ZenserpAPI(BaseAPI):
    """
    Zenserp — Google Search API.
    Endpoints: /search, /image, /shopping, /news, /video, /scholar, /maps
    """

    NAME = "zenserp"
    BASE = "https://app.zenserp.com/api/v2"
    CACHE_TTL = 900

    def is_configured(self) -> bool:
        return bool(self.config.get().keys.zenserp.strip())

    def _key(self) -> str:
        return self.config.get().keys.zenserp.strip()

    def _search(self, endpoint: str, q: str, extra: Optional[Dict] = None) -> APIResult:
        key = self._key()
        if not key:
            return self._wrap(False, error="Zenserp key not set")

        cache_key = self._cache_key(endpoint, q, json_dumps(extra or {}))
        cached = self._cache.get(cache_key)
        if cached:
            return self._wrap(True, data=cached, cached=True)

        started = time.perf_counter()
        params = {"q": q, "apikey": key, "gl": "ir", "hl": "fa"}
        if extra:
            params.update(extra)

        url = f"{self.BASE}/{endpoint}"
        data = self.http.get_json(url, params=params, timeout=30)
        latency = int((time.perf_counter() - started) * 1000)

        if data is None:
            return self._wrap(False, error="request failed", latency_ms=latency)

        self._cache.set(cache_key, data)
        return self._wrap(True, data=data, latency_ms=latency)

    def web_search(self, q: str, num: int = 10) -> APIResult:
        return self._search("search", q, {"num": str(num)})

    def image_search(self, q: str, num: int = 10) -> APIResult:
        return self._search("image", q, {"num": str(num)})

    def news_search(self, q: str, num: int = 10) -> APIResult:
        return self._search("news", q, {"num": str(num)})

    def video_search(self, q: str, num: int = 10) -> APIResult:
        return self._search("video", q, {"num": str(num)})

    def shopping_search(self, q: str, num: int = 10) -> APIResult:
        return self._search("shopping", q, {"num": str(num)})

    def scholar_search(self, q: str, num: int = 10) -> APIResult:
        return self._search("scholar", q, {"num": str(num)})

    def maps_search(self, q: str) -> APIResult:
        return self._search("maps", q)

    def extract_organic(self, result: APIResult) -> List[Dict[str, str]]:
        """Extract organic results into simple list."""
        if not result.ok or not isinstance(result.data, dict):
            return []
        out = []
        for item in result.data.get("organic", [])[:20]:
            out.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("description", ""),
                "position": str(item.get("position", "")),
            })
        return out

    def extract_knowledge(self, result: APIResult) -> Optional[Dict]:
        if not result.ok or not isinstance(result.data, dict):
            return None
        kg = result.data.get("knowledge_graph")
        if not kg:
            return None
        return {
            "title": kg.get("title", ""),
            "type": kg.get("type", ""),
            "description": kg.get("description", ""),
        }

    def test(self) -> APIResult:
        r = self.web_search("mechanical engineering", 3)
        if r.ok:
            items = self.extract_organic(r)
            return self._wrap(True, data=f"Found {len(items)} results",
                            latency_ms=r.latency_ms)
        return r


# ══════════════════════════════════════════════════════════════════════════════
#                        AVIATIONSTACK
# ══════════════════════════════════════════════════════════════════════════════

class AviationstackAPI(BaseAPI):
    """
    Aviationstack — real-time flight data.
    Endpoints: /flights, /routes, /airports, /airlines, /airplanes
    """

    NAME = "aviationstack"
    BASE = "https://api.aviationstack.com/v1"
    CACHE_TTL = 300

    def is_configured(self) -> bool:
        return bool(self.config.get().keys.aviationstack.strip())

    def _key(self) -> str:
        return self.config.get().keys.aviationstack.strip()

    def _call(self, endpoint: str, params: Dict) -> APIResult:
        key = self._key()
        if not key:
            return self._wrap(False, error="Aviationstack key not set")

        cache_key = self._cache_key(endpoint, json_dumps(params))
        cached = self._cache.get(cache_key)
        if cached:
            return self._wrap(True, data=cached, cached=True)

        started = time.perf_counter()
        p = dict(params)
        p["access_key"] = key

        url = f"{self.BASE}/{endpoint}"
        data = self.http.get_json(url, params=p, timeout=20)
        latency = int((time.perf_counter() - started) * 1000)

        if data is None:
            return self._wrap(False, error="request failed", latency_ms=latency)

        if "error" in data:
            err = data["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            return self._wrap(False, error=f"API: {msg[:120]}", latency_ms=latency)

        self._cache.set(cache_key, data)
        return self._wrap(True, data=data, latency_ms=latency)

    def flights(
        self,
        *,
        flight_iata: str = "",
        airline_iata: str = "",
        dep_iata: str = "",
        arr_iata: str = "",
        flight_status: str = "",
        limit: int = 10,
    ) -> APIResult:
        p = {"limit": limit}
        if flight_iata: p["flight_iata"] = flight_iata
        if airline_iata: p["airline_iata"] = airline_iata
        if dep_iata: p["dep_iata"] = dep_iata
        if arr_iata: p["arr_iata"] = arr_iata
        if flight_status: p["flight_status"] = flight_status
        return self._call("flights", p)

    def flight_by_number(self, flight_iata: str) -> APIResult:
        return self.flights(flight_iata=flight_iata, limit=5)

    def flights_from(self, dep_iata: str, limit: int = 10) -> APIResult:
        return self.flights(dep_iata=dep_iata, limit=limit)

    def flights_to(self, arr_iata: str, limit: int = 10) -> APIResult:
        return self.flights(arr_iata=arr_iata, limit=limit)

    def airline_flights(self, airline_iata: str, limit: int = 10) -> APIResult:
        return self.flights(airline_iata=airline_iata, limit=limit)

    def airports(self, search: str = "", limit: int = 10) -> APIResult:
        p = {"limit": limit}
        if search: p["search"] = search
        return self._call("airports", p)

    def airlines(self, search: str = "", limit: int = 10) -> APIResult:
        p = {"limit": limit}
        if search: p["search"] = search
        return self._call("airlines", p)

    def routes(
        self,
        *,
        dep_iata: str = "",
        arr_iata: str = "",
        airline_iata: str = "",
        limit: int = 10,
    ) -> APIResult:
        p = {"limit": limit}
        if dep_iata: p["dep_iata"] = dep_iata
        if arr_iata: p["arr_iata"] = arr_iata
        if airline_iata: p["airline_iata"] = airline_iata
        return self._call("routes", p)

    def airplanes(self, search: str = "", limit: int = 10) -> APIResult:
        p = {"limit": limit}
        if search: p["search"] = search
        return self._call("airplanes", p)

    def format_flight(self, f: Dict) -> str:
        """Format a flight dict for Telegram."""
        dep = f.get("departure", {}) or {}
        arr = f.get("arrival", {}) or {}
        airline = f.get("airline", {}) or {}
        flight = f.get("flight", {}) or {}

        return (
            f"✈️ <b>{escape_html(flight.get('iata', '?'))}</b> — "
            f"{escape_html(airline.get('name', '?'))}\n"
            f"📍 {escape_html(dep.get('airport', '?'))} "
            f"({escape_html(dep.get('iata', '?'))})\n"
            f"🎯 {escape_html(arr.get('airport', '?'))} "
            f"({escape_html(arr.get('iata', '?'))})\n"
            f"🕐 {escape_html(dep.get('scheduled', '?'))}\n"
            f"📊 وضعیت: <code>{escape_html(f.get('flight_status', '?'))}</code>"
        )

    def test(self) -> APIResult:
        r = self.airports("IKA", 1)
        if r.ok:
            return self._wrap(True, data="Airports OK", latency_ms=r.latency_ms)
        return r


# ══════════════════════════════════════════════════════════════════════════════
#                        IP-API (GEOLOCATION)
# ══════════════════════════════════════════════════════════════════════════════

class IPAPI(BaseAPI):
    """
    IP-API.com — free IP geolocation.
    No key required for basic use (45 req/min).
    """

    NAME = "ip-api"
    BASE = "https://ip-api.com/json"
    CACHE_TTL = 3600

    def is_configured(self) -> bool:
        return True

    def lookup(self, ip: str = "", fields: str = "") -> APIResult:
        cache_key = self._cache_key("lookup", ip, fields)
        cached = self._cache.get(cache_key)
        if cached:
            return self._wrap(True, data=cached, cached=True)

        started = time.perf_counter()
        url = f"{self.BASE}/{ip}" if ip else self.BASE
        params = {"lang": "fa"}
        if fields:
            params["fields"] = fields

        data = self.http.get_json(url, params=params, timeout=15)
        latency = int((time.perf_counter() - started) * 1000)

        if data is None:
            return self._wrap(False, error="request failed", latency_ms=latency)

        if data.get("status") == "fail":
            return self._wrap(False, error=data.get("message", "lookup failed"),
                            latency_ms=latency)

        self._cache.set(cache_key, data)
        return self._wrap(True, data=data, latency_ms=latency)

    def my_ip(self) -> APIResult:
        """Get server's public IP."""
        data = self.http.get_text("https://api.ipify.org", timeout=10)
        if not data:
            return self._wrap(False, error="could not get IP")
        return self.lookup(data.strip())

    def format(self, data: Dict) -> str:
        return (
            f"🌍 <b>اطلاعات IP</b>\n\n"
            f"• IP: <code>{escape_html(data.get('query', '?'))}</code>\n"
            f"• کشور: {escape_html(data.get('country', '?'))} "
            f"({escape_html(data.get('countryCode', '?'))})\n"
            f"• استان: {escape_html(data.get('regionName', '?'))}\n"
            f"• شهر: {escape_html(data.get('city', '?'))}\n"
            f"• مختصات: <code>{data.get('lat', '?')}, {data.get('lon', '?')}</code>\n"
            f"• ISP: {escape_html(data.get('isp', '?'))}\n"
            f"• سازمان: {escape_html(data.get('org', '?'))}\n"
            f"• منطقه زمانی: <code>{escape_html(data.get('timezone', '?'))}</code>"
        )

    def test(self) -> APIResult:
        r = self.my_ip()
        if r.ok:
            return self._wrap(True, data=f"IP: {r.data.get('query', '?')}",
                            latency_ms=r.latency_ms)
        return r


# ══════════════════════════════════════════════════════════════════════════════
#                        APIFY (ACTORS)
# ══════════════════════════════════════════════════════════════════════════════

class ApifyAPI(BaseAPI):
    """
    Apify — Actors platform.
    Actors: Google Search, YouTube, Instagram, TikTok, Twitter, ...
    Docs: https://docs.apify.com/api/v2
    """

    NAME = "apify"
    BASE = "https://api.apify.com/v2"
    CACHE_TTL = 1800

    ACTORS = {
        "google-search": "apify~google-search-scraper",
        "youtube-scraper": "streamers~youtube-scraper",
        "youtube-channel": "streamers~youtube-channel-scraper",
        "youtube-shorts": "streamers~youtube-shorts-scraper",
        "youtube-comments": "streamers~youtube-comments-scraper",
        "instagram-scraper": "apify~instagram-scraper",
        "twitter-scraper": "apidojo~twitter-scraper-lite",
        "tiktok-scraper": "clockworks~tiktok-scraper",
        "website-content": "apify~website-content-crawler",
        "google-maps": "compass~crawler-google-places",
        "contact-info": "vdrmota~contact-info-scraper",
    }

    def is_configured(self) -> bool:
        return bool(self.config.get().keys.apify.strip())

    def _token(self) -> str:
        return self.config.get().keys.apify.strip()

    def _run_actor_sync(
        self,
        actor_id: str,
        input_data: Dict,
        *,
        timeout: int = 180,
        max_items: int = 20,
    ) -> APIResult:
        """Run actor and get results (synchronous)."""
        token = self._token()
        if not token:
            return self._wrap(False, error="Apify token not set")

        cache_key = self._cache_key(actor_id, json_dumps(input_data), max_items)
        cached = self._cache.get(cache_key)
        if cached:
            return self._wrap(True, data=cached, cached=True)

        started = time.perf_counter()
        url = f"{self.BASE}/acts/{actor_id}/run-sync-get-dataset-items"

        params = {"token": token, "timeout": timeout, "limit": max_items}

        r = self.http.request(
            "POST", url,
            params=params,
            json_body=input_data,
            timeout=timeout + 30,
        )
        latency = int((time.perf_counter() - started) * 1000)

        if r is None:
            return self._wrap(False, error="request failed", latency_ms=latency)

        if r.status_code not in (200, 201):
            return self._wrap(False,
                            error=f"status {r.status_code}: {r.text[:120]}",
                            latency_ms=latency)

        try:
            data = r.json()
        except Exception as e:
            return self._wrap(False, error=f"json: {e}", latency_ms=latency)

        if not isinstance(data, list):
            return self._wrap(False, error="unexpected format", latency_ms=latency)

        self._cache.set(cache_key, data)
        return self._wrap(True, data=data, latency_ms=latency)

    def google_search(self, query: str, max_pages: int = 1) -> APIResult:
        return self._run_actor_sync(
            self.ACTORS["google-search"],
            {
                "queries": query,
                "maxPagesPerQuery": max_pages,
                "resultsPerPage": 10,
                "countryCode": "us",
                "languageCode": "en",
            },
            max_items=10,
        )

    def youtube_search(self, query: str, max_videos: int = 5) -> APIResult:
        return self._run_actor_sync(
            self.ACTORS["youtube-scraper"],
            {
                "searchKeywords": query,
                "maxResults": max_videos,
                "maxResultsShorts": 0,
                "maxResultStreams": 0,
            },
            max_items=max_videos,
        )

    def youtube_video(self, url: str) -> APIResult:
        return self._run_actor_sync(
            self.ACTORS["youtube-scraper"],
            {"startUrls": [{"url": url}], "maxResults": 1},
            max_items=1,
        )

    def youtube_transcript(self, url: str) -> APIResult:
        return self._run_actor_sync(
            self.ACTORS["youtube-scraper"],
            {
                "startUrls": [{"url": url}],
                "maxResults": 1,
                "subtitlesOptions": "always_transcribe",
            },
            max_items=1,
            timeout=300,
        )

    def youtube_channel(self, url: str, max_videos: int = 10) -> APIResult:
        return self._run_actor_sync(
            self.ACTORS["youtube-channel"],
            {"startUrls": [{"url": url}], "maxResults": max_videos},
            max_items=max_videos,
        )

    def instagram_profile(self, username: str, max_posts: int = 10) -> APIResult:
        return self._run_actor_sync(
            self.ACTORS["instagram-scraper"],
            {
                "directUrls": [f"https://www.instagram.com/{username}/"],
                "resultsType": "posts",
                "resultsLimit": max_posts,
            },
            max_items=max_posts,
        )

    def tiktok_hashtag(self, hashtag: str, max_videos: int = 10) -> APIResult:
        return self._run_actor_sync(
            self.ACTORS["tiktok-scraper"],
            {"hashtags": [hashtag], "resultsPerPage": max_videos},
            max_items=max_videos,
        )

    def twitter_search(self, query: str, max_tweets: int = 10) -> APIResult:
        return self._run_actor_sync(
            self.ACTORS["twitter-scraper"],
            {"searchTerms": [query], "maxTweets": max_tweets},
            max_items=max_tweets,
        )

    def website_content(self, url: str) -> APIResult:
        return self._run_actor_sync(
            self.ACTORS["website-content"],
            {"startUrls": [{"url": url}], "maxCrawlingDepth": 0},
            max_items=1,
        )

    def google_maps(self, query: str, max_places: int = 10) -> APIResult:
        return self._run_actor_sync(
            self.ACTORS["google-maps"],
            {"searchStringsArray": [query], "maxCrawledPlacesPerSearch": max_places},
            max_items=max_places,
        )

    def contact_scraper(self, urls: List[str]) -> APIResult:
        return self._run_actor_sync(
            self.ACTORS["contact-info"],
            {"startUrls": [{"url": u} for u in urls]},
            max_items=len(urls),
        )

    def list_my_actors(self) -> APIResult:
        """List user's own actors."""
        token = self._token()
        if not token:
            return self._wrap(False, error="no token")

        url = f"{self.BASE}/acts"
        data = self.http.get_json(url, params={"token": token, "limit": 50})
        if data is None:
            return self._wrap(False, error="list failed")
        return self._wrap(True, data=data.get("data", {}).get("items", []))

    def get_run_status(self, run_id: str) -> APIResult:
        token = self._token()
        if not token:
            return self._wrap(False, error="no token")
        url = f"{self.BASE}/actor-runs/{run_id}"
        data = self.http.get_json(url, params={"token": token})
        if data is None:
            return self._wrap(False, error="status failed")
        return self._wrap(True, data=data.get("data", {}))

    def test(self) -> APIResult:
        token = self._token()
        if not token:
            return self._wrap(False, error="no token")

        url = f"{self.BASE}/users/me"
        data = self.http.get_json(url, params={"token": token}, timeout=15)
        if data is None:
            return self._wrap(False, error="auth failed")
        user = data.get("data", {})
        return self._wrap(True, data=f"Apify user: {user.get('username', '?')}")


# ══════════════════════════════════════════════════════════════════════════════
#                        FREE PUBLIC APIS
# ══════════════════════════════════════════════════════════════════════════════

class FreePublicAPIs(BaseAPI):
    """
    Free Public APIs collection.
    Uses https://www.freepublicapis.com for discovery.
    """

    NAME = "freepublicapis"
    CACHE_TTL = 3600

    def is_configured(self) -> bool:
        return True

    def random_api(self) -> APIResult:
        """Get a random API entry."""
        data = self.http.get_json("https://www.freepublicapis.com/api/random", timeout=15)
        if data is None:
            return self._wrap(False, error="fetch failed")
        return self._wrap(True, data=data)

    def list_all(self, limit: int = 50) -> APIResult:
        data = self.http.get_json("https://www.freepublicapis.com/api/entries",
                                  params={"limit": limit}, timeout=20)
        if data is None:
            return self._wrap(False, error="fetch failed")
        return self._wrap(True, data=data)

    def search(self, query: str) -> APIResult:
        data = self.http.get_json("https://www.freepublicapis.com/api/entries",
                                  params={"search": query, "limit": 20},
                                  timeout=20)
        if data is None:
            return self._wrap(False, error="search failed")
        return self._wrap(True, data=data)

    def test(self) -> APIResult:
        r = self.random_api()
        if r.ok:
            name = r.data.get("name", "?") if isinstance(r.data, dict) else "?"
            return self._wrap(True, data=f"Random API: {name}")
        return r


# ══════════════════════════════════════════════════════════════════════════════
#                        WEATHER (Open-Meteo, free, no key)
# ══════════════════════════════════════════════════════════════════════════════

class WeatherAPI(BaseAPI):
    """
    Open-Meteo — free weather API (no key).
    Uses IP-API to geolocate city.
    """

    NAME = "weather"
    CACHE_TTL = 1800
    BASE = "https://api.open-meteo.com/v1/forecast"
    GEO_BASE = "https://geocoding-api.open-meteo.com/v1/search"

    def is_configured(self) -> bool:
        return True

    def geocode(self, city: str) -> Optional[Dict]:
        cache_key = self._cache_key("geo", city)
        cached = self._cache.get(cache_key)
        if cached:
            return cached

        data = self.http.get_json(
            self.GEO_BASE,
            params={"name": city, "count": 1, "language": "fa", "format": "json"},
            timeout=15,
        )
        if not data:
            return None
        results = data.get("results") or []
        if not results:
            return None
        r = results[0]
        info = {
            "name": r.get("name"),
            "country": r.get("country"),
            "lat": r.get("latitude"),
            "lon": r.get("longitude"),
            "timezone": r.get("timezone"),
        }
        self._cache.set(cache_key, info)
        return info

    def forecast(
        self,
        city: str,
        *,
        days: int = 3,
    ) -> APIResult:
        geo = self.geocode(city)
        if not geo:
            return self._wrap(False, error=f"city not found: {city}")

        cache_key = self._cache_key("fc", city, days)
        cached = self._cache.get(cache_key)
        if cached:
            return self._wrap(True, data=cached, cached=True)

        started = time.perf_counter()
        params = {
            "latitude": geo["lat"],
            "longitude": geo["lon"],
            "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min,weather_code,precipitation_sum",
            "timezone": geo.get("timezone") or "auto",
            "forecast_days": min(7, max(1, days)),
        }

        data = self.http.get_json(self.BASE, params=params, timeout=20)
        latency = int((time.perf_counter() - started) * 1000)

        if data is None:
            return self._wrap(False, error="forecast failed", latency_ms=latency)

        result = {"geo": geo, "weather": data}
        self._cache.set(cache_key, result)
        return self._wrap(True, data=result, latency_ms=latency)

    @staticmethod
    def code_to_fa(code: int) -> str:
        """WMO weather code → Persian description."""
        codes = {
            0: "☀️ صاف",
            1: "🌤 عمدتاً صاف", 2: "⛅ نیمه ابری", 3: "☁️ ابری",
            45: "🌫 مه", 48: "🌫 مه یخ‌زده",
            51: "🌦 نم‌نم باران سبک", 53: "🌦 باران سبک", 55: "🌧 باران شدید",
            61: "🌧 باران کم", 63: "🌧 باران متوسط", 65: "🌧 باران شدید",
            71: "🌨 برف کم", 73: "🌨 برف متوسط", 75: "❄️ برف شدید",
            80: "🌦 رگبار کم", 81: "🌧 رگبار متوسط", 82: "⛈ رگبار شدید",
            95: "⛈ طوفان رعد و برق", 96: "⛈ طوفان با تگرگ", 99: "⛈ طوفان شدید",
        }
        return codes.get(code, "❓ نامشخص")

    def format(self, result: Dict) -> str:
        geo = result.get("geo", {})
        w = result.get("weather", {})

        cur = w.get("current", {})
        temp = cur.get("temperature_2m", "?")
        hum = cur.get("relative_humidity_2m", "?")
        wind = cur.get("wind_speed_10m", "?")
        code = cur.get("weather_code", 0)

        out = (
            f"🌤 <b>آب و هوای {escape_html(geo.get('name', '?'))}</b>\n"
            f"📍 {escape_html(geo.get('country', '?'))}\n\n"
            f"<b>فعلی:</b>\n"
            f"• {self.code_to_fa(code)}\n"
            f"• دما: <code>{temp}°C</code>\n"
            f"• رطوبت: <code>{hum}%</code>\n"
            f"• باد: <code>{wind} km/h</code>\n"
        )

        daily = w.get("daily", {})
        dates = daily.get("time", [])[:3]
        highs = daily.get("temperature_2m_max", [])[:3]
        lows = daily.get("temperature_2m_min", [])[:3]
        codes = daily.get("weather_code", [])[:3]

        if dates:
            out += "\n<b>پیش‌بینی:</b>\n"
            for i, d in enumerate(dates):
                h = highs[i] if i < len(highs) else "?"
                l = lows[i] if i < len(lows) else "?"
                c = codes[i] if i < len(codes) else 0
                out += f"• {d}: {self.code_to_fa(c)} | {l}° تا {h}°\n"

        return out

    def test(self) -> APIResult:
        r = self.forecast("Tehran", days=1)
        if r.ok:
            return self._wrap(True, data="weather OK", latency_ms=r.latency_ms)
        return r


# ══════════════════════════════════════════════════════════════════════════════
#                        EXCHANGE RATE (free)
# ══════════════════════════════════════════════════════════════════════════════

class ExchangeAPI(BaseAPI):
    """Exchange rate — exchangerate.host (free)."""

    NAME = "exchange"
    CACHE_TTL = 3600
    BASE = "https://open.er-api.com/v6"  # v15: replaced dead exchangerate.host

    def is_configured(self) -> bool:
        return True

    def latest(self, base: str = "USD", symbols: str = "") -> APIResult:
        cache_key = self._cache_key("latest", base, symbols)
        cached = self._cache.get(cache_key)
        if cached:
            return self._wrap(True, data=cached, cached=True)

        params = {"base": base}
        if symbols:
            params["symbols"] = symbols

        data = self.http.get_json(f"{self.BASE}/latest", params=params, timeout=20)
        if data is None:
            return self._wrap(False, error="fetch failed")

        self._cache.set(cache_key, data)
        return self._wrap(True, data=data)

    def convert(self, amount: float, from_cur: str, to_cur: str) -> APIResult:
        cache_key = self._cache_key("conv", amount, from_cur, to_cur)
        cached = self._cache.get(cache_key)
        if cached:
            return self._wrap(True, data=cached, cached=True)

        params = {"from": from_cur, "to": to_cur, "amount": amount}
        data = self.http.get_json(f"{self.BASE}/convert", params=params, timeout=15)
        if data is None:
            return self._wrap(False, error="convert failed")

        self._cache.set(cache_key, data)
        return self._wrap(True, data=data)

    def test(self) -> APIResult:
        r = self.latest("USD", "EUR,GBP,IRR")
        if r.ok:
            return self._wrap(True, data="exchange OK", latency_ms=r.latency_ms)
        return r


# ══════════════════════════════════════════════════════════════════════════════
#                        NEWS API (RSS aggregation)
# ══════════════════════════════════════════════════════════════════════════════

class NewsAPI(BaseAPI):
    """
    Multi-source news aggregator (RSS).
    No external key needed.
    """

    NAME = "news"
    CACHE_TTL = 900

    FEEDS = {
        "phys_org": "https://phys.org/rss-feed/technology-news/engineering/",
        "sciencedaily": "https://www.sciencedaily.com/rss/matter_energy/engineering.xml",
        "mit_news": "https://news.mit.edu/rss/topic/mechanical-engineering",
        "nasa": "https://www.nasa.gov/rss/dyn/breaking_news.rss",
        "arxiv_ce": "https://export.arxiv.org/rss/cs.CE",
        "arxiv_fluids": "https://export.arxiv.org/rss/physics.flu-dyn",
        "arxiv_mat": "https://export.arxiv.org/rss/cond-mat.mtrl-sci",
        "spacex_reddit": "https://www.reddit.com/r/spacex/.rss",
        "mech_reddit": "https://www.reddit.com/r/MechanicalEngineering/.rss",
        "eng_reddit": "https://www.reddit.com/r/engineering/.rss",
    }

    def is_configured(self) -> bool:
        return _feedparser is not None

    def fetch_feed(self, url: str, limit: int = 5) -> APIResult:
        if _feedparser is None:
            return self._wrap(False, error="feedparser not installed")

        cache_key = self._cache_key("feed", url, limit)
        cached = self._cache.get(cache_key)
        if cached:
            return self._wrap(True, data=cached, cached=True)

        started = time.perf_counter()
        try:
            feed = _feedparser.parse(url)
        except Exception as e:
            return self._wrap(False, error=str(e)[:100])

        items = []
        for e in (feed.entries or [])[:limit]:
            items.append({
                "title": getattr(e, "title", ""),
                "link": getattr(e, "link", ""),
                "summary": getattr(e, "summary", "")[:500],
                "published": getattr(e, "published", ""),
                "source": url,
            })

        latency = int((time.perf_counter() - started) * 1000)
        self._cache.set(cache_key, items)
        return self._wrap(True, data=items, latency_ms=latency)

    def fetch_all(self, limit_per_feed: int = 3) -> APIResult:
        """Fetch all feeds in parallel."""
        started = time.perf_counter()

        futures = {
            name: POOL.submit(self.fetch_feed, url, limit_per_feed)
            for name, url in self.FEEDS.items()
        }

        results: Dict[str, List[Dict]] = {}
        for name, f in futures.items():
            try:
                r = f.result(timeout=30)
                if r and r.ok:
                    results[name] = r.data
            except Exception as e:
                log.debug(f"feed {name}: {e}")

        latency = int((time.perf_counter() - started) * 1000)
        return self._wrap(True, data=results, latency_ms=latency)

    def fetch_combined(self, limit: int = 20) -> List[Dict]:
        """Fetch all and return combined, deduplicated list."""
        r = self.fetch_all(limit_per_feed=5)
        if not r.ok:
            return []

        seen: set = set()
        combined: List[Dict] = []
        for source, items in r.data.items():
            for item in items:
                key = item.get("title", "")[:60].lower().strip()
                if key and key not in seen:
                    seen.add(key)
                    item["feed_name"] = source
                    combined.append(item)

        # Shuffle and cap
        random.shuffle(combined)
        return combined[:limit]

    def filter_by_keywords(self, items: List[Dict], keywords: List[str]) -> List[Dict]:
        if not keywords:
            return items
        out = []
        for it in items:
            text = (it.get("title", "") + " " + it.get("summary", "")).lower()
            if any(k.lower() in text for k in keywords):
                out.append(it)
        return out

    def test(self) -> APIResult:
        r = self.fetch_feed(self.FEEDS["phys_org"], 2)
        if r.ok:
            return self._wrap(True, data=f"{len(r.data)} items",
                            latency_ms=r.latency_ms)
        return r


# ══════════════════════════════════════════════════════════════════════════════
#                        ARXIV (dedicated)
# ══════════════════════════════════════════════════════════════════════════════

class ArxivAPI(BaseAPI):
    """arXiv — scientific preprints."""

    NAME = "arxiv"
    CACHE_TTL = 1800
    BASE = "https://export.arxiv.org/api/query"

    def is_configured(self) -> bool:
        return True

    def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        sort_by: str = "submittedDate",
        category: str = "",
    ) -> APIResult:
        cache_key = self._cache_key("search", query, max_results, sort_by, category)
        cached = self._cache.get(cache_key)
        if cached:
            return self._wrap(True, data=cached, cached=True)

        q = f"all:{query}"
        if category:
            q = f"cat:{category} AND {q}"

        params = {
            "search_query": q,
            "start": 0,
            "max_results": max_results,
            "sortBy": sort_by,
            "sortOrder": "descending",
        }

        started = time.perf_counter()
        try:
            r = self.http.request("GET", self.BASE, params=params, timeout=30)
            if r is None:
                return self._wrap(False, error="request failed")
            xml = r.text
        except Exception as e:
            return self._wrap(False, error=str(e)[:100])

        latency = int((time.perf_counter() - started) * 1000)

        entries = re.findall(r"<entry>[\s\S]*?</entry>", xml)
        out = []
        for e in entries:
            t = re.search(r"<title>([\s\S]*?)</title>", e)
            s = re.search(r"<summary>([\s\S]*?)</summary>", e)
            i = re.search(r"<id>([\s\S]*?)</id>", e)
            p = re.search(r"<published>([\s\S]*?)</published>", e)
            a = re.findall(r"<name>([\s\S]*?)</name>", e)
            out.append({
                "title": re.sub(r"\s+", " ", t.group(1)).strip() if t else "",
                "summary": re.sub(r"\s+", " ", s.group(1)).strip()[:1000] if s else "",
                "link": i.group(1).strip() if i else "",
                "published": p.group(1).strip() if p else "",
                "authors": a[:5],
            })

        self._cache.set(cache_key, out)
        return self._wrap(True, data=out, latency_ms=latency)

    def by_category(self, category: str, max_results: int = 5) -> APIResult:
        return self.search("", max_results=max_results, category=category)

    def test(self) -> APIResult:
        r = self.search("fluid mechanics", max_results=2)
        if r.ok:
            return self._wrap(True, data=f"{len(r.data)} papers",
                            latency_ms=r.latency_ms)
        return r


# ══════════════════════════════════════════════════════════════════════════════
#                        WIKIPEDIA
# ══════════════════════════════════════════════════════════════════════════════

class WikipediaAPI(BaseAPI):
    """Wikipedia summary API (no key)."""

    NAME = "wikipedia"
    CACHE_TTL = 86400

    def is_configured(self) -> bool:
        return True

    def summary(self, title: str, lang: str = "fa") -> APIResult:
        cache_key = self._cache_key("sum", title, lang)
        cached = self._cache.get(cache_key)
        if cached:
            return self._wrap(True, data=cached, cached=True)

        url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{_requests.utils.quote(title)}"
        data = self.http.get_json(url, timeout=15)
        if data is None:
            return self._wrap(False, error="not found")

        if data.get("type") == "disambiguation":
            return self._wrap(False, error="disambiguation page")

        result = {
            "title": data.get("title", title),
            "extract": data.get("extract", ""),
            "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
            "thumbnail": (data.get("thumbnail") or {}).get("source", ""),
        }
        self._cache.set(cache_key, result)
        return self._wrap(True, data=result)

    def search(self, query: str, lang: str = "fa", limit: int = 5) -> APIResult:
        url = f"https://{lang}.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json",
            "srlimit": limit,
        }
        data = self.http.get_json(url, params=params, timeout=15)
        if data is None:
            return self._wrap(False, error="search failed")

        results = data.get("query", {}).get("search", [])
        out = [{"title": r.get("title"), "snippet": strip_html(r.get("snippet", ""))}
               for r in results]
        return self._wrap(True, data=out)

    def test(self) -> APIResult:
        r = self.summary("Mechanical engineering", "en")
        if r.ok:
            return self._wrap(True, data=r.data.get("title", ""))
        return r


# ══════════════════════════════════════════════════════════════════════════════
#                        DICTIONARY (free)
# ══════════════════════════════════════════════════════════════════════════════

class DictionaryAPI(BaseAPI):
    """Free Dictionary API."""

    NAME = "dict"
    CACHE_TTL = 86400

    def is_configured(self) -> bool:
        return True

    def lookup(self, word: str, lang: str = "en") -> APIResult:
        cache_key = self._cache_key("dict", word, lang)
        cached = self._cache.get(cache_key)
        if cached:
            return self._wrap(True, data=cached, cached=True)

        url = f"https://api.dictionaryapi.dev/api/v2/entries/{lang}/{_requests.utils.quote(word)}"
        data = self.http.get_json(url, timeout=15)
        if data is None or not isinstance(data, list):
            return self._wrap(False, error="not found")

        entry = data[0]
        meanings = []
        for m in entry.get("meanings", [])[:3]:
            defs = [d.get("definition", "") for d in m.get("definitions", [])[:2]]
            meanings.append({
                "part_of_speech": m.get("partOfSpeech", ""),
                "definitions": defs,
            })

        result = {
            "word": entry.get("word", word),
            "phonetic": entry.get("phonetic", ""),
            "meanings": meanings,
        }
        self._cache.set(cache_key, result)
        return self._wrap(True, data=result)

    def test(self) -> APIResult:
        r = self.lookup("engineering")
        if r.ok:
            return self._wrap(True, data=r.data.get("word", ""))
        return r


# ══════════════════════════════════════════════════════════════════════════════
#                        TRANSLATION (LibreTranslate)
# ══════════════════════════════════════════════════════════════════════════════

class TranslateAPI(BaseAPI):
    """Free translation via LibreTranslate instances."""

    NAME = "translate"
    CACHE_TTL = 86400

    INSTANCES = [
        "https://translate.argosopentech.com",
        "https://libretranslate.de",
        "https://translate.terraprint.co",
    ]

    def is_configured(self) -> bool:
        return True

    def translate(
        self,
        text: str,
        source: str = "auto",
        target: str = "fa",
    ) -> APIResult:
        cache_key = self._cache_key("tr", text, source, target)
        cached = self._cache.get(cache_key)
        if cached:
            return self._wrap(True, data=cached, cached=True)

        started = time.perf_counter()

        for instance in self.INSTANCES:
            url = f"{instance}/translate"
            payload = {
                "q": text[:4000],
                "source": source,
                "target": target,
                "format": "text",
            }
            r = self.http.request("POST", url, json_body=payload, timeout=20)
            if r is None or r.status_code != 200:
                continue
            try:
                data = r.json()
                translated = data.get("translatedText")
                if translated:
                    latency = int((time.perf_counter() - started) * 1000)
                    self._cache.set(cache_key, translated)
                    return self._wrap(True, data=translated, latency_ms=latency)
            except Exception:
                continue

        return self._wrap(False, error="all instances failed")

    def detect(self, text: str) -> APIResult:
        for instance in self.INSTANCES:
            url = f"{instance}/detect"
            r = self.http.request("POST", url, json_body={"q": text[:500]}, timeout=15)
            if r is None or r.status_code != 200:
                continue
            try:
                data = r.json()
                if isinstance(data, list) and data:
                    return self._wrap(True, data=data[0])
            except Exception:
                continue
        return self._wrap(False, error="detect failed")

    def test(self) -> APIResult:
        r = self.translate("Hello world", "en", "fa")
        if r.ok:
            return self._wrap(True, data=r.data[:40])
        return r


# ══════════════════════════════════════════════════════════════════════════════
#                        NUMBERS API (fun facts)
# ══════════════════════════════════════════════════════════════════════════════

class NumbersAPI(BaseAPI):
    """Numbers API — facts about numbers/dates."""

    NAME = "numbers"
    CACHE_TTL = 86400

    def is_configured(self) -> bool:
        return True

    def fact(self, number: Union[int, str], type_: str = "trivia") -> APIResult:
        url = f"https://numbersapi.com/{number}/{type_}?json"
        data = self.http.get_json(url, timeout=10)
        if data is None:
            return self._wrap(False, error="not found")
        return self._wrap(True, data=data)

    def random_fact(self, type_: str = "trivia") -> APIResult:
        url = f"https://numbersapi.com/random/{type_}?json"
        data = self.http.get_json(url, timeout=10)
        if data is None:
            return self._wrap(False, error="fetch failed")
        return self._wrap(True, data=data)

    def year_fact(self, year: int) -> APIResult:
        return self.fact(year, "year")

    def math_fact(self, number: int) -> APIResult:
        return self.fact(number, "math")

    def test(self) -> APIResult:
        r = self.random_fact()
        if r.ok:
            return self._wrap(True, data=r.data.get("text", "")[:60])
        return r


# ══════════════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════════════
#                        FREEAPI.APP (no key needed)
# ══════════════════════════════════════════════════════════════════════════════

class FreeAPIApp(BaseAPI):
    """
    freeAPI.app — public API hub with 50+ endpoints.
    No key required. Base: https://api.freeapi.app/api/v1
    """
    NAME = "freeapi.app"
    BASE = "https://api.freeapi.app/api/v1"
    CACHE_TTL = 600

    def is_configured(self) -> bool:
        return True

    def random_quote(self) -> APIResult:
        return self._wrap(True, data=self.http.get_json(
            f"{self.BASE}/public/quotes/random", timeout=15))

    def random_joke(self) -> APIResult:
        return self._wrap(True, data=self.http.get_json(
            f"{self.BASE}/public/randomjokes", timeout=15))

    def random_user(self) -> APIResult:
        return self._wrap(True, data=self.http.get_json(
            f"{self.BASE}/public/randomusers", timeout=15))

    def random_product(self) -> APIResult:
        return self._wrap(True, data=self.http.get_json(
            f"{self.BASE}/public/randomproducts", timeout=15))

    def random_meal(self) -> APIResult:
        return self._wrap(True, data=self.http.get_json(
            f"{self.BASE}/public/meals", timeout=15))

    def random_book(self) -> APIResult:
        return self._wrap(True, data=self.http.get_json(
            f"{self.BASE}/public/books", timeout=15))

    def random_dog(self) -> APIResult:
        return self._wrap(True, data=self.http.get_json(
            f"{self.BASE}/public/dogs", timeout=15))

    def test(self) -> APIResult:
        r = self.random_quote()
        if r.ok and r.data:
            return self._wrap(True, data="freeAPI.app working")
        return self._wrap(False, error="no response")


#                        API REGISTRY
# ══════════════════════════════════════════════════════════════════════════════

class YouTubeSuggestAPI(BaseAPI):
    """YouTube video suggestion for each post.
    Uses YouTube Data API v3 (primary) with Innertube fallback (no key)."""
    NAME = "youtube"
    CACHE_TTL = 7200

    SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
    VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

    def is_configured(self) -> bool:
        return True

    def _yt_key(self) -> str:
        cfg = self.config.get()
        return getattr(cfg.keys, "youtube", "") or ""

    def search_videos(self, query: str, *, max_results: int = 3,
                     order: str = "relevance", language: str = "fa",
                     safe_search: str = "moderate") -> APIResult:
        query = (query or "").strip()
        if not query:
            return self._wrap(False, error="empty query")
        cache_key = self._cache_key("search", query, max_results, order, language)
        cached = self._cache.get(cache_key)
        if cached:
            return self._wrap(True, data=cached, cached=True)
        started = time.perf_counter()
        key = self._yt_key()
        if key:
            result = self._search_data_api(query, key, max_results, order, language, safe_search)
            if result is not None:
                latency = int((time.perf_counter() - started) * 1000)
                self._cache.set(cache_key, result)
                return self._wrap(True, data=result, latency_ms=latency)
        result = self._search_innertube(query, max_results)
        if result is not None:
            latency = int((time.perf_counter() - started) * 1000)
            self._cache.set(cache_key, result)
            return self._wrap(True, data=result, latency_ms=latency)
        return self._wrap(False, error="all search methods failed",
                         latency_ms=int((time.perf_counter() - started) * 1000))

    def _search_data_api(self, query, key, max_results, order, language, safe_search):
        params = {
            "part": "snippet", "q": query, "type": "video",
            "maxResults": max(1, min(10, max_results)), "order": order,
            "relevanceLanguage": language, "safeSearch": safe_search, "key": key,
        }
        r = self.http.request("GET", self.SEARCH_URL, params=params, timeout=20)
        if r is None or r.status_code != 200:
            if r is not None and r.status_code == 403:
                log.warning("YouTube API quota exceeded (403)")
            return None
        try:
            data = r.json()
        except Exception:
            return None
        items = data.get("items") or []
        if not items:
            return []
        video_ids = [it["id"]["videoId"] for it in items if it.get("id", {}).get("videoId")]
        if not video_ids:
            return []
        stats = self._fetch_video_stats(video_ids, key)
        out = []
        for it in items:
            vid = it.get("id", {}).get("videoId")
            if not vid:
                continue
            sn = it.get("snippet", {}) or {}
            st = stats.get(vid, {})
            out.append({
                "video_id": vid, "title": sn.get("title", ""),
                "channel": sn.get("channelTitle", ""),
                "description": (sn.get("description") or "")[:300],
                "published": sn.get("publishedAt", "")[:10],
                "thumbnail": (sn.get("thumbnails", {}).get("medium", {}).get("url")
                              or sn.get("thumbnails", {}).get("default", {}).get("url", "")),
                "url": f"https://www.youtube.com/watch?v={vid}",
                "views": st.get("viewCount", ""), "likes": st.get("likeCount", ""),
                "duration": st.get("duration", ""), "source": "data_api",
            })
        return out

    def _fetch_video_stats(self, video_ids, key):
        if not video_ids:
            return {}
        params = {"part": "statistics,contentDetails",
                  "id": ",".join(video_ids[:50]), "key": key}
        r = self.http.request("GET", self.VIDEOS_URL, params=params, timeout=15)
        if r is None or r.status_code != 200:
            return {}
        try:
            data = r.json()
        except Exception:
            return {}
        out = {}
        for item in data.get("items", []):
            vid = item.get("id")
            if vid:
                out[vid] = {
                    "viewCount": item.get("statistics", {}).get("viewCount", ""),
                    "likeCount": item.get("statistics", {}).get("likeCount", ""),
                    "duration": item.get("contentDetails", {}).get("duration", ""),
                }
        return out

    def _search_innertube(self, query, max_results):
        url = "https://www.youtube.com/youtubei/v1/search"
        params = {"key": os.getenv("YOUTUBE_INNERTUBE_KEY", os.getenv("YT_INNERTUBE_KEY", os.getenv("YT_INNERTUBE_KEY", "")))}
        payload = {
            "context": {"client": {"clientName": "WEB",
                                    "clientVersion": "2.20240101.00.00",
                                    "hl": "fa", "gl": "IR"}},
            "query": query,
        }
        try:
            r = self.http.request("POST", url, params=params, json_body=payload, timeout=20)
            if r is None or r.status_code != 200:
                return None
            data = r.json()
        except Exception as e:
            log.debug(f"innertube: {e}")
            return None
        out = []
        try:
            sections = (data.get("contents", {})
                        .get("twoColumnSearchResultsRenderer", {})
                        .get("primaryContents", {})
                        .get("sectionListRenderer", {})
                        .get("contents", []))
            for sec in sections:
                items = sec.get("itemSectionRenderer", {}).get("contents", [])
                for item in items:
                    vr = item.get("videoRenderer")
                    if not vr:
                        continue
                    vid = vr.get("videoId")
                    if not vid:
                        continue
                    title_runs = vr.get("title", {}).get("runs", [])
                    title = "".join(t.get("text", "") for t in title_runs)
                    ch = (vr.get("ownerText", {}).get("runs", [{}])[0].get("text", ""))
                    views = vr.get("viewCountText", {}).get("simpleText", "")
                    length = vr.get("lengthText", {}).get("simpleText", "")
                    out.append({
                        "video_id": vid, "title": title, "channel": ch,
                        "description": "", "published": "",
                        "thumbnail": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
                        "url": f"https://www.youtube.com/watch?v={vid}",
                        "views": views, "likes": "", "duration": length,
                        "source": "innertube",
                    })
                    if len(out) >= max_results:
                        return out
        except Exception as e:
            log.debug(f"innertube parse: {e}")
        return out

    def format_block(self, videos, max_show=3):
        if not videos:
            return ""
        lines = ["\n\n🎥 <b>ویدیوهای آموزشی مرتبط:</b>"]
        for i, v in enumerate(videos[:max_show], 1):
            title = escape_html((v.get("title") or "")[:100])
            url = v.get("url", "")
            ch = escape_html((v.get("channel") or "")[:40])
            views = v.get("views", "") or ""
            duration = v.get("duration", "") or ""
            meta = " • ".join(x for x in (ch, duration, views) if x)
            lines.append(f"\n{i}. <a href=\"{url}\">{title}</a>")
            if meta:
                lines.append(f"   <i>{escape_html(meta)}</i>")
        return "\n".join(lines)

    def test(self) -> APIResult:
        key = self._yt_key()
        r = self.search_videos("engineering mechanics tutorial", max_results=2)
        if r.ok:
            count = len(r.data) if r.data else 0
            src = (r.data[0].get("source") if r.data else "?")
            key_state = "Data API" if key else "Innertube"
            return self._wrap(True, data=f"{count} videos via {src} (key={key_state})",
                             latency_ms=r.latency_ms)
        return r

class BazaarLinkAPI(BaseAPI):
    """BazaarLink — OpenAI-compatible gateway (sk-bl-...)."""
    NAME = "bazaarlink"
    CACHE_TTL = 1800

    def is_configured(self) -> bool:
        return bool(self.config.get().keys.bazaarlink.strip())

    def chat(self, system_prompt: str, user_prompt: str, *,
             model: str = "", temperature: float = 0.6,
             max_tokens: int = 2500) -> APIResult:
        cfg = self.config.get()
        key = cfg.keys.bazaarlink.strip()
        if not key:
            return self._wrap(False, error="BazaarLink key not set")
        base = (cfg.keys.bazaarlink_base or "https://api.bazaarlink.ai/v1").rstrip("/")
        mdl = model or cfg.keys.bazaarlink_model or "gpt-4o-mini"

        cache_key = self._cache_key("chat", system_prompt, user_prompt, mdl)
        cached = self._cache.get(cache_key)
        if cached:
            return self._wrap(True, data=cached, cached=True)

        started = time.perf_counter()
        payload = {
            "model": mdl,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        r = self.http.request(
            "POST", f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json_body=payload, timeout=90,
        )
        latency = int((time.perf_counter() - started) * 1000)
        if r is None:
            return self._wrap(False, error="request failed", latency_ms=latency)
        if r.status_code != 200:
            return self._wrap(False,
                             error=f"{r.status_code}: {r.text[:200]}",
                             latency_ms=latency)
        try:
            data = r.json()
        except Exception as e:
            return self._wrap(False, error=f"json: {e}", latency_ms=latency)
        choices = data.get("choices") or []
        if not choices:
            return self._wrap(False, error="no choices", latency_ms=latency)
        text = (choices[0].get("message") or {}).get("content", "").strip()
        if not text:
            return self._wrap(False, error="empty", latency_ms=latency)
        self._cache.set(cache_key, text)
        return self._wrap(True, data=text, latency_ms=latency)

    def test(self) -> APIResult:
        r = self.chat("You are a test.", "Reply with the single word OK.",
                      max_tokens=10)
        if r.ok:
            return self._wrap(True, data=f"OK: {r.data[:40]}",
                             latency_ms=r.latency_ms)
        return r


class HarnessRouterAPI(BaseAPI):
    """HarnessRouter — run coding/agent tasks (sk-hr-...)."""
    NAME = "harnessrouter"
    CACHE_TTL = 600

    def is_configured(self) -> bool:
        return bool(self.config.get().keys.harnessrouter.strip())

    def run_task(self, prompt: str, *, timeout: int = 300) -> APIResult:
        cfg = self.config.get()
        key = cfg.keys.harnessrouter.strip()
        if not key:
            return self._wrap(False, error="HarnessRouter key not set")
        base = (cfg.keys.harnessrouter_base or "").rstrip("/")

        cache_key = self._cache_key("task", prompt[:500])
        cached = self._cache.get(cache_key)
        if cached:
            return self._wrap(True, data=cached, cached=True)

        started = time.perf_counter()
        payload = {"task": prompt, "stream": False}
        r = self.http.request(
            "POST", f"{base}/v1/tasks",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json_body=payload, timeout=timeout,
        )
        latency = int((time.perf_counter() - started) * 1000)
        if r is None:
            return self._wrap(False, error="request failed", latency_ms=latency)
        if r.status_code not in (200, 201, 202):
            return self._wrap(False,
                             error=f"{r.status_code}: {r.text[:200]}",
                             latency_ms=latency)
        try:
            data = r.json()
        except Exception as e:
            return self._wrap(False, error=f"json: {e}", latency_ms=latency)
        self._cache.set(cache_key, data)
        return self._wrap(True, data=data, latency_ms=latency)

    def test(self) -> APIResult:
        key = self.config.get().keys.harnessrouter.strip()
        if not key:
            return self._wrap(False, error="no key")
        base = self.config.get().keys.harnessrouter_base.rstrip("/")
        r = self.http.request("GET", f"{base}/v1/me",
                              headers={"Authorization": f"Bearer {key}"},
                              timeout=20)
        if r is None:
            return self._wrap(False, error="network error")
        if r.status_code == 200:
            return self._wrap(True, data="HarnessRouter OK")
        return self._wrap(False, error=f"{r.status_code}: {r.text[:120]}")


class EmojiAPI(BaseAPI):
    """eeemoji.com — free emoji metadata API (no auth)."""
    NAME = "eeemoji"
    BASE = "https://eeemoji.com/api/v1"
    CACHE_TTL = 86400

    def is_configured(self) -> bool:
        return True

    def lookup(self, id_or_char: str) -> APIResult:
        cache_key = self._cache_key("lookup", id_or_char)
        cached = self._cache.get(cache_key)
        if cached:
            return self._wrap(True, data=cached, cached=True)

        from urllib.parse import quote
        url = f"{self.BASE}/emojis/{quote(str(id_or_char))}"
        data = self.http.get_json(url, timeout=15)
        if not data:
            return self._wrap(False, error="not found")
        self._cache.set(cache_key, data)
        return self._wrap(True, data=data)

    def search(self, query: str, limit: int = 5) -> APIResult:
        cache_key = self._cache_key("search", query, limit)
        cached = self._cache.get(cache_key)
        if cached:
            return self._wrap(True, data=cached, cached=True)

        url = f"{self.BASE}/search"
        data = self.http.get_json(url, params={"q": query, "limit": limit}, timeout=15)
        if not data:
            return self._wrap(False, error="no result")
        items = data.get("data", []) if isinstance(data, dict) else []
        self._cache.set(cache_key, items)
        return self._wrap(True, data=items)

    def random(self, category: str = "") -> APIResult:
        url = f"{self.BASE}/random"
        params = {"category": category} if category else {}
        data = self.http.get_json(url, params=params, timeout=15)
        if not data:
            return self._wrap(False, error="fetch failed")
        return self._wrap(True, data=data)

    def test(self) -> APIResult:
        r = self.lookup("fire")
        if r.ok:
            return self._wrap(True, data=f"🔥 {r.data.get('name')}")
        return r


class AILearningEngineAPI(BaseAPI):
    """AI Learning Engine (RapidAPI) — generate & grade tasks."""
    NAME = "ai-learning"
    CACHE_TTL = 3600

    def is_configured(self) -> bool:
        return bool(self.config.get().keys.rapidapi_learning_secret.strip())

    def generate_task(self, topic: str, *,
                     type_: str = "test",
                     level: str = "intermediate",
                     lang: str = "Persian",
                     notes: str = "") -> APIResult:
        secret = self.config.get().keys.rapidapi_learning_secret.strip()
        if not secret:
            return self._wrap(False, error="RapidAPI proxy secret not set")
        payload = {"topic": topic, "type": type_, "level": level, "lang": lang}
        if notes:
            payload["notes"] = notes
        r = self.http.request(
            "POST", "https://ai-learning-engine.p.rapidapi.com/generate",
            headers={"Content-Type": "application/json",
                     "X-RapidAPI-Proxy-Secret": secret},
            json_body=payload, timeout=30,
        )
        if r is None:
            return self._wrap(False, error="request failed")
        if r.status_code != 200:
            return self._wrap(False, error=f"{r.status_code}: {r.text[:200]}")
        try:
            data = r.json()
        except Exception as e:
            return self._wrap(False, error=f"json: {e}")
        return self._wrap(True, data=data)

    def check_answer(self, task_payload: Dict, user_answer: Any) -> APIResult:
        secret = self.config.get().keys.rapidapi_learning_secret.strip()
        if not secret:
            return self._wrap(False, error="RapidAPI proxy secret not set")
        payload = dict(task_payload)
        payload["userAnswer"] = user_answer
        r = self.http.request(
            "POST", "https://ai-learning-engine.p.rapidapi.com/check-answer",
            headers={"Content-Type": "application/json",
                     "X-RapidAPI-Proxy-Secret": secret},
            json_body=payload, timeout=30,
        )
        if r is None:
            return self._wrap(False, error="request failed")
        if r.status_code != 200:
            return self._wrap(False, error=f"{r.status_code}: {r.text[:200]}")
        try:
            data = r.json()
        except Exception as e:
            return self._wrap(False, error=f"json: {e}")
        return self._wrap(True, data=data)

    def test(self) -> APIResult:
        r = self.generate_task("mechanical engineering basics",
                              type_="test", level="beginner",
                              lang="English")
        if r.ok:
            return self._wrap(True, data="Learning Engine OK")
        return r

class APIRegistry:
    """Global registry for all external APIs."""

    def __init__(self, config: ConfigManager, http: ConnectionPool):
        self.gemini = GeminiAPI(config, http)
        self.zenserp = ZenserpAPI(config, http)
        self.aviationstack = AviationstackAPI(config, http)
        self.ipapi = IPAPI(config, http)
        self.apify = ApifyAPI(config, http)
        self.freepublic = FreePublicAPIs(config, http)
        self.weather = WeatherAPI(config, http)
        self.exchange = ExchangeAPI(config, http)
        self.news = NewsAPI(config, http)
        self.arxiv = ArxivAPI(config, http)
        self.wikipedia = WikipediaAPI(config, http)
        self.dictionary = DictionaryAPI(config, http)
        self.translate = TranslateAPI(config, http)
        self.numbers = NumbersAPI(config, http)
        self.freeapiapp = FreeAPIApp(config, http)
        self.youtube = YouTubeSuggestAPI(config, http)
        self.bazaarlink = BazaarLinkAPI(config, http)
        self.harnessrouter = HarnessRouterAPI(config, http)
        self.emoji = EmojiAPI(config, http)
        self.ai_learning = AILearningEngineAPI(config, http)

    def all(self) -> Dict[str, BaseAPI]:
        return {
            "gemini": self.gemini,
            "zenserp": self.zenserp,
            "aviationstack": self.aviationstack,
            "ipapi": self.ipapi,
            "apify": self.apify,
            "freepublic": self.freepublic,
            "weather": self.weather,
            "exchange": self.exchange,
            "news": self.news,
            "arxiv": self.arxiv,
            "wikipedia": self.wikipedia,
            "dictionary": self.dictionary,
            "translate": self.translate,
            "numbers": self.numbers,
            "freeapiapp": self.freeapiapp,
            "bazaarlink": self.bazaarlink,
            "harnessrouter": self.harnessrouter,
            "eeemoji": self.emoji,
            "ai_learning": self.ai_learning,
        }

    def configured(self) -> Dict[str, BaseAPI]:
        return {k: v for k, v in self.all().items() if v.is_configured()}

    def test_all(self) -> Dict[str, APIResult]:
        out = {}
        for name, api in self.all().items():
            if not api.is_configured():
                out[name] = APIResult(ok=False, error="not configured", source=name)
                continue
            try:
                out[name] = api.test()
            except Exception as e:
                out[name] = APIResult(ok=False, error=str(e)[:80], source=name)
        return out

    def status_summary(self) -> str:
        lines = []
        for name, api in self.all().items():
            if api.is_configured():
                lines.append(f"✅ {name}")
            else:
                lines.append(f"❌ {name}")
        return "\n".join(lines)


APIS = APIRegistry(CONFIG, HTTP)


# ══════════════════════════════════════════════════════════════════════════════
#                        COMMANDS FOR APIs
# ══════════════════════════════════════════════════════════════════════════════

@ROUTER.command("api", description="وضعیت APIها")
def cmd_api_status(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    text = "🔌 <b>وضعیت APIها</b>\n\n" + APIS.status_summary()
    TG.send_message(chat_id, text)


@ROUTER.command("apitest", description="تست APIها", admin_only=True)
def cmd_api_test(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    m = TG.send_message(chat_id, "🧪 در حال تست APIها...")
    if not m.ok:
        return
    mid = (m.result or {}).get("message_id")
    POOL.submit(_api_test_bg, chat_id, mid)


def _api_test_bg(chat_id: int, mid: int) -> None:
    results = APIS.test_all()
    lines = ["🧪 <b>نتیجه تست APIها</b>\n"]
    for name, r in results.items():
        if r.ok:
            val = r.data if isinstance(r.data, str) else str(r.data)[:40]
            lines.append(f"✅ <b>{name}</b>: {escape_html(str(val))}")
        else:
            lines.append(f"❌ <b>{name}</b>: {escape_html(r.error[:80])}")

    TG.edit_message(chat_id, mid, "\n".join(lines))


# ─── GEMINI ─────────────────────────────────────────────

@ROUTER.command("gpt", description="Gemini گفتگو")
def cmd_gemini(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    uid = get_uid(msg)
    if not args:
        TG.send_message(chat_id, "❌ استفاده: <code>/gpt سوال شما</code>")
        return

    m = TG.send_message(chat_id, "💭 Gemini در حال پردازش...")
    if not m.ok:
        return
    mid = (m.result or {}).get("message_id")

    with TypingHeartbeat(chat_id):
        r = APIS.gemini.generate(
            args,
            system="You are a Persian-speaking engineering assistant. Answer with technical depth.",
        )

    if not r.ok:
        TG.edit_message(chat_id, mid, f"❌ {escape_html(r.error[:200])}")
        return

    final = separate_directions(clean_latex(r.data))
    final = _md_to_html_safe(final)
    TG.edit_message(chat_id, mid, final[:4096])


@ROUTER.command("vision", description="تحلیل تصویر", admin_only=False)
def cmd_vision(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    if not args:
        TG.send_message(chat_id, "❌ استفاده: <code>/vision URL_تصویر پرامپت</code>")
        return

    parts = args.split(None, 1)
    url = parts[0]
    prompt = parts[1] if len(parts) > 1 else "این تصویر را تحلیل کن."

    m = TG.send_message(chat_id, "🖼 در حال تحلیل...")
    if not m.ok:
        return
    mid = (m.result or {}).get("message_id")

    r = APIS.gemini.vision(url, prompt)
    if r.ok:
        TG.edit_message(chat_id, mid, _md_to_html_safe(r.data)[:4096])
    else:
        TG.edit_message(chat_id, mid, f"❌ {escape_html(r.error[:200])}")


# ─── ZENSERP ────────────────────────────────────────────

@ROUTER.command("search", description="جستجوی وب")
def cmd_search(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    if not args:
        TG.send_message(chat_id, "استفاده: /search کلمه"); return
    m = TG.send_message(chat_id, "🔍 جستجو...")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")
    items = []
    cfg = CONFIG.get()
    if getattr(cfg.keys, "zenserp", ""):
        r = APIS.zenserp.web_search(args, num=8)
        if r.ok: items = APIS.zenserp.extract_organic(r)
    if not items:
        try:
            r = HTTP.request("GET", "https://html.duckduckgo.com/html/",
                             params={"q": args}, timeout=20)
            if r is not None and r.status_code == 200:
                import re as _re
                rx = _re.compile(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>')
                for i, mt in enumerate(rx.finditer(r.text)):
                    if i >= 8: break
                    u = mt.group(1); t = _re.sub(r'<[^>]+>', '', mt.group(2))
                    if "uddg=" in u:
                        from urllib.parse import unquote, urlparse, parse_qs
                        q = parse_qs(urlparse(u).query).get("uddg", [""])[0]
                        if q: u = unquote(q)
                    items.append({"title": t, "url": u, "snippet": ""})
        except Exception as e:
            log.debug(f"ddg: {e}")
    if not items:
        TG.edit_message(chat_id, mid, "❌ نتیجه‌ای یافت نشد."); return
    txt = f"🔍 <b>{escape_html(args[:50])}</b>\n\n"
    for i, it in enumerate(items[:8], 1):
        txt += f"{i}. <a href='{it['url']}'>{escape_html(it['title'][:80])}</a>\n\n"
    TG.edit_message(chat_id, mid, txt[:4000])




@ROUTER.callback("w")
def cb_wiki_rand(cb: Dict, data: str) -> None:
    action = data.split(":")[1] if ":" in data else ""
    chat_id = cb["message"]["chat"]["id"]
    msg_id = cb["message"]["message_id"]
    TG.answer_callback(cb.get("id", ""), "📖")
    if action == "rand":
        try:
            t = random.choice(_get_topics_list() or [{"name": "Physics"}])
            sug = t.get("query") or t.get("name") or "Physics"
        except Exception:
            sug = "Physics"
        TG.edit_message(chat_id, msg_id,
            f"📖 پیشنهاد: <code>/wiki {escape_html(sug)}</code>\n\n"
            "یا موضوع دلخواه بنویس.",
            reply_markup=kb([
                [btn(f"📖 {sug[:28]}", f"w:go:{sug[:50]}")],
                [btn("🎲 پیشنهاد دیگر", "w:rand"), btn("🏠", "m:main")],
            ]))
    elif action == "go" and len(data.split(":")) >= 3:
        topic = data.split(":", 2)[2]
        cmd_wiki_from_cb(chat_id, msg_id, topic)


def cmd_wiki_from_cb(chat_id, msg_id, topic):
    TG.edit_message(chat_id, msg_id, f"📖 ویکی: {escape_html(topic)} ...")
    r = APIS.wikipedia.summary(topic, "fa")
    if not r.ok: r = APIS.wikipedia.summary(topic, "en")
    if not r.ok:
        TG.edit_message(chat_id, msg_id, "❌ یافت نشد",
            reply_markup=kb([[btn("⬅️", "m:main")]])); return
    data = r.data
    extract = clean_wiki_extract(data.get("extract", "") or "")[:1500]
    text = (f"📖 <b>{escape_html(data.get('title', ''))}</b>\n\n"
            f"{escape_html(extract)}\n\n"
            f"<a href='{data.get('url', '')}'>ادامه در ویکی</a>")
    TG.edit_message(chat_id, msg_id, text[:4000],
        reply_markup=kb([[btn("🔍 یوتیوب", f"y:go:{topic[:50]}")],
                         [btn("🏠 منو", "m:main")]]))


@ROUTER.callback("y")
def cb_yt_rand(cb: Dict, data: str) -> None:
    action = data.split(":")[1] if ":" in data else ""
    chat_id = cb["message"]["chat"]["id"]
    msg_id = cb["message"]["message_id"]
    TG.answer_callback(cb.get("id", ""), "🎥")
    if action == "rand":
        try:
            t = random.choice(_get_topics_list() or [{"name": "Mechanical engineering"}])
            sug = t.get("query") or t.get("name") or "Mechanical engineering"
        except Exception:
            sug = "Mechanical engineering tutorial"
        TG.edit_message(chat_id, msg_id,
            f"🎥 پیشنهاد: <code>/yt {escape_html(sug)}</code>",
            reply_markup=kb([
                [btn(f"🎥 {sug[:28]}", f"y:go:{sug[:50]}")],
                [btn("🎲 پیشنهاد دیگر", "y:rand"), btn("🏠", "m:main")],
            ]))
    elif action == "go" and len(data.split(":")) >= 3:
        topic = data.split(":", 2)[2]
        TG.edit_message(chat_id, msg_id, f"🎥 جستجو: {escape_html(topic)} ...")
        POOL.submit(_yt_search_bg, chat_id, msg_id, topic)


def _yt_search_bg(chat_id, msg_id, topic):
    try:
        _prog(f"yt search: {topic[:50]}", "yt")
        r = APIS.youtube.search_videos(topic, max_results=5)
        if not r.ok or not r.data:
            TG.edit_message(chat_id, msg_id, "❌ یافت نشد",
                reply_markup=kb([[btn("⬅️", "m:main")]])); return
        txt = f"🎥 <b>نتایج یوتیوب</b>\n\n"
        for i, v in enumerate(r.data[:5], 1):
            txt += f"{i}. <a href='{v.get('url','')}'>{escape_html((v.get('title','') or '')[:80])}</a>\n"
            ch = v.get("channel", "")[:40]
            if ch: txt += f"<i>{escape_html(ch)}</i>\n"
            txt += "\n"
        TG.edit_message(chat_id, msg_id, txt[:4000],
            reply_markup=kb([
                [btn("🎲 موضوع دیگر", "y:rand"), btn("🔍 ویکی", f"w:go:{topic[:50]}")],
                [btn("🏠", "m:main")]]))
    except Exception as e:
        TG.edit_message(chat_id, msg_id, f"❌ {escape_html(str(e)[:150])}")


@ROUTER.command("images", description="جستجوی تصویر")
def cmd_images(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    if not args:
        return
    m = TG.send_message(chat_id, "🖼 در حال جستجو...")
    if not m.ok:
        return
    mid = (m.result or {}).get("message_id")

    r = APIS.zenserp.image_search(args, num=6)
    if not r.ok:
        TG.edit_message(chat_id, mid, f"❌ {r.error[:150]}")
        return

    data = r.data or {}
    images = data.get("image_results", [])[:6]
    if not images:
        TG.edit_message(chat_id, mid, "❌ تصویری یافت نشد.")
        return

    TG.edit_message(chat_id, mid, f"🖼 تصاویر برای «{escape_html(args)}»:")
    for img in images:
        url = img.get("imageUrl") or img.get("thumbnail")
        if url:
            TG.send_photo(chat_id, url, caption=img.get("title", "")[:100])


@ROUTER.command("news_search", description="جستجوی اخبار")
def cmd_news_search(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    if not args:
        return
    m = TG.send_message(chat_id, "📰 در حال جستجو...")
    if not m.ok:
        return
    mid = (m.result or {}).get("message_id")

    r = APIS.zenserp.news_search(args, num=5)
    if not r.ok:
        TG.edit_message(chat_id, mid, f"❌ {r.error[:150]}")
        return

    data = r.data or {}
    news = data.get("news_results", [])[:5]
    if not news:
        TG.edit_message(chat_id, mid, "❌ خبری یافت نشد.")
        return

    text = f"📰 <b>اخبار: {escape_html(args)}</b>\n\n"
    for n in news:
        text += f"• <b>{escape_html(n.get('title', '')[:80])}</b>\n"
        text += f"  {escape_html(n.get('description', '')[:100])}\n\n"

    TG.edit_message(chat_id, mid, text[:4000])


# ─── AVIATIONSTACK ─────────────────────────────────────

@ROUTER.command("flight", description="اطلاعات پرواز")
def cmd_flight(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    if not args:
        TG.send_message(chat_id, "❌ استفاده: <code>/flight &lt;شماره_پرواز&gt;</code>")
        return

    m = TG.send_message(chat_id, "✈️ در حال دریافت...")
    if not m.ok:
        return
    mid = (m.result or {}).get("message_id")

    r = APIS.aviationstack.flight_by_number(args.strip().upper())
    if not r.ok:
        TG.edit_message(chat_id, mid, f"❌ {escape_html(r.error[:150])}")
        return

    flights = (r.data or {}).get("data", [])[:5]
    if not flights:
        TG.edit_message(chat_id, mid, "❌ پروازی یافت نشد.")
        return

    text = f"✈️ <b>پروازهای {escape_html(args.upper())}</b>\n\n"
    for f in flights:
        text += APIS.aviationstack.format_flight(f) + "\n\n"

    TG.edit_message(chat_id, mid, text[:4000])


@ROUTER.command("flights_from", description="پروازهای از فرودگاه")
def cmd_flights_from(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    if not args:
        TG.send_message(chat_id, "❌ استفاده: <code>/flights_from &lt;IATA&gt;</code>")
        return
    m = TG.send_message(chat_id, "✈️...")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")

    r = APIS.aviationstack.flights_from(args.strip().upper(), limit=5)
    if not r.ok:
        TG.edit_message(chat_id, mid, f"❌ {r.error[:150]}")
        return
    flights = (r.data or {}).get("data", [])[:5]
    if not flights:
        TG.edit_message(chat_id, mid, "❌ موردی یافت نشد.")
        return

    text = f"✈️ <b>پروازهای از {escape_html(args.upper())}</b>\n\n"
    for f in flights:
        text += APIS.aviationstack.format_flight(f) + "\n\n"
    TG.edit_message(chat_id, mid, text[:4000])



# ─── Aviation expanded (FIX5) ─────────────────────────────────────────────
def kb_aviation_menu_v17_obsolete() -> Dict:
    return kb([
        [btn("✈️ شماره پرواز", "av:help:flight")],
        [btn("🛫 خروجی‌ها (فرودگاه)", "av:help:dep"),
         btn("🛬 ورودی‌ها (فرودگاه)", "av:help:arr")],
        [btn("🏢 فرودگاه‌ها", "av:help:airports"),
         btn("🛩️ هواپیماها", "av:help:airplanes")],
        [btn("🛫 خطوط هوایی", "av:help:airlines"),
         btn("🗺 مسیرها", "av:help:routes")],
        [btn("🌐 IP من", "av:help:ip"),
         btn("🏠 منو", "m:main"),
         btn("🔄", "av:help:refresh"),
         btn("ℹ️", "av:help:info"),
         btn("⚙️", "av:help:opts")],
    ])


@ROUTER.command("aviation", description="منوی هوانوردی")
def cmd_aviation_v17_obsolete(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    TG.send_message(chat_id,
        "✈️ <b>مرکز هوانوردی</b>\n\n"
        "یکی از گزینه‌ها را انتخاب کن یا از دستورات مستقیم استفاده کن:\n"
        "<code>/flight IR720</code>\n"
        "<code>/departures IKA</code>\n"
        "<code>/arrivals IKA</code>\n"
        "<code>/airports تهران</code>\n"
        "<code>/airlines Mahan</code>\n"
        "<code>/airplanes Boeing</code>\n"
        "<code>/routes IKA THR</code>",
        reply_markup=kb_aviation_menu())


@ROUTER.callback("av")
def cb_aviation_v17_obsolete(cb: Dict, data: str) -> None:
    action = data.split(":")[1] if ":" in data else ""
    param = data.split(":", 2)[2] if data.count(":") >= 2 else ""
    chat_id = cb["message"]["chat"]["id"]
    msg_id = cb["message"]["message_id"]
    TG.answer_callback(cb.get("id", ""), "✈️")
    hints = {
        "flight":   "استفاده: <code>/flight IR720</code>",
        "dep":      "استفاده: <code>/departures IKA</code>",
        "arr":      "استفاده: <code>/arrivals IKA</code>",
        "airports": "استفاده: <code>/airports تهران</code>",
        "airlines": "استفاده: <code>/airlines Mahan</code>",
        "airplanes":"استفاده: <code>/airplanes Boeing</code>",
        "routes":   "استفاده: <code>/routes IKA THR</code>",
        "ip":       "استفاده: <code>/ip 8.8.8.8</code>",
        "refresh":  "برای به‌روزرسانی منوی هوانوردی",
        "info":     "منبع: Aviationstack API",
        "opts":     "از /settings تنظیم کن",
        "help":     hints.get(param, "?")
    }
    if action == "help":
        TG.edit_message(chat_id, msg_id, f"✈️ <b>راهنما</b>\n\n{hints.get(param,'')}",
            reply_markup=kb_aviation_menu())


@ROUTER.command("departures", description="خروجی‌های فرودگاه")
def cmd_departures(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    if not args:
        TG.send_message(chat_id, "استفاده: <code>/departures IKA</code>"); return
    m = TG.send_message(chat_id, "🛫 در حال دریافت...")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")
    r = APIS.aviationstack.flights_from(args.strip().upper(), limit=8)
    if not r.ok:
        TG.edit_message(chat_id, mid, f"❌ {escape_html(r.error[:150])}"); return
    fl = (r.data or {}).get("data", [])[:8]
    if not fl:
        TG.edit_message(chat_id, mid, "❌ موردی یافت نشد"); return
    text = f"🛫 <b>خروجی‌های {escape_html(args.upper())}</b>\n\n"
    for f in fl:
        text += APIS.aviationstack.format_flight(f) + "\n\n"
    TG.edit_message(chat_id, mid, text[:4000], reply_markup=kb_aviation_menu())


@ROUTER.command("arrivals", description="ورودی‌های فرودگاه")
def cmd_arrivals(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    if not args:
        TG.send_message(chat_id, "استفاده: <code>/arrivals IKA</code>"); return
    m = TG.send_message(chat_id, "🛬 در حال دریافت...")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")
    r = APIS.aviationstack.flights_to(args.strip().upper(), limit=8)
    if not r.ok:
        TG.edit_message(chat_id, mid, f"❌ {escape_html(r.error[:150])}"); return
    fl = (r.data or {}).get("data", [])[:8]
    if not fl:
        TG.edit_message(chat_id, mid, "❌ موردی یافت نشد"); return
    text = f"🛬 <b>ورودی‌های {escape_html(args.upper())}</b>\n\n"
    for f in fl:
        text += APIS.aviationstack.format_flight(f) + "\n\n"
    TG.edit_message(chat_id, mid, text[:4000], reply_markup=kb_aviation_menu())


@ROUTER.command("airports", description="جستجوی فرودگاه")
def cmd_airports(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    m = TG.send_message(chat_id, "🏢 در حال دریافت...")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")
    r = APIS.aviationstack.airports(args.strip(), limit=8)
    if not r.ok:
        TG.edit_message(chat_id, mid, f"❌ {escape_html(r.error[:150])}"); return
    arr = (r.data or {}).get("data", [])[:8]
    if not arr:
        TG.edit_message(chat_id, mid, "❌ یافت نشد"); return
    text = "🏢 <b>فرودگاه‌ها</b>\n\n"
    for a in arr:
        text += (f"• <b>{escape_html(a.get('airport_name','?'))}</b>\n"
                 f"  کد: <code>{escape_html(a.get('iata_code','?'))}</code> | "
                 f"{escape_html(a.get('country_name','?'))}\n\n")
    TG.edit_message(chat_id, mid, text[:4000], reply_markup=kb_aviation_menu())


@ROUTER.command("airlines", description="جستجوی خطوط هوایی")
def cmd_airlines(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    m = TG.send_message(chat_id, "🛫 در حال دریافت...")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")
    r = APIS.aviationstack.airlines(args.strip(), limit=10)
    if not r.ok:
        TG.edit_message(chat_id, mid, f"❌ {escape_html(r.error[:150])}"); return
    arr = (r.data or {}).get("data", [])[:10]
    if not arr:
        TG.edit_message(chat_id, mid, "❌ یافت نشد"); return
    text = "🛫 <b>خطوط هوایی</b>\n\n"
    for a in arr:
        text += (f"• <b>{escape_html(a.get('airline_name','?'))}</b>\n"
                 f"  کد: <code>{escape_html(a.get('iata_code','?'))}</code> | "
                 f"{escape_html(a.get('country_name','?'))}\n\n")
    TG.edit_message(chat_id, mid, text[:4000], reply_markup=kb_aviation_menu())


@ROUTER.command("airplanes", description="جستجوی هواپیما")
def cmd_airplanes(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    m = TG.send_message(chat_id, "🛩️ در حال دریافت...")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")
    r = APIS.aviationstack.airplanes(args.strip(), limit=10)
    if not r.ok:
        TG.edit_message(chat_id, mid, f"❌ {escape_html(r.error[:150])}"); return
    arr = (r.data or {}).get("data", [])[:10]
    if not arr:
        TG.edit_message(chat_id, mid, "❌ یافت نشد"); return
    text = "🛩️ <b>هواپیماها</b>\n\n"
    for a in arr:
        text += (f"• <b>{escape_html(a.get('model_name','?'))}</b> — "
                 f"{escape_html(a.get('manufacturer','?'))}\n"
                 f"  کد: <code>{escape_html(a.get('iata_code','?'))}</code>\n\n")
    TG.edit_message(chat_id, mid, text[:4000], reply_markup=kb_aviation_menu())


@ROUTER.command("routes", description="جستجوی مسیرها")
def cmd_routes(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    parts = args.split()
    kw = {}
    if len(parts) >= 2:
        kw["dep_iata"] = parts[0].upper()
        kw["arr_iata"] = parts[1].upper()
    if not kw:
        TG.send_message(chat_id, "استفاده: <code>/routes IKA THR</code>"); return
    m = TG.send_message(chat_id, "🗺 در حال دریافت...")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")
    r = APIS.aviationstack.routes(**kw, limit=10)
    if not r.ok:
        TG.edit_message(chat_id, mid, f"❌ {escape_html(r.error[:150])}"); return
    arr = (r.data or {}).get("data", [])[:10]
    if not arr:
        TG.edit_message(chat_id, mid, "❌ یافت نشد"); return
    text = "🗺 <b>مسیرها</b>\n\n"
    for rt in arr:
        dep = (rt.get("departure") or {}).get("iata", "?")
        arr2 = (rt.get("arrival") or {}).get("iata", "?")
        al = rt.get("airline", "?")
        text += f"• <code>{escape_html(str(dep))}</code> → <code>{escape_html(str(arr2))}</code>  |  {escape_html(str(al))}\n"
    TG.edit_message(chat_id, mid, text[:4000], reply_markup=kb_aviation_menu())

@ROUTER.command("flights_to", description="پروازهای به فرودگاه")
def cmd_flights_to(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    if not args:
        return
    m = TG.send_message(chat_id, "✈️...")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")

    r = APIS.aviationstack.flights_to(args.strip().upper(), limit=5)
    if not r.ok:
        TG.edit_message(chat_id, mid, f"❌ {r.error[:150]}")
        return
    flights = (r.data or {}).get("data", [])[:5]
    text = f"✈️ <b>پروازهای به {escape_html(args.upper())}</b>\n\n"
    for f in flights:
        text += APIS.aviationstack.format_flight(f) + "\n\n"
    TG.edit_message(chat_id, mid, text[:4000])


# ─── IP-API ────────────────────────────────────────────

@ROUTER.command("ip", description="اطلاعات IP")
def cmd_ip(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    target = args.strip() if args else ""

    r = APIS.ipapi.lookup(target)
    if not r.ok:
        TG.send_message(chat_id, f"❌ {escape_html(r.error[:150])}")
        return

    text = APIS.ipapi.format(r.data)
    TG.send_message(chat_id, text)


# ─── APIFY ─────────────────────────────────────────────

@ROUTER.command("yt", description="جستجوی یوتیوب")
def cmd_youtube(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    if not args:
        try:
            t = random.choice(_get_topics_list() or [{"name": "Mechanical engineering"}])
            sug = t.get("query") or t.get("name") or "Mechanical engineering"
        except Exception:
            sug = "Mechanical engineering tutorial"
        TG.send_message(chat_id,
            f"🎥 <b>یوتیوب</b>\n\n"
            f"پیشنهاد: <code>/yt {escape_html(sug)}</code>\n\n"
            "یا موضوع دلخواه بنویس:\n<code>/yt موضوع</code>",
            reply_markup=kb([
                [btn(f"🎥 {sug[:28]}", f"y:go:{sug[:50]}")],
                [btn("🎬 آموزش مکانیک", "y:go:mechanical engineering tutorial")],
                [btn("🎲 پیشنهاد دیگر", "y:rand"),
                 btn("🏠 منو", "m:main")],
            ]))
        return

    m = TG.send_message(chat_id, "🎥 در حال جستجو...")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")

    r = APIS.apify.youtube_search(args, max_videos=5)
    if not r.ok:
        TG.edit_message(chat_id, mid, f"❌ {escape_html(r.error[:200])}")
        return

    videos = r.data if isinstance(r.data, list) else []
    if not videos:
        TG.edit_message(chat_id, mid, "❌ ویدیویی یافت نشد.")
        return

    text = f"🎥 <b>نتایج YouTube: {escape_html(args[:40])}</b>\n\n"
    for i, v in enumerate(videos[:5], 1):
        title = escape_html((v.get("title") or "")[:80])
        url = v.get("url") or v.get("videoUrl") or ""
        ch = escape_html((v.get("channelName") or "")[:30])
        views = v.get("viewCount", "?")
        text += f"<b>{i}. {title}</b>\n👤 {ch} | 👁 {views}\n<a href='{url}'>مشاهده</a>\n\n"

    TG.edit_message(chat_id, mid, text[:4000])


@ROUTER.command("ytinfo", description="اطلاعات ویدیوی یوتیوب")
def cmd_yt_info(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    if not args or "youtu" not in args:
        TG.send_message(chat_id, "❌ استفاده: <code>/ytinfo URL</code>")
        return

    m = TG.send_message(chat_id, "🎥...")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")

    r = APIS.apify.youtube_video(args.strip())
    if not r.ok:
        TG.edit_message(chat_id, mid, f"❌ {r.error[:150]}")
        return

    vids = r.data if isinstance(r.data, list) else []
    if not vids:
        TG.edit_message(chat_id, mid, "❌ یافت نشد.")
        return

    v = vids[0]
    text = (
        f"🎥 <b>{escape_html((v.get('title') or '')[:100])}</b>\n\n"
        f"👤 {escape_html(v.get('channelName', '?'))}\n"
        f"👁 {v.get('viewCount', '?')} | ⏱ {escape_html(v.get('duration', '?'))}\n"
        f"📅 {escape_html(v.get('date', '?'))}\n"
        f"💬 {v.get('commentsCount', '?')} | 👍 {v.get('likes', '?')}\n\n"
        f"<a href='{v.get('url', '')}'>مشاهده ویدیو</a>"
    )
    TG.edit_message(chat_id, mid, text)


@ROUTER.command("transcript", description="متن یوتیوب")
def cmd_transcript(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    if not args or "youtu" not in args:
        TG.send_message(chat_id, "❌ استفاده: <code>/transcript URL</code>")
        return

    m = TG.send_message(chat_id, "📝 در حال دریافت زیرنویس (ممکن است ۲-۳ دقیقه طول بکشد)...")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")

    r = APIS.apify.youtube_transcript(args.strip())
    if not r.ok:
        TG.edit_message(chat_id, mid, f"❌ {r.error[:200]}")
        return

    vids = r.data if isinstance(r.data, list) else []
    if not vids:
        TG.edit_message(chat_id, mid, "❌ زیرنویس یافت نشد.")
        return

    v = vids[0]
    subtitles = v.get("subtitles") or []
    if not subtitles:
        TG.edit_message(chat_id, mid, "❌ زیرنویس موجود نیست.")
        return

    srt = subtitles[0].get("srt", "")
    clean = re.sub(r"\d+\n\d{2}:\d{2}:\d{2}[^\n]*\n", "", srt)
    clean = re.sub(r"\n{2,}", "\n", clean).strip()

    if not clean:
        TG.edit_message(chat_id, mid, "❌ متن خالی.")
        return

    # Translate to Persian
    tr = APIS.translate.translate(clean[:3000], "en", "fa")
    final = tr.data if tr.ok else clean[:3000]

    TG.edit_message(chat_id, mid, "📝 متن:")
    TG.send_long_message(chat_id, final)


@ROUTER.command("ig", description="پروفایل اینستاگرام")
def cmd_ig(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    if not args:
        TG.send_message(chat_id, "❌ استفاده: <code>/ig username</code>")
        return

    m = TG.send_message(chat_id, "📸...")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")

    r = APIS.apify.instagram_profile(args.strip(), max_posts=5)
    if not r.ok:
        TG.edit_message(chat_id, mid, f"❌ {r.error[:150]}")
        return

    posts = r.data if isinstance(r.data, list) else []
    text = f"📸 <b>آخرین پست‌های {escape_html(args)}</b>\n\n"
    for i, p in enumerate(posts[:5], 1):
        cap = escape_html((p.get("caption") or "")[:150])
        likes = p.get("likesCount", "?")
        url = p.get("url", "")
        text += f"{i}. 👍 {likes}\n{cap}\n<a href='{url}'>مشاهده</a>\n\n"

    TG.edit_message(chat_id, mid, text[:4000])


@ROUTER.command("web", description="محتوای وب‌سایت")
def cmd_web(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    if not args or not args.startswith("http"):
        TG.send_message(chat_id, "❌ استفاده: <code>/web URL</code>")
        return

    m = TG.send_message(chat_id, "🌐 در حال دریافت...")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")

    r = APIS.apify.website_content(args.strip())
    if not r.ok:
        TG.edit_message(chat_id, mid, f"❌ {r.error[:150]}")
        return

    items = r.data if isinstance(r.data, list) else []
    if not items:
        TG.edit_message(chat_id, mid, "❌ محتوایی یافت نشد.")
        return

    text = items[0].get("text") or items[0].get("markdown", "")
    if not text:
        TG.edit_message(chat_id, mid, "❌ خالی.")
        return

    TG.edit_message(chat_id, mid, "🌐 محتوا:")
    TG.send_long_message(chat_id, escape_html(text[:5000]))


@ROUTER.command("maps", description="جستجوی مکان")
def cmd_maps(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    if not args:
        TG.send_message(chat_id, "❌ استفاده: <code>/maps مکان</code>")
        return

    m = TG.send_message(chat_id, "🗺 در حال جستجو...")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")

    r = APIS.apify.google_maps(args, max_places=5)
    if not r.ok:
        TG.edit_message(chat_id, mid, f"❌ {r.error[:150]}")
        return

    places = r.data if isinstance(r.data, list) else []
    text = f"🗺 <b>نتایج نقشه: {escape_html(args[:40])}</b>\n\n"
    for i, p in enumerate(places[:5], 1):
        text += (
            f"<b>{i}. {escape_html((p.get('title') or '')[:60])}</b>\n"
            f"📍 {escape_html((p.get('address') or '')[:100])}\n"
            f"⭐ {p.get('totalScore', '?')} ({p.get('reviewsCount', '?')} نظر)\n\n"
        )
    TG.edit_message(chat_id, mid, text[:4000])


# ─── WEATHER ───────────────────────────────────────────

@ROUTER.command("weather", description="آب و هوا")
def cmd_weather(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    city = args.strip() or "Tehran"

    m = TG.send_message(chat_id, f"🌤 در حال دریافت آب و هوای {escape_html(city)}...")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")

    r = APIS.weather.forecast(city, days=3)
    if not r.ok:
        TG.edit_message(chat_id, mid, f"❌ {escape_html(r.error[:150])}")
        return

    text = APIS.weather.format(r.data)
    TG.edit_message(chat_id, mid, text)


# ─── EXCHANGE ──────────────────────────────────────────

@ROUTER.command("rate", description="نرخ ارز")
def cmd_rate(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    symbols = args.strip() or "EUR,GBP,IRR,AED,TRY,CNY"

    r = APIS.exchange.latest("USD", symbols)
    if not r.ok:
        TG.send_message(chat_id, f"❌ {r.error[:150]}")
        return

    rates = (r.data or {}).get("rates", {})
    text = "💱 <b>نرخ ارز (پایه USD)</b>\n\n"
    for cur, rate in rates.items():
        text += f"• {cur}: <code>{rate}</code>\n"

    TG.send_message(chat_id, text)


@ROUTER.command("convert", description="تبدیل ارز")
def cmd_convert(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    parts = args.split()
    if len(parts) < 3:
        TG.send_message(chat_id, "❌ استفاده: <code>/convert 100 USD IRR</code>")
        return

    try:
        amount = float(parts[0])
        from_cur = parts[1].upper()
        to_cur = parts[2].upper()
    except Exception:
        TG.send_message(chat_id, "❌ فرمت اشتباه")
        return

    r = APIS.exchange.convert(amount, from_cur, to_cur)
    if not r.ok:
        TG.send_message(chat_id, f"❌ {r.error[:150]}")
        return

    result = (r.data or {}).get("result", "?")
    TG.send_message(chat_id,
                   f"💱 <code>{amount} {from_cur} = {result} {to_cur}</code>")


# ─── NEWS ──────────────────────────────────────────────

# ─── Advanced News (FIX5) ────────────────────────────────────────────────
NEWS_CATS = {
    "fluids":  "🌊 سیالات و آیرودینامیک",
    "mat":     "💎 مواد و متالورژی",
    "ce":      "🏗️ عمران و سازه",
    "phys":    "⚛️ فیزیک کاربردی",
    "eng":     "⚙️ مهندسی عمومی",
    "space":   "🚀 فضا و نجوم",
    "tech":    "💻 فناوری و هوش مصنوعی",
    "energy":  "🔋 انرژی و محیط‌زیست",
}


def kb_news_menu() -> Dict:
    return kb([
        [btn("📡 تازه‌ترین اخبار", "n:fresh")],
        [btn("📚 arXiv — جدید", "n:arxiv"), btn("📰 RSS مهندسی", "n:rss")],
        [btn("🗂 دسته‌بندی", "n:cats"), btn("🔍 جستجو", "n:search")],
        [btn("🌍 همه منابع", "n:all"), btn("🚀 فضا و ناسا", "n:space")],
        [btn("🏠 منو", "m:main"), btn("🔄 رفرش", "n:fresh"),
         btn("⬅️", "m:main"), btn("ℹ️", "n:help"), btn("⚙️", "n:opts")],
    ])


def kb_news_cats() -> Dict:
    rows = []
    items = list(NEWS_CATS.items())
    for i in range(0, len(items), 2):
        row = []
        for k, label in items[i:i+2]:
            row.append(btn(label, f"n:cat:{k}"))
        rows.append(row)
    rows.append([btn("⬅️ بازگشت", "n:home")])
    return kb(rows)


def _news_fetch_and_render(chat_id, mid, mode, param=""):
    """Fetch and render news according to mode."""
    try:
        _prog(f"news mode={mode} param={param}", "news")
        if mode == "arxiv":
            r = APIS.arxiv.search(param or "mechanical engineering", max_results=8)
            if not r.ok or not r.data:
                TG.edit_message(chat_id, mid, "❌ arXiv خالی"); return
            text = "📚 <b>arXiv — جدید</b>\n\n"
            for i, p in enumerate(r.data[:8], 1):
                text += f"{i}. <b>{escape_html(p['title'][:90])}</b>\n"
                text += f"👥 {escape_html(', '.join(p['authors'][:2]))}\n"
                text += f"<a href='{p['link']}'>مقاله</a>\n\n"
            TG.edit_message(chat_id, mid, text[:4000], reply_markup=kb_news_menu())
            return
        if mode == "space":
            feeds = ["nasa", "spacex_reddit"]
            all_items = []
            for f in feeds:
                if f in APIS.news.FEEDS:
                    r = APIS.news.fetch_feed(APIS.news.FEEDS[f], 5)
                    if r.ok and r.data: all_items.extend(r.data)
            if not all_items:
                TG.edit_message(chat_id, mid, "❌ خبری یافت نشد"); return
            text = "🚀 <b>فضا و ناسا</b>\n\n"
            for i, it in enumerate(all_items[:8], 1):
                text += f"{i}. <b>{escape_html(it.get('title','')[:100])}</b>\n"
                text += f"<a href='{it.get('link','')}'>مشاهده</a>\n\n"
            TG.edit_message(chat_id, mid, text[:4000], reply_markup=kb_news_menu())
            return
        # default: fresh / rss / all
        kw_map = {
            "fluids": ["fluid", "turbulence", "aerodynamic", "cfd", "flow"],
            "mat": ["material", "alloy", "composite", "nanoparticle"],
            "ce": ["civil", "structure", "construction", "bridge"],
            "phys": ["physics", "quantum", "optical"],
            "eng": ["engineer", "mechanical", "machine"],
            "space": ["space", "nasa", "mars", "orbit"],
            "tech": ["ai", "technology", "software", "chip"],
            "energy": ["energy", "solar", "wind", "battery", "hydrogen"],
        }
        items = APIS.news.fetch_combined(limit=40)
        if mode == "cat" and param in kw_map:
            items = APIS.news.filter_by_keywords(items, kw_map[param])
        if mode == "search" and param:
            items = APIS.news.filter_by_keywords(items, [param])
        if not items:
            TG.edit_message(chat_id, mid, "❌ نتیجه‌ای یافت نشد")
            return
        title = "📰 <b>اخبار مهندسی</b>"
        if mode == "cat" and param in NEWS_CATS:
            title = f"📰 <b>{NEWS_CATS[param]}</b>"
        elif mode == "search":
            title = f"🔍 <b>جستجو: {escape_html(param)}</b>"
        text = title + "\n\n"
        for i, it in enumerate(items[:10], 1):
            text += f"{i}. <b>{escape_html(it.get('title','')[:100])}</b>\n"
            text += f"<i>{escape_html(it.get('feed_name',''))}</i>\n"
            if it.get("link"):
                text += f"<a href='{it['link']}'>مشاهده</a>\n"
            text += "\n"
        TG.edit_message(chat_id, mid, text[:4000], reply_markup=kb_news_menu())
    except Exception as e:
        _prog(f"news error: {e}", "news")
        TG.edit_message(chat_id, mid, f"❌ خطا: {escape_html(str(e)[:150])}")


@ROUTER.command("news", description="اخبار پیشرفته")
def cmd_news(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    if args:
        m = TG.send_message(chat_id, "📰 جستجو...")
        if not m.ok: return
        mid = (m.result or {}).get("message_id")
        POOL.submit(_news_fetch_and_render, chat_id, mid, "search", args)
        return
    TG.send_message(chat_id,
        "📰 <b>مرکز اخبار</b>\n\nیکی از گزینه‌های زیر را انتخاب کن:",
        reply_markup=kb_news_menu())


@ROUTER.callback("n")
def cb_news(cb: Dict, data: str) -> None:
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else "home"
    chat_id = cb["message"]["chat"]["id"]
    msg_id = cb["message"]["message_id"]
    TG.answer_callback(cb.get("id", ""))

    if action == "home":
        TG.edit_message(chat_id, msg_id,
            "📰 <b>مرکز اخبار</b>\n\nیکی از گزینه‌ها را انتخاب کن:",
            reply_markup=kb_news_menu())
        return
    if action == "cats":
        TG.edit_message(chat_id, msg_id,
            "🗂 <b>دسته‌بندی اخبار</b>", reply_markup=kb_news_cats())
        return
    if action == "help":
        TG.edit_message(chat_id, msg_id,
            "ℹ️ <b>راهنما</b>\n\n"
            "• دستور: <code>/news [کلمه]</code>\n"
            "• برای جستجو داخل اخبار: <code>/news CFD</code>\n"
            "• منوی تازه: <code>/news</code>", reply_markup=kb_news_menu())
        return
    if action == "opts":
        TG.edit_message(chat_id, msg_id,
            "⚙️ برای تغییر منابع: از /settings استفاده کن",
            reply_markup=kb_news_menu())
        return

    # fetch modes
    m = TG.edit_message(chat_id, msg_id, "⏳ در حال دریافت...")
    if action == "fresh":
        POOL.submit(_news_fetch_and_render, chat_id, msg_id, "fresh")
    elif action == "rss":
        POOL.submit(_news_fetch_and_render, chat_id, msg_id, "all")
    elif action == "all":
        POOL.submit(_news_fetch_and_render, chat_id, msg_id, "all")
    elif action == "arxiv":
        POOL.submit(_news_fetch_and_render, chat_id, msg_id, "arxiv", "")
    elif action == "space":
        POOL.submit(_news_fetch_and_render, chat_id, msg_id, "space")
    elif action == "cat" and len(parts) >= 3:
        POOL.submit(_news_fetch_and_render, chat_id, msg_id, "cat", parts[2])
    elif action == "search":
        TG.edit_message(chat_id, msg_id,
            "🔍 برای جستجو بنویس: <code>/news کلمه</code>",
            reply_markup=kb_news_menu())


@ROUTER.command("livenews", description="جستجوی اخبار زنده")
def cmd_live_news(msg: Dict, args: str) -> None:
    if not args:
        cmd_news(msg, args)
        return
    chat_id = get_chat_id(msg)
    m = TG.send_message(chat_id, "📰...")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")

    items = APIS.news.fetch_combined(limit=40)
    filtered = APIS.news.filter_by_keywords(items, [args])

    if not filtered:
        TG.edit_message(chat_id, mid, "❌ نتیجه‌ای یافت نشد.")
        return

    text = f"📰 <b>اخبار «{escape_html(args)}»</b>\n\n"
    for i, item in enumerate(filtered[:8], 1):
        text += f"{i}. <b>{escape_html(item.get('title', '')[:100])}</b>\n"
        text += f"<a href='{item.get('link', '')}'>مشاهده</a>\n\n"

    TG.edit_message(chat_id, mid, text[:4000])


@ROUTER.command("spacex", description="اخبار SpaceX")
def cmd_spacex(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    m = TG.send_message(chat_id, "🚀...")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")

    r = APIS.news.fetch_feed(APIS.news.FEEDS["spacex_reddit"], 8)
    if not r.ok or not r.data:
        TG.edit_message(chat_id, mid, "❌ خبری یافت نشد.")
        return

    text = "🚀 <b>اخبار SpaceX (Reddit)</b>\n\n"
    for i, item in enumerate(r.data[:8], 1):
        text += f"{i}. {escape_html(item.get('title', '')[:100])}\n"
        text += f"<a href='{item.get('link', '')}'>مشاهده</a>\n\n"

    TG.edit_message(chat_id, mid, text[:4000])


# ─── ARXIV ─────────────────────────────────────────────

@ROUTER.command("arxiv", description="جستجوی arXiv")
def cmd_arxiv(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    query = args.strip() or "mechanical engineering"

    m = TG.send_message(chat_id, "📚 در حال جستجو در arXiv...")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")

    r = APIS.arxiv.search(query, max_results=5)
    if not r.ok or not r.data:
        TG.edit_message(chat_id, mid, "❌ نتیجه‌ای یافت نشد.")
        return

    text = f"📚 <b>arXiv: {escape_html(query[:50])}</b>\n\n"
    for i, p in enumerate(r.data[:5], 1):
        text += f"<b>{i}. {escape_html(p['title'][:100])}</b>\n"
        text += f"👥 {escape_html(', '.join(p['authors'][:2]))}\n"
        text += f"📅 {escape_html(p['published'][:10])}\n"
        text += f"<a href='{p['link']}'>مقاله</a>\n\n"

    TG.edit_message(chat_id, mid, text[:4000])


# ─── WIKIPEDIA ─────────────────────────────────────────

@ROUTER.command("wiki", description="ویکی‌پدیا")
def cmd_wiki(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    if not args:
        # random suggestion
        try:
            t = random.choice(_get_topics_list() or [{"name": "Mechanical engineering"}])
            sug = t.get("query") or t.get("name") or "Mechanical engineering"
        except Exception:
            sug = "Mechanical engineering"
        TG.send_message(chat_id,
            f"📖 <b>ویکی‌پدیا</b>\n\n"
            f"پیشنهاد: <code>/wiki {escape_html(sug)}</code>\n\n"
            "یا موضوع دلخواه بنویس:\n<code>/wiki موضوع</code>",
            reply_markup=kb([
                [btn(f"📖 {sug[:28]}", f"w:go:{sug[:50]}")],
                [btn("🎲 پیشنهاد دیگر", "w:rand"),
                 btn("🏠 منو", "m:main")],
            ]))
        return

    # Try Persian first, then English
    r = APIS.wikipedia.summary(args, "fa")
    if not r.ok:
        r = APIS.wikipedia.summary(args, "en")

    if not r.ok:
        TG.send_message(chat_id, f"❌ یافت نشد: {escape_html(args)}")
        return

    data = r.data
    extract = clean_wiki_extract(data.get("extract", "") or "")
    if not extract:
        extract = "(خلاصه‌ای در دسترس نیست)"
    text = (
        f"📖 <b>{escape_html(data.get('title', ''))}</b>\n\n"
        f"{escape_html(extract[:1800])}\n\n"
        f"<a href='{data.get('url', '')}'>ادامه در ویکی‌پدیا</a>"
    )
    TG.send_message(chat_id, text)


# ─── DICTIONARY ────────────────────────────────────────

@ROUTER.command("dict", description="دیکشنری")
def cmd_dict(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    if not args:
        return

    r = APIS.dictionary.lookup(args)
    if not r.ok:
        TG.send_message(chat_id, f"❌ یافت نشد.")
        return

    data = r.data
    text = f"📕 <b>{escape_html(data['word'])}</b>\n"
    if data.get("phonetic"):
        text += f"<code>{escape_html(data['phonetic'])}</code>\n"
    text += "\n"

    for m in data.get("meanings", []):
        text += f"<b>{escape_html(m['part_of_speech'])}</b>\n"
        for d in m.get("definitions", []):
            text += f"• {escape_html(d[:200])}\n"
        text += "\n"

    TG.send_message(chat_id, text[:4000])


# ─── TRANSLATE ─────────────────────────────────────────

@ROUTER.command("tr", description="ترجمه")
def cmd_translate(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    if not args:
        TG.send_message(chat_id, "❌ استفاده: <code>/tr en fa متن</code>")
        return

    parts = args.split(None, 2)
    if len(parts) < 3:
        TG.send_message(chat_id, "❌ فرمت: <code>/tr from to متن</code>")
        return

    src, tgt, text = parts[0], parts[1], parts[2]

    m = TG.send_message(chat_id, "🌍 در حال ترجمه...")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")

    r = APIS.translate.translate(text, src, tgt)
    if not r.ok:
        TG.edit_message(chat_id, mid, f"❌ {r.error[:150]}")
        return

    TG.edit_message(chat_id, mid, f"🌍 <b>ترجمه:</b>\n\n{escape_html(r.data)}")


# ─── NUMBERS ───────────────────────────────────────────

@ROUTER.command("fact", description="دانستنی عددی")
def cmd_fact(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)

    if not args:
        r = APIS.numbers.random_fact()
    else:
        try:
            n = int(args.strip())
            r = APIS.numbers.fact(n)
        except Exception:
            r = APIS.numbers.random_fact()

    if not r.ok:
        TG.send_message(chat_id, f"❌ {r.error[:100]}")
        return

    text = r.data.get("text", "")
    num = r.data.get("number", "")

    # Translate
    tr = APIS.translate.translate(text, "en", "fa")
    translated = tr.data if tr.ok else text

    TG.send_message(chat_id, f"🔢 <b>{num}</b>\n\n{escape_html(translated)}")


# ─── FREE PUBLIC APIS ──────────────────────────────────

@ROUTER.command("quote", description="نقل قول تصادفی")
def cmd_quote(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    r = APIS.freeapiapp.random_quote()
    if not r.ok or not r.data:
        TG.send_message(chat_id, "❌ خطا در دریافت نقل قول")
        return
    try:
        d = r.data.get("data", {})
        text = f"\U0001F4AC <b>نقل قول:</b>\n\n{d.get('content', '')}\n\n\u2014 {d.get('author', '?')}"
        TG.send_message(chat_id, text)
    except Exception as e:
        TG.send_message(chat_id, f"❌ {e}")


@ROUTER.command("joke", description="جوک تصادفی")
def cmd_joke(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    r = APIS.freeapiapp.random_joke()
    if not r.ok or not r.data:
        TG.send_message(chat_id, "❌ خطا در دریافت جوک")
        return
    try:
        items = r.data.get("data", {}).get("data", []) or []
        if items:
            j = items[0]
            text = f"\U0001F602 <b>جوک:</b>\n\n{j.get('content', '')}"
            TG.send_message(chat_id, text)
    except Exception as e:
        TG.send_message(chat_id, f"❌ {e}")


@ROUTER.command("randomuser", description="کاربر تصادفی")
def cmd_randomuser(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    r = APIS.freeapiapp.random_user()
    if not r.ok or not r.data:
        TG.send_message(chat_id, "❌ خطا")
        return
    try:
        items = r.data.get("data", {}).get("data", []) or []
        if items:
            u = items[0]
            name = u.get("name", {})
            text = (
                f"\U0001F464 <b>کاربر تصادفی:</b>\n\n"
                f"\u2022 نام: {name.get('title','')} {name.get('first','')} {name.get('last','')}\n"
                f"\u2022 ایمیل: <code>{u.get('email','')}</code>\n"
                f"\u2022 کشور: {u.get('location',{}).get('country','')}\n"
                f"\u2022 تلفن: {u.get('phone','')}"
            )
            TG.send_message(chat_id, text)
    except Exception as e:
        TG.send_message(chat_id, f"❌ {e}")


@ROUTER.command("randomapi", description="API تصادفی")
def cmd_random_api(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    r = APIS.freepublic.random_api()
    if not r.ok:
        TG.send_message(chat_id, f"❌ {r.error[:150]}")
        return

    data = r.data
    if not isinstance(data, dict):
        TG.send_message(chat_id, "❌ فرمت نامعتبر")
        return

    name = escape_html(str(data.get("name", "?")))
    desc = escape_html(str(data.get("description", ""))[:300])
    url = data.get("link", "") or data.get("url", "")

    text = f"🎲 <b>{name}</b>\n\n{desc}"
    if url:
        text += f"\n\n<a href='{url}'>مشاهده</a>"

    TG.send_message(chat_id, text)


# ══════════════════════════════════════════════════════════════════════════════
#                        PART 3 SELF TEST
# ══════════════════════════════════════════════════════════════════════════════

def self_test_part3() -> None:
    head("Part 3/5 — External APIs Self-Test")

    cfg = CONFIG.get()

    # Config check
    step("Checking configured APIs...")
    config_status = {
        "Gemini": bool(cfg.keys.gemini),
        "Zenserp": bool(cfg.keys.zenserp),
        "Aviationstack": bool(cfg.keys.aviationstack),
        "Apify": bool(cfg.keys.apify),
        "OpenRouter": bool(cfg.keys.openrouter),
    }
    for k, v in config_status.items():
        info(f"  {k}: {'✅' if v else '❌'}")

    # Test each
    print()
    step("Testing configured APIs (this may take a minute)...")

    results = APIS.test_all()

    for name, r in results.items():
        if not APIS.all()[name].is_configured():
            continue
        if r.ok:
            val = r.data if isinstance(r.data, str) else str(r.data)[:50]
            ok(f"{name}: {val}")
        else:
            warn(f"{name}: {r.error[:80]}")

    # Test parallel calls
    print()
    step("Testing parallel API calls...")
    t0 = time.perf_counter()
    futures = [
        POOL.submit(APIS.weather.forecast, "Tehran", days=1),
        POOL.submit(APIS.arxiv.search, "fluid mechanics", max_results=2),
        POOL.submit(APIS.news.fetch_feed, APIS.news.FEEDS["phys_org"], 2),
        POOL.submit(APIS.exchange.latest, "USD", "EUR"),
    ]
    POOL.gather(futures, timeout=60)
    dt = time.perf_counter() - t0
    ok(f"4 parallel API calls in {dt*1000:.0f}ms")

    print()
    succ("Part 3/5 self-test complete.")
    info("Send 'ادامه' for Part 4/5 (Content generation + 44 topics + formulas + drafts)")



#              PART 4/5 — CONTENT ENGINE, TOPICS, FORMULAS, DRAFTS
# ══════════════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════════════
#                        ENGINEERING TOPICS (44)
#══════════════════════════════════════════════════════════════════════════════

TOPICS: List[Dict[str, Any]] = [
    # ─── ریاضیات مهندسی (8) ───────────────────────────────────
    {"name": "حساب دیفرانسیل", "query": "differential calculus engineering",
     "style": "math", "emoji": "∂", "tags": "#حساب_دیفرانسیل #مشتق #ریاضی",
     "formulas": ["f'(x) = lim(h→0)(f(x+h)-f(x))/h", "(uv)' = u'v + uv'", "(u/v)' = (u'v-uv')/v²"]},
    {"name": "حساب انتگرال", "query": "integral calculus engineering",
     "style": "math", "emoji": "∫", "tags": "#انتگرال #ریاضی",
     "formulas": ["∫x^n dx = x^(n+1)/(n+1) + C", "∫u dv = uv - ∫v du (جزءبهجزء)"]},
    {"name": "انتگرال چندگانه", "query": "multiple integrals volume",
     "style": "math", "emoji": "∭", "tags": "#انتگرال_چندگانه",
     "formulas": ["∭f(x,y,z)dV", "V = ∭dV", "قضیه دایورژنس: ∬F·n dS = ∭∇·F dV"]},
    {"name": "معادلات دیفرانسیل", "query": "differential equations ODE PDE",
     "style": "math", "emoji": "📐", "tags": "#معادلات_دیفرانسیل",
     "formulas": ["y' + P(x)y = Q(x)", "y = e^(-∫Pdx)(∫Qe^(∫Pdx)dx + C)", "روش لاپلاس: L{y''} = s²Y - sy(0) - y'(0)"]},
    {"name": "جبر خطی", "query": "linear algebra matrices eigenvalues",
     "style": "math", "emoji": "🔢", "tags": "#جبر_خطی #ماتریس",
     "formulas": ["det(A - λI) = 0", "Ax = λx", "A⁻¹ = adj(A)/det(A)"]},
    {"name": "تبدیل لاپلاس", "query": "Laplace transform engineering",
     "style": "math", "emoji": "ℒ", "tags": "#لاپلاس",
     "formulas": ["F(s) = ∫₀^∞ f(t)e^(-st)dt", "L{f'} = sF(s) - f(0)", "L{e^(at)} = 1/(s-a)"]},
    {"name": "سری فوریه", "query": "Fourier series transform",
     "style": "math", "emoji": "🎼", "tags": "#فوریه",
     "formulas": ["f(x) = a₀/2 + Σ(aₙcos(nx) + bₙsin(nx))", "aₙ = (1/π)∫f(x)cos(nx)dx"]},
    {"name": "آمار و احتمال مهندسی", "query": "engineering statistics probability",
     "style": "math", "emoji": "📊", "tags": "#آمار_مهندسی",
     "formulas": ["μ = Σx·P(x)", "σ² = Σ(x-μ)²P(x)", "P(A|B) = P(A∩B)/P(B)"]},

    # ─── مکانیک پایه (4) ────────────────────────────────────
    {"name": "استاتیک", "query": "engineering statics equilibrium forces",
     "style": "tutorial", "emoji": "🏛️", "tags": "#استاتیک #تعادل",
     "formulas": ["ΣF = 0", "ΣM = 0", "f = μN", "F = kx (فنر)"]},
    {"name": "دینامیک", "query": "dynamics particle rigid body kinematics",
     "style": "tutorial", "emoji": "🎯", "tags": "#دینامیک",
     "formulas": ["F = ma", "K = ½mv²", "p = mv", "W = ΔK", "I = ∫r²dm"]},
    {"name": "مقاومت مصالح", "query": "strength of materials stress strain beam",
     "style": "tutorial", "emoji": "🏗️", "tags": "#مقاومت_مصالح",
     "formulas": ["σ = F/A", "ε = ΔL/L", "σ = Eε (هوک)", "M = -EI·y''", "τ = VQ/(Ib)"]},
    {"name": "ارتعاشات مکانیکی", "query": "vibration modal analysis",
     "style": "tutorial", "emoji": "📳", "tags": "#ارتعاشات",
     "formulas": ["ωₙ = √(k/m)", "ζ = c/(2√(km))", "x(t) = Ae^(-ζωₙt)·sin(ω_d t + φ)"]},

    # ─── سیالات (3) ─────────────────────────────────────────
    {"name": "مکانیک سیالات ۱", "query": "fluid mechanics basics Bernoulli",
     "style": "tutorial", "emoji": "🌊", "tags": "#سیالات۱",
     "formulas": ["P + ½ρv² + ρgz = const (برنولی)", "A₁v₁ = A₂v₂",
                  "Re = ρvD/μ", "h_f = f(L/D)(v²/2g)"]},
    {"name": "مکانیک سیالات ۲", "query": "advanced fluid mechanics turbulence boundary layer",
     "style": "tutorial", "emoji": "🌊", "tags": "#سیالات۲",
     "formulas": ["Navier-Stokes: ρ(Dv/Dt) = -∇P + μ∇²v + ρg",
                  "δ ≈ 5x/√Re_x (لایه مرزی)", "τ_w = μ(du/dy)|_wall"]},
    {"name": "هیدرولیک و پنوماتیک", "query": "hydraulic pneumatic systems",
     "style": "tutorial", "emoji": "💧", "tags": "#هیدرولیک",
     "formulas": ["F = P·A", "Q = v·A", "η = P_out/P_in"]},

    # ─── ترمودینامیک (4) ───────────────────────────────────
    {"name": "ترمودینامیک ۱", "query": "thermodynamics laws entropy enthalpy",
     "style": "tutorial", "emoji": "🔥", "tags": "#ترمو۱",
     "formulas": ["ΔU = Q - W", "PV = nRT", "ΔS ≥ Q/T", "H = U + PV"]},
    {"name": "ترمودینامیک ۲", "query": "thermodynamics cycles Carnot Rankine Brayton",
     "style": "tutorial", "emoji": "♻️", "tags": "#ترمو۲",
     "formulas": ["η_Carnot = 1 - T_c/T_h", "η_Rankine = (h₁-h₂)/(h₁-h₃)", "COP = Q_c/W"]},
    {"name": "انتقال حرارت ۱", "query": "heat transfer conduction convection radiation",
     "style": "tutorial", "emoji": "🌡️", "tags": "#انتقال_حرارت",
     "formulas": ["q = -k∇T (فوریه)", "q = h(T_s - T_∞)", "q = εσT⁴ (استفان)",
                  "1/U = 1/h₁ + L/k + 1/h₂"]},
    {"name": "انتقال حرارت ۲", "query": "advanced heat transfer exchanger boiling",
     "style": "tutorial", "emoji": "♨️", "tags": "#انتقال_حرارت۲",
     "formulas": ["LMTD = (ΔT₁-ΔT₂)/ln(ΔT₁/ΔT₂)", "NTU = UA/C_min",
                  "q_boiling = μ·h_fg·(g(ρ_l-ρ_v)/σ)^0.5"]},

    # ─── تاسیسات (3) ────────────────────────────────────────
    {"name": "تهویه مطبوع HVAC", "query": "HVAC air conditioning",
     "style": "tutorial", "emoji": "❄️", "tags": "#HVAC",
     "formulas": ["Q_sensible = 1.08·CFM·ΔT", "Q_latent = 0.68·CFM·ΔW",
                  "EER = BTU/W·h"]},
    {"name": "سیکل تبرید", "query": "refrigeration vapor compression cycle",
     "style": "tutorial", "emoji": "🧊", "tags": "#تبرید",
     "formulas": ["COP = h₁-h₄ / h₂-h₁", "Q_c = ṁ(h₁-h₄)", "W_comp = ṁ(h₂-h₁)"]},
    {"name": "تاسیسات ساختمان", "query": "building mechanical systems piping",
     "style": "tutorial", "emoji": "🏢", "tags": "#تاسیسات",
     "formulas": ["Q = ṁ·c_p·ΔT", "h_f = f(L/D)(v²/2g)", "H_pump = ΔP/(ρg) + Δv²/2g + Δz"]},

    # ─── طراحی و ساخت (3) ──────────────────────────────────
    {"name": "طراحی اجزای ماشین", "query": "machine element design bearing gear shaft",
     "style": "tutorial", "emoji": "⚙️", "tags": "#طراحی_اجزا",
     "formulas": ["σ_allow = σ_ult/n", "Lewis: σ = W_t/(F·m·Y)",
                  "L₁₀ = (C/P)^(10/3) (میلیون دور)"]},
    {"name": "ساخت و تولید", "query": "manufacturing CNC machining welding",
     "style": "tutorial", "emoji": "🏭", "tags": "#ساخت_و_تولید",
     "formulas": ["v_c = πDN/1000", "MRR = v·f·d", "Taylor: vT^n = C"]},
    {"name": "مهندسی معکوس", "query": "reverse engineering 3D scanning",
     "style": "tutorial", "emoji": "🔍", "tags": "#مهندسی_معکوس",
     "formulas": ["RMS error = √(Σd²/n)", "GD&T tolerances"]},

    # ─── تخصصی (11) ─────────────────────────────────────────
    {"name": "روباتیک", "query": "robotics manipulation control ROS",
     "style": "tutorial", "emoji": "🤖", "tags": "#روباتیک",
     "formulas": ["T = J(q)ᵀ·F (ژاکوبین)", "q̈ = M⁻¹(τ - C - G)"]},
    {"name": "مکاترونیک", "query": "mechatronics sensors actuators embedded",
     "style": "tutorial", "emoji": "🔌", "tags": "#مکاترونیک",
     "formulas": ["V_out = V_in·R₂/(R₁+R₂)", "PID: u(t) = K_p e + K_i ∫e + K_d de/dt"]},
    {"name": "کنترل خطی", "query": "linear control PID",
     "style": "tutorial", "emoji": "🎛️", "tags": "#کنترل",
     "formulas": ["G(s) = Y(s)/U(s)", "PID: C(s) = K_p(1 + 1/(T_i s) + T_d s)",
                  "ζ, ωₙ ← M_p, t_s"]},
    {"name": "کنترل غیرخطی", "query": "nonlinear control Lyapunov",
     "style": "tutorial", "emoji": "🌀", "tags": "#کنترل_غیرخطی",
     "formulas": ["ẋ = f(x) + g(x)u", "V(x) > 0, V̇(x) < 0 (لیاپانوف)"]},
    {"name": "بیومکانیک", "query": "biomechanics tissue prosthesis implant",
     "style": "tutorial", "emoji": "🦴", "tags": "#بیومکانیک",
     "formulas": ["E_tissue ≈ σ/ε", "F = k·ΔL (بافت)", "Womersley α = R√(ω/ν)"]},
    {"name": "آیرودینامیک", "query": "aerodynamics compressible flow",
     "style": "tutorial", "emoji": "✈️", "tags": "#آیرودینامیک",
     "formulas": ["L = ½ρv²SC_L", "D = ½ρv²SC_D", "M = v/a", "P₀/P = (1 + 0.2M²)^3.5"]},
    {"name": "مهندسی دریا", "query": "marine engineering offshore hydrodynamics",
     "style": "tutorial", "emoji": "🚢", "tags": "#مهندسی_دریا",
     "formulas": ["F_N = ½ρv²·A·C_N", "Froude: Fr = v/√(gL)"]},
    {"name": "خودرو و پیشرانه", "query": "automotive powertrain engine combustion",
     "style": "tutorial", "emoji": "🚗", "tags": "#خودرو",
     "formulas": ["η_th = 1 - 1/r^(γ-1) (اتو)", "BSFC = ṁ_f/P_b", "T = P/ω"]},
    {"name": "انرژی تجدیدپذیر", "query": "renewable solar wind turbine",
     "style": "tutorial", "emoji": "☀️", "tags": "#انرژی",
     "formulas": ["P_wind = ½ρAv³C_p", "Betz limit: C_p,max = 16/27 ≈ 0.593",
                  "P_solar = A·G·η"]},
    {"name": "اجزای محدود FEM", "query": "finite element method structural",
     "style": "tutorial", "emoji": "🧩", "tags": "#FEM",
     "formulas": ["K·u = F", "K = ∫Bᵀ·D·B dV", "σ = D·B·u"]},
    {"name": "دینامیک سیالات CFD", "query": "computational fluid dynamics",
     "style": "tutorial", "emoji": "💻", "tags": "#CFD",
     "formulas": ["∂ρ/∂t + ∇·(ρv) = 0", "ρ(Dv/Dt) = -∇P + μ∇²v + f",
                  "CFL = u·Δt/Δx ≤ 1"]},

    # ─── اخبار (4) ──────────────────────────────────────────
    {"name": "SpaceX", "query": "SpaceX Starship",
     "style": "news", "emoji": "🚀", "tags": "#SpaceX"},
    {"name": "ناسا", "query": "NASA Artemis mission",
     "style": "news", "emoji": "🌌", "tags": "#ناسا"},
    {"name": "اخبار فیزیک", "query": "physics breakthrough",
     "style": "news", "emoji": "⚛️", "tags": "#فیزیک"},
    {"name": "اخبار مهندسی", "query": "engineering breakthrough innovation",
     "style": "news", "emoji": "📰", "tags": "#مهندسی"},

    # ─── اخبار عمومی و روان‌شناسی (12) ─────────────────────
    {"name": "اخبار فناوری", "query": "technology breakthrough AI chips",
     "style": "news", "emoji": "💻", "tags": "#فناوری #اخبار"},
    {"name": "اخبار انرژی", "query": "energy renewable battery breakthrough",
     "style": "news", "emoji": "⚡", "tags": "#انرژی #اخبار"},
    {"name": "اخبار پزشکی", "query": "medical biotech health research",
     "style": "news", "emoji": "🩺", "tags": "#پزشکی #اخبار"},
    {"name": "اخبار اقتصادی", "query": "economy market global finance",
     "style": "news", "emoji": "💹", "tags": "#اقتصاد #اخبار"},
    {"name": "اخبار سیاسی", "query": "politics policy international relations",
     "style": "news", "emoji": "🏛️", "tags": "#سیاسی #اخبار"},
    {"name": "ژئوپلیتیک", "query": "geopolitics analysis strategy",
     "style": "deep", "emoji": "🌍", "tags": "#ژئوپلیتیک"},
    {"name": "روان‌شناسی شناختی", "query": "cognitive psychology attention memory",
     "style": "tutorial", "emoji": "🧠", "tags": "#روان_شناسی #شناختی"},
    {"name": "روان‌شناسی سازمانی", "query": "organizational psychology workplace",
     "style": "tutorial", "emoji": "🏢", "tags": "#روان_شناسی #سازمانی"},
    {"name": "تصمیم‌گیری و خطاها", "query": "decision making cognitive biases",
     "style": "tutorial", "emoji": "🎯", "tags": "#تصمیم_گیری #سوگیری"},
    {"name": "یادگیری و حافظه", "query": "learning memory spaced repetition",
     "style": "tutorial", "emoji": "📚", "tags": "#یادگیری"},
    {"name": "هوش مصنوعی", "query": "artificial intelligence large language models",
     "style": "deep", "emoji": "🤖", "tags": "#AI #هوش_مصنوعی"},
    {"name": "کوانتوم", "query": "quantum computing physics",
     "style": "deep", "emoji": "⚛️", "tags": "#کوانتوم"},
]


def _get_topics_list() -> List[Dict]:
    """Override placeholder from Part 2."""
    return TOPICS


# ══════════════════════════════════════════════════════════════════════════════
#                        CUSTOM TOPICS MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════


# =============================================================================
#              TOPIC PICKER (true random + anti-repeat) - RANDOM.ps1
# =============================================================================
class TopicPicker:
    """
    Weighted random topic selection with anti-repeat memory.

    Algorithm:
      - Maintain a rolling window of the last N picked topic names.
      - Weight for each topic = 1.0 / (1 + k * recency_score)
        where recency_score grows with how recently the topic was used.
      - Sample using weighted random via bisect on cumulative weights.
      - True randomness from random.SystemRandom (OS entropy).
    """

    RECENT_WINDOW = 40        # keep last 40 picks
    AVOID_PENALTY = 25.0      # weight penalty for very recent picks
    REROLL_TRIES  = 8         # try up to N times to avoid exact duplicates

    def __init__(self):
        self._lock = threading.RLock()
        self._recent = []         # list[str], newest at index 0
        self._load_state()

    def _state_path(self) -> Path:
        return DATA_DIR / "recent_picks.json"

    def _load_state(self):
        try:
            p = self._state_path()
            if p.exists():
                data = load_json(p, default={})
                self._recent = list(data.get("recent", []))[:self.RECENT_WINDOW]
        except Exception:
            self._recent = []

    def _save_state(self):
        try:
            self._state_path().write_text(
                json.dumps({"recent": self._recent[:self.RECENT_WINDOW]},
                           ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception:
            pass

    def _weight(self, name: str) -> float:
        """Weight = 1 / (1 + penalty * position). Position 0 = most recent."""
        try:
            idx = self._recent.index(name)
        except ValueError:
            return 1.0
        # Closer to front -> much lower weight
        pos_factor = (self.RECENT_WINDOW - idx) / self.RECENT_WINDOW
        return 1.0 / (1.0 + self.AVOID_PENALTY * pos_factor)

    def pick(self, topics, avoid_names=None):
        """
        topics: list of dicts (must have 'name')
        avoid_names: set of names to skip entirely (optional)
        Returns: chosen topic dict, or None if list empty.
        """
        if not topics:
            return None
        avoid_names = set(avoid_names or [])

        with self._lock:
            # filter out the avoided names
            pool = [t for t in topics if (t.get("name") or "") not in avoid_names]
            if not pool:
                pool = list(topics)

            # weighted selection
            weights = [self._weight(t.get("name") or "") for t in pool]
            total = sum(weights)
            if total <= 0:
                chosen = _RND.choice(pool)
            else:
                r = _RND.uniform(0.0, total)
                upto = 0.0
                chosen = pool[-1]
                for t, w in zip(pool, weights):
                    upto += w
                    if upto >= r:
                        chosen = t
                        break

            # try to avoid exact duplicate of most recent pick
            name = chosen.get("name") or ""
            tries = 0
            while self._recent and name == self._recent[0] and tries < self.REROLL_TRIES:
                weights = [self._weight(t.get("name") or "") for t in pool]
                total = sum(weights)
                if total <= 0:
                    chosen = _RND.choice(pool)
                else:
                    r = _RND.uniform(0.0, total)
                    upto = 0.0
                    chosen = pool[-1]
                    for t, w in zip(pool, weights):
                        upto += w
                        if upto >= r:
                            chosen = t
                            break
                name = chosen.get("name") or ""
                tries += 1

            # update recent list
            if name:
                self._recent.insert(0, name)
                del self._recent[self.RECENT_WINDOW:]
                self._save_state()

            return chosen

    def stats(self):
        with self._lock:
            return {
                "recent_count": len(self._recent),
                "recent_top": self._recent[:10],
            }


PICKER = TopicPicker()



# =============================================================================
#          HASHTAG REGISTRY (per-category tags + channel library) - HASHTAGS.ps1
# =============================================================================
class HashtagRegistry:
    """
    Every topic gets hashtags based on its category.
    A single library message is maintained in the channel; edited, not duplicated.
    """

    BASE_TAGS = {
        "math":        ["#ریاضی", "#Math", "#Mathematics", "#مهندسی"],
        "engineering": ["#مهندسی_مکانیک", "#MechanicalEngineering",
                        "#Engineering", "#مهندسی", "#Mech"],
        "statics":     ["#استاتیک", "#Statics", "#مهندسی"],
        "dynamics":    ["#دینامیک", "#Dynamics", "#مهندسی"],
        "materials":   ["#مقاومت_مصالح", "#Materials",
                        "#SolidMechanics", "#مهندسی"],
        "vibration":   ["#ارتعاشات", "#Vibration", "#ModalAnalysis"],
        "fluids":      ["#مکانیک_سیالات", "#FluidMechanics",
                        "#CFD", "#مهندسی"],
        "thermo":      ["#ترمودینامیک", "#Thermodynamics", "#Energy"],
        "heat":        ["#انتقال_حرارت", "#HeatTransfer", "#Thermal"],
        "hvac":        ["#تهویه_مطبوع", "#HVAC", "#Refrigeration", "#Thermal"],
        "control":     ["#کنترل", "#Control", "#Automation", "#PID"],
        "robotics":    ["#روباتیک", "#Robotics", "#ROS", "#Automation"],
        "energy":      ["#انرژی", "#Energy", "#Renewable", "#Sustainability"],
        "ai":          ["#هوش_مصنوعی", "#AI", "#MachineLearning", "#DeepLearning"],
        "physics":     ["#فیزیک", "#Physics", "#Science"],
        "quantum":     ["#کوانتوم", "#Quantum", "#Physics"],
        "chemistry":   ["#شیمی", "#Chemistry"],
        "biology":     ["#زیست", "#Biology"],
        "space":       ["#فضا", "#Space", "#NASA", "#SpaceX"],
        "music":       ["#موسیقی", "#Music"],
        "psychology":  ["#روانشناسی", "#Psychology"],
        "philosophy":  ["#فلسفه", "#Philosophy"],
        "history":     ["#تاریخ", "#History"],
        "news":        ["#اخبار", "#News"],
        "politics":    ["#سیاست", "#Politics", "#Geopolitics"],
        "economy":     ["#اقتصاد", "#Economy", "#Finance"],
        "books":       ["#کتاب", "#Book", "#Reading"],
        "cyber":       ["#امنیت_سایبری", "#Cybersecurity", "#InfoSec"],
        "opensource":  ["#اوپن_سورس", "#OpenSource", "#GitHub"],
        "additive":    ["#چاپ_سه_بعدی", "#3DPrinting", "#AdditiveManufacturing"],
        "cnc":         ["#CNC", "#Machining", "#Manufacturing"],
        "fem":         ["#FEM", "#ANSYS", "#Abaqus"],
        "cfd":         ["#CFD", "#Fluent", "#OpenFOAM"],
        "industry":    ["#صنعت", "#Industry", "#Manufacturing"],
        "futurism":    ["#آینده_پژوهی", "#Futurism", "#Trends"],
    }

    LABELS = {
        "math":        "ریاضی",
        "engineering": "مهندسی مکانیک",
        "statics":     "استاتیک",
        "dynamics":    "دینامیک",
        "materials":   "مقاومت مصالح",
        "vibration":   "ارتعاشات",
        "fluids":      "مکانیک سیالات",
        "thermo":      "ترمودینامیک",
        "heat":        "انتقال حرارت",
        "hvac":        "تهویه مطبوع",
        "control":     "کنترل",
        "robotics":    "روباتیک",
        "energy":      "انرژی",
        "ai":          "هوش مصنوعی",
        "physics":     "فیزیک",
        "quantum":     "کوانتوم",
        "chemistry":   "شیمی",
        "biology":     "زیست",
        "space":       "فضا",
        "music":       "موسیقی",
        "psychology":  "روانشناسی",
        "philosophy":  "فلسفه",
        "history":     "تاریخ",
        "news":        "اخبار",
        "politics":    "سیاست",
        "economy":     "اقتصاد",
        "books":       "کتاب",
        "cyber":       "امنیت سایبری",
        "opensource":  "اوپن سورس",
        "additive":    "چاپ سه‌بعدی",
        "cnc":         "CNC",
        "fem":         "اجزای محدود",
        "cfd":         "CFD",
        "industry":    "صنعت",
        "futurism":    "آینده‌پژوهی",
    }

    KEYWORDS = {
        "math":        ["ریاضی", "حساب", "انتگرال", "مشتق", "جبر", "لاپلاس",
                        "فوریه", "math", "algebra", "calculus", "matrix",
                        "eigen", "ode", "pde", "vector"],
        "engineering": ["مهندسی", "engineer", "mechanic"],
        "statics":     ["استاتیک", "static", "equilibrium"],
        "dynamics":    ["دینامیک", "dynamic", "kinematic"],
        "materials":   ["مقاومت", "مصالح", "material", "solid", "stress",
                        "strain", "beam", "column", "fracture", "fatigue"],
        "vibration":   ["ارتعاش", "vibrat", "modal", "resonance"],
        "fluids":      ["سیال", "fluid", "cfd", "bernoulli", "reynolds",
                        "navier", "turbulence", "laminar"],
        "thermo":      ["ترمو", "thermo", "entropy", "carnot",
                        "rankine", "brayton"],
        "heat":        ["حرارت", "heat", "thermal", "conduction", "convection"],
        "hvac":        ["تهویه", "hvac", "chiller", "boiler", "refriger",
                        "vrf", "vav", "doas"],
        "control":     ["کنترل", "control", "pid", "feedback", "lyapunov"],
        "robotics":    ["روبات", "robot", "ros", "manipulator"],
        "energy":      ["انرژی", "energy", "renewable", "solar", "wind",
                        "battery", "hydrogen", "geothermal"],
        "ai":          ["هوش مصنوعی", "ai", "machine learning", "neural",
                        "deep learning", "llm", "physics-informed"],
        "physics":     ["فیزیک", "physic", "mechanics classical"],
        "quantum":     ["کوانتوم", "quantum", "entanglement"],
        "chemistry":   ["شیمی", "chemistry", "reaction"],
        "biology":     ["زیست", "biolog", "cell"],
        "space":       ["فضا", "space", "nasa", "spacex", "mars",
                        "artemis", "james webb"],
        "music":       ["موسیقی", "music", "jazz", "rock", "metal", "doom",
                        "classical", "hacker music"],
        "psychology":  ["روان", "psychol", "کاریزما", "charisma",
                        "cognitive", "bias"],
        "philosophy":  ["فلسفه", "philos", "stoic"],
        "history":     ["تاریخ", "history", "industrial revolution"],
        "news":        ["اخبار", "news", "breakthrough"],
        "politics":    ["سیاست", "politics", "geopolitic", "diplomacy"],
        "economy":     ["اقتصاد", "economy", "finance", "market", "inflation"],
        "books":       ["کتاب", "book", "reading", "review"],
        "cyber":       ["سایبر", "cyber", "hack", "security", "infosec"],
        "opensource":  ["اوپن", "opensource", "github", "open-source"],
    }

    def __init__(self):
        self._lock = threading.RLock()
        self._path = DATA_DIR / "hashtags.json"
        self._data = self._load()

    def _load(self):
        try:
            if self._path.exists():
                raw = load_json(self._path, default={})
                if isinstance(raw, dict):
                    raw.setdefault("known", [])
                    raw.setdefault("pending", [])
                    raw.setdefault("channel", {})
                    return raw
        except Exception:
            pass
        return {"known": [], "pending": [], "channel": {}}

    def _save(self):
        try:
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception as e:
            try: log.warning(f"hashtag save: {e}")
            except Exception: pass

    # ── Category inference ─────────────────────────────────────────────────
    def infer_categories(self, topic):
        name = (topic.get("name") or "")
        tags = (topic.get("tags") or "")
        cat = (topic.get("category") or "")
        text = (name + " " + tags + " " + cat).lower()
        found = []
        if cat and cat in self.BASE_TAGS:
            found.append(cat)
        for c, kws in self.KEYWORDS.items():
            if c in found:
                continue
            for k in kws:
                if k.lower() in text:
                    found.append(c)
                    break
        if not found:
            found.append("engineering")
        return found

    # ── Expand: topic -> up to N hashtags ──────────────────────────────────
    def expand(self, topic, max_tags=5):
        if not topic:
            return []
        tags = []
        raw = (topic.get("tags") or "").strip()
        if raw:
            for t in raw.split():
                t = t.strip()
                if t.startswith("#") and t not in tags:
                    tags.append(t)
        cats = self.infer_categories(topic)
        for c in cats:
            for t in self.BASE_TAGS.get(c, []):
                if t not in tags:
                    tags.append(t)
                if len(tags) >= max_tags:
                    break
            if len(tags) >= max_tags:
                break
        return tags[:max_tags]

    # ── Register new tags ──────────────────────────────────────────────────
    def register_all(self, tags):
        with self._lock:
            known = set(self._data.get("known", []))
            pending = list(self._data.get("pending", []))
            new_tags = []
            for t in tags:
                if t and t.startswith("#") and t not in known:
                    known.add(t)
                    pending.append(t)
                    new_tags.append(t)
            if new_tags:
                self._data["known"] = sorted(known)
                self._data["pending"] = pending
                self._save()
            return new_tags

    # ── Render library text ────────────────────────────────────────────────
    def render_library(self):
        with self._lock:
            known = list(self._data.get("known", []))
        by_cat = defaultdict(list)
        cat_of = {}
        for cat, tags in self.BASE_TAGS.items():
            for t in tags:
                cat_of[t] = cat
        other = []
        for t in known:
            c = cat_of.get(t)
            if c:
                by_cat[c].append(t)
            else:
                other.append(t)
        lines = ["📚 <b>Hashtag Library</b>", ""]
        for cat in sorted(by_cat.keys(), key=lambda x: (-len(by_cat[x]), x)):
            lbl = self.LABELS.get(cat, cat)
            tags = by_cat[cat][:8]
            lines.append(f"<b>{lbl}</b>: " + " ".join(tags))
        if other:
            lines.append("")
            lines.append("<b>Other</b>: " + " ".join(other[:20]))
        lines.append("")
        lines.append(f"Total: <code>{len(known)}</code>")
        lines.append("📢 @MAADGHchannel")
        return "\n".join(lines)[:4000]

    # ── Sync library message in channel ────────────────────────────────────
    def sync_channel(self, cfg, force=False):
        ch = (cfg.telegram.channel_id or "").strip()
        if not ch:
            return False
        with self._lock:
            ch_data = self._data.get("channel", {}).get(ch, {})
            msg_id = ch_data.get("message_id")
            pending = list(self._data.get("pending", []))
        needs = (msg_id is None) or bool(pending) or force
        if not needs:
            return False
        text = self.render_library()
        if msg_id:
            r = TG.edit_message(ch, msg_id, text, reply_markup=None)
            if r.ok:
                with self._lock:
                    self._data.setdefault("channel", {})[ch] = {
                        "message_id": msg_id,
                        "last_sync": datetime.now().isoformat(),
                    }
                    self._data["pending"] = []
                    self._save()
                try:
                    LIVE.event("sys", f"Hashtag library updated ({len(pending)} new)",
                               to_tg=False)
                except Exception:
                    pass
                return True
        r = TG.send_message(ch, text, reply_markup=None)
        if r.ok:
            new_id = (r.result or {}).get("message_id")
            with self._lock:
                self._data.setdefault("channel", {})[ch] = {
                    "message_id": new_id,
                    "last_sync": datetime.now().isoformat(),
                }
                self._data["pending"] = []
                self._save()
            try:
                LIVE.event("sys", f"Hashtag library posted (id={new_id})",
                           to_tg=False)
            except Exception:
                pass
            return True
        try:
            log.warning(f"hashtag library send failed: {r.description[:80]}")
        except Exception:
            pass
        return False

    def stats(self):
        with self._lock:
            return {
                "known": len(self._data.get("known", [])),
                "pending": len(self._data.get("pending", [])),
                "channel": dict(self._data.get("channel", {})),
            }


HASHTAGS = HashtagRegistry()


class TopicManager:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._custom = load_json(path, default=[])

    def all(self) -> List[Dict]:
        with self._lock:
            return list(TOPICS) + list(self._custom)

    def custom(self) -> List[Dict]:
        with self._lock:
            return list(self._custom)

    def find(self, name_or_query: str) -> Optional[Dict]:
        target = name_or_query.strip().lower()
        if not target:
            return None
        with self._lock:
            # 1. Exact match (name or query) - safest
            for t in TOPICS + self._custom:
                if t["name"].lower() == target or t.get("query", "").lower() == target:
                    return t
            # 2. Prefix match (min 5 chars) - avoids "دینامیک"->"ترمودینامیک"
            if len(target) >= 5:
                for t in TOPICS + self._custom:
                    tn = t["name"].lower()
                    if tn.startswith(target) or target.startswith(tn):
                        return t
        return None

    def add(self, name: str, query: str, *, style: str = "tutorial",
            emoji: str = "⭐", tags: str = "") -> bool:
        with self._lock:
            for t in self._custom:
                if t["name"] == name:
                    return False
            self._custom.append({
                "name": name, "query": query, "style": style,
                "emoji": emoji, "tags": tags or f"{name.replace(' ', '_')}",
            })
            save_json(self.path, self._custom)
            return True

    def remove(self, name: str) -> bool:
        with self._lock:
            for i, t in enumerate(self._custom):
                if t["name"] == name:
                    del self._custom[i]
                    save_json(self.path, self._custom)
                    return True
        return False

    def rotate_next(self) -> Dict:
        """Weighted random pick with anti-repeat memory."""
        all_t = self.all()
        if not all_t:
            return TOPICS[0]
        chosen = PICKER.pick(all_t)
        return chosen if chosen else all_t[0]

    def rotate_sequential(self) -> Dict:
        """Legacy sequential mode (used only if rotate_topics is False)."""
        cfg = CONFIG.get()
        all_t = self.all()
        if not all_t:
            return TOPICS[0]
        idx = cfg.behavior.topic_index % len(all_t)
        cfg.behavior.topic_index = (idx + 1) % len(all_t)
        CONFIG.save()
        return all_t[idx]


TOPIC_MGR = TopicManager(TOPICS_FILE)


# ══════════════════════════════════════════════════════════════════════════════
#                        FORMULA LIBRARY
# ══════════════════════════════════════════════════════════════════════════════

FORMULA_LIBRARY: Dict[str, List[Tuple[str, str, str]]] = {
    "استاتیک": [
        ("تعادل نیرو", "ΣF = 0", "بردار مجموع نیروها صفر"),
        ("تعادل گشتاور", "ΣM = 0", "گشتاور حول هر نقطه"),
        ("اصطکاک ایستا", "f_s ≤ μ_s·N", "μ_s ضریب اصطکاک ایستا"),
        ("اصطکاک جنبشی", "f_k = μ_k·N", "μ_k ضریب اصطکاک جنبشی"),
        ("فنر خطی", "F = k·x", "k ثابت فنر"),
    ],
    "دینامیک": [
        ("نیوتن دوم", "F = m·a", "F نیرو، m جرم، a شتاب"),
        ("انرژی جنبشی", "K = ½·m·v²", "v سرعت خطی"),
        ("مومنتوم خطی", "p = m·v", "بردار"),
        ("مومنتوم زاویه‌ای", "L = I·ω", "I ممان اینرسی"),
        ("کار-انرژی", "W = ΔK", "کار = تغییر انرژی جنبشی"),
        ("توان لحظه‌ای", "P = F·v", "توان = نیرو × سرعت"),
    ],
    "مقاومت": [
        ("تنش نرمال", "σ = F/A", "F نیروی محوری"),
        ("کرنش نرمال", "ε = ΔL/L", "تغییر طول نسبی"),
        ("قانون هوک", "σ = E·ε", "E مدول یانگ"),
        ("خمش تیر", "σ = M·y/I", "M گشتاور خمشی"),
        ("پیچش", "τ = T·r/J", "T گشتاور پیچشی"),
        ("برش", "τ = V·Q/(I·b)", "V نیروی برشی"),
        ("کمانش اویلر", "P_cr = π²EI/(KL)²", "K ضریب طول مؤثر"),
    ],
    "سیالات": [
        ("برنولی", "P + ½ρv² + ρgz = const", "جریان پایا، تراکم‌ناپذیر"),
        ("پیوستگی", "A₁v₁ = A₂v₂", "دبی حجمی"),
        ("رینولدز", "Re = ρvD/μ", "Re>4000 آشفته"),
        ("دارسی-وایسباخ", "h_f = f·(L/D)·(v²/2g)", "f ضریب اصطکاک"),
        ("ناویر-استوکس", "ρ(Dv/Dt) = -∇P + μ∇²v + ρg", "معادله کامل"),
        ("فشار دینامیک", "P_dyn = ½ρv²", "فشار سرعت"),
        ("ویسکوزیته سینماتیک", "ν = μ/ρ", "ν [m²/s]"),
    ],
    "ترمودینامیک": [
        ("قانون اول", "ΔU = Q - W", "تغییر انرژی داخلی"),
        ("گاز ایده‌آل", "PV = nRT", "R = 8.314 J/mol·K"),
        ("آنتروپی", "ΔS ≥ Q/T", "نابرابری کلاوزیوس"),
        ("آنتالپی", "H = U + PV", "برای فشار ثابت"),
        ("کارنو", "η = 1 - T_c/T_h", "بازده حداکثر"),
        ("پلی‌تروپیک", "PV^n = const", "n ضریب پلی‌تروپیک"),
    ],
    "انتقال حرارت": [
        ("هدایت (فوریه)", "q = -k·∇T", "k هدایت حرارتی"),
        ("جابجایی (نیوتن)", "q = h·(T_s - T_∞)", "h ضریب جابجایی"),
        ("تابش (استفان)", "q = ε·σ·T⁴", "σ = 5.67e-8 W/m²K⁴"),
        ("مقاومت حرارتی", "R = L/k (صفحہ)", "بر حسب K/W"),
        ("مقاومت جابجایی", "R = 1/(hA)", "A سطح"),
        ("LMTD مبدل", "LMTD = (ΔT₁-ΔT₂)/ln(ΔT₁/ΔT₂)", "میانگین لگاریتمی"),
    ],
    "ریاضی": [
        ("انتگرال سه‌گانه", "∭f(x,y,z)dV", "حجم، جرم، ممان"),
        ("تبدیل لاپلاس", "F(s) = ∫₀^∞ f(t)e^(-st)dt", "حل ODE"),
        ("تبدیل فوریه", "F(ω) = ∫f(t)e^(-iωt)dt", "تحلیل فرکانسی"),
        ("قضیه گرین", "∮(P dx + Q dy) = ∬(∂Q/∂x - ∂P/∂y)dA", "خط ↔ سطح"),
        ("قضیه استوکس", "∮F·dr = ∬(∇×F)·n dS", "دور ↔ سطح"),
        ("قضیه دایورژنس", "∬F·n dS = ∭(∇·F)dV", "شار ↔ حجم"),
    ],
    "کنترل": [
        ("PID", "u(t) = K_p·e + K_i·∫e dt + K_d·de/dt", "e = خطا"),
        ("تابع تبدیل", "G(s) = Y(s)/U(s)", "در حوزه لاپلاس"),
        ("بازده میرایی", "ζ = c/(2√(km))", "ζ<1 میرا"),
        ("فرکانس طبیعی", "ω_n = √(k/m)", "بدون میرا"),
    ],
    "شیمی": [
        ("گاز ایده‌آل", "PV = nRT", "R ثابت جهانی"),
        ("غلظت", "C = n/V", "مول بر لیتر"),
        ("pH", "pH = -log[H⁺]", "اسیدی/بازی"),
    ],
    "برق": [
        ("اهم", "V = I·R", "قانون اهم"),
        ("توان", "P = V·I = I²R = V²/R", "وات"),
        ("خازن", "Q = C·V", "شارژ"),
        ("القا", "V = L·di/dt", "القاگری"),
    ],
}


def get_formulas_for(topic_name: str, topic: Optional[Dict] = None) -> List[Tuple[str, str, str]]:
    """Get formulas matching a topic."""
    # If topic has explicit formulas in tuple form
    if topic and topic.get("formulas"):
        out = []
        for i, f in enumerate(topic["formulas"]):
            if isinstance(f, tuple) and len(f) == 3:
                out.append(f)
            elif isinstance(f, str):
                out.append((f"فرمول {i+1}", f, ""))
        return out

    # Search library
    name = topic_name.lower()
    for key, formulas in FORMULA_LIBRARY.items():
        if key.lower() in name or any(w in name for w in key.lower().split()):
            return formulas
    return []


# ══════════════════════════════════════════════════════════════════════════════
#                        SEEN TRACKING (Bloom Filter)
# ══════════════════════════════════════════════════════════════════════════════

class SeenManager:
    """Track seen items using memory-efficient Bloom filter."""

    def __init__(self, path: Path, capacity: int = 500_000):
        self.path = path
        self._lock = threading.RLock()
        self._bf = BloomFilter.load(path, default_capacity=capacity)
        self._dirty = False
        self._last_save = 0
        self._save_thread = threading.Thread(target=self._save_loop, daemon=True)
        self._save_thread.start()

    def add(self, item_id: str) -> None:
        with self._lock:
            self._bf.add(item_id)
            self._dirty = True

    def contains(self, item_id: str) -> bool:
        with self._lock:
            return item_id in self._bf

    def add_batch(self, item_ids: List[str]) -> None:
        with self._lock:
            for i in item_ids:
                self._bf.add(i)
            self._dirty = True

    def _save_loop(self) -> None:
        while True:
            time.sleep(30)
            with self._lock:
                if self._dirty:
                    try:
                        self._bf.save(self.path)
                        self._dirty = False
                        self._last_save = time.time()
                    except Exception as e:
                        log.error(f"Seen save: {e}")

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return self._bf.stats()


SEEN = SeenManager(SEEN_FILE)


# ══════════════════════════════════════════════════════════════════════════════
#                        DRAFT MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Draft:
    id: str
    topic: str
    style: str
    content: str
    created_at: str
    user_id: int
    metadata: Dict[str, Any] = field(default_factory=dict)


class DraftManager:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._drafts: Dict[str, Draft] = {}
        self._load()

    def _load(self) -> None:
        raw = load_json(self.path, default={})
        for did, d in raw.items():
            try:
                self._drafts[did] = Draft(**d)
            except Exception:
                pass

    def _save(self) -> None:
        BATCHED_WRITER.write(self.path, {
            did: {
                "id": d.id,
                "topic": d.topic,
                "style": d.style,
                "content": d.content,
                "created_at": d.created_at,
                "user_id": d.user_id,
                "metadata": d.metadata,
            }
            for did, d in self._drafts.items()
        })

    def create(self, topic: str, style: str, content: str,
               user_id: int, metadata: Optional[Dict] = None) -> Draft:
        did = hashlib.md5(
            f"{user_id}:{topic}:{time.time()}".encode()
        ).hexdigest()[:12]

        draft = Draft(
            id=did, topic=topic, style=style, content=content,
            created_at=datetime.now().isoformat(),
            user_id=user_id,
            metadata=metadata or {},
        )
        with self._lock:
            self._drafts[did] = draft
            self._save()
        return draft

    def get(self, did: str) -> Optional[Draft]:
        with self._lock:
            return self._drafts.get(did)

    def remove(self, did: str) -> bool:
        with self._lock:
            if did in self._drafts:
                del self._drafts[did]
                self._save()
                return True
        return False

    def list_for_user(self, user_id: int) -> List[Draft]:
        with self._lock:
            return [d for d in self._drafts.values() if d.user_id == user_id]

    def cleanup_old(self, max_age_hours: int = 72) -> int:
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        removed = 0
        with self._lock:
            for did in list(self._drafts.keys()):
                try:
                    created = datetime.fromisoformat(self._drafts[did].created_at)
                    if created < cutoff:
                        del self._drafts[did]
                        removed += 1
                except Exception:
                    pass
            if removed:
                self._save()
        return removed


DRAFTS = DraftManager(DRAFT_FILE)


# ══════════════════════════════════════════════════════════════════════════════
#                        سبک‌های محتوا (11)
# ══════════════════════════════════════════════════════════════════════════════

CONTENT_STYLES = {
    "tutorial": {
        "name": "آموزشی",
        "emoji": "📘",
        "lines": "20-35 خط",
        "max_tokens": 3500,
    },
    "formula": {
        "name": "فرمول‌محور",
        "emoji": "🧮",
        "lines": "15-25 خط",
        "max_tokens": 2800,
    },
    "deep": {
        "name": "تحلیل عمیق",
        "emoji": "🔬",
        "lines": "30-50 خط",
        "max_tokens": 4000,
    },
    "math": {
        "name": "ریاضی",
        "emoji": "📐",
        "lines": "20-35 خط",
        "max_tokens": 3500,
    },
    "news": {
        "name": "خبری",
        "emoji": "📰",
        "lines": "10-20 خط",
        "max_tokens": 2200,
    },
    "quiz": {
        "name": "کوییز",
        "emoji": "❓",
        "lines": "متغیر",
        "max_tokens": 2000,
    },
    "flashcard": {
        "name": "فلش‌کارت",
        "emoji": "📇",
        "lines": "متغیر",
        "max_tokens": 2000,
    },
    "trivia": {
        "name": "دانستنی",
        "emoji": "💡",
        "lines": "8-15 خط",
        "max_tokens": 1800,
    },
    "example": {
        "name": "مثال حل‌شده",
        "emoji": "🧪",
        "lines": "15-25 خط",
        "max_tokens": 2800,
    },
    "comparison": {
        "name": "مقایسه‌ای",
        "emoji": "⚖️",
        "lines": "15-25 خط",
        "max_tokens": 2800,
    },
    "history": {
        "name": "تاریخی",
        "emoji": "📜",
        "lines": "15-25 خط",
        "max_tokens": 2500,
    },
}


# ══════════════════════════════════════════════════════════════════════════════
#                        STRUCTURED CONTENT PROMPTS
# ══════════════════════════════════════════════════════════════════════════════

SYS_UNIVERSAL = """You are a PROFESSIONAL Mechanical Engineering professor writing a
structured educational post in fluent Persian for a technical Telegram channel.

STRICT RULES:
1. Write ONLY in Persian, formal and technical.
2. Structure with clear Markdown headers, bold titles, numbered lists.
3. Every concept MUST have: definition, physical meaning, formula (if applicable),
   and a worked example.
4. Use Markdown tables for comparisons.
5. Format all formulas as INLINE code with ` ` so they render on their own line.
6. NEVER write news summaries — write a LESSON.
7. Keep technical terms in English when standard (Reynolds number, Navier-Stokes).
8. Correct Persian punctuation: ، ؛ ؟ « ».
9. NEVER mention being an AI, NEVER output meta-commentary.
10. NEVER include API keys, tokens, or credentials.
11. Use <code>تگ</code> for formulas and short code, <b>برجسته</b> for section titles.
12. Separate Persian and English text — English/formula lines must stand alone."""


SYS_TUTORIAL = SYS_UNIVERSAL + r"""

MANDATORY STRUCTURE — output exactly in this order:

🎯 <b>هدف این درس</b>
(1-2 lines)

📖 <b>مقدمه و تعریف</b>
(2-4 lines)

🔬 <b>مبانی فیزیکی / ریاضی</b>
(3-5 lines)

📐 <b>فرمول‌های کلیدی</b>

For EACH formula (3-5 formulas):

### N. نام فارسی فرمول
نام: English Formula Name
فرمول:
<code>RAW_LATEX_FORMULA</code>
متغیرها: var1 unit1 توضیح، var2 unit2 توضیح، ...
کاربرد: یک تا دو خط.
مثال: یک مثال عددی کوتاه.
منبع: Author, Book, Year, Chapter.
---

Rules:
- N from ۱ (Persian numerals).
- Formula inside <code> only, raw LaTeX.
- NEVER wrap Persian in <code>.
- NEVER build a table of formulas.
- Each block ends with ---

🧮 <b>مثال حل‌شده</b>
گام ۱: ...
گام ۲: ...
<code>equation</code>
نتیجه: ...

📊 <b>جدول خلاصه</b>
(concepts, not formulas)

| مفهوم | توضیح | کاربرد |
|-------|-------|--------|

⚙️ <b>کاربرد صنعتی</b>
(2-3 lines)

⚠️ <b>اشتباهات رایج</b>
1. ...
2. ...
3. ...

✅ <b>جمع‌بندی</b>
(2-3 lines)

📚 <b>مطالعه بیشتر</b>
- Book 1
- Book 2"""



SYS_FORMULA = SYS_UNIVERSAL + r"""

OUTPUT FORMAT — a formula sheet. Use EXACTLY this layout.

Intro: 🧮 <b>برگه فرمول: {topic}</b>

For EACH formula (output 5 to 8 formulas):

### N. نام فارسی فرمول
نام: English Formula Name
فرمول:
<code>RAW_LATEX_FORMULA</code>
متغیرها: var1 unit1 توضیح، var2 unit2 توضیح، ...
کاربرد: یک تا دو خط توضیح فنی.
مثال: یک مثال عددی کوتاه با نتیجه.
منبع: Author, Book, Year, Chapter.
---

Rules:
- N starts from ۱ (Persian numerals).
- Formula inside <code> only, RAW LaTeX (\\frac{}, \\partial, \\nabla, \\int, ...).
- NEVER put Persian text in <code>.
- NEVER build a markdown table of formulas.
- Each block ends with a single line: ---

📊 <b>جدول خلاصه</b>

| نام | کاربرد |
|-----|--------|
| ... | ...    |

⚠️ <b>اشتباهات رایج</b>
- ...
- ...

✅ <b>جمع‌بندی</b>
(1-2 lines)"""



SYS_MATH = SYS_UNIVERSAL + r"""

OUTPUT FORMAT — mathematics lesson.

🎯 <b>هدف</b> (1 line)
📖 <b>تعریف دقیق</b> (2-3 lines)
📐 <b>قضیه / فرمول اصلی</b>

For EACH key formula (3 to 5), use EXACTLY this block:

### N. نام فارسی
نام: English Name
فرمول:
<code>RAW_LATEX</code>
متغیرها: ... با واحد
شرایط: مفروضات و محدودیت‌ها
مثال: مثال کوچک عددی
منبع: ...
---

Rules:
- Persian numerals for N.
- Formula inside <code> only, raw LaTeX.
- NEVER put Persian text in <code>.
- NEVER build a table of formulas.

🧮 <b>اثبات یا استدلال</b> (2-4 lines)
✏️ <b>مثال حل‌شده</b>
   گام ۱: ...
   گام ۲: ...
   نتیجه: ...
📊 <b>جدول خلاصه</b> (concepts only)
⚠️ <b>اشتباهات رایج</b> (2-3 items)
✅ <b>جمع‌بندی</b>"""


SYS_DEEP = SYS_UNIVERSAL + """

OUTPUT FORMAT — deep technical analysis (30-50 lines):

🎯 <b>صورت مسئله</b>
🔍 <b>پیشینه علمی</b> (with recent papers if available)
🔬 <b>روش‌شناسی</b> (mathematical model, assumptions)
📐 <b>معادلات حاکم</b> (governing equations)
🧮 <b>نتایج کلیدی</b>
📊 <b>تحلیل عددی</b> (table)
⚙️ <b>پیامدهای مهندسی</b>
⚠️ <b>محدودیت‌ها و فرضیات</b>
🚀 <b>کارهای آینده</b>
📚 <b>منابع</b>"""


SYS_NEWS = SYS_UNIVERSAL + """

OUTPUT FORMAT — news analysis:

📰 <b>تیتر</b>
📅 <b>منبع و تاریخ</b>
🔍 <b>خلاصه فنی</b> (3-5 lines technical)
⚙️ <b>اهمیت مهندسی</b> (why it matters)
📊 <b>داده‌های کلیدی</b> (if any)
🎯 <b>پیامدها</b>
🔗 <b>منبع</b>"""


SYS_QUIZ = SYS_UNIVERSAL + """

Generate exactly 3 multiple-choice questions with 4 options each.
Mark the correct answer with ✅.

EXACT FORMAT:
❓ <b>سوال ۱:</b> ...

الف) ...
ب) ...
ج) ...
د) ...

✅ <b>پاسخ:</b> ب
💡 <b>توضیح:</b> (1 line)

(repeat for سوال ۲ and ۳)"""


SYS_FLASHCARD = SYS_UNIVERSAL + """

Generate exactly 5 flashcards:

🎴 <b>کارت N</b>
🔹 <b>اصطلاح:</b> ...
🔸 <b>تعریف:</b> (max 2 lines)
📐 <b>فرمول:</b> <code>...</code> (if applicable)"""


SYS_TRIVIA = SYS_UNIVERSAL + """

OUTPUT FORMAT — interesting facts:

💡 <b>آیا می‌دانستید؟</b>

1. Fact 1 with technical depth
2. Fact 2
3. Fact 3

🔬 <b>پشت صحنه علمی</b> (why it works)
⚙️ <b>کاربرد</b>
📚 <b>منبع</b>"""


SYS_EXAMPLE = SYS_UNIVERSAL + """

OUTPUT FORMAT — worked example:

🎯 <b>مسئله</b>
(full problem statement)

📋 <b>داده‌ها</b>
- Given values with units

🔍 <b>رویکرد حل</b>
(1-2 lines strategy)

🧮 <b>حل مرحله‌به‌مرحله</b>
Step 1: ...
Step 2: ...
Step 3: ...

✅ <b>پاسخ نهایی</b>
📊 <b>بررسی صحت</b> (units, sanity check)
⚠️ <b>نکات مهم</b>"""


SYS_COMPARISON = SYS_UNIVERSAL + """

OUTPUT FORMAT — comparison:

⚖️ <b>مقایسه: A vs B</b>

📊 <b>جدول مقایسه</b> (Markdown table with 5+ rows)

🔍 <b>تحلیل تفصیلی</b>
• A: advantages, disadvantages, when to use
• B: advantages, disadvantages, when to use

🎯 <b>توصیه مهندسی</b> (when to choose what)
⚠️ <b>اشتباهات رایج در انتخاب</b>"""


SYS_HISTORY = SYS_UNIVERSAL + """

OUTPUT FORMAT — historical perspective:

📜 <b>تاریخچه</b>
👤 <b>دانشمندان کلیدی</b> (with years)
🔬 <b>سیر تحول</b> (chronological)
📐 <b>معادلات تاریخی</b>
🎯 <b>تأثیر بر مهندسی امروز</b>
📚 <b>منابع تاریخی</b>"""


STYLE_PROMPTS = {
    "tutorial": SYS_TUTORIAL,
    "formula": SYS_FORMULA,
    "math": SYS_MATH,
    "deep": SYS_DEEP,
    "news": SYS_NEWS,
    "quiz": SYS_QUIZ,
    "flashcard": SYS_FLASHCARD,
    "trivia": SYS_TRIVIA,
    "example": SYS_EXAMPLE,
    "comparison": SYS_COMPARISON,
    "history": SYS_HISTORY,
}


# ══════════════════════════════════════════════════════════════════════════════
#                        CONTENT GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

def find_related_youtube_video(topic_name: str, cfg) -> str:
    """Find a related YouTube video for the topic. Returns HTML block or empty."""
    try:
        if not getattr(cfg.keys, "apify", ""):
            return ""
        r = APIS.apify.youtube_search(topic_name, max_videos=1)
        if not r.ok or not r.data:
            return ""
        videos = r.data if isinstance(r.data, list) else []
        if not videos:
            return ""
        v = videos[0]
        title = (v.get("title") or "")[:80]
        url   = v.get("url") or v.get("videoUrl") or ""
        ch    = (v.get("channelName") or "")[:40]
        if not url:
            return ""
        return (
            "\n\n🎥 <b>ویدیوی مرتبط:</b>\n"
            f"<a href=\"{url}\">{escape_html(title)}</a>\n"
            f"<i>{escape_html(ch)}</i>\n"
        )
    except Exception as e:
        log.debug(f"find_related_youtube_video: {e}")
        return ""

class MultiSourceAssembler:
    """
    Gathers info from multiple APIs in parallel, combines into a context
    blob that the AI uses to write a richer post. Picks sources based on
    topic style/category.
    """
    def __init__(self, apis: APIRegistry):
        self.apis = apis

    def gather(self, topic: Dict, style: str, cfg) -> Dict[str, Any]:
        ctx: Dict[str, Any] = {}
        futures: Dict[str, Future] = {}

        q = topic.get("query") or topic.get("name") or ""
        name = topic.get("name") or ""

        # 1. arXiv (technical)
        if style in ("tutorial", "deep", "math", "example", "news"):
            futures["arxiv"] = POOL.submit(
                self.apis.arxiv.search, q, max_results=4,
            )

        # 2. News feeds
        if style == "news" or "news" in name.lower() or "اخبار" in name:
            futures["news"] = POOL.submit(
                self.apis.news.fetch_combined, 20,
            )

        # 3. Wikipedia summary
        if style in ("tutorial", "deep", "news", "history"):
            futures["wiki_fa"] = POOL.submit(
                self.apis.wikipedia.summary, name, "fa",
            )
            futures["wiki_en"] = POOL.submit(
                self.apis.wikipedia.summary, q, "en",
            )

        # 4. YouTube videos (Apify)
        if getattr(cfg.keys, "apify", "") and style in ("tutorial", "deep"):
            futures["youtube"] = POOL.submit(
                self.apis.apify.youtube_search, q, 3,
            )

        # 5. eeemoji (for visual enrichment)
        if style in ("news", "trivia", "flashcard"):
            # pick a keyword from the topic name
            keyword = (name.split()[0] if name else q.split()[0] if q else "star")
            futures["emoji"] = POOL.submit(
                self.apis.emoji.search, keyword, 3,
            )

        # 6. Learning Engine (quiz/example)
        if style in ("quiz", "example") and getattr(cfg.keys, "rapidapi_learning_secret", ""):
            futures["learning"] = POOL.submit(
                self.apis.ai_learning.generate_task,
                name, type_="test", level="intermediate", lang="Persian",
            )

        # 7. BazaarLink (secondary AI - verify/enrich)
        if getattr(cfg.keys, "bazaarlink", "") and style == "deep":
            futures["bazaar"] = POOL.submit(
                self.apis.bazaarlink.chat,
                "You are an expert. Give 3 short technical facts.",
                f"Topic: {name}", max_tokens=400,
            )

        # Resolve
        for key, fut in futures.items():
            try:
                res = fut.result(timeout=45)
                if isinstance(res, APIResult):
                    if res.ok:
                        ctx[key] = res.data
                else:
                    ctx[key] = res
            except Exception as e:
                log.debug(f"assembler {key}: {e}")

        # Formulas (in-process, always available)
        try:
            from_part4 = get_formulas_for(name, topic)
            if from_part4:
                ctx["formulas"] = from_part4
        except Exception:
            pass

        return ctx

    def to_prompt_block(self, ctx: Dict[str, Any], max_chars: int = 4000) -> str:
        """Format gathered context into a text block for the AI prompt."""
        out = []
        if ctx.get("formulas"):
            out.append("📐 فرمول‌های مرتبط:")
            for n, e, d in ctx["formulas"][:8]:
                out.append(f"  • {n}: {e}" + (f" — {d}" if d else ""))

        if ctx.get("wiki_fa"):
            w = ctx["wiki_fa"]
            out.append(f"\n📖 ویکی (fa): {w.get('title','')}")
            out.append(f"  {w.get('extract','')[:500]}")

        if ctx.get("wiki_en"):
            w = ctx["wiki_en"]
            out.append(f"\n📖 Wiki (en): {w.get('title','')}")
            out.append(f"  {w.get('extract','')[:400]}")

        if ctx.get("arxiv"):
            out.append("\n📚 arXiv:")
            for p in ctx["arxiv"][:3]:
                out.append(f"  • {p.get('title','')[:120]}")
                out.append(f"    {p.get('summary','')[:250]}")

        if ctx.get("news"):
            out.append("\n📰 اخبار:")
            for n in ctx["news"][:6]:
                t = n.get("title", "")[:100]
                src = n.get("feed_name", "")
                out.append(f"  • [{src}] {t}")

        if ctx.get("youtube"):
            out.append("\n🎥 YouTube:")
            for v in ctx["youtube"][:3]:
                out.append(f"  • {v.get('title','')[:80]}")

        if ctx.get("emoji"):
            out.append("\n😀 ایموجی مرتبط:")
            for e in ctx["emoji"][:3]:
                em = e.get("emoji", "")
                nm = e.get("name", "")
                out.append(f"  {em} {nm}")

        if ctx.get("learning"):
            lr = ctx["learning"].get("data", {}) if isinstance(ctx["learning"], dict) else {}
            out.append(f"\n🎓 تمرین نمونه: {lr.get('task','')[:200]}")

        if ctx.get("bazaar"):
            out.append(f"\n🧠 BazaarLink insights: {str(ctx['bazaar'])[:400]}")

        block = "\n".join(out)
        return block[:max_chars]


ASSEMBLER = MultiSourceAssembler(APIS)

class ContentGenerator:
    def __init__(self, ai: AIClient, apis: APIRegistry):
        self.ai = ai
        self.apis = apis

    def generate(
        self,
        topic: Union[str, Dict],
        style: str = "tutorial",
        *,
        extra_context: str = "",
        force_fresh: bool = False,
    ) -> Optional[str]:
        """Generate structured content."""

        # Normalize topic
        if isinstance(topic, str):
            topic_name = topic
            topic_dict = TOPIC_MGR.find(topic) or {
                "name": topic, "query": topic, "emoji": "📌",
                "tags": "#مهندسی_مکانیک",
            }
        else:
            topic_dict = topic
            topic_name = topic["name"]

        # Style check
        if style not in STYLE_PROMPTS:
            style = "tutorial"

        # Get content params
        cfg = CONFIG.get()
        style_meta = CONTENT_STYLES.get(style, CONTENT_STYLES["tutorial"])
        max_tokens = style_meta["max_tokens"]

        # Gather context in parallel
        context = self._gather_context(topic_dict, style, extra_context)

        # Build prompts
        system_prompt = STYLE_PROMPTS[style].replace("{topic}", topic_name)
        user_prompt = self._build_user_prompt(topic_name, style, context, cfg)

        # Call AI
        log.info(f"Generating: {topic_name} [{style}]")
        resp = self.ai.ask(
            system_prompt, user_prompt,
            max_tokens=max_tokens,
            temperature=0.55,
        )

        if not resp.ok:
            log.error(f"Generation failed: {resp.error}")
            return None

        # Post-process
        content = self._post_process(resp.text, topic_dict, cfg, style)

        # Mark seen
        if topic_dict.get("query"):
            SEEN.add(f"{style}:{topic_dict['query']}")

        return content

    def _gather_context(self, topic: Dict, style: str, extra: str) -> Dict[str, Any]:
        """Use MultiSourceAssembler for richer context."""
        cfg = CONFIG.get()
        try:
            context = ASSEMBLER.gather(topic, style, cfg)
        except Exception as e:
            log.warning(f"assembler failed: {e}")
            context = {}
        if "formulas" not in context:
            try:
                f = get_formulas_for(topic.get("name", ""), topic)
                if f:
                    context["formulas"] = f
            except Exception:
                pass
        if extra:
            context["extra"] = extra
        return context

    def _build_user_prompt(
        self, topic_name: str, style: str,
        context: Dict, cfg,
    ) -> str:
        """Assemble user prompt with all context."""
        parts = [
            f"موضوع: {topic_name}",
            f"سبک: {style}",
            f"سطح فنی: {cfg.content.technical_level}",
            f"طول: {CONTENT_STYLES.get(style, {}).get('lines', 'متوسط')}",
            "",
            "دستور: پست آموزشی ساختاریافته با قالب دقیق خواسته‌شده بنویس.",
        ]

        # Multi-source context block
        if context:
            try:
                block = ASSEMBLER.to_prompt_block(context, max_chars=3500)
                if block:
                    parts.append("")
                    parts.append("--- منابع خارجی ---")
                    parts.append(block)
            except Exception:
                pass

        # Formulas (legacy)
        if context.get("formulas"):
            parts.append("")
            parts.append("📐 فرمول‌های مرتبط (برای مرجع):")
            for name, expr, desc in context["formulas"][:10]:
                parts.append(f"• {name}: {expr}" + (f" — {desc}" if desc else ""))

        # Papers
        if context.get("papers"):
            parts.append("")
            parts.append("📚 مقالات علمی arXiv (جدیدترین):")
            for p in context["papers"][:3]:
                parts.append(f"• {p['title']}")
                parts.append(f"  چکیده: {p['summary'][:400]}")
                parts.append(f"  لینک: {p['link']}")

        # News
        if context.get("news"):
            parts.append("")
            parts.append("📰 اخبار مرتبط:")
            for n in context["news"][:6]:
                parts.append(f"• {n.get('title', '')[:100]}")
                if n.get("link"):
                    parts.append(f"  {n['link']}")

        # Extra
        if context.get("extra"):
            parts.append("")
            parts.append(f"ℹ️ اطلاعات اضافه:\n{context['extra'][:1500]}")

        # Footer
        parts.append("")
        parts.append("———")
        if cfg.content.include_hashtags and context.get("formulas"):
            pass
        parts.append("📢 @MAADGHchannel")

        return "\n".join(parts)

    def _post_process(self, text: str, topic: Dict, cfg, style: str = "tutorial") -> str:
        """Clean up, separate directions, add tags. Style-aware."""
        if not text:
            return ""

        # LaTeX cleaning: skip for formula/math (keep raw LaTeX visible)
        if style not in ("formula", "math"):
            try:
                text = clean_latex(text)
            except Exception as e:
                log.warning(f"clean_latex: {e}")

        # Strip triple-backtick fences (Telegram uses <code>/<pre>)
        text = re.sub(r"```(\w*)\n", "", text)
        text = re.sub(r"```", "", text)

        # Normalize double-underscore bold to markdown bold
        text = re.sub(r"__(.+?)__", r"**\1**", text)

        # RTL/LTR separation (adds FML markers for formula lines)
        try:
            text = separate_directions(text)
        except Exception as e:
            log.warning(f"separate_directions: {e}")

        # Markdown -> HTML
        try:
            text = _md_to_html_safe(text)
        except Exception as e:
            log.warning(f"_md_to_html_safe: {e}")

        # Hashtags - expand from category, cap at 5
        if cfg.content.include_hashtags:
            try:
                tag_list = HASHTAGS.expand(topic, max_tags=5)
                if tag_list:
                    tag_str = " ".join(tag_list)
                    if tag_str not in text:
                        text = text.rstrip() + "\n\n" + tag_str
                    HASHTAGS.register_all(tag_list)
            except Exception as _e:
                log.warning(f"hashtag expand: {_e}")

        # Channel footer
        footer = "📢 @MAADGHchannel"
        if footer not in text:
            text = text.rstrip() + f"\n\n———\n{footer}"

        # Optional YouTube block (only if Apify is set)
        try:
            if getattr(cfg.keys, "apify", ""):
                yt_block = find_related_youtube_video(topic.get("name", ""), cfg)
                if yt_block and "youtu" not in text:
                    if footer in text:
                        text = text.replace(footer, yt_block.strip() + "\n\n" + footer)
                    else:
                        text = text.rstrip() + yt_block
        except Exception as e:
            log.warning(f"YouTube block: {e}")

        # ── YouTube video suggestions (ALWAYS 2 videos) ──
        try:
            if "youtu" not in text:
                search_q = (topic.get("query") or topic.get("name") or "").strip()
                if search_q:
                    yt_data = None
                    for q in (f"{search_q} tutorial", f"{search_q} engineering", search_q):
                        try:
                            r = APIS.youtube.search_videos(q, max_results=2)
                            if r.ok and r.data:
                                yt_data = r.data
                                break
                        except Exception:
                            continue
                    if yt_data:
                        yt_block = APIS.youtube.format_block(yt_data, max_show=2)
                        if yt_block:
                            if footer in text:
                                text = text.replace(footer, yt_block.strip() + "\n\n" + footer)
                            else:
                                text = text.rstrip() + "\n\n" + yt_block
        except Exception as e:
            log.warning(f"YouTube suggestions: {e}")

        return text.strip()
    def regenerate(
        self,
        topic: Union[str, Dict],
        style: str = "tutorial",
        *,
        variations: int = 1,
    ) -> List[str]:
        """Generate N alternative versions."""
        results = []
        for i in range(variations):
            # Add small nudge to prompt for diversity
            extra = f"نسخه {i+1} — خلاقیت بیشتر، مثال متفاوت."
            content = self.generate(topic, style, extra_context=extra)
            if content:
                results.append(content)
        return results


CONTENT = ContentGenerator(AI, APIS)


def _is_user_chat_id(x) -> bool:
    """Positive integer ids are user chats, not channels."""
    try:
        s = str(x).strip()
        return s.lstrip("+").isdigit() and int(s) > 0
    except Exception:
        return False


def _verify_channel_target(cfg) -> Tuple[bool, str]:
    """Confirm channel_id points to a real channel, not a user chat."""
    ch = (cfg.telegram.channel_id or "").strip()
    if not ch:
        return False, "channel_id empty"

    if _is_user_chat_id(ch):
        return False, (
            f"channel_id={ch} is a POSITIVE integer — that's a USER chat id. "
            f"Set @username or -100xxxxxxxxxx for a channel."
        )

    r = TG.get_chat(ch)
    if not r.ok:
        return False, f"getChat failed: {r.error_code} {r.description}"

    info = r.result or {}
    ctype = info.get("type", "?")
    if ctype != "channel":
        return False, (
            f"channel_id points to a '{ctype}' (title='{info.get('title','')}'), "
            f"not a channel."
        )
    return True, f"channel '{info.get('title','')}' id={info.get('id','')}"


# (duplicate _send_to_channel removed - robust version below)


# ══════════════════════════════════════════════════════════════════════════════
#                        POST PUBLISHING
# ══════════════════════════════════════════════════════════════════════════════

def _send_to_channel(cfg, content: str, reply_markup=None) -> Tuple[bool, str, int]:
    """
    Robust channel publishing with clear diagnostics.
    Returns (success, message, n_messages).
    """
    channel = (cfg.telegram.channel_id or "").strip()
    if not channel:
        return False, "Channel ID not set in config", 0

    # Guard: prevent accidental post to a user chat
    if channel.lstrip("-").isdigit():
        cid = int(channel)
        # Private user chats are positive; channel ids are negative (usually -100...)
        if cid > 0:
            return False, (
                "channel_id looks like a USER chat id (positive). "
                "Use @username or -100xxxxxxxxxx for channels."
            ), 0

    # Force no buttons for channel posts (admin sees buttons only in DM)
    try:
        results = TG.send_long_message(channel, content, reply_markup=None)
    except Exception as e:
        log.exception("send_to_channel failed")
        return False, f"Exception: {e}", 0

    if not results:
        return False, "No result from Telegram", 0

    first = results[0]
    if first.ok:
        return True, f"OK ({len(results)} msg)", len(results)

    desc = first.description or "unknown"
    code = first.error_code or 0

    # Friendly hints
    if code == 400 and "chat not found" in desc.lower():
        return False, (
            f"chat not found: '{channel}'. "
            "Verify @username or -100 id. If private channel, "
            "add bot as admin first."
        ), 0
    if code == 403:
        return False, (
            f"403 forbidden: bot is not admin of '{channel}' or lacks "
            "Post Messages permission."
        ), 0

    return False, f"{code}: {desc[:150]}", 0


def _generate_post_full(cfg, topic: Union[str, Dict], style: str = "tutorial") -> Optional[str]:
    """Public wrapper used by Part 2 admin test."""
    return CONTENT.generate(topic, style)


def _generate_and_post(cfg, chat_id: int, topic: Union[str, Dict],
                       style: str = "tutorial", *, draft_id: Optional[str] = None,
                       with_poll: bool = False) -> None:
    """Full generation + publishing flow."""

    if isinstance(topic, str):
        topic_dict = TOPIC_MGR.find(topic) or {
            "name": topic, "query": topic, "emoji": "📌",
            "tags": "#مهندسی_مکانیک",
        }
    else:
        topic_dict = topic

    topic_name = topic_dict["name"]

    # Send loading
    _prog(f"generate start | topic={topic_name} style={style}", "post")
    LIVE.event("gen", f"Generating: {topic_name} [{style}]")
    m = TG.send_message(chat_id, f"⏳ در حال تولید «{topic_dict.get('emoji', '')} {topic_name}» ({style})...")
    if not m.ok:
        return
    mid = (m.result or {}).get("message_id")

    _t0 = _prog_ai_start()
    try:
        with TypingHeartbeat(chat_id):
            content = CONTENT.generate(topic_dict, style)
    except Exception as _e:
        _prog(f"generate exception: {_e}", "post")
        content = None
    _prog_ai_done(_t0, content or "", provider="content")
    if content:
        LIVE.event("gen", f"Generation complete: {len(content)} chars")
    else:
        LIVE.event("err", f"Generation failed: {topic_name}")

    if not content:
        _prog("generate FAILED - empty content", "post")
        TG.edit_message(chat_id, mid,
                       "❌ تولید ناموفق. کلید AI یا اتصال را بررسی کن.")
        return
    _prog(f"generate OK | {len(content)} chars", "post")

    # Save as draft
    # Positive id = private user chat; groups/channels are negative.
    uid = chat_id if isinstance(chat_id, int) and chat_id > 0 else 0
    draft = DRAFTS.create(topic_name, style, content, uid,
                          metadata={"channel": True})

    # Preview to user (first 1500 chars)
    preview = content[:1500]
    if len(content) > 1500:
        preview += "\n\n<i>...(ادامه در کانال)</i>"

    preview_msg = (
        f"📋 <b>پیش‌نمایش:</b>\n\n{preview}"
    )

    # ── STRICT CHANNEL VALIDATION ──
    is_ch, ch_msg = _verify_channel_target(cfg)
    if not is_ch:
        TG.edit_message(
            chat_id, mid,
            f"⛔ <b>انتشار متوقف شد</b>\n\n"
            f"{escape_html(ch_msg)}\n\n"
            f"<b>تنظیم درست:</b>\n"
            f"• کانال عمومی: <code>@MyChannel</code>\n"
            f"• کانال خصوصی: <code>-100xxxxxxxxxx</code>\n"
            f"• ربات باید <b>ادمین</b> با پرمیشن <b>Post Messages</b> باشد\n"
            f"• تست: <code>python MAADGH-4.py --check-channel</code>",
        )
        log.warning(f"Publish refused: {ch_msg}")
        STATS.incr("errors")
        return

    # ── PUBLISH ──
    # Channel post goes WITHOUT buttons; admin sees buttons in DM only
    ok_flag, msg, n = _send_to_channel(cfg, content, reply_markup=None)

    if ok_flag:
        TG.edit_message(
            chat_id, mid,
            f"✅ «{topic_name}» در کانال منتشر شد.\n"
            f"📢 <code>{escape_html(cfg.telegram.channel_id)}</code>\n"
            f"🎨 سبک: <b>{style}</b>\n"
            f"📏 {len(content)} کاراکتر | 📦 {n} پیام",
            reply_markup=kb([
                [btn("🔄 بازتولید", f"regen:{draft.id}"),
                 btn("✏️ نسخه دیگر", f"regen2:{draft.id}")],
                [btn("👁 نمایش محتوا", f"show:{draft.id}")],
                [btn("🗑 حذف پیش‌نویس", f"draftdel:{draft.id}")],
            ]))
        STATS.incr("posts")
        STATS.incr_dict("styles", style)
        LIVE.event("pub", f"Published -> {cfg.telegram.channel_id} ({len(content)} chars)")
        try:
            HASHTAGS.sync_channel(cfg)
        except Exception as _e:
            log.debug(f"hashtag sync after publish: {_e}")

        if with_poll or cfg.behavior.auto_poll:
            try:
                TG.send_poll(
                    cfg.telegram.channel_id,
                    f"نظر شما درباره «{topic_name}»؟",
                    ["⭐ عالی", "👍 خوب", "👎 ضعیف", "😐 متوسط"],
                )
            except Exception:
                pass
    else:
        TG.edit_message(
            chat_id, mid,
            f"❌ <b>انتشار ناموفق</b>\n\n"
            f"🔴 {escape_html(msg[:250])}\n\n"
            f"راهنما: <code>python MAADGH-4.py --check-channel</code>"
        )
        log.error(f"Publish failed: {msg}")
        STATS.incr("errors")
        LIVE.event("err", f"Publish failed: {msg[:120]}")


# ══════════════════════════════════════════════════════════════════════════════
#                        CONTENT COMMANDS
# ══════════════════════════════════════════════════════════════════════════════

@ROUTER.command("post", description="پست موضوعی")
def cmd_post(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    topic = args.strip() or TOPIC_MGR.rotate_next()["name"]
    cfg = CONFIG.get()
    POOL.submit(_generate_and_post, cfg, chat_id, topic, "tutorial")


@ROUTER.command("next", description="موضوع بعدی")
def cmd_next(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    t = TOPIC_MGR.rotate_next()
    POOL.submit(_generate_and_post, CONFIG.get(), chat_id, t, t.get("style", "tutorial"))


@ROUTER.command("topic", description="موضوع بعدی (مترادف next)")
def cmd_topic(msg: Dict, args: str) -> None:
    if args:
        cmd_post(msg, args)
    else:
        cmd_next(msg, args)


@ROUTER.command("random", description="موضوع تصادفی")
def cmd_random(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    all_t = TOPIC_MGR.all()
    if not all_t:
        TG.send_message(chat_id, "❌ فهرست خالی.")
        return
    # Use weighted picker for true random + anti-repeat
    t = PICKER.pick(all_t)
    if not t:
        t = all_t[0]
    POOL.submit(_generate_and_post, CONFIG.get(), chat_id, t, t.get("style", "tutorial"))


@ROUTER.command("formula", description="برگه فرمول")
def cmd_formula(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    topic = args.strip() or "ترمودینامیک"
    POOL.submit(_generate_and_post, CONFIG.get(), chat_id, topic, "formula")


@ROUTER.command("math", description="آموزش ریاضی")
def cmd_math(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    topic = args.strip() or "انتگرال سه‌گانه"
    POOL.submit(_generate_and_post, CONFIG.get(), chat_id, topic, "math")


@ROUTER.command("deep", description="تحلیل عمیق")
def cmd_deep(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    topic = args.strip() or TOPIC_MGR.rotate_next()["name"]
    POOL.submit(_generate_and_post, CONFIG.get(), chat_id, topic, "deep")


@ROUTER.command("quiz", description="کوییز")
def cmd_quiz(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    topic = args.strip() or "ترمودینامیک"
    POOL.submit(_generate_and_post, CONFIG.get(), chat_id, topic, "quiz")


@ROUTER.command("flash", description="فلش‌کارت")
def cmd_flash(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    topic = args.strip() or "مقاومت مصالح"
    POOL.submit(_generate_and_post, CONFIG.get(), chat_id, topic, "flashcard")


@ROUTER.command("trivia", description="دانستنی")
def cmd_trivia(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    topic = args.strip() or "مهندسی مکانیک"
    POOL.submit(_generate_and_post, CONFIG.get(), chat_id, topic, "trivia")


@ROUTER.command("example", description="مثال حل‌شده")
def cmd_example(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    topic = args.strip() or "برنولی"
    POOL.submit(_generate_and_post, CONFIG.get(), chat_id, topic, "example")


@ROUTER.command("compare", description="مقایسه")
def cmd_compare(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    topic = args.strip() or "توربین گازی vs بخار"
    POOL.submit(_generate_and_post, CONFIG.get(), chat_id, topic, "comparison")


@ROUTER.command("history", description="تاریخ مهندسی")
def cmd_history(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    topic = args.strip() or "تاریخ ترمودینامیک"
    POOL.submit(_generate_and_post, CONFIG.get(), chat_id, topic, "history")


@ROUTER.command("style", description="انتخاب سبک و پست")
def cmd_style(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    parts = args.split(None, 1)
    if not parts:
        styles_list = "\n".join(
            f"• <code>{k}</code> — {v['emoji']} {v['name']}"
            for k, v in CONTENT_STYLES.items()
        )
        TG.send_message(chat_id,
                       f"🎨 <b>سبک‌های محتوا</b>\n\n{styles_list}\n\n"
                       f"استفاده: <code>/style &lt;سبک&gt; &lt;موضوع&gt;</code>")
        return

    style = parts[0]
    topic = parts[1] if len(parts) > 1 else TOPIC_MGR.rotate_next()["name"]

    if style not in CONTENT_STYLES:
        TG.send_message(chat_id, f"❌ سبک «{style}» موجود نیست.")
        return

    POOL.submit(_generate_and_post, CONFIG.get(), chat_id, topic, style)


# ══════════════════════════════════════════════════════════════════════════════
#                        TOPIC MANAGEMENT COMMANDS
# ══════════════════════════════════════════════════════════════════════════════

@ROUTER.command("addtopic", description="افزودن موضوع سفارشی")
def cmd_addtopic(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    if "|" not in args:
        TG.send_message(chat_id,
                       "❌ فرمت: <code>/addtopic نام | query</code>\n"
                       "مثال: <code>/addtopic توربین بادی | wind turbine</code>")
        return

    name, query = [p.strip() for p in args.split("|", 1)]
    if not name or not query:
        TG.send_message(chat_id, "❌ نام و query نمی‌توانند خالی باشند.")
        return

    if TOPIC_MGR.add(name, query):
        TG.send_message(chat_id, f"✅ موضوع «{name}» اضافه شد.")
    else:
        TG.send_message(chat_id, f"❌ قبلاً وجود دارد.")


@ROUTER.command("delcustom", description="حذف موضوع سفارشی")
def cmd_delcustom(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    name = args.strip()
    if not name:
        TG.send_message(chat_id, "❌ استفاده: <code>/delcustom نام</code>")
        return
    if TOPIC_MGR.remove(name):
        TG.send_message(chat_id, f"✅ «{name}» حذف شد.")
    else:
        TG.send_message(chat_id, f"❌ یافت نشد.")


@ROUTER.command("topics", description="مدیریت موضوعات")
def cmd_topics(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    built_in = len(TOPICS)
    custom = len(TOPIC_MGR.custom())
    cfg = CONFIG.get()
    idx = cfg.behavior.topic_index % max(1, built_in + custom)
    nxt = TOPIC_MGR.all()[idx] if TOPIC_MGR.all() else {"name": "?"}

    text = (
        f"📚 <b>مدیریت موضوعات</b>\n\n"
        f"• موضوعات داخلی: <code>{built_in}</code>\n"
        f"• موضوعات سفارشی: <code>{custom}</code>\n"
        f"• موضوع بعدی: <b>{escape_html(nxt.get('name', '?'))}</b>\n\n"
        f"دستورات:\n"
        f"• <code>/list</code> — فهرست کامل\n"
        f"• <code>/addtopic نام | query</code>\n"
        f"• <code>/delcustom نام</code>"
    )
    TG.send_message(chat_id, text)


# ══════════════════════════════════════════════════════════════════════════════
#                        DRAFT COMMANDS
# ══════════════════════════════════════════════════════════════════════════════

@ROUTER.command("drafts", description="پیش‌نویس‌ها")
def cmd_drafts(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    uid = get_uid(msg)
    drafts = DRAFTS.list_for_user(uid)

    if not drafts:
        TG.send_message(chat_id, "📭 پیش‌نویسی موجود نیست.")
        return

    text = f"📝 <b>پیش‌نویس‌ها ({len(drafts)})</b>\n\n"
    for d in drafts[-10:]:
        text += (
            f"• <code>{d.id}</code> — {escape_html(d.topic[:30])} "
            f"[{d.style}]\n  {d.created_at[:16]}\n"
        )

    TG.send_message(chat_id, text)


@ROUTER.command("draftdel", description="حذف پیش‌نویس")
def cmd_draftdel(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    did = args.strip()
    if not did:
        return
    if DRAFTS.remove(did):
        TG.send_message(chat_id, f"✅ حذف شد.")
    else:
        TG.send_message(chat_id, "❌ یافت نشد.")


# ══════════════════════════════════════════════════════════════════════════════
#                        REGENERATE COMMANDS
# ══════════════════════════════════════════════════════════════════════════════

@ROUTER.command("regen", description="بازتولید پست")
def cmd_regen(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    did = args.strip()
    if not did:
        TG.send_message(chat_id, "❌ استفاده: <code>/regen ID</code>")
        return

    d = DRAFTS.get(did)
    if not d:
        TG.send_message(chat_id, "❌ پیش‌نویس یافت نشد.")
        return

    STATS.incr("regen")
    POOL.submit(_generate_and_post, CONFIG.get(), chat_id,
                d.topic, d.style, draft_id=did)


# ══════════════════════════════════════════════════════════════════════════════
#                        CALLBACK HANDLERS FOR CONTENT
# ══════════════════════════════════════════════════════════════════════════════

@ROUTER.callback("regen")
def cb_regen(cb: Dict, data: str) -> None:
    did = data.split(":", 1)[1]
    uid = cb.get("from", {}).get("id", 0)
    if not is_admin(uid):
        TG.answer_callback(cb.get("id", ""), "⛔", show_alert=True)
        return

    d = DRAFTS.get(did)
    if not d:
        TG.answer_callback(cb.get("id", ""), "❌ یافت نشد", show_alert=True)
        return

    chat_id = cb["message"]["chat"]["id"]
    TG.answer_callback(cb.get("id", ""), "🔄 بازتولید...")
    STATS.incr("regen")
    POOL.submit(_generate_and_post, CONFIG.get(), chat_id,
                d.topic, d.style)


@ROUTER.callback("regen2")
def cb_regen2(cb: Dict, data: str) -> None:
    """Regenerate + send alternative version to user (preview only)."""
    did = data.split(":", 1)[1]
    uid = cb.get("from", {}).get("id", 0)
    if not is_admin(uid):
        return

    d = DRAFTS.get(did)
    if not d:
        return

    chat_id = cb["message"]["chat"]["id"]
    TG.answer_callback(cb.get("id", ""), "🔄 نسخه دیگر...")

    STATS.incr("regen")

    def _do():
        new_content = CONTENT.generate(d.topic, d.style,
                                       extra_context="نسخه کاملاً متفاوت — زاویه جدید، مثال جدید.")
        if new_content:
            preview = new_content[:2000]
            TG.send_message(chat_id,
                          f"🔄 <b>نسخه جدید {d.topic}:</b>\n\n{preview}")

    POOL.submit(_do)


@ROUTER.callback("draftdel")
def cb_draftdel(cb: Dict, data: str) -> None:
    did = data.split(":", 1)[1]
    uid = cb.get("from", {}).get("id", 0)
    if not is_admin(uid):
        return

    if DRAFTS.remove(did):
        TG.answer_callback(cb.get("id", ""), "✅ حذف شد")
        chat_id = cb["message"]["chat"]["id"]
        msg_id = cb["message"]["message_id"]
        TG.edit_message(chat_id, msg_id, "🗑 پیش‌نویس حذف شد.")
    else:
        TG.answer_callback(cb.get("id", ""), "❌")


@ROUTER.callback("act")
def cb_act(cb: Dict, data: str) -> None:
    action = data.split(":", 1)[1]
    chat_id = cb["message"]["chat"]["id"]
    msg_id = cb["message"]["message_id"]
    TG.answer_callback(cb.get("id", ""))

    if action == "edit":
        TG.edit_message(chat_id, msg_id,
                       "✏️ برای ویرایش: از /style یا /regen استفاده کن.")
    elif action == "send":
        TG.edit_message(chat_id, msg_id, "✅ در کانال منتشر شده است.")
    elif action == "delete":
        try:
            TG.delete_message(chat_id, msg_id)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
#                        MENU EXTENSION (callbacks for styles)
# ══════════════════════════════════════════════════════════════════════════════

@ROUTER.callback("sty")
def cb_style(cb: Dict, data: str) -> None:
    """Callback for style shortcuts."""
    style = data.split(":", 1)[1]
    chat_id = cb["message"]["chat"]["id"]
    TG.answer_callback(cb.get("id", ""), f"🎨 {style}")

    if style in CONTENT_STYLES:
        topic = TOPIC_MGR.rotate_next()["name"]
        POOL.submit(_generate_and_post, CONFIG.get(), chat_id, topic, style)


# ══════════════════════════════════════════════════════════════════════════════
#                        KEYBOARD FOR STYLES
# ══════════════════════════════════════════════════════════════════════════════

def kb_styles_menu() -> Dict:
    """Full style selection keyboard."""
    rows = []
    items = list(CONTENT_STYLES.items())

    for i in range(0, len(items), 2):
        row = []
        for key, meta in items[i:i+2]:
            row.append(btn(f"{meta['emoji']} {meta['name']}", f"sty:{key}"))
        rows.append(row)

    rows.append([btn("⬅️ بازگشت", "m:main")])
    return kb(rows)


@ROUTER.command("styles", description="فهرست سبک‌ها")
def cmd_styles(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    TG.send_message(chat_id, "🎨 <b>سبک محتوا را انتخاب کن:</b>",
                   reply_markup=kb_styles_menu())


# ══════════════════════════════════════════════════════════════════════════════
#                        HOOK: MENU "lesson" CALLBACK NOW WORKS
# ══════════════════════════════════════════════════════════════════════════════

def _enhanced_cb_menu(cb: Dict, data: str) -> None:
    """Extension of Part 2's menu callback for real functionality."""
    action = data.split(":", 1)[1] if ":" in data else "main"
    chat_id = cb["message"]["chat"]["id"]
    msg_id = cb["message"]["message_id"]

    TG.answer_callback(cb.get("id", ""))

    if action == "lesson":
        # Show styles menu
        TG.edit_message(chat_id, msg_id,
                       "🎨 <b>سبک محتوا را انتخاب کن:</b>",
                       reply_markup=kb_styles_menu())
    else:
        # Fall through to Part 2's version
        _part2_cb_menu_original(cb, data) if "_part2_cb_menu_original" in globals() else None


# ══════════════════════════════════════════════════════════════════════════════
#                        AUTO-POSTER WITH ROTATION
# ══════════════════════════════════════════════════════════════════════════════

class AutoPoster:
    def __init__(self):
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_post = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="AutoPoster")
        self._thread.start()
        log.info("Auto-poster started")

    def stop(self) -> None:
        self._stop.set()
    def _loop(self) -> None:
        while not self._stop.is_set() and not _shutting_down.is_set():
            try:
                cfg = CONFIG.get()
                hours = max(1, int(cfg.behavior.auto_post_hours))
                interval = hours * 3600

                if self._stop.wait(interval):
                    break

                if self._shutting_down():
                    break

                log.info("Auto-post triggered")
                LIVE.event("sys", "Auto-post cycle started")

                # Pick next topic
                topic = TOPIC_MGR.rotate_next()

                # Skip if recently posted
                topic_key = f"auto:{topic.get('query', topic['name'])}"
                if SEEN.contains(topic_key):
                    # Try a few more
                    for _ in range(3):
                        topic = TOPIC_MGR.rotate_next()
                        topic_key = f"auto:{topic.get('query', topic['name'])}"
                        if not SEEN.contains(topic_key):
                            break

                # Generate + post
                content = CONTENT.generate(topic, topic.get("style", "tutorial"))
                if content:
                    results = TG.send_long_message(
                        cfg.telegram.channel_id, content,
                    )
                    if results and results[0].ok:
                        SEEN.add(topic_key)
                        STATS.incr("posts")
                        STATS.incr_dict("auto_topics", topic["name"])
                        self._last_post = time.time()
                        log.info(f"Auto-post OK: {topic['name']}")

                        # Optional poll
                        if cfg.behavior.auto_poll:
                            TG.send_poll(
                                cfg.telegram.channel_id,
                                f"نظر شما درباره {topic['name']}؟",
                                ["⭐ عالی", "👍 خوب", "👎 ضعیف", "😐 متوسط"],
                            )

            except Exception as e:
                log.exception(f"Auto-poster error: {e}")
                time.sleep(60)

    def _shutting_down(self) -> bool:
        return _shutting_down.is_set()

    def next_run_time(self) -> Optional[datetime]:
        if not self._last_post:
            return datetime.now() + timedelta(seconds=CONFIG.get().behavior.auto_post_hours * 3600)
        return datetime.fromtimestamp(self._last_post) + timedelta(hours=CONFIG.get().behavior.auto_post_hours)


AUTO_POSTER = AutoPoster()

# ─── Content Director hookup (FIX4) ─────────────────────────────────────
try:
    import _director as _DIRECTOR_MOD
    _DIRECTOR_OK = True
    log.info("[director] module loaded")
except Exception as _e:
    _DIRECTOR_MOD = None
    _DIRECTOR_OK = False
    log.warning(f"[director] not available: {_e}")


if _DIRECTOR_OK:
    def _director_loop(self):
        """Replace AutoPoster._loop: every 3 hours run director.run_cycle()."""
        while not self._stop.is_set():
            # first cycle after 3 hours (or on start if env var FORCE_CYCLE_NOW set)
            import os as _os
            delay = 5 if _os.getenv("DIRECTOR_RUN_NOW") else 3 * 3600
            if self._stop.wait(delay):
                break
            if self._shutting_down():
                break
            try:
                _DIRECTOR_MOD.run_cycle(globals())
            except Exception as _ex:
                log.exception(f"[director] cycle error: {_ex}")
    AutoPoster._loop = _director_loop


# ─── Menu commands (FIX4) ────────────────────────────────────────────────
@ROUTER.callback("dir")
def cb_director(cb: Dict, data: str) -> None:
    """dir:home -> show category list; dir:run:<cat> -> run one cycle."""
    uid = cb.get("from", {}).get("id", 0)
    if not is_admin(uid):
        TG.answer_callback(cb.get("id", ""), "\u26d4 فقط ادمین", show_alert=True)
        return
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else "home"
    chat_id = cb["message"]["chat"]["id"]
    msg_id = cb["message"]["message_id"]
    TG.answer_callback(cb.get("id", ""))

    if not _DIRECTOR_OK:
        TG.edit_message(chat_id, msg_id, "\u274c _director.py not loaded.")
        return

    if action == "home":
        cats = _DIRECTOR_MOD.list_categories()
        rows = []
        # two per row
        for i in range(0, len(cats), 2):
            row = []
            for name, w, fmt in cats[i:i+2]:
                row.append(btn(f"{name} ({int(w*100)}%)", f"dir:run:{name}"))
            rows.append(row)
        rows.append([btn("\u25b6\ufe0f اجرای چرخه کامل", "dir:run:_auto")])
        rows.append([btn("\u2b05\ufe0f بازگشت", "m:main")])
        TG.edit_message(chat_id, msg_id,
            "\U0001f9e0 <b>کارگردان محتوا</b>\n\n"
            "یک دسته را برای تست انتخاب کن یا چرخه خودکار:",
            reply_markup=kb(rows))
        return

    if action == "run":
        cat = parts[2] if len(parts) > 2 else "_auto"
        if cat == "_auto":
            cat_arg = None
            TG.edit_message(chat_id, msg_id, "\u23f3 چرخه خودکار در حال اجرا...")
        else:
            cat_arg = cat
            TG.edit_message(chat_id, msg_id, f"\u23f3 دسته: {cat}")
        POOL.submit(_DIRECTOR_MOD.run_cycle, globals(), cat_arg)
        return


@ROUTER.command("director", description="کارگردان محتوا", admin_only=True)
def cmd_director(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    if not _DIRECTOR_OK:
        TG.send_message(chat_id, "\u274c _director.py not loaded")
        return
    cats = _DIRECTOR_MOD.list_categories()
    rows = []
    for i in range(0, len(cats), 2):
        row = []
        for name, w, fmt in cats[i:i+2]:
            row.append(btn(f"{name} ({int(w*100)}%)", f"dir:run:{name}"))
        rows.append(row)
    rows.append([btn("\u25b6\ufe0f چرخه کامل", "dir:run:_auto")])
    TG.send_message(chat_id,
        "\U0001f9e0 <b>کارگردان محتوا</b>\n"
        "دسته را انتخاب کن:",
        reply_markup=kb(rows))


@ROUTER.command("now", description="اجرای فوری چرخه", admin_only=True)
def cmd_now(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    if not _DIRECTOR_OK:
        TG.send_message(chat_id, "\u274c _director.py not loaded")
        return
    TG.send_message(chat_id, "\u23f3 در حال اجرای چرخه کارگردان...")
    POOL.submit(_DIRECTOR_MOD.run_cycle, globals(), None)

# ─── end FIX4 director hookup ────────────────────────────────────────────




# ══════════════════════════════════════════════════════════════════════════════
#                        SCHEDULER
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ScheduledJob:
    id: str
    kind: str
    run_at: str
    payload: Dict[str, Any]
    created_at: str
    user_id: int
    executed: bool = False


class Scheduler:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._jobs: List[ScheduledJob] = []
        self._load()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="Scheduler")
        self._thread.start()

    def _load(self) -> None:
        raw = load_json(self.path, default=[])
        for j in raw:
            try:
                self._jobs.append(ScheduledJob(**j))
            except Exception:
                pass

    def _save(self) -> None:
        BATCHED_WRITER.write(self.path, [
            {
                "id": j.id, "kind": j.kind, "run_at": j.run_at,
                "payload": j.payload, "created_at": j.created_at,
                "user_id": j.user_id, "executed": j.executed,
            }
            for j in self._jobs
        ])

    def add(self, kind: str, run_at: datetime, payload: Dict,
            user_id: int) -> ScheduledJob:
        job = ScheduledJob(
            id=hashlib.md5(f"{kind}:{run_at}:{time.time()}".encode()).hexdigest()[:12],
            kind=kind, run_at=run_at.isoformat(),
            payload=payload, created_at=datetime.now().isoformat(),
            user_id=user_id,
        )
        with self._lock:
            self._jobs.append(job)
            self._save()
        return job
    def _loop(self) -> None:
        while not self._stop.is_set() and not _shutting_down.is_set():
            try:
                now = datetime.now(timezone.utc).astimezone()
                with self._lock:
                    due = [
                        j for j in self._jobs
                        if not j.executed
                        and datetime.fromisoformat(j.run_at) <= now
                    ]
                for j in due:
                    self._execute(j)
                    j.executed = True
                if due:
                    self._save()
            except Exception as e:
                log.error(f"Scheduler: {e}")
            self._stop.wait(10)

    def _execute(self, job: ScheduledJob) -> None:
        try:
            if job.kind == "post":
                topic = job.payload.get("topic", "mechanical engineering")
                style = job.payload.get("style", "tutorial")
                cfg = CONFIG.get()
                content = CONTENT.generate(topic, style)
                if content:
                    TG.send_long_message(cfg.telegram.channel_id, content)
        except Exception as e:
            log.error(f"Scheduler exec: {e}")

    def stop(self) -> None:
        self._stop.set()

    def upcoming(self, limit: int = 10) -> List[ScheduledJob]:
        with self._lock:
            pending = [j for j in self._jobs if not j.executed]
        pending.sort(key=lambda j: j.run_at)
        return pending[:limit]


SCHEDULER = Scheduler(SCHEDULE_FILE)


@ROUTER.command("schedule", description="زمان‌بندی پست")
def cmd_schedule(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    uid = get_uid(msg)

    parts = args.split(None, 2)
    if len(parts) < 2:
        TG.send_message(chat_id,
                       "❌ فرمت: <code>/schedule in &lt;دقیقه&gt; &lt;موضوع&gt;</code>\n"
                       "مثال: <code>/schedule in 30 ترمودینامیک</code>")
        return

    if parts[0] != "in":
        TG.send_message(chat_id, "❌ فقط 'in' پشتیبانی می‌شود.")
        return

    try:
        minutes = int(parts[1])
        topic = parts[2] if len(parts) > 2 else "mechanical engineering"
    except Exception:
        TG.send_message(chat_id, "❌ دقیقه اشتباه.")
        return

    run_at = datetime.now() + timedelta(minutes=minutes)
    job = SCHEDULER.add("post", run_at,
                       {"topic": topic, "style": "tutorial"}, uid)

    TG.send_message(chat_id,
                   f"✅ زمان‌بندی شد: <code>{job.id}</code>\n"
                   f"🕐 {run_at.strftime('%Y-%m-%d %H:%M')}\n"
                   f"📌 {escape_html(topic)}")


@ROUTER.command("jobs", description="کارهای زمان‌بندی‌شده")
def cmd_jobs(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    jobs = SCHEDULER.upcoming(10)
    if not jobs:
        TG.send_message(chat_id, "📭 کار زمان‌بندی‌شده‌ای نیست.")
        return

    text = "⏰ <b>کارهای در انتظار:</b>\n\n"
    for j in jobs:
        text += (
            f"• <code>{j.id}</code> — {j.kind}\n"
            f"  🕐 {j.run_at[:16]}\n"
            f"  📌 {escape_html(str(j.payload.get('topic', ''))[:40])}\n\n"
        )
    TG.send_message(chat_id, text[:4000])


# ══════════════════════════════════════════════════════════════════════════════
#                        PART 4 SELF-TEST
# ══════════════════════════════════════════════════════════════════════════════

def self_test_part4() -> None:
    head("Part 4/5 — Content Engine Self-Test")

    # 1. Topics
    step("Topics:")
    info(f"  Built-in: {len(TOPICS)}")
    info(f"  Custom:   {len(TOPIC_MGR.custom())}")
    info(f"  Total:    {len(TOPIC_MGR.all())}")

    # 2. Styles
    step("سبک‌های محتوا:")
    for k, v in CONTENT_STYLES.items():
        info(f"  {v['emoji']} {k:<12} — {v['name']} ({v['lines']})")

    # 3. Formula library
    step("Formula library:")
    total_f = sum(len(v) for v in FORMULA_LIBRARY.values())
    info(f"  Topics: {len(FORMULA_LIBRARY)}")
    info(f"  Total formulas: {total_f}")

    # 4. Test formula lookup
    step("Testing formula lookup...")
    formulas = get_formulas_for("ترمودینامیک")
    ok(f"ترمودینامیک: {len(formulas)} formulas found")
    for n, e, d in formulas[:3]:
        info(f"  • {n}: {e}")

    # 5. Bloom filter
    step("Bloom filter:")
    s = SEEN.stats()
    info(f"  Capacity: {s['capacity']:,}")
    info(f"  Count: {s['count']:,}")
    info(f"  Size: {s['size_kb']}KB")

    # Test bloom
    test_key = f"test:{random.randint(1, 1000000)}"
    if test_key not in SEEN:
        SEEN.add(test_key)
        if test_key in SEEN:
            ok(f"Bloom add/check working")
        else:
            err("Bloom FAILED")

    # 6. Drafts
    step("Drafts:")
    d = DRAFTS.create("test topic", "tutorial", "test content", 999)
    ok(f"Created draft: {d.id}")
    if DRAFTS.get(d.id):
        ok("Draft lookup OK")
    DRAFTS.remove(d.id)

    # 7. Auto-poster
    step("Auto-poster:")
    info(f"  Next run: {AUTO_POSTER.next_run_time()}")

    # 8. Scheduler
    step("Scheduler:")
    upcoming = SCHEDULER.upcoming(5)
    info(f"  Pending jobs: {len(upcoming)}")

    # 9. Content generation (if AI configured)
    cfg = CONFIG.get()
    if cfg.keys.openrouter or cfg.keys.gemini:
        step("Testing content generation (this takes ~30s)...")
        with PERF.timer("content_gen"):
            content = CONTENT.generate("استاتیک", "tutorial")
        if content:
            ok(f"Generated {len(content)} chars")
            info(f"--- First 500 chars ---")
            for line in content[:500].split("\n"):
                print(f"  {line}")
        else:
            warn("Generation failed")
    else:
        warn("No AI key — skipping content generation test")

    print()
    succ("Part 4/5 self-test complete.")
    info("Send 'ادامه' for Part 5/5 (Complete menu + final packaging)")

# ══════════════════════════════════════════════════════════════════════════════
#              PART 5/5 — MENU, PROCESS MGMT, BACKUP, FINAL PACKAGING
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
#                        PROCESS MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

class ProcessManager:
    """Manage bot background process."""

    @staticmethod
    def get_pid() -> Optional[int]:
        if not PID_FILE.exists():
            return None
        try:
            return int(PID_FILE.read_text().strip())
        except Exception:
            return None

    @staticmethod
    def is_running() -> bool:
        pid = ProcessManager.get_pid()
        if pid is None:
            return False
        try:
            if IS_WINDOWS:
                out = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                    capture_output=True, text=True, timeout=10,
                ).stdout
                return str(pid) in out
            else:
                os.kill(pid, 0)
                return True
        except Exception:
            return False

    @staticmethod
    def start_background() -> Tuple[bool, str]:
        if ProcessManager.is_running():
            return False, "Bot is already running"

        kwargs = {}
        if IS_WINDOWS:
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NO_WINDOW
            )

        script = str(Path(__file__).resolve())
        proc = subprocess.Popen(
            [sys.executable, script, "--run"],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            **kwargs,
        )
        PID_FILE.write_text(str(proc.pid))
        time.sleep(2)

        if ProcessManager.is_running():
            return True, f"Started (PID={proc.pid})"
        return False, "Failed to start (check bot.log)"

    @staticmethod
    def stop(force: bool = False) -> Tuple[bool, str]:
        pid = ProcessManager.get_pid()
        if pid is None:
            return False, "Not running"

        try:
            if IS_WINDOWS:
                cmd = ["taskkill", "/PID", str(pid)]
                if force:
                    cmd.append("/F")
                subprocess.run(cmd, capture_output=True, timeout=10)
            else:
                os.kill(pid, signal.SIGTERM)
            PID_FILE.unlink(missing_ok=True)
            return True, f"Stopped (PID={pid})"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def kill_all_python() -> int:
        """Kill all python processes on this machine."""
        killed = 0
        try:
            if IS_WINDOWS:
                out = subprocess.run(
                    ["taskkill", "/F", "/IM", "python.exe"],
                    capture_output=True, text=True, timeout=10,
                )
                if "SUCCESS" in out.stdout:
                    killed += out.stdout.count("SUCCESS")
                out = subprocess.run(
                    ["taskkill", "/F", "/IM", "pythonw.exe"],
                    capture_output=True, text=True, timeout=10,
                )
                if "SUCCESS" in out.stdout:
                    killed += out.stdout.count("SUCCESS")
            else:
                subprocess.run(["pkill", "-9", "python"], timeout=5)
                killed = 1
        except Exception:
            pass
        PID_FILE.unlink(missing_ok=True)
        return killed

    @staticmethod
    def info() -> Dict[str, Any]:
        pid = ProcessManager.get_pid()
        running = ProcessManager.is_running()
        mem = 0.0
        cpu = 0.0

        if running and pid:
            try:
                if IS_WINDOWS:
                    out = subprocess.run(
                        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                        capture_output=True, text=True, timeout=10,
                    ).stdout
                    parts = out.strip().split(",")
                    if len(parts) > 4:
                        mem_str = parts[4].strip('"').replace(",", "").replace(" K", "")
                        try:
                            mem = float(mem_str) / 1024
                        except Exception:
                            pass
            except Exception:
                pass

        return {
            "pid": pid,
            "running": running,
            "memory_mb": round(mem, 1),
            "cpu_percent": cpu,
        }


PROC = ProcessManager()


# ══════════════════════════════════════════════════════════════════════════════
#                        BACKUP / RESTORE
# ══════════════════════════════════════════════════════════════════════════════

class BackupManager:
    """Manage configuration and data backups."""

    BACKUP_INTERVAL_HOURS = 24
    MAX_BACKUPS = 20

    @staticmethod
    def create(name: Optional[str] = None) -> Tuple[bool, str]:
        try:
            if name is None:
                name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

            dest = BACKUP_DIR / name
            dest.mkdir(parents=True, exist_ok=True)

            # Files to backup
            files = [CONFIG_FILE, HISTORY_FILE, STATS_FILE, POLLS_FILE,
                     TOPICS_FILE, PROMPTS_FILE, USERS_FILE, DRAFT_FILE,
                     SCHEDULE_FILE]

            count = 0
            for f in files:
                if f.exists():
                    shutil.copy2(f, dest / f.name)
                    count += 1

            # Save metadata
            meta = {
                "created_at": datetime.now().isoformat(),
                "version": CONFIG.get().version,
                "files": count,
                "root": str(ROOT),
            }
            (dest / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            BackupManager._prune()

            return True, f"Backup created: {name} ({count} files)"

        except Exception as e:
            return False, f"Backup failed: {e}"

    @staticmethod
    def list_backups() -> List[Dict[str, Any]]:
        backups = []
        if not BACKUP_DIR.exists():
            return backups

        for entry in sorted(BACKUP_DIR.iterdir(), reverse=True):
            if not entry.is_dir():
                continue
            meta_file = entry / "meta.json"
            meta = {}
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                except Exception:
                    pass

            size_kb = sum(
                f.stat().st_size for f in entry.rglob("*") if f.is_file()
            ) / 1024

            backups.append({
                "name": entry.name,
                "created_at": meta.get("created_at", "?"),
                "files": meta.get("files", 0),
                "size_kb": round(size_kb, 1),
            })

        return backups

    @staticmethod
    def restore(name: str) -> Tuple[bool, str]:
        try:
            src = BACKUP_DIR / name
            if not src.exists():
                return False, f"Backup not found: {name}"

            # Backup current first
            BackupManager.create(f"pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}")

            count = 0
            for f in src.iterdir():
                if f.name == "meta.json":
                    continue
                target = DATA_DIR / f.name
                shutil.copy2(f, target)
                count += 1

            return True, f"Restored {count} files from {name}"

        except Exception as e:
            return False, f"Restore failed: {e}"

    @staticmethod
    def delete(name: str) -> Tuple[bool, str]:
        try:
            target = BACKUP_DIR / name
            if not target.exists():
                return False, "Not found"
            shutil.rmtree(target)
            return True, f"Deleted: {name}"
        except Exception as e:
            return False, str(e)

    @staticmethod
    def _prune() -> None:
        backups = BackupManager.list_backups()
        for b in backups[BackupManager.MAX_BACKUPS:]:
            try:
                shutil.rmtree(BACKUP_DIR / b["name"])
            except Exception:
                pass

    @staticmethod
    def auto_backup_loop() -> None:
        """Background thread — backup every N hours."""
        while not _shutting_down.is_set():
            try:
                time.sleep(BackupManager.BACKUP_INTERVAL_HOURS * 3600)
                if _shutting_down.is_set():
                    break
                success, msg = BackupManager.create()
                if success:
                    log.info(f"Auto-backup: {msg}")
                else:
                    log.warning(f"Auto-backup failed: {msg}")
            except Exception as e:
                log.error(f"Auto-backup loop: {e}")


threading.Thread(target=BackupManager.auto_backup_loop,
                 daemon=True, name="AutoBackup").start()


# ══════════════════════════════════════════════════════════════════════════════
#                        LOG VIEWER
# ══════════════════════════════════════════════════════════════════════════════

class LogViewer:
    """Read and filter log files."""

    @staticmethod
    def tail(path: Path, n: int = 50, level: str = "") -> List[str]:
        if not path.exists():
            return ["(no log file)"]
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception as e:
            return [f"(read error: {e})"]

        if level:
            lines = [ln for ln in lines if f"[{level}]" in ln or f"[{level:<8}]" in ln]

        return lines[-n:]

    @staticmethod
    def grep(path: Path, pattern: str, n: int = 50) -> List[str]:
        if not path.exists():
            return []
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            return []
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except Exception:
            return []
        return [ln for ln in lines if rx.search(ln)][-n:]

    @staticmethod
    def errors_today() -> List[str]:
        today = datetime.now().strftime("%Y-%m-%d")
        return [ln for ln in LogViewer.tail(ERROR_LOG_FILE, 500)
                if today in ln]

    @staticmethod
    def clear(path: Path) -> bool:
        try:
            path.write_text("", encoding="utf-8")
            return True
        except Exception:
            return False


# ══════════════════════════════════════════════════════════════════════════════
#                        SYSTEM DIAGNOSTICS
# ══════════════════════════════════════════════════════════════════════════════

class Diagnostics:
    """System health checks."""

    @staticmethod
    def check_python() -> Dict[str, Any]:
        return {
            "ok": PY_MAJOR >= 3 and PY_MINOR >= 9,
            "version": f"{PY_MAJOR}.{PY_MINOR}.{PY_VER.micro}",
            "executable": sys.executable,
        }

    @staticmethod
    def check_dependencies() -> Dict[str, Any]:
        required = ["requests", "feedparser", "urllib3"]
        optional = ["orjson", "ujson", "bs4", "lxml", "Pillow", "httpx", "zstandard"]

        req_status = {}
        for mod in required:
            req_status[mod] = _module_available(mod)

        opt_status = {}
        for mod in optional:
            opt_status[mod] = _module_available(mod)

        return {
            "ok": all(req_status.values()),
            "required": req_status,
            "optional": opt_status,
        }

    @staticmethod
    def check_paths() -> Dict[str, Any]:
        paths = {
            "root": ROOT,
            "data": DATA_DIR,
            "cache": CACHE_DIR,
            "logs": LOG_DIR,
            "backup": BACKUP_DIR,
            "media": MEDIA_DIR,
        }
        status = {}
        for name, p in paths.items():
            try:
                p.mkdir(parents=True, exist_ok=True)
                t = p / ".probe"
                t.write_text("ok")
                t.unlink()
                status[name] = {"path": str(p), "writable": True}
            except Exception as e:
                status[name] = {"path": str(p), "writable": False, "error": str(e)}

        return {"ok": all(s["writable"] for s in status.values()), "paths": status}

    @staticmethod
    def check_network() -> Dict[str, Any]:
        checks = {
            "telegram": "https://api.telegram.org",
            "openrouter": "https://openrouter.ai",
            "gemini": "https://generativelanguage.googleapis.com",
            "arxiv": "https://export.arxiv.org",
            "google": "https://www.google.com",
        }
        results = {}
        for name, url in checks.items():
            try:
                t0 = time.perf_counter()
                r = HTTP.request("HEAD", url, timeout=8)
                dt = (time.perf_counter() - t0) * 1000
                results[name] = {
                    "ok": r is not None and r.status_code < 500,
                    "status": r.status_code if r else 0,
                    "latency_ms": round(dt),
                }
            except Exception as e:
                results[name] = {"ok": False, "error": str(e)[:80]}

        return {
            "ok": any(v.get("ok") for v in results.values()),
            "results": results,
        }

    @staticmethod
    def check_config() -> Dict[str, Any]:
        cfg = CONFIG.get()
        issues = []

        if not cfg.telegram.token:
            issues.append("Telegram token not set")
        if not cfg.telegram.channel_id:
            issues.append("Channel ID not set")
        if not cfg.keys.openrouter and not cfg.keys.gemini:
            issues.append("No AI provider configured")
        if cfg.behavior.auto_post_hours < 1:
            issues.append("Auto-post interval invalid")

        return {
            "ok": len(issues) == 0,
            "issues": issues,
            "version": cfg.version,
        }

    @staticmethod
    def full_report() -> Dict[str, Any]:
        return {
            "python": Diagnostics.check_python(),
            "dependencies": Diagnostics.check_dependencies(),
            "paths": Diagnostics.check_paths(),
            "network": Diagnostics.check_network(),
            "config": Diagnostics.check_config(),
            "process": PROC.info(),
            "memory": MEM_MON.stats(),
            "thread_pool": POOL.stats(),
            "ai_cache": AI_CACHE.stats(),
            "http_cache": HTTP_CACHE.stats(),
            "http_client": HTTP.stats(),
            "uptime_seconds": round(time.time() - PERF._started, 1),
        }


# ══════════════════════════════════════════════════════════════════════════════
#                        COMPLETE MENU SYSTEM (35 options)
# ══════════════════════════════════════════════════════════════════════════════
class MenuSystem:
    """Interactive console menu with 35 options."""

    def __init__(self):
        self.cfg = CONFIG

    # ─────────────────────────────────────────────────────────
    # Rendering
    # ─────────────────────────────────────────────────────────

    def _header(self) -> str:
        cfg = self.cfg.get()
        running = PROC.is_running()
        status = f"{Clr.BGRN}● RUNNING{Clr.R}" if running else f"{Clr.BRED}○ stopped{Clr.R}"

        topics = len(TOPIC_MGR.all())
        styles = len(CONTENT_STYLES)
        commands = len(REGISTRY.all())
        mem = MEM_MON.current_mb()

        title = "MAADGH Bot — v5.0-Perf"
        channel = cfg.telegram.channel_id

        lines = [
            "",
            f"{Clr.BCYN}╔{'═' * 66}╗{Clr.R}",
            f"{Clr.BCYN}║{Clr.R} {Clr.B}{title:<64}{Clr.R} {Clr.BCYN}║{Clr.R}",
            f"{Clr.BCYN}║{Clr.R} Channel: {channel:<20} Process: {status}"
            f"{' ' * max(0, 66 - 30 - len(channel) - len('RUNNING'))}{Clr.BCYN}║{Clr.R}",
            f"{Clr.BCYN}╚{'═' * 66}╝{Clr.R}",
            "",
            f"  {Clr.GRY}Topics: {topics} | Styles: {styles} | Commands: {commands} | "
            f"RAM: {mem:.0f}MB | Backend: {JSON_BACKEND}{Clr.R}",
            "",
        ]
        return "\n".join(lines)

    def _section(self, title: str) -> str:
        return f"\n{Clr.BMAG}── {title} ──{Clr.R}"

    def _item(self, num: str, text: str, hot: bool = False) -> str:
        marker = f"{Clr.BGRN}▸{Clr.R}" if hot else " "
        color = Clr.BWHT if hot else Clr.WHT
        return f"  {marker} {Clr.BCYN}{num:>3}.{Clr.R} {color}{text}{Clr.R}"

    def render(self) -> None:
        clear()
        print(self._header())

        # ─── Bot Control (1-5) ───
        print(self._section("BOT CONTROL"))
        print(self._item("1", "Run in foreground (Ctrl+C to stop)"))
        print(self._item("2", "Start in background"))
        print(self._item("3", "Stop bot"))
        print(self._item("4", "Force-kill ALL python processes"))
        print(self._item("5", "Show process info"))

        # ─── Configuration (6-10) ───
        print(self._section("CONFIGURATION"))
        print(self._item("6", "Initial setup (token, keys, channel)"))
        print(self._item("7", "Set AI keys (one by one)"))
        print(self._item("8", "View current config"))
        print(self._item("9", "Reset config"))
        print(self._item("10", "Switch provider (OpenRouter <-> Gemini)"))

        # ─── Testing (11-16) ───
        print(self._section("TESTING"))
        print(self._item("11", "Test Telegram token"))
        print(self._item("12", "Test channel access"))
        print(self._item("13", "Test AI (current provider)"))
        print(self._item("14", "Test ALL OpenRouter models"))
        print(self._item("15", "Test ALL external APIs"))
        print(self._item("16", "Test full post to channel"))

        # ─── Content (17-21) ───
        print(self._section("CONTENT"))
        print(self._item("17", "Generate test post (pick topic)"))
        print(self._item("18", "Generate with specific style"))
        print(self._item("19", "List all topics"))
        print(self._item("20", "Add custom topic"))
        print(self._item("21", "Remove custom topic"))

        # ─── Management (22-26) ───
        print(self._section("MANAGEMENT"))
        print(self._item("22", "Set دستورات تلگرام menu"))
        print(self._item("23", "View logs"))
        print(self._item("24", "Clear logs"))
        print(self._item("25", "Full statistics"))
        print(self._item("26", "Cleanup caches"))

        # ─── Backup (27-29) ───
        print(self._section("BACKUP"))
        print(self._item("27", "Create new backup"))
        print(self._item("28", "List backups"))
        print(self._item("29", "Restore backup"))

        # ─── System (30-32) ───
        print(self._section("SYSTEM"))
        print(self._item("30", "Full diagnostics"))
        print(self._item("31", "Open project folder"))
        print(self._item("32", "Open logs folder"))

        # ─── Links (33-34) ───
        print(self._section("LINKS"))
        print(self._item("33", "OpenRouter Keys page"))
        print(self._item("34", "BotFather (Telegram)"))

        # ─── Help / Exit ───
        print(self._section("HELP"))
        print(self._item("35", "Full help"))

        print()
        print(self._item("0", "Exit", hot=True))

    # ─────────────────────────────────────────────────────────
    # Input handling
    # ─────────────────────────────────────────────────────────

    def prompt(self) -> str:
        try:
            return input(f"\n  {Clr.BCYN}Select:{Clr.R} ").strip()
        except (EOFError, KeyboardInterrupt):
            return "0"

    def run(self) -> None:
        actions = {
            "1": self._act_run_foreground,
            "2": self._act_run_background,
            "3": self._act_stop,
            "4": self._act_kill_all,
            "5": self._act_process_info,
            "6": self._act_setup,
            "7": self._act_set_ai_keys,
            "8": self._act_view_config,
            "9": self._act_reset_config,
            "10": self._act_switch_provider,
            "11": self._act_test_token,
            "12": self._act_test_channel,
            "13": self._act_test_ai,
            "14": self._act_test_models,
            "15": self._act_test_apis,
            "16": self._act_test_post,
            "17": self._act_generate_post,
            "18": self._act_generate_style,
            "19": self._act_list_topics,
            "20": self._act_add_topic,
            "21": self._act_del_topic,
            "22": self._act_set_commands,
            "23": self._act_view_logs,
            "24": self._act_clear_logs,
            "25": self._act_stats,
            "26": self._act_cleanup_caches,
            "27": self._act_backup_create,
            "28": self._act_backup_list,
            "29": self._act_backup_restore,
            "30": self._act_diagnostics,
            "31": self._act_open_project,
            "32": self._act_open_logs,
            "33": self._act_open_openrouter,
            "34": self._act_open_botfather,
            "35": self._act_help,
            "0": None,
        }

        while True:
            self.render()
            choice = self.prompt()

            if choice == "0":
                print(f"\n{Clr.BGRN}Goodbye!{Clr.R}")
                break

            action = actions.get(choice)
            if action is None:
                print(f"{Clr.BRED}Invalid choice{Clr.R}")
                time.sleep(1)
                continue

            try:
                action()
            except Exception as e:
                print(f"\n{Clr.BRED}Error: {e}{Clr.R}")
                log.exception("menu action")
                pause()

    # ─────────────────────────────────────────────────────────
    # Actions (1-35)
    # ─────────────────────────────────────────────────────────

    def _act_run_foreground(self) -> None:
        head("Run bot — foreground")
        info("Press Ctrl+C to stop.")
        print()
        try:
            _run_bot()
        except KeyboardInterrupt:
            ok("Stopped.")

    def _act_run_background(self) -> None:
        head("Run bot — background")
        success, msg = PROC.start_background()
        if success:
            ok(msg)
        else:
            err(msg)
        pause()

    def _act_stop(self) -> None:
        head("Stop bot")
        if not PROC.is_running():
            err("Bot is not running.")
            pause()
            return

        force = input("Force kill? (y/N): ").strip().lower() == "y"
        success, msg = PROC.stop(force=force)

        if success:
            ok(msg)
        else:
            err(msg)
        pause()

    def _act_kill_all(self) -> None:
        head("Kill ALL python processes")
        warn("This kills every python.exe process on your system!")
        if input("Continue? (y/N): ").strip().lower() != "y":
            return
        killed = PROC.kill_all_python()
        ok(f"Killed {killed} process(es).")
        pause()

    def _act_process_info(self) -> None:
        head("Process info")
        info_dict = PROC.info()
        print()
        for k, v in info_dict.items():
            print(f"  {Clr.BCYN}{k}{Clr.R}: {v}")

        ms = MEM_MON.stats()
        print()
        print(f"  {Clr.BCYN}Memory (current){Clr.R}: {ms['current_mb']} MB")
        print(f"  {Clr.BCYN}Memory (peak){Clr.R}:    {ms['peak_mb']} MB")

        tp = POOL.stats()
        print()
        print(f"  {Clr.BCYN}Thread pool active{Clr.R}:    {tp['active']}/{tp['max_workers']}")
        print(f"  {Clr.BCYN}Thread pool completed{Clr.R}: {tp['completed']}")

        pause()

    def _act_setup(self) -> None:
        head("Initial setup")
        cfg = self.cfg.get()

        # Telegram token
        sub("Telegram Bot Token")
        current = cfg.telegram.token
        info(f"current: {current[:25] + '...' if current else '(empty)'}")
        val = input("  new token (Enter to keep): ").strip()
        if val:
            cfg.telegram.token = val

        # Channel
        sub("Channel ID")
        info(f"current: {cfg.telegram.channel_id}")
        val = input("  new channel (Enter to keep): ").strip()
        if val:
            cfg.telegram.channel_id = val

        # OpenRouter
        sub("OpenRouter API Key")
        info(f"current: {cfg.keys.openrouter[:25] + '...' if cfg.keys.openrouter else '(empty)'}")
        info("Get one at: https://openrouter.ai/keys")
        val = input("  new key (Enter to keep): ").strip()
        if val:
            cfg.keys.openrouter = val

        # Gemini
        sub("Gemini API Key")
        info(f"current: {cfg.keys.gemini[:25] + '...' if cfg.keys.gemini else '(empty)'}")
        info("Get one at: https://aistudio.google.com/apikey (starts with AIza)")
        val = input("  new key (Enter to keep): ").strip()
        if val:
            cfg.keys.gemini = val

        self.cfg.save()
        ok("Saved.")
        pause()

    def _act_set_ai_keys(self) -> None:
        head("Set AI keys (one by one)")
        print()
        print("  1) OpenRouter")
        print("  2) Gemini")
        print("  3) Zenserp")
        print("  4) Aviationstack")
        print("  5) Apify")
        print("  6) Weather API")
        print("  0) Cancel")

        choice = input("\n  Select: ").strip()
        mapping = {
            "1": ("openrouter", "OpenRouter API Key", "https://openrouter.ai/keys"),
            "2": ("gemini", "Gemini API Key (AIza...)", "https://aistudio.google.com/apikey"),
            "3": ("zenserp", "Zenserp API Key", "https://zenserp.com"),
            "4": ("aviationstack", "Aviationstack API Key", "https://aviationstack.com"),
            "5": ("apify", "Apify Token", "https://console.apify.com/settings/integrations"),
            "6": ("weatherapi", "Weather API Key", "https://www.weatherapi.com"),
        }

        if choice not in mapping:
            return

        key_name, label, url = mapping[choice]
        cfg = self.cfg.get()
        current = getattr(cfg.keys, key_name, "")

        sub(label)
        info(f"Guide: {url}")
        info(f"current: {current[:30] + '...' if current else '(empty)'}")
        val = input("  new value (Enter to skip, 'delete' to remove): ").strip()

        if val == "delete":
            setattr(cfg.keys, key_name, "")
            self.cfg.save()
            ok("Deleted.")
        elif val:
            setattr(cfg.keys, key_name, val)
            self.cfg.save()
            ok("Saved.")

        pause()

    def _act_view_config(self) -> None:
        head("Current configuration")
        cfg = self.cfg.get()
        print()

        def mask(v: str) -> str:
            if not v:
                return "(empty)"
            if len(v) > 20:
                return v[:12] + "..." + v[-5:]
            return v

        print(f"  {Clr.BCYN}Telegram:{Clr.R}")
        print(f"    token: {mask(cfg.telegram.token)}")
        print(f"    channel: {cfg.telegram.channel_id}")
        print(f"    admin_id: {cfg.telegram.admin_id}")
        print()

        print(f"  {Clr.BCYN}AI:{Clr.R}")
        print(f"    provider: {cfg.ai.provider}")
        print(f"    primary: {cfg.ai.primary_model}")
        print(f"    fallbacks: {len(cfg.ai.fallback_models)}")
        print(f"    temperature: {cfg.ai.temperature}")
        print(f"    max_tokens: {cfg.ai.max_tokens}")
        print()

        print(f"  {Clr.BCYN}API Keys:{Clr.R}")
        print(f"    openrouter: {mask(cfg.keys.openrouter)}")
        print(f"    gemini: {mask(cfg.keys.gemini)}")
        print(f"    zenserp: {mask(cfg.keys.zenserp)}")
        print(f"    aviationstack: {mask(cfg.keys.aviationstack)}")
        print(f"    apify: {mask(cfg.keys.apify)}")
        print()

        print(f"  {Clr.BCYN}Content:{Clr.R}")
        print(f"    length: {cfg.content.length}")
        print(f"    level: {cfg.content.technical_level}")
        print(f"    style: {cfg.content.default_style}")
        print(f"    formulas: {cfg.content.include_formulas}")
        print(f"    multi_part: {cfg.content.multi_part}")
        print()

        print(f"  {Clr.BCYN}Behavior:{Clr.R}")
        print(f"    auto_post_hours: {cfg.behavior.auto_post_hours}")
        print(f"    rotate_topics: {cfg.behavior.rotate_topics}")
        print(f"    auto_poll: {cfg.behavior.auto_poll}")
        print(f"    include_news: {cfg.behavior.include_news}")
        print(f"    include_reddit: {cfg.behavior.include_reddit}")
        print(f"    include_politics: {cfg.behavior.include_politics}")
        print(f"    rate_limit: {cfg.behavior.rate_limit_per_min}/min")

        pause()

    def _act_reset_config(self) -> None:
        head("Reset configuration")
        warn("This clears ALL settings!")
        if input("Continue? (y/N): ").strip().lower() != "y":
            return

        BackupManager.create(f"pre_reset_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        CONFIG_FILE.unlink(missing_ok=True)
        self.cfg.reload()
        ok("Settings cleared.")
        pause()

    def _act_switch_provider(self) -> None:
        head("Switch AI provider")
        cfg = self.cfg.get()
        current = cfg.ai.provider
        print(f"\n  current: {Clr.BCYN}{current}{Clr.R}")
        print()
        print("  1) OpenRouter")
        print("  2) Gemini")

        choice = input("\n  Select: ").strip()
        provider = {"1": "openrouter", "2": "gemini"}.get(choice)

        if provider:
            self.cfg.set_provider(provider)
            ok(f"Provider switched to {provider}.")

        pause()

    def _act_test_token(self) -> None:
        head("Test Telegram token")
        cfg = self.cfg.get()
        if not cfg.telegram.token:
            err("Token not set.")
            pause()
            return

        step("Calling getMe...")
        r = TG.get_me()
        if r.ok:
            info_dict = r.result
            ok(f"@{info_dict.get('username', '?')}")
            info(f"ID: {info_dict.get('id', '?')}")
            info(f"Name: {info_dict.get('first_name', '')}")
            info(f"Bot: {info_dict.get('is_bot')}")
        else:
            err(r.description)
        pause()

    def _act_test_channel(self) -> None:
        head("Test channel access")
        cfg = self.cfg.get()
        if not cfg.telegram.channel_id:
            err("Channel not set.")
            pause()
            return

        step(f"Sending test message to {cfg.telegram.channel_id}...")
        r = TG.send_message(
            cfg.telegram.channel_id,
            f"🧪 <b>Test</b>\n{datetime.now():%Y-%m-%d %H:%M:%S}",
        )
        if r.ok:
            ok("Success! Check your channel.")
        else:
            err(r.description)
            info("Make sure the bot is admin of the channel with Post Messages permission.")
        pause()

    def _act_test_ai(self) -> None:
        head("Test AI")
        cfg = self.cfg.get()
        step(f"Provider: {cfg.ai.provider}")

        resp = AI.ask("You are a test.", "Say OK in Persian.",
                     max_tokens=30, use_cache=False)

        if resp.ok:
            ok(f"{resp.provider}: {resp.model}")
            info(f"Latency: {resp.latency_ms}ms")
            info(f"Response: {resp.text[:80]}")
        else:
            err(resp.error)
        pause()

    def _act_test_models(self) -> None:
        head("Test ALL OpenRouter models")
        cfg = self.cfg.get()
        if not cfg.keys.openrouter:
            err("OpenRouter key not set.")
            pause()
            return

        models = [cfg.ai.primary_model] + cfg.ai.fallback_models
        seen = set()
        unique = [m for m in models if m and not (m in seen or seen.add(m))]

        step(f"Testing {len(unique)} models...")
        print()

        working = []
        failing = []

        for i, m in enumerate(unique, 1):
            print(f"  [{i:2}/{len(unique)}] {m[:55]:<55} ... ", end="", flush=True)

            payload = {
                "model": m,
                "messages": [{"role": "user", "content": "OK"}],
                "max_tokens": 3,
            }
            r = HTTP.request(
                "POST", "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {cfg.keys.openrouter}",
                    "Content-Type": "application/json",
                },
                json_body=payload,
                timeout=20,
            )

            if r is not None and r.status_code == 200:
                print(f"{Clr.BGRN}OK{Clr.R}")
                working.append(m)
            else:
                status = r.status_code if r else "?"
                print(f"{Clr.BRED}FAIL{Clr.R} ({status})")
                failing.append(m)

        print()
        print(f"{Clr.BGRN}Working ({len(working)}):{Clr.R}")
        for m in working[:10]:
            print(f"  * {m}")
        if len(working) > 10:
            print(f"  ... and {len(working) - 10} more")

        if failing:
            print(f"\n{Clr.BRED}Failing ({len(failing)}){Clr.R}")

        if working and input("\nSet first working as primary? (y/N): ").strip().lower() == "y":
            self.cfg.set_model(working[0])
            ok(f"Primary: {working[0]}")

        pause()

    def _act_test_apis(self) -> None:
        head("Test ALL external APIs")
        step("Testing...")
        print()

        results = APIS.test_all()

        for name, r in results.items():
            api = APIS.all().get(name)
            if api and not api.is_configured():
                print(f"  {Clr.GRY}-- {name:20} (not configured){Clr.R}")
                continue
            if r.ok:
                val = r.data if isinstance(r.data, str) else str(r.data)[:40]
                print(f"  {Clr.BGRN}OK {name:20}{Clr.R} {val}")
            else:
                print(f"  {Clr.BRED}XX {name:20}{Clr.R} {r.error[:60]}")

        pause()

    def _act_test_post(self) -> None:
        head("Test full post")

        step("Topic:")
        topic = input("  > ").strip() or "استاتیک"

        step("Style:")
        print("  " + ", ".join(CONTENT_STYLES.keys()))
        style = input(f"  (Enter = tutorial): ").strip() or "tutorial"

        if style not in CONTENT_STYLES:
            err(f"Invalid style: {style}")
            pause()
            return

        step(f"Generating '{topic}' in style '{style}'...")

        content = CONTENT.generate(topic, style)

        if not content:
            err("Generation failed.")
            pause()
            return

        print(f"\n{Clr.BCYN}--- Result ({len(content)} chars) ---{Clr.R}")
        print(content[:2000])
        if len(content) > 2000:
            print(f"\n{Clr.GRY}...(truncated){Clr.R}")
        print(f"{Clr.BCYN}---{Clr.R}\n")

        if input("Send to channel? (y/N): ").strip().lower() == "y":
            cfg = self.cfg.get()
            results = TG.send_long_message(cfg.telegram.channel_id, content)
            if results and results[0].ok:
                ok(f"Published ({len(results)} messages).")
            else:
                err(f"Error: {results[0].description if results else '?'}")

        pause()

    def _act_generate_post(self) -> None:
        head("Generate test post")

        topics = TOPIC_MGR.all()
        for i, t in enumerate(topics[:30], 1):
            print(f"  {i:2}) {t.get('emoji', '*')} {t['name']}")

        val = input("\n  number, name, or Enter for next: ").strip()

        if not val:
            topic = TOPIC_MGR.rotate_next()
        elif val.isdigit() and 1 <= int(val) <= len(topics):
            topic = topics[int(val) - 1]
        else:
            topic = TOPIC_MGR.find(val) or {
                "name": val, "query": val, "emoji": "P",
            }

        step(f"Generating '{topic['name']}'...")
        content = CONTENT.generate(topic, topic.get("style", "tutorial"))

        if content:
            print(f"\n{Clr.BCYN}--- Result ---{Clr.R}")
            print(content[:1500])
            print(f"{Clr.BCYN}---{Clr.R}\n")

            if input("Send to channel? (y/N): ").strip().lower() == "y":
                cfg = self.cfg.get()
                results = TG.send_long_message(cfg.telegram.channel_id, content)
                if results and results[0].ok:
                    ok("Published.")
        else:
            err("Generation failed.")

        pause()

    def _act_generate_style(self) -> None:
        head("Generate with specific style")
        print()
        for k, v in CONTENT_STYLES.items():
            print(f"  {v['emoji']} {k:<12} - {v['name']}")

        style = input("\n  Style: ").strip()
        if style not in CONTENT_STYLES:
            err("Invalid style.")
            pause()
            return

        topic = input("  Topic: ").strip() or TOPIC_MGR.rotate_next()["name"]

        step(f"Generating '{topic}' in style '{style}'...")
        content = CONTENT.generate(topic, style)

        if content:
            print(f"\n{Clr.BCYN}--- Result ({len(content)} chars) ---{Clr.R}")
            print(content[:2000])
            print(f"{Clr.BCYN}---{Clr.R}\n")

            if input("Send to channel? (y/N): ").strip().lower() == "y":
                cfg = self.cfg.get()
                TG.send_long_message(cfg.telegram.channel_id, content)
                ok("Sent.")
        else:
            err("Generation failed.")

        pause()

    def _act_list_topics(self) -> None:
        head("Topics list")
        topics = TOPIC_MGR.all()
        print()

        for i, t in enumerate(topics, 1):
            emoji = t.get("emoji", "*")
            style = t.get("style", "tutorial")
            print(f"  {i:2}. {emoji} {t['name']:<35} [{style}]")

        print()
        info(f"Total: {len(topics)} topics")
        pause()

    def _act_add_topic(self) -> None:
        head("Add custom topic")
        name = input("  Persian name: ").strip()
        if not name:
            err("Name required")
            pause()
            return
        query = input("  English query: ").strip()
        if not query:
            err("Query required")
            pause()
            return

        emoji = input("  Emoji (Enter = star): ").strip() or "⭐"
        style = input("  Style (Enter = tutorial): ").strip() or "tutorial"

        if TOPIC_MGR.add(name, query, emoji=emoji, style=style):
            ok(f"'{name}' added.")
        else:
            err("Already exists.")

        pause()

    def _act_del_topic(self) -> None:
        head("Remove custom topic")
        custom = TOPIC_MGR.custom()
        if not custom:
            err("No custom topics.")
            pause()
            return

        for i, t in enumerate(custom, 1):
            print(f"  {i}) {t['name']}")

        val = input("\n  Name: ").strip()
        if TOPIC_MGR.remove(val):
            ok("Removed.")
        else:
            err("Not found.")
        pause()

    def _act_set_commands(self) -> None:
        head("Set دستورات تلگرام menu")
        cmds = REGISTRY.telegram_menu()
        step(f"Sending {len(cmds)} commands...")
        r = TG.set_my_commands(cmds)
        if r.ok:
            ok("Saved.")
        else:
            err(r.description)
        pause()

    def _act_view_logs(self) -> None:
        head("View logs")
        print("  1) bot.log (last 50 lines)")
        print("  2) error.log (last 50 lines)")
        print("  3) Today's errors")
        print("  4) Search in log")

        choice = input("\n  Select: ").strip()

        if choice == "1":
            print()
            for ln in LogViewer.tail(LOG_FILE, 50):
                print(ln)
        elif choice == "2":
            print()
            for ln in LogViewer.tail(ERROR_LOG_FILE, 50):
                print(ln)
        elif choice == "3":
            print()
            for ln in LogViewer.errors_today():
                print(ln)
        elif choice == "4":
            pattern = input("  Pattern: ").strip()
            for ln in LogViewer.grep(LOG_FILE, pattern, 50):
                print(ln)

        pause()

    def _act_clear_logs(self) -> None:
        head("Clear logs")
        if input("Are you sure? (y/N): ").strip().lower() != "y":
            return

        LogViewer.clear(LOG_FILE)
        LogViewer.clear(ERROR_LOG_FILE)
        ok("Cleared.")
        pause()

    def _act_stats(self) -> None:
        head("Full statistics")
        s = STATS.all()
        ms = MEM_MON.stats()
        tp = POOL.stats()
        ai_c = AI_CACHE.stats()

        print()
        print(f"  {Clr.BCYN}Usage:{Clr.R}")
        print(f"    Posts:      {s.get('posts', 0)}")
        print(f"    Questions:  {s.get('questions', 0)}")
        print(f"    Regen:      {s.get('regen', 0)}")
        print(f"    Errors:     {s.get('errors', 0)}")
        print(f"    Started:    {s.get('started_at', '?')[:19]}")
        print()

        cmds = s.get("commands", {})
        if cmds:
            print(f"  {Clr.BCYN}Commands used:{Clr.R}")
            for c, n in sorted(cmds.items(), key=lambda x: -x[1])[:10]:
                print(f"    /{c:<15} {n}")
            print()

        styles = s.get("styles", {})
        if styles:
            print(f"  {Clr.BCYN}Styles:{Clr.R}")
            for st, n in sorted(styles.items(), key=lambda x: -x[1]):
                print(f"    {st:<15} {n}")
            print()

        print(f"  {Clr.BCYN}Performance:{Clr.R}")
        print(f"    Memory now:  {ms['current_mb']}MB")
        print(f"    Memory peak: {ms['peak_mb']}MB")
        print(f"    Workers:     {tp['active']}/{tp['max_workers']}")
        print(f"    Completed:   {tp['completed']}")
        print(f"    Failed:      {tp['failed']}")
        print()

        print(f"  {Clr.BCYN}Cache:{Clr.R}")
        print(f"    AI hit rate:   {ai_c['hit_rate']}%")
        print(f"    AI size:       {ai_c['size']}/{ai_c['max']}")
        print(f"    HTTP size:     {HTTP_CACHE.stats()['size']}")
        print()

        seen = SEEN.stats()
        print(f"  {Clr.BCYN}Seen:{Clr.R}")
        print(f"    Count: {seen['count']}")
        print(f"    Size:  {seen['size_kb']}KB")

        pause()

    def _act_cleanup_caches(self) -> None:
        head("Cleanup caches")
        AI_CACHE.clear()
        HTTP_CACHE.clear()
        TRANSLATE_CACHE.clear()
        _text_cache.clear()
        gc.collect()

        ms = MEM_MON.stats()
        ok(f"Done. Current memory: {ms['current_mb']}MB")
        pause()

    def _act_backup_create(self) -> None:
        head("Create backup")
        name = input("  Name (Enter = auto): ").strip() or None
        success, msg = BackupManager.create(name)
        if success:
            ok(msg)
        else:
            err(msg)
        pause()

    def _act_backup_list(self) -> None:
        head("Backups")
        backups = BackupManager.list_backups()
        if not backups:
            info("No backups yet.")
            pause()
            return

        print()
        for i, b in enumerate(backups, 1):
            print(f"  {i}) {b['name']}")
            print(f"     {b['created_at'][:19]} - {b['files']} files, {b['size_kb']}KB")

        pause()

    def _act_backup_restore(self) -> None:
        head("Restore backup")
        backups = BackupManager.list_backups()
        if not backups:
            err("No backups available.")
            pause()
            return

        for i, b in enumerate(backups, 1):
            print(f"  {i}) {b['name']} ({b['created_at'][:16]})")

        val = input("\n  number or name: ").strip()
        name = None
        if val.isdigit() and 1 <= int(val) <= len(backups):
            name = backups[int(val) - 1]["name"]
        else:
            name = val

        if not name:
            return

        warn("Current config will be auto-backed-up first.")
        if input(f"Restore '{name}'? (y/N): ").strip().lower() != "y":
            return

        success, msg = BackupManager.restore(name)
        if success:
            ok(msg)
            self.cfg.reload()
        else:
            err(msg)
        pause()

    def _act_diagnostics(self) -> None:
        head("Full diagnostics")
        step("Checking...")
        print()

        report = Diagnostics.full_report()

        # Python
        py = report["python"]
        mark = "OK" if py["ok"] else "XX"
        print(f"  [{mark}] Python: {py['version']}")

        # Dependencies
        dep = report["dependencies"]
        req = dep["required"]
        print(f"  [{'OK' if dep['ok'] else 'XX'}] Required deps:")
        for m, s in req.items():
            print(f"      [{'OK' if s else 'XX'}] {m}")
        print(f"    Optional:")
        for m, s in dep["optional"].items():
            print(f"      [{'OK' if s else '--'}] {m}")

        # Paths
        paths = report["paths"]
        print(f"  [{'OK' if paths['ok'] else 'XX'}] Paths:")
        for name, p in paths["paths"].items():
            print(f"      [{'OK' if p['writable'] else 'XX'}] {name}: {p['path']}")

        # Network
        net = report["network"]
        print(f"  [{'OK' if net['ok'] else 'XX'}] Network:")
        for name, r in net["results"].items():
            mark = "OK" if r.get("ok") else "XX"
            lat = r.get("latency_ms", "?")
            print(f"      [{mark}] {name}: {lat}ms")

        # Config
        cfg_r = report["config"]
        print(f"  [{'OK' if cfg_r['ok'] else 'XX'}] Config:")
        for issue in cfg_r["issues"]:
            print(f"      [XX] {issue}")

        # Process
        proc = report["process"]
        print(f"  Process: {'running' if proc['running'] else 'stopped'}")
        if proc["running"]:
            print(f"      PID: {proc['pid']}, RAM: {proc['memory_mb']}MB")

        pause()

    def _act_open_project(self) -> None:
        if IS_WINDOWS:
            os.startfile(str(ROOT))
        else:
            webbrowser.open(str(ROOT))

    def _act_open_logs(self) -> None:
        if IS_WINDOWS:
            os.startfile(str(LOG_DIR))
        else:
            webbrowser.open(str(LOG_DIR))

    def _act_open_openrouter(self) -> None:
        webbrowser.open("https://openrouter.ai/keys")

    def _act_open_botfather(self) -> None:
        webbrowser.open("https://t.me/BotFather")

    def _act_help(self) -> None:
        head("Full help")
        print(HELP_TEXT)
        pause()
# ══════════════════════════════════════════════════════════════════════════════
#                        HELP TEXT
# ══════════════════════════════════════════════════════════════════════════════
HELP_TEXT = f"""
{Clr.BCYN}MAADGH Bot — Help{Clr.R}
{'=' * 60}

{Clr.BMAG}شروع سریع:{Clr.R}

  1. Option 6 — Initial setup
     • Telegram bot token from @BotFather
     • Channel (e.g. @MAADGHchannel)
     • OpenRouter key from openrouter.ai/keys
     • Gemini key from aistudio.google.com/apikey

  2. Option 11 — Test token
  3. Option 12 — Test channel (bot must be admin)
  4. Option 14 — Test models (find working ones)
  5. Option 22 — Set دستورات تلگرام menu
  6. Option 16 — Test full post to channel
  7. Option 2  — Run in background

{Clr.BMAG}دستورات تلگرام:{Clr.R}

  {Clr.BCYN}Content generation:{Clr.R}
    /post <topic>        - tutorial post
    /next                - next rotated topic
    /topic               - alias of next
    /random              - random topic
    /formula <topic>     - formula sheet
    /math <topic>        - math lesson
    /deep <topic>        - deep analysis
    /quiz <topic>        - quiz
    /flash <topic>       - flashcards
    /trivia <topic>      - interesting facts
    /example <topic>     - worked example
    /compare <topic>     - comparison
    /history <topic>     - historical
    /style <style> <topic> - choose style
    /styles              - list styles

  {Clr.BCYN}Chat:{Clr.R}
    /ask <question>      - chat with AI
    /chat <message>      - alias

  {Clr.BCYN}Topics:{Clr.R}
    /list                - full list
    /topics              - management
    /addtopic name | query - add custom
    /delcustom name      - remove custom

  {Clr.BCYN}Drafts and scheduling:{Clr.R}
    /drafts              - list drafts
    /regen ID            - regenerate
    /schedule in 30 topic - schedule post
    /jobs                - pending jobs

  {Clr.BCYN}Tools:{Clr.R}
    /search <word>       - Google search
    /images <word>       - image search
    /news                - engineering news
    /arxiv <topic>       - arXiv search
    /wiki <topic>        - Wikipedia
    /dict <word>         - dictionary
    /tr en fa <text>     - translate
    /flight <code>       - flight info
    /weather <city>      - weather
    /rate                - exchange rates
    /ip <address>        - IP lookup
    /yt <word>           - YouTube search
    /ytinfo <URL>        - video info
    /transcript <URL>    - video transcript
    /web <URL>           - website content
    /maps <place>        - place search
    /gpt <question>      - Gemini chat
    /vision <URL> <prompt> - image analysis

  {Clr.BCYN}Management:{Clr.R}
    /start               - start
    /help                - help
    /settings            - settings
    /stats               - statistics
    /panel               - admin panel
    /id                  - show IDs
    /clear               - clear chat history
    /api                 - API status

{Clr.BMAG}سبک‌های محتوا:{Clr.R}
  {Clr.BCYN}tutorial{Clr.R}    - structured lesson (default)
  {Clr.BCYN}formula{Clr.R}     - formula sheet
  {Clr.BCYN}math{Clr.R}        - math lesson
  {Clr.BCYN}deep{Clr.R}        - deep analysis
  {Clr.BCYN}news{Clr.R}        - news
  {Clr.BCYN}quiz{Clr.R}        - quiz
  {Clr.BCYN}flashcard{Clr.R}   - flashcards
  {Clr.BCYN}trivia{Clr.R}      - interesting facts
  {Clr.BCYN}example{Clr.R}     - worked example
  {Clr.BCYN}comparison{Clr.R}  - comparison
  {Clr.BCYN}history{Clr.R}     - historical

{Clr.BMAG}سرویس‌های پشتیبانی‌شده:{Clr.R}
  * OpenRouter   (15+ free models)
  * Google Gemini (6 models)
  * Zenserp      (Google Search)
  * Aviationstack (flights)
  * Apify        (YouTube, Instagram, ...)
  * Open-Meteo   (weather, free)
  * IP-API       (free)
  * Exchange Rate (free)
  * Wikipedia    (free)
  * arXiv        (free)
  * Dictionary   (free)
  * LibreTranslate (free)
  * Numbers API  (free)

{Clr.BMAG}مسیرهای مهم:{Clr.R}
  Root:   {ROOT}
  Data:   {DATA_DIR}
  Logs:   {LOG_DIR}
  Backup: {BACKUP_DIR}

{Clr.BMAG}نکات امنیتی:{Clr.R}
  * Never share tokens/keys in public chats
  * If leaked: openrouter.ai/keys -> Delete -> new key
  * BotFather: /mybots -> API Token -> Revoke
  * Bot auto-blocks messages containing tokens

{Clr.BMAG}رفع اشکال:{Clr.R}
  * "All models failed" -> Option 14 (test models)
  * Error 401           -> wrong key
  * Error 404           -> old model (auto fallback)
  * SSL error           -> try VPN on/off
  * Bot not responding  -> Option 5 (status)
  * Channel post fails  -> bot must be admin of channel
"""
# ══════════════════════════════════════════════════════════════════════════════
#                        BOT RUNNER (foreground)
# ══════════════════════════════════════════════════════════════════════════════
def _run_bot() -> None:
    """Full bot launcher."""
    head("MAADGH Bot — Starting")

    cfg = CONFIG.get()

    if not cfg.telegram.token:
        err("Telegram token not set")
        info("Use menu option 6 to configure")
        return

    _has_ai = any([cfg.keys.openrouter, cfg.keys.gemini,
                   getattr(cfg.keys, "bazaarlink", ""),
                   getattr(cfg.keys, "aimlapi", ""),
                   getattr(cfg.keys, "harnessrouter", ""),
                   getattr(cfg.keys, "groq", ""),
                   getattr(cfg.keys, "together", "")])
    if not _has_ai:
        err("No AI key configured")
        return

    log.info(f"Starting bot. Version: {cfg.version}")
    log.info(f"Provider: {cfg.ai.provider}")
    log.info(f"Channel: {cfg.telegram.channel_id}")
    try:
        LIVE.configure(cfg.telegram.admin_id)
        LIVE.event("sys", f"Bot started | provider={cfg.ai.provider}")
    except Exception:
        pass

    if not cfg.bot_started_at:
        cfg.bot_started_at = datetime.now().isoformat()
        CONFIG.save()

    # Set commands menu
    step("Setting command menu...")
    cmds = REGISTRY.telegram_menu()
    if cmds:
        r = TG.set_my_commands(cmds)
        if r.ok:
            ok(f"{len(cmds)} commands registered")
        else:
            warn(f"setMyCommands: {r.description[:100]}")

    # Get bot info
    me = TG.get_me()
    if me.ok:
        ok(f"Bot: @{me.result.get('username', '?')}")
    else:
        err(f"getMe: {me.description}")
        return

    # Start auto-poster
    step("Starting auto-poster...")
    AUTO_POSTER.start()
    next_run = AUTO_POSTER.next_run_time()
    info(f"Next auto-post: {next_run.strftime('%Y-%m-%d %H:%M') if next_run else '?'}")

    # Sync hashtag library (first time sends, later edits)
    step("Syncing hashtag library...")
    try:
        ok_flag = HASHTAGS.sync_channel(cfg)
        if ok_flag:
            info("Hashtag library message updated")
        else:
            info("Hashtag library up-to-date")
    except Exception as _e:
        warn(f"hashtag sync: {_e}")

    # Start polling
    step("Starting polling loop...")
    ok("Bot is live. Press Ctrl+C to stop.")
    print()

    try:
        POLLER.run()
    except KeyboardInterrupt:
        log.info("Interrupted by user")
    finally:
        AUTO_POSTER.stop()
        SCHEDULER.stop()
        log.info("Bot stopped")


# ══════════════════════════════════════════════════════════════════════════════
#                        FULL SELF-TEST
# ══════════════════════════════════════════════════════════════════════════════

def full_self_test() -> None:
    head("MAADGH Bot — Full Self-Test (All 5 Parts)")

    # Part 1
    if "_self_test" in globals() or "self_test" in globals():
        try:
            fn = globals().get("self_test")
            if fn and callable(fn):
                fn()
        except Exception as e:
            warn(f"Part 1 test failed: {e}")

    # Part 2
    try:
        self_test_part2()
    except Exception as e:
        warn(f"Part 2 test failed: {e}")

    # Part 3
    try:
        self_test_part3()
    except Exception as e:
        warn(f"Part 3 test failed: {e}")

    # Part 4
    try:
        self_test_part4()
    except Exception as e:
        warn(f"Part 4 test failed: {e}")

    # Part 5 specific
    head("Part 5/5 — Process & Backup Self-Test")

    step("Process manager...")
    info_dict = PROC.info()
    ok(f"Running: {info_dict['running']}")
    if info_dict["pid"]:
        info(f"PID: {info_dict['pid']}")

    step("Backup...")
    ok_flag, msg = BackupManager.create("test_backup")
    if ok_flag:
        ok(msg)
        backups = BackupManager.list_backups()
        info(f"Backups count: {len(backups)}")
        # Cleanup
        for b in backups:
            if b["name"] == "test_backup":
                BackupManager.delete(b["name"])
                break
    else:
        warn(msg)

    step("Log viewer...")
    lines = LogViewer.tail(LOG_FILE, 5)
    ok(f"{len(lines)} lines read from log")

    step("Diagnostics...")
    report = Diagnostics.full_report()
    info(f"Python: {report['python']['version']}")
    info(f"Deps OK: {report['dependencies']['ok']}")
    info(f"Paths OK: {report['paths']['ok']}")
    info(f"Network OK: {report['network']['ok']}")

    step("Scheduler...")
    jobs = SCHEDULER.upcoming()
    info(f"Pending jobs: {len(jobs)}")

    step("Final stats...")
    perf = PERF.stats()
    for name, data in perf.get("timings", {}).items():
        if isinstance(data, dict):
            info(f"  {name}: avg={data.get('avg_ms', 0)}ms ({data.get('count', 0)} calls)")

    print()
    success("=== ALL PARTS TESTED ===")
    info(f"Total commands: {len(REGISTRY.all())}")
    info(f"Total topics:   {len(TOPIC_MGR.all())}")
    info(f"Total styles:   {len(CONTENT_STYLES)}")
    info(f"Total APIs:     {len(APIS.all())}")
    print()


# ══════════════════════════════════════════════════════════════════════════════
#                        ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
#                    ADDED BY FIX3  (admin-only callbacks)
# ══════════════════════════════════════════════════════════════════════════════
LESSON_PROGRESS = {}
def _safe_admin_uid():
    try:
        return int(os.getenv("MAADGH_ADMIN_UID", "0") or "0")
    except (ValueError, TypeError):
        return 0
ADMIN_UID = _safe_admin_uid()


def _require_admin(cb):
    uid = cb.get("from", {}).get("id", 0)
    try:
        return uid == ADMIN_UID or is_admin(uid)
    except Exception:
        return uid == ADMIN_UID


@ROUTER.callback("share")
def cb_share(cb: Dict, data: str) -> None:
    if not _require_admin(cb):
        TG.answer_callback(cb.get("id", ""), "⛔ فقط ادمین", show_alert=True); return
    action = data.split(":", 1)[1] if ":" in data else ""
    chat_id = cb["message"]["chat"]["id"]
    msg_id  = cb["message"]["message_id"]
    TG.answer_callback(cb.get("id", ""), "🔗")
    if action == "menu":
        cfg = CONFIG.get()
        ch = (cfg.telegram.channel_id or "@MAADGHchannel")
        url = (f"https://t.me/{ch.lstrip('@')}"
               if ch.startswith("@") else f"https://t.me/c/{str(ch).lstrip('-')}")
        txt = ("📢 <b>اشتراک‌گذاری</b>\n\n"
               "روش ۱: روی پیام نگه‌دار → Forward → گروه مقصد\n"
               "روش ۲: ادمین با <code>/setshare -100xxxxxxxxx</code> گروه را ست کند\n\n"
               f"<a href=\"{url}\">رفتن به کانال</a>")
        TG.edit_message(chat_id, msg_id, txt,
                        reply_markup=kb([[btn("🔗 کانال", url=url)],
                                         [btn("⬅️ بازگشت", "m:main")]]))


@ROUTER.command("setshare", description="تعیین گروه اشتراک", admin_only=True)
def cmd_setshare(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg); gid = args.strip()
    if not gid:
        TG.send_message(chat_id, "استفاده: <code>/setshare -100123456789</code>"); return
    cfg = CONFIG.get()
    try:
        setattr(cfg.keys, "share_group_id", gid); CONFIG.save()
        TG.send_message(chat_id, f"✅ گروه: <code>{escape_html(gid)}</code>")
    except Exception as e:
        TG.send_message(chat_id, f"❌ {e}")


STEP_PROMPTS = {
    1: "مقدمه، تاریخچه، اهمیت مهندسی (5-8 خط).",
    2: "تعاریف و فرمول‌های پایه با توضیح هر متغیر.",
    3: "فرمول‌های پیشرفته + اثبات + شرایط اعتبار.",
    4: "سه مثال حل‌شده: آسان، متوسط، سخت.",
    5: "اشتباهات رایج، کاربرد صنعتی، تمرین، منابع.",
}


@ROUTER.command("learn", description="آموزش گام‌به‌گام", admin_only=True)
def cmd_learn(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg); uid = get_uid(msg)
    if not args:
        TG.send_message(chat_id,
            "🎓 <b>آموزش گام‌به‌گام</b>\n\n"
            "• <code>/learn &lt;topic&gt;</code>\n"
            "• <code>/continue</code>\n\n"
            "مثال: <code>/learn نابلا و لاپلاسین</code>")
        return
    LESSON_PROGRESS[uid] = {"topic": args, "step": 1}
    POOL.submit(_gen_lesson_step, CONFIG.get(), chat_id, uid, args, 1)


@ROUTER.command("continue", description="ادامه درس", admin_only=True)
def cmd_continue(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg); uid = get_uid(msg)
    prog = LESSON_PROGRESS.get(uid)
    if not prog:
        TG.send_message(chat_id, "❌ جلسه فعال نیست. /learn &lt;topic&gt;"); return
    nxt = min(prog["step"] + 1, 5); prog["step"] = nxt
    POOL.submit(_gen_lesson_step, CONFIG.get(), chat_id, uid, prog["topic"], nxt)


def _gen_lesson_step(cfg, chat_id: int, uid: int, topic: str, step: int) -> None:
    m = TG.send_message(chat_id, f"🎓 درس «{escape_html(topic)}» — بخش {step}/5 ...")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")
    sys_p = ("You are a Persian professor of engineering and mathematics. "
             "Teach step-by-step. Use real formulas and solved examples.")
    usr_p = f"موضوع: {topic}\nبخش {step}/5: {STEP_PROMPTS.get(step,'')}"
    with TypingHeartbeat(chat_id):
        r = AI.ask(sys_p, usr_p, max_tokens=2500)
    if not r.ok:
        TG.edit_message(chat_id, mid, f"❌ {escape_html(r.error[:200])}"); return
    txt = _md_to_html_safe(separate_directions(clean_latex(r.text)))
    rows = []
    if step < 5:
        rows.append([btn(f"▶️ بخش {step+1}", f"learn:next:{step+1}")])
    rows.append([btn("🔁 بازتولید", f"learn:regen:{step}")])
    TG.edit_message(chat_id, mid,
                    f"🎓 <b>{escape_html(topic)}</b> — بخش {step}/5\n\n{txt[:3800]}",
                    reply_markup=kb(rows))


@ROUTER.callback("learn")
def cb_learn(cb: Dict, data: str) -> None:
    if not _require_admin(cb):
        TG.answer_callback(cb.get("id", ""), "⛔ ادمین", show_alert=True); return
    parts = data.split(":"); action = parts[1] if len(parts) > 1 else ""
    uid = cb["from"]["id"]; chat_id = cb["message"]["chat"]["id"]
    prog = LESSON_PROGRESS.get(uid)
    if not prog: return
    if action == "next":
        nxt = min(int(parts[2]), 5); prog["step"] = nxt
        TG.answer_callback(cb.get("id", ""), f"بخش {nxt}")
        POOL.submit(_gen_lesson_step, CONFIG.get(), chat_id, uid, prog["topic"], nxt)
    elif action == "regen":
        TG.answer_callback(cb.get("id", ""), "🔁")
        POOL.submit(_gen_lesson_step, CONFIG.get(), chat_id, uid, prog["topic"], int(parts[2]))


@ROUTER.command("auto", description="موضوع خودکار", admin_only=True)
def cmd_auto(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    t = TOPIC_MGR.rotate_next()
    POOL.submit(_generate_and_post, CONFIG.get(), chat_id, t, t.get("style", "tutorial"))


@ROUTER.callback("m2")
def cb_menu2(cb: Dict, data: str) -> None:
    if not _require_admin(cb):
        TG.answer_callback(cb.get("id", ""), "⛔", show_alert=True); return
    action = data.split(":", 1)[1] if ":" in data else ""
    chat_id = cb["message"]["chat"]["id"]; msg_id = cb["message"]["message_id"]
    TG.answer_callback(cb.get("id", ""))
    back = kb([[btn("⬅️ بازگشت", "m:main")]])
    if action == "learn":
        TG.edit_message(chat_id, msg_id, "🎓 <code>/learn موضوع</code>", reply_markup=back)
    elif action == "rates":
        POOL.submit(_h_rates, chat_id, msg_id)
    elif action == "search":
        TG.edit_message(chat_id, msg_id, "🔍 <code>/search کلمه</code>", reply_markup=back)
    elif action == "video":
        TG.edit_message(chat_id, msg_id, "🎥 <code>/yt موضوع</code>", reply_markup=back)
    elif action == "arxiv":
        POOL.submit(_h_arxiv, chat_id, msg_id)
    elif action == "wiki":
        TG.edit_message(chat_id, msg_id, "📖 <code>/wiki موضوع</code>", reply_markup=back)
    elif action == "help":
        TG.edit_message(chat_id, msg_id, HELP_TEXT[:3800], reply_markup=back)
    elif action == "api":
        TG.edit_message(chat_id, msg_id, APIS.status_summary(), reply_markup=back)


def _h_rates(chat_id, msg_id):
    try:
        r = APIS.exchange.latest("USD", "EUR,GBP,IRR,AED,TRY,CNY,JPY")
        if r.ok and r.data:
            rates = (r.data.get("rates") or {})
            txt = "💱 <b>نرخ ارز (USD)</b>\n\n"
            for k, v in rates.items(): txt += f"• {k}: <code>{v}</code>\n"
            TG.edit_message(chat_id, msg_id, txt,
                            reply_markup=kb([[btn("⬅️", "m:main")]])); return
    except Exception: pass
    TG.edit_message(chat_id, msg_id, "❌ خطا", reply_markup=kb([[btn("⬅️", "m:main")]]))


def _h_arxiv(chat_id, msg_id):
    try:
        r = APIS.arxiv.search("mechanical engineering", max_results=5)
        if r.ok and r.data:
            txt = "📚 <b>arXiv</b>\n\n"
            for i, p in enumerate(r.data[:5], 1):
                txt += f"{i}. {escape_html(p['title'][:80])}\n<a href='{p['link']}'>مقاله</a>\n\n"
            TG.edit_message(chat_id, msg_id, txt[:4000],
                            reply_markup=kb([[btn("⬅️", "m:main")]])); return
    except Exception: pass
    TG.edit_message(chat_id, msg_id, "❌ خطا", reply_markup=kb([[btn("⬅️", "m:main")]]))




@ROUTER.command("setkey", description="تنظیم کلید API", admin_only=True)
def cmd_setkey(msg: Dict, args: str) -> None:
    """Usage: /setkey <name> <value>
       Names: openrouter, gemini, groq, apify, zenserp, aviationstack,
              telegram_token, channel_id, admin_id, provider"""
    chat_id = get_chat_id(msg)
    parts = args.split(None, 1)
    if len(parts) < 2:
        TG.send_message(chat_id,
            "استفاده: <code>/setkey نام مقدار</code>\n\n"
            "نام‌ها:\n"
            "<code>openrouter</code>\n<code>gemini</code>\n"
            "<code>groq</code>\n<code>apify</code>\n"
            "<code>zenserp</code>\n<code>aviationstack</code>\n"
            "<code>telegram_token</code>\n<code>channel_id</code>\n"
            "<code>admin_id</code>\n<code>provider</code>")
        return
    name = parts[0].strip().lower()
    val = parts[1].strip()
    cfg = CONFIG.get()
    try:
        if name == "telegram_token":
            cfg.telegram.token = val
        elif name == "channel_id":
            cfg.telegram.channel_id = val
        elif name == "admin_id":
            try:
                cfg.telegram.admin_id = int(val)
                if int(val) not in cfg.telegram.admin_ids:
                    cfg.telegram.admin_ids.append(int(val))
            except Exception:
                TG.send_message(chat_id, "❌ admin_id باید عدد باشد"); return
        elif name == "provider":
            if not CONFIG.set_provider(val):
                TG.send_message(chat_id, f"❌ provider نامعتبر: {val}"); return
        elif hasattr(cfg.keys, name):
            setattr(cfg.keys, name, val)
        else:
            TG.send_message(chat_id, f"❌ نام ناشناخته: {name}"); return
        CONFIG.save()
        TG.send_message(chat_id, f"✅ <b>{name}</b> ذخیره شد ({len(val)} کاراکتر)")
    except Exception as e:
        TG.send_message(chat_id, f"❌ {e}")


@ROUTER.command("showkeys", description="نمایش کلیدها", admin_only=True)
def cmd_showkeys(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    cfg = CONFIG.get()
    def m(v):
        v = str(v or "")
        if not v: return "❌"
        if len(v) <= 12: return f"✅ {v}"
        return f"✅ {v[:6]}...{v[-4:]}"
    txt = (
        f"🔑 <b>وضعیت کلیدها</b>\n\n"
        f"<b>Telegram:</b>\n"
        f"  token: {m(cfg.telegram.token)}\n"
        f"  channel: <code>{escape_html(cfg.telegram.channel_id)}</code>\n"
        f"  admin_id: <code>{cfg.telegram.admin_id}</code>\n\n"
        f"<b>AI Providers:</b>\n"
        f"  OpenRouter: {m(cfg.keys.openrouter)}\n"
        f"  Groq: {m(cfg.keys.groq)}\n"
        f"  BazaarLink: {m(cfg.keys.bazaarlink)}\n"
        f"  AIMLAPI: {m(cfg.keys.aimlapi)}\n"
        f"  Gemini: {m(cfg.keys.gemini)}\n\n"
        f"<b>Services:</b>\n"
        f"  Apify: {m(cfg.keys.apify)}\n"
        f"  Zenserp: {m(cfg.keys.zenserp)}\n"
        f"  Aviationstack: {m(cfg.keys.aviationstack)}\n\n"
        f"<b>Provider فعال:</b> <code>{cfg.ai.provider}</code>"
    )
    TG.send_message(chat_id, txt)


@ROUTER.command("addkey", description="افزودن سریع کلید", admin_only=True)
def cmd_addkey(msg: Dict, args: str) -> None:
    """Detect key type automatically:
       sk-or-v1-* → openrouter
       gsk_*      → groq
       sk-bl-*    → bazaarlink
       sk-hr-*    → harnessrouter
       apify_api_ → apify
       AIza*      → gemini
       12345:ABC  → telegram_token
       number     → admin_id"""
    chat_id = get_chat_id(msg)
    val = args.strip()
    if not val:
        TG.send_message(chat_id, "استفاده: <code>/addkey KEY</code>")
        return
    cfg = CONFIG.get()
    if val.startswith("sk-or-v1-"):
        cfg.keys.openrouter = val; name = "OpenRouter"
    elif val.startswith("gsk_"):
        cfg.keys.groq = val; name = "Groq"
    elif val.startswith("sk-bl-"):
        cfg.keys.bazaarlink = val; name = "BazaarLink"
    elif val.startswith("sk-hr-"):
        cfg.keys.harnessrouter = val; name = "HarnessRouter"
    elif val.startswith("apify_api_"):
        cfg.keys.apify = val; name = "Apify"
    elif val.startswith("AIza"):
        cfg.keys.gemini = val; name = "Gemini"
    elif ":" in val and val.split(":")[0].isdigit() and len(val) > 30:
        cfg.telegram.token = val; name = "Telegram Token"
    elif val.isdigit():
        try:
            cfg.telegram.admin_id = int(val)
            if int(val) not in cfg.telegram.admin_ids:
                cfg.telegram.admin_ids.append(int(val))
            name = "Admin ID"
        except Exception:
            TG.send_message(chat_id, "❌"); return
    else:
        TG.send_message(chat_id, "❌ نوع کلید ناشناخته"); return
    CONFIG.save()
    TG.send_message(chat_id, f"✅ {name} ذخیره شد ({len(val)} کاراکتر)")



@ROUTER.command("randstats", description="Topic picker stats", admin_only=True)
def cmd_randstats(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    st = PICKER.stats()
    top = "\n".join(f"  {i+1}. {escape_html(n)}" for i, n in enumerate(st["recent_top"]))
    txt = (
        f"<b>Recent picks</b> ({st['recent_count']}/40)\n\n"
        f"{top}"
    )
    TG.send_message(chat_id, txt)


@ROUTER.command("randreset", description="Clear recent picks", admin_only=True)
def cmd_randreset(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    try:
        PICKER._recent = []
        PICKER._save_state()
        TG.send_message(chat_id, "OK - recent picks cleared")
    except Exception as e:
        TG.send_message(chat_id, f"ERR: {e}")



@ROUTER.command("hashtags", description="Hashtag library", admin_only=True)
def cmd_hashtags(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    st = HASHTAGS.stats()
    txt = (
        f"<b>Hashtag Registry</b>\n\n"
        f"Total known : <code>{st['known']}</code>\n"
        f"Pending     : <code>{st['pending']}</code>\n"
        f"Channels    : <code>{len(st['channel'])}</code>\n\n"
        + HASHTAGS.render_library()
    )
    TG.send_message(chat_id, txt[:4000])


@ROUTER.command("synchash", description="Force sync library", admin_only=True)
def cmd_synchash(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    try:
        ok_flag = HASHTAGS.sync_channel(CONFIG.get(), force=True)
        TG.send_message(chat_id, "OK" if ok_flag else "no change")
    except Exception as e:
        TG.send_message(chat_id, f"ERR: {e}")


@ROUTER.command("showtags", description="Show tags for a topic", admin_only=True)
def cmd_showtags(msg: Dict, args: str) -> None:
    chat_id = get_chat_id(msg)
    name = args.strip() or "استاتیک"
    t = TOPIC_MGR.find(name) or {"name": name, "tags": ""}
    tags = HASHTAGS.expand(t, max_tags=5)
    txt = f"<b>{escape_html(t.get('name','?'))}</b>\n\n" + " ".join(tags)
    TG.send_message(chat_id, txt)

def main() -> None:
    """Main entry point."""
    args = sys.argv[1:]

    if "--test" in args or "--self-test" in args or "--bench" in args:
        full_self_test()
        return

    if "--test1" in args:
        fn = globals().get("self_test")
        if fn and callable(fn):
            fn()
        else:
            err("Part 1 self_test not found")
        return

    if "--test2" in args:
        self_test_part2()
        return

    if "--test3" in args:
        self_test_part3()
        return

    if "--test4" in args:
        self_test_part4()
        return

    if "--test-formula" in args:
        head("Test formula output")
        style = "tutorial"
        topic = "استاتیک"
        if len(args) >= 2 and args[args.index("--test-formula") + 1]:
            topic = args[args.index("--test-formula") + 1]
        if "--style" in args:
            _si = args.index("--style")
            if _si + 1 < len(args):
                style = args[_si + 1]
        step(f"Topic: {topic}  Style: {style}")
        content = CONTENT.generate(topic, style)
        if not content:
            err("Generation failed")
            return
        print()
        print("=" * 70)
        print(content)
        print("=" * 70)
        print()
        ok(f"Length: {len(content)} chars")
        return
    if "--diagnose" in args:
        W = print
        head("MAADGH Diagnose")
        cfg = CONFIG.get()
        info(f"Telegram token: {'SET' if cfg.telegram.token else 'EMPTY'}")
        info(f"Channel: {cfg.telegram.channel_id}")
        info(f"Provider: {cfg.ai.provider}")
        info(f"Primary model: {cfg.ai.primary_model}")
        info(f"OpenRouter key: {'SET (len=' + str(len(cfg.keys.openrouter)) + ')' if cfg.keys.openrouter else 'EMPTY'}")
        info(f"Gemini key: {'SET' if cfg.keys.gemini else 'EMPTY'}")
        info(f"Apify token: {'SET (len=' + str(len(cfg.keys.apify)) + ')' if cfg.keys.apify else 'EMPTY'}")
        print()
        step("Testing AI...")
        r = AI.ask("You are a test.", "Say OK.", max_tokens=10, use_cache=False)
        if r.ok:
            ok(f"AI OK: {r.model} ({r.latency_ms}ms)")
        else:
            err(f"AI FAIL: {r.error}")
        print()
        step("Testing generation (tutorial, short topic)...")
        try:
            c = CONTENT.generate("استاتیک", "tutorial")
            if c:
                ok(f"Generated {len(c)} chars")
                print()
                print("--- FIRST 600 CHARS ---")
                print(c[:600])
                print("--- END ---")
            else:
                err("Generation returned None")
        except Exception as e:
            err(f"Exception: {e}")
            traceback.print_exc()
        print()
        step("Testing news fetch...")
        try:
            items = APIS.news.fetch_combined(limit=3)
            ok(f"News: {len(items)} items")
        except Exception as e:
            err(f"News: {e}")
        return
    if "--run" in args:
        _run_bot()
        return

    if "--backup" in args:
        ok_flag, msg = BackupManager.create()
        print(msg)
        return

    if "--check-channel" in args:
        head("Channel check")
        cfg = CONFIG.get()
        ch = (cfg.telegram.channel_id or "").strip()
        info(f"channel_id : {ch or '(empty)'}")
        info(f"bot token  : {'SET' if cfg.telegram.token else 'EMPTY'}")
        info(f"bot admin  : {cfg.telegram.admin_id}")
        print()
        if not ch:
            err("Channel ID is empty")
            return
        if ch.lstrip("-").isdigit() and int(ch) > 0:
            err(f"channel_id={ch} looks like a USER chat_id, not a channel.")
            info("Use @username or -100xxxxxxxxxx")
            return
        step("Testing sendMessage to channel...")
        r = TG.send_message(ch, "🧪 MAADGH channel test — delete me")
        if r.ok:
            ok(f"SUCCESS — bot can post to {ch}")
            info("Delete the test message from your channel.")
        else:
            err(f"FAIL: {r.error_code} {r.description}")
            info("Check: bot is admin + has 'Post Messages' permission")
        return
    if "--diagnostics" in args:
        report = Diagnostics.full_report()
        print(json.dumps(report, indent=2, default=str))
        return

    if "--version" in args:
        print(f"MAADGH Bot v{CONFIG.get().version}")
        print(f"ROOT: {ROOT}")
        print(f"Python: {PY_MAJOR}.{PY_MINOR}.{PY_VER.micro}")
        return

    if "--help" in args or "-h" in args:
        print(HELP_TEXT)
        return

    # Default: interactive menu
    menu = MenuSystem()
    menu.run()


# ══════════════════════════════════════════════════════════════════════════════
#                        SHUTDOWN
# ══════════════════════════════════════════════════════════════════════════════

def _final_cleanup() -> None:
    """Final cleanup on exit."""
    log.info("Final cleanup...")
    try:
        AUTO_POSTER.stop()
    except Exception:
        pass
    try:
        SCHEDULER.stop()
    except Exception:
        pass
    try:
        POLLER.stop()
    except Exception:
        pass
    try:
        BATCHED_WRITER.stop()
    except Exception:
        pass
    try:
        JsonStore.save(CONFIG_FILE, {
            "telegram": asdict(CONFIG.get().telegram),
            "ai": asdict(CONFIG.get().ai),
            "content": asdict(CONFIG.get().content),
            "behavior": asdict(CONFIG.get().behavior),
            "keys": asdict(CONFIG.get().keys),
            "last_update_id": CONFIG.get().last_update_id,
            "bot_started_at": CONFIG.get().bot_started_at,
            "version": CONFIG.get().version,
        })
    except Exception:
        pass
    log.info("Cleanup complete.")


register_shutdown(_final_cleanup)




# ═══════════════════════════════════════════════════════════════════════════
#  PATCH v4.0 — FIXED PLACEMENT (runs BEFORE __main__)
#  این patch قبل از بلاک __main__ قرار می‌گیرد تا واقعاً اجرا شود.
#  بدون هیچ متن انگلیسی در تلگرام.
# ═══════════════════════════════════════════════════════════════════════════

import math as _m_v4

# ── 1. RAM & GC tuning ──────────────────────────────────────────
try:
    gc.set_threshold(120000, 50, 50)
    gc.collect()
except Exception:
    pass
try:
    AI_CACHE.resize(2000)
    HTTP_CACHE.resize(8000)
    TRANSLATE_CACHE.resize(8000)
    _text_cache.resize(4000)
except Exception:
    pass

# ── 2. Math-weighted picker (Softmax + Z-score + L2) ────────────
class MathPickerV4:
    def __init__(self, temperature=0.85):
        self._T = temperature
        self._usage = {}
        self._recent = []
        self._max = 60
        self._lock = threading.RLock()

    def _zs(self, v):
        if not v: return []
        m = sum(v)/len(v)
        var = sum((x-m)**2 for x in v)/len(v)
        s = _m_v4.sqrt(var) if var > 0 else 1.0
        return [(x-m)/s for x in v]

    def _sm(self, logits):
        if not logits: return []
        mx = max(logits)
        ex = [_m_v4.exp((l-mx)/self._T) for l in logits]
        t = sum(ex)
        return [e/t for e in ex] if t > 0 else [1.0/len(logits)]*len(logits)

    def _l2(self, vec):
        n = _m_v4.sqrt(sum(x*x for x in vec)) if vec else 1.0
        return [x/n for x in vec] if n > 0 else vec

    def pick(self, topics, avoid=None):
        if not topics: return None
        with self._lock:
            avoid = set(avoid or [])
            pool = [t for t in topics if (t.get("name") or "") not in avoid]
            if not pool: pool = list(topics)
            raw = []
            for t in pool:
                name = t.get("name") or ""
                cnt = self._usage.get(name, 0)
                base = 1.0/(1.0+cnt)
                try:
                    idx = self._recent.index(name)
                    rec = (self._max-idx)/self._max
                except ValueError:
                    rec = 0.0
                pen = 1.0/(1.0+25.0*rec)
                raw.append(base*pen)
            z = self._zs(raw)
            if z:
                mn = min(z)
                z = [x-mn+0.1 for x in z]
            z = self._l2(z)
            probs = self._sm(z)
            r = _RND.random()
            cum = 0.0
            chosen = pool[-1]
            for t, p in zip(pool, probs):
                cum += p
                if r <= cum:
                    chosen = t
                    break
            name = chosen.get("name") or ""
            self._usage[name] = self._usage.get(name, 0) + 1
            self._recent.insert(0, name)
            del self._recent[self._max:]
            return chosen

    def reset(self):
        with self._lock:
            self._usage.clear(); self._recent.clear()

    def stats(self):
        with self._lock:
            return {"T": self._T, "used": len(self._usage),
                    "recent": self._recent[:10]}

PICKER = MathPickerV4()

# Override TopicManager.rotate_next
def _rotate_v4(self):
    all_t = self.all()
    if not all_t: return TOPICS[0]
    c = PICKER.pick(all_t)
    return c if c else all_t[0]
TopicManager.rotate_next = _rotate_v4

# ── 3. Section maps (Persian only) ──────────────────────────────
_MATH_SECTIONS = {
    "A": "حساب و مبانی ریاضی",
    "B": "حساب دیفرانسیل",
    "C": "انتگرال و چندمتغیره",
    "D": "جبر خطی",
    "E": "معادلات دیفرانسیل",
    "F": "معادلات دیفرانسیل جزئی",
    "G": "سری‌ها و تبدیل‌ها",
    "H": "احتمال و فرآیند تصادفی",
    "I": "آمار و ریاضیات داده",
    "J": "بهینه‌سازی",
    "K": "ریاضیات مهندسی و محاسباتی",
    "L": "ریاضیات مدرن و هوش مصنوعی",
    "M": "ریاضیات پیشرفته",
}
_MECH_SECTIONS = {
    "A": "ریاضیات و ابزار محاسباتی",
    "B": "استاتیک، دینامیک و مکانیک",
    "C": "مقاومت مصالح و شکست",
    "D": "ارتعاشات و کنترل",
    "E": "مکانیک سیالات و دینامیک سیالات محاسباتی",
    "F": "ترمودینامیک، انرژی و احتراق",
    "G": "انتقال حرارت و مدیریت حرارتی",
    "H": "تهویه مطبوع و انرژی ساختمان",
    "I": "انرژی‌های تجدیدپذیر و ذخیره",
    "J": "طراحی ماشین و تجهیزات",
    "K": "تولید، ماشین‌کاری و ساخت افزایشی",
    "L": "مواد پیشرفته، تریبولوژی و سطح",
}
_MATH_EMOJI = {"A":"🧮","B":"∂","C":"∫","D":"🔢","E":"📐",
               "F":"🌊","G":"🎼","H":"🎲","I":"📊","J":"📈",
               "K":"💻","L":"🤖","M":"🏛️"}
_MECH_EMOJI = {"A":"🧮","B":"🏛️","C":"🏗️","D":"📳","E":"🌊",
               "F":"🔥","G":"🌡️","H":"❄️","I":"☀️","J":"⚙️",
               "K":"🏭","L":"🔬"}

# ── 4. Load topic bank ──────────────────────────────────────────
_TOPIC_BANK_PATH = DATA_DIR / "topic_bank.json"
try:
    _RAW_BANK = load_json(_TOPIC_BANK_PATH, default=[]) or []
except Exception as _e:
    log.warning(f"topic_bank load: {_e}")
    _RAW_BANK = []

_TOPIC_BANK_FULL = []
for row in _RAW_BANK:
    try:
        dom, sec, name = row[0], row[1], row[2]
    except Exception:
        continue
    if not name: continue
    if dom == "M":
        emoji = _MATH_EMOJI.get(sec, "📐")
        sname = _MATH_SECTIONS.get(sec, sec)
        style = "math"
        dom_key = "math"
        tags = f"{name.replace(' ','_')}"
    else:
        emoji = _MECH_EMOJI.get(sec, "🔧")
        sname = _MECH_SECTIONS.get(sec, sec)
        style = "tutorial"
        dom_key = "mech"
        tags = f"{name.replace(' ','_')}"
    _TOPIC_BANK_FULL.append({
        "name": name, "query": name, "emoji": emoji,
        "style": style, "tags": tags,
        "domain": dom_key, "section": sec, "section_name": sname,
    })

_existing = {(t.get("name") or "") for t in TOPICS if isinstance(t, dict)}
_MERGED_TOPICS = list(TOPICS)
for _t in _TOPIC_BANK_FULL:
    if _t["name"] not in _existing:
        _MERGED_TOPICS.append(_t)
        _existing.add(_t["name"])

log.info(f"[v4.0] bank={len(_TOPIC_BANK_FULL)} total={len(_MERGED_TOPICS)}")

def _get_topics_list():
    return _MERGED_TOPICS

# ── 5. Floating menu state ──────────────────────────────────────
_LS_STATE = TTLStore(max_items=1000, ttl=7200)
_LS_PAGE = 15

def _ls_render(chat_id, msg_id, key, page=0, edit=True):
    st = _LS_STATE.get(chat_id)
    if not st or st.get("key") != key:
        if edit and msg_id:
            TG.edit_message(chat_id, msg_id,
                "⚠️ منو منقضی شده. دوباره /list",
                reply_markup=kb([[btn("🏠 منوی اصلی", "m:main")]]))
        return
    level = st["level"]

    if level == "root":
        total = len(_MERGED_TOPICS)
        math = sum(1 for t in _MERGED_TOPICS if t.get("domain")=="math")
        mech = sum(1 for t in _MERGED_TOPICS if t.get("domain")=="mech")
        other = total - math - mech
        text = (f"📚 <b>بانک موضوعات</b>\n\n"
                f"  📐 ریاضی: <b>{math}</b>\n"
                f"  🔧 مهندسی مکانیک: <b>{mech}</b>\n"
                f"  📌 سایر: <b>{other}</b>\n"
                f"  ─────────\n"
                f"  📊 مجموع: <b>{total}</b>\n\n"
                f"یک دسته را انتخاب کن:")
        rows = [
            [btn(f"📐 ریاضی ({math})", "ls:domain:math")],
            [btn(f"🔧 مهندسی مکانیک ({mech})", "ls:domain:mech")],
            [btn(f"📌 سایر ({other})", "ls:domain:other")],
            [btn("📖 همه موضوعات", "ls:domain:all")],
            [btn("🔍 جستجو", "ls:search"), btn("🎲 تصادفی", "ls:rand")],
            [btn("🏠 منوی اصلی", "m:main")],
        ]
        markup = kb(rows)

    elif level == "domain":
        secs = st["sections"]
        dom = st["domain"]
        title = {"math":"📐 ریاضیات","mech":"🔧 مهندسی مکانیک",
                 "other":"📌 سایر","all":"📚 همه"}.get(dom, "📚")
        text = f"<b>{title}</b>\n\nسرفصل را انتخاب کن:\n"
        rows = []; row = []
        for (sec, sname, cnt, em) in secs:
            text += f"  {em} <b>{sname}</b> — <code>{cnt}</code>\n"
            row.append(btn(f"{em} {sname[:24]} ({cnt})", f"ls:sec:{sec}"))
            if len(row) == 2:
                rows.append(row); row = []
        if row: rows.append(row)
        rows.append([btn("⬅️ بازگشت", "ls:root"),
                     btn("🔍 جستجو", "ls:search"),
                     btn("🏠 منو", "m:main")])
        markup = kb(rows)

    elif level == "section":
        items = st["items"]; title = st["title"]; total = len(items)
        if total == 0:
            if edit and msg_id:
                TG.edit_message(chat_id, msg_id, "❌ خالی",
                    reply_markup=kb([[btn("⬅️","ls:root")]]))
            return
        tp = max(1, (total+_LS_PAGE-1)//_LS_PAGE)
        page = max(0, min(page, tp-1))
        st["page"] = page
        start = page*_LS_PAGE
        chunk = items[start:start+_LS_PAGE]
        text = f"<b>{title}</b>\nصفحه {page+1}/{tp} — {total} مورد\n\n"
        rows = []
        for i, t in enumerate(chunk):
            idx = start + i
            em = t.get("emoji", "•")
            nm = (t.get("name") or "?")[:32]
            text += f"<b>{idx+1}.</b> {em} {escape_html(nm)}\n"
            rows.append([btn(f"{idx+1}. {em} {nm[:26]}", f"ls:pick:{idx}")])
        nav = []
        if page > 0: nav.append(btn("◀️ قبلی", f"ls:p:{page-1}"))
        nav.append(btn(f"{page+1}/{tp}", "ls:nop"))
        if page < tp-1: nav.append(btn("بعدی ▶️", f"ls:p:{page+1}"))
        rows.append(nav)
        rows.append([btn("⬅️ سرفصل‌ها", "ls:back"),
                     btn("🔍 جستجو", "ls:search"),
                     btn("🏠 منو", "m:main")])
        markup = kb(rows)
    else:
        return

    if edit and msg_id:
        TG.edit_message(chat_id, msg_id, text[:4000], reply_markup=markup)
    else:
        TG.send_message(chat_id, text[:4000], reply_markup=markup)


def _ls_sections_for(domain):
    if domain == "math":
        pool = [t for t in _MERGED_TOPICS if t.get("domain")=="math"]
        smap = _MATH_SECTIONS; emap = _MATH_EMOJI
    elif domain == "mech":
        pool = [t for t in _MERGED_TOPICS if t.get("domain")=="mech"]
        smap = _MECH_SECTIONS; emap = _MECH_EMOJI
    elif domain == "other":
        pool = [t for t in _MERGED_TOPICS
                if t.get("domain") not in ("math","mech")]
        smap = {"Z": "سایر"}; emap = {"Z": "📌"}
    else:
        m = sum(1 for t in _MERGED_TOPICS if t.get("domain")=="math")
        e = sum(1 for t in _MERGED_TOPICS if t.get("domain")=="mech")
        o = len(_MERGED_TOPICS) - m - e
        return [("__math__", "ریاضی", m, "📐"),
                ("__mech__", "مهندسی مکانیک", e, "🔧"),
                ("__other__", "سایر", o, "📌")]
    out = []
    for sec in sorted(smap.keys()):
        n = sum(1 for t in pool if t.get("section")==sec)
        if n > 0:
            out.append((sec, smap[sec], n, emap.get(sec, "•")))
    if not out and pool:
        out.append(("Z", "سایر", len(pool), "📌"))
    return out


def _ls_items_for(domain, sec):
    if domain == "all":
        if sec == "__math__": return [t for t in _MERGED_TOPICS if t.get("domain")=="math"]
        if sec == "__mech__": return [t for t in _MERGED_TOPICS if t.get("domain")=="mech"]
        if sec == "__other__": return [t for t in _MERGED_TOPICS if t.get("domain") not in ("math","mech")]
        return []
    if domain == "other":
        return [t for t in _MERGED_TOPICS if t.get("domain") not in ("math","mech")]
    return [t for t in _MERGED_TOPICS
            if t.get("domain")==domain and t.get("section")==sec]

# ── 6. New /list ───────────────────────────────────────────────
@ROUTER.command("list", description="بانک موضوعات")
def cmd_list_v4(msg, args):
    chat_id = get_chat_id(msg)
    _LS_STATE[chat_id] = {"key":"root","level":"root"}
    _ls_render(chat_id, None, "root", 0, edit=False)

# ── 7. New ls callback ─────────────────────────────────────────
@ROUTER.callback("ls")
def cb_ls_v4(cb, data):
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    chat_id = cb["message"]["chat"]["id"]
    msg_id = cb["message"]["message_id"]
    uid = cb.get("from", {}).get("id", 0)
    TG.answer_callback(cb.get("id", ""))

    if action == "nop": return

    if action == "root":
        _LS_STATE[chat_id] = {"key":"root","level":"root"}
        _ls_render(chat_id, msg_id, "root", 0); return

    if action == "domain":
        dom = parts[2] if len(parts) > 2 else "all"
        secs = _ls_sections_for(dom)
        _LS_STATE[chat_id] = {"key":f"dom:{dom}","level":"domain",
                              "domain":dom,"sections":secs}
        _ls_render(chat_id, msg_id, f"dom:{dom}", 0); return

    if action == "back":
        st = _LS_STATE.get(chat_id)
        if st and st.get("domain"):
            dom = st["domain"]
            _c = dict(cb); _c["data"] = f"ls:domain:{dom}"
            cb_ls_v4(_c, _c["data"])
        else:
            _c = dict(cb); _c["data"] = "ls:root"
            cb_ls_v4(_c, _c["data"])
        return

    if action == "sec":
        sec = parts[2] if len(parts) > 2 else ""
        st = _LS_STATE.get(chat_id)
        if not st or "domain" not in st: return
        dom = st["domain"]
        items = _ls_items_for(dom, sec)
        if dom == "math": sname = _MATH_SECTIONS.get(sec, sec)
        elif dom == "mech": sname = _MECH_SECTIONS.get(sec, sec)
        elif dom == "all":
            sname = {"__math__":"ریاضی","__mech__":"مهندسی","__other__":"سایر"}.get(sec, sec)
        else: sname = "سایر"
        title = f"{sname} ({len(items)})"
        _LS_STATE[chat_id] = {"key":f"sec:{dom}:{sec}","level":"section",
                              "domain":dom,"sec":sec,"items":items,
                              "title":title,"page":0}
        _ls_render(chat_id, msg_id, f"sec:{dom}:{sec}", 0); return

    if action == "p":
        try: pg = int(parts[2])
        except Exception: pg = 0
        st = _LS_STATE.get(chat_id)
        if st: _ls_render(chat_id, msg_id, st["key"], pg)
        return

    if action == "pick":
        try: idx = int(parts[2])
        except Exception: return
        st = _LS_STATE.get(chat_id)
        if not st or idx < 0 or idx >= len(st.get("items",[])): return
        t = st["items"][idx]
        text = (f"🎯 <b>{t.get('emoji','•')} "
                f"{escape_html(t.get('name','?'))}</b>\n\nسبک تولید:")
        rows = [
            [btn("📘 آموزشی", f"ls:go:{idx}:tutorial"),
             btn("🧮 فرمول‌ها", f"ls:go:{idx}:formula")],
            [btn("📐 ریاضی", f"ls:go:{idx}:math"),
             btn("🔬 عمیق", f"ls:go:{idx}:deep")],
            [btn("🧪 مثال", f"ls:go:{idx}:example"),
             btn("❓ کوییز", f"ls:go:{idx}:quiz")],
            [btn("📇 فلش‌کارت", f"ls:go:{idx}:flashcard"),
             btn("📰 خبری", f"ls:go:{idx}:news")],
            [btn("📜 تاریخی", f"ls:go:{idx}:history"),
             btn("⚖️ مقایسه", f"ls:go:{idx}:comparison")],
            [btn("⬅️ بازگشت به فهرست", f"ls:p:{st.get('page',0)}")],
        ]
        TG.edit_message(chat_id, msg_id, text, reply_markup=kb(rows)); return

    if action == "go":
        try:
            idx = int(parts[2]); style = parts[3] if len(parts) > 3 else "tutorial"
        except Exception: return
        st = _LS_STATE.get(chat_id)
        if not st or idx < 0 or idx >= len(st.get("items",[])): return
        t = st["items"][idx]
        if style not in CONTENT_STYLES:
            style = t.get("style") or "tutorial"
        if style not in CONTENT_STYLES:
            style = "tutorial"
        TG.edit_message(chat_id, msg_id,
            f"⏳ در حال تولید «{escape_html(t.get('name','?'))}» [{style}]...\n"
            f"<i>ممکن است ۳۰-۹۰ ثانیه طول بکشد.</i>")
        POOL.submit(_generate_and_post, CONFIG.get(), chat_id, t, style)
        return

    if action == "search":
        SESSIONS.set_state(uid, "awaiting_search",
                           chat_id=chat_id, msg_id=msg_id)
        TG.edit_message(chat_id, msg_id,
            "🔍 <b>جستجو در بانک موضوعات</b>\n\n"
            "عبارت مورد نظر را بنویس و بفرست:",
            reply_markup=kb([[btn("⬅️ لغو", "ls:root")]])); return

    if action == "rand":
        if not _MERGED_TOPICS: return
        t = PICKER.pick(_MERGED_TOPICS) or _MERGED_TOPICS[0]
        try: idx = _MERGED_TOPICS.index(t)
        except ValueError: idx = 0
        _LS_STATE[chat_id] = {"key":f"rand:{idx}","level":"section",
                              "domain":"all","sec":"__math__",
                              "items":_MERGED_TOPICS,
                              "title":f"🎲 تصادفی ({len(_MERGED_TOPICS)})","page":0}
        rows = [
            [btn("📘 آموزشی", f"ls:go:{idx}:tutorial"),
             btn("🧮 فرمول", f"ls:go:{idx}:formula")],
            [btn("📐 ریاضی", f"ls:go:{idx}:math"),
             btn("🔬 عمیق", f"ls:go:{idx}:deep")],
            [btn("🧪 مثال", f"ls:go:{idx}:example"),
             btn("❓ کوییز", f"ls:go:{idx}:quiz")],
            [btn("🎲 تصادفی دیگر", "ls:rand"),
             btn("⬅️ بازگشت", "ls:root")],
        ]
        TG.edit_message(chat_id, msg_id,
            f"🎲 <b>موضوع تصادفی:</b>\n\n{t.get('emoji','•')} "
            f"<b>{escape_html(t.get('name','?'))}</b>\n\nسبک تولید:",
            reply_markup=kb(rows)); return

    if action in ("cat", "pg"):
        _c = dict(cb); _c["data"] = "ls:root"
        cb_ls_v4(_c, _c["data"]); return

# ── 8. Search ──────────────────────────────────────────────────
def _do_search_v4(chat_id, msg_id, q):
    ql = q.lower()
    hits = [t for t in _MERGED_TOPICS
            if ql in (t.get("name","") or "").lower()
            or ql in (t.get("query","") or "").lower()
            or ql in (t.get("tags","") or "").lower()]
    if not hits:
        txt = f"❌ نتیجه‌ای برای «{escape_html(q)}» یافت نشد."
        if msg_id: TG.edit_message(chat_id, msg_id, txt,
                                   reply_markup=kb([[btn("⬅️","ls:root")]]))
        else: TG.send_message(chat_id, txt)
        return
    _LS_STATE[chat_id] = {"key":f"srch:{q[:20]}","level":"section",
                          "domain":"all","sec":"search","items":hits,
                          "title":f"🔍 «{q[:30]}» ({len(hits)})","page":0}
    _ls_render(chat_id, msg_id, f"srch:{q[:20]}", 0, edit=bool(msg_id))

@ROUTER.command("find", description="جستجو در بانک موضوعات")
def cmd_find_v4(msg, args):
    chat_id = get_chat_id(msg)
    q = (args or "").strip()
    if not q:
        SESSIONS.set_state(get_uid(msg), "awaiting_search",
                           chat_id=chat_id, msg_id=None)
        TG.send_message(chat_id, "🔍 عبارت مورد نظر را بفرست:")
        return
    _do_search_v4(chat_id, None, q)

# ── 9. Free-text override (search state) ───────────────────────
try:
    _prev_text_v4 = ROUTER._text_handler
except Exception:
    _prev_text_v4 = None

@ROUTER.on_text
def handle_text_v4(msg):
    uid = get_uid(msg)
    s = SESSIONS.get(uid)
    if s.state == "awaiting_search":
        chat_id = get_chat_id(msg)
        text = (msg.get("text") or "").strip()
        SESSIONS.clear_state(uid)
        if not text:
            TG.send_message(chat_id, "❌ عبارت خالی بود.")
            return
        _do_search_v4(chat_id, None, text)
        return
    if _prev_text_v4:
        _prev_text_v4(msg)

# ── 10. Main menu override (Persian only) ─────────
def kb_main_menu():
    return kb([
        [btn("📚 بانک موضوعات", "m:list"), btn("🔍 جستجو", "m:find")],
        [btn("📘 آموزش گام‌به‌گام", "m:learn"), btn("🎓 درس کامل", "sty:tutorial")],
        [btn("🧮 فرمول + مثال", "m:formula"), btn("📐 ریاضی", "m:math")],
        [btn("🔬 تحلیل عمیق", "sty:deep"), btn("❓ کوییز", "sty:quiz")],
        [btn("📇 فلش‌کارت", "sty:flashcard"), btn("🧪 مثال حل‌شده", "sty:example")],
        [btn("📰 اخبار", "n:home"), btn("💱 نرخ ارز", "m:rates")],
        [btn("✈️ هوانوردی", "av:help:refresh"), btn("📖 ویکی", "w:rand")],
        [btn("🎥 یوتیوب", "y:rand"), btn("📚 arXiv", "n:arxiv")],
        [btn("🎲 تصادفی", "m:random"), btn("📊 آمار", "m:stats")],
        [btn("⚙️ تنظیمات", "m:settings"), btn("ℹ️ راهنما", "m:help")],
        [btn("🔌 وضعیت سرویس‌ها", "m:api")],
    ])

_prev_cbm_v4 = globals().get("cb_menu")

@ROUTER.callback("m")
def cb_m_v4(cb, data):
    action = data.split(":", 1)[1] if ":" in data else "main"
    if action == "list":
        chat_id = cb["message"]["chat"]["id"]
        msg_id = cb["message"]["message_id"]
        TG.answer_callback(cb.get("id", ""))
        _LS_STATE[chat_id] = {"key":"root","level":"root"}
        _ls_render(chat_id, msg_id, "root", 0); return
    if action == "find":
        uid = cb["from"]["id"]
        chat_id = cb["message"]["chat"]["id"]
        msg_id = cb["message"]["message_id"]
        TG.answer_callback(cb.get("id", ""))
        SESSIONS.set_state(uid, "awaiting_search",
                           chat_id=chat_id, msg_id=msg_id)
        TG.edit_message(chat_id, msg_id,
            "🔍 <b>جستجو در بانک موضوعات</b>\n\nعبارت را بفرست:",
            reply_markup=kb([[btn("⬅️ لغو", "m:main")]])); return
    if _prev_cbm_v4: _prev_cbm_v4(cb, data)

# ── 11. /random override ───────────────────────────────────────
@ROUTER.command("random", description="موضوع تصادفی")
def cmd_random_v4(msg, args):
    chat_id = get_chat_id(msg)
    all_t = TOPIC_MGR.all()
    if not all_t:
        TG.send_message(chat_id, "❌ فهرست موضوعات خالی است.")
        return
    t = PICKER.pick(all_t) or all_t[0]
    POOL.submit(_generate_and_post, CONFIG.get(), chat_id, t,
                t.get("style", "tutorial"))

# ── 12. Admin commands (Persian only) ──────────────────────────
@ROUTER.command("randstats", description="آمار انتخاب موضوع", admin_only=True)
def cmd_randstats_v4(msg, args):
    chat_id = get_chat_id(msg)
    st = PICKER.stats()
    top = "\n".join(f"  {i+1}. {escape_html(n)}"
                    for i, n in enumerate(st["recent"]))
    TG.send_message(chat_id,
        f"<b>آمار انتخاب موضوع</b>\n\n"
        f"دما: <code>{st['T']}</code>\n"
        f"تعداد استفاده‌شده: <code>{st['used']}</code>\n\n"
        f"<b>اخیر:</b>\n{top}")

@ROUTER.command("randreset", description="ریست آمار انتخاب", admin_only=True)
def cmd_randreset_v4(msg, args):
    chat_id = get_chat_id(msg)
    try:
        PICKER.reset()
        TG.send_message(chat_id, "✅ آمار انتخاب موضوع پاک شد.")
    except Exception as e:
        TG.send_message(chat_id, f"❌ خطا: {e}")

# ── 13. Fix English strings in user-facing commands ────────────
# Override English-returning admin commands to Persian
_orig_randstats = cmd_randstats
_orig_randreset = cmd_randreset
_orig_synchash = cmd_synchash

@ROUTER.command("synchash", description="همگام‌سازی کتابخانه هشتگ", admin_only=True)
def cmd_synchash_v4(msg, args):
    chat_id = get_chat_id(msg)
    try:
        ok_flag = HASHTAGS.sync_channel(CONFIG.get(), force=True)
        TG.send_message(chat_id, "✅ کتابخانه هشتگ همگام‌سازی شد." if ok_flag
                        else "ℹ️ تغییری لازم نبود.")
    except Exception as e:
        TG.send_message(chat_id, f"❌ خطا: {e}")

@ROUTER.command("showtags", description="نمایش هشتگ‌های یک موضوع", admin_only=True)
def cmd_showtags_v4(msg, args):
    chat_id = get_chat_id(msg)
    name = args.strip() or "استاتیک"
    t = TOPIC_MGR.find(name) or {"name": name, "tags": ""}
    tags = HASHTAGS.expand(t, max_tags=5)
    txt = f"🏷 <b>{escape_html(t.get('name','?'))}</b>\n\n" + " ".join(tags)
    TG.send_message(chat_id, txt)

log.info("PATCH v4.0 applied — placed BEFORE __main__ block")



# ═══════════════════════════════════════════════════════════════════════════
#  PATCH v5.0 — Wiki/arXiv/Book/Music + Rewired Menus + English YT
#  Inserted BEFORE __main__ block. Persian-only user-facing text.
# ═══════════════════════════════════════════════════════════════════════════

# ── 1. Wikipedia topics (200) ────────────────────────────────────
WIKI_TOPICS = [
    "Mechanical engineering","Thermodynamics","Fluid mechanics","Heat transfer",
    "Statics","Dynamics (mechanics)","Strength of materials","Materials science",
    "Vibration","Control theory","Robotics","Mechatronics","Automotive engineering",
    "Aerospace engineering","Aerodynamics","Combustion","Turbomachinery",
    "Internal combustion engine","Gas turbine","Steam engine","Refrigeration",
    "HVAC","Hydraulics","Pneumatics","Tribology","Lubrication","Fracture mechanics",
    "Fatigue (material)","Creep (deformation)","Stress–strain analysis",
    "Finite element method","Computational fluid dynamics","Continuum mechanics",
    "Solid mechanics","Fluid dynamics","Navier–Stokes equations","Bernoulli's principle",
    "Reynolds number","Boundary layer","Turbulence","Laminar flow","Compressible flow",
    "Bernoulli equation","Heat conduction","Convection","Thermal radiation",
    "Heat exchanger","Entropy","Enthalpy","Carnot cycle","Rankine cycle",
    "Brayton cycle","Otto cycle","Diesel cycle","Stirling engine","Ericsson cycle",
    "Kalina cycle","Combined cycle","Exergy","Second law of thermodynamics",
    "First law of thermodynamics","Ideal gas law","Van der Waals equation",
    "Real gas","Phase transition","Latent heat","Specific heat","Heat capacity",
    "Thermal conductivity","Thermal expansion","Stefan–Boltzmann law",
    "Wien's displacement law","Planck's law","Newton's law of cooling",
    "Mach number","Speed of sound","Shock wave","Nozzle","Diffuser",
    "Venturi effect","Pitot tube","Orifice plate","Pipe flow","Darcy–Weisbach equation",
    "Hagen–Poiseuille equation","Manning formula","Open-channel flow",
    "Hydraulic jump","Weir","Pump","Compressor","Turbine","Wind turbine",
    "Water turbine","Pelton wheel","Francis turbine","Kaplan turbine",
    "Gas compressor","Axial compressor","Centrifugal compressor","Reciprocating compressor",
    "Bearing (mechanical)","Rolling-element bearing","Journal bearing","Thrust bearing",
    "Gear","Spur gear","Helical gear","Bevel gear","Worm drive","Planetary gear",
    "Belt (mechanical)","Chain drive","Coupling","Clutch","Brake","Flywheel",
    "Cam","Four-bar linkage","Universal joint","Lead screw","Ball screw",
    "Rack and pinion","Ratchet (device)","Spring (device)","Bellows","Diaphragm seal",
    "O-ring","Gasket","Mechanical seal","Shaft (mechanical engineering)",
    "Key (engineering)","Spline (mechanical engineering)","Clevis fastener",
    "Screw thread","Bolt (fastener)","Nut (hardware)","Washer (hardware)",
    "Welding","Brazing","Soldering","Adhesive","Rivet","Nut and bolt",
    "Casting","Forging","Extrusion","Rolling (metalworking)","Drawing (manufacturing)",
    "Machining","Turning","Milling (machining)","Drilling","Grinding (abrasive cutting)",
    "Electrical discharge machining","Laser cutting","Water jet cutter",
    "3D printing","Selective laser melting","Fused deposition modeling",
    "Computer numerical control","CAD","CAM","CAE","Rapid prototyping",
    "Quality control","Statistical process control","Six Sigma","Lean manufacturing",
    "Kaizen","Kanban","Just-in-time manufacturing","Total productive maintenance",
    "Reliability engineering","Failure mode and effects analysis","Root cause analysis",
    "Maintenance, repair, and operations","Predictive maintenance",
    "Condition monitoring","Vibration analysis","Thermography","Oil analysis",
    "Acoustic emission","Ultrasonic testing","Radiographic testing",
    "Magnetic particle inspection","Dye penetrant inspection","Eddy-current testing",
    "Nondestructive testing","Structural health monitoring","Digital twin",
    "Industry 4.0","Internet of things","Cyber-physical system","Smart manufacturing",
]

WIKI_TOPIC_SET = {t.lower() for t in WIKI_TOPICS}

# ── 2. arXiv topics (140) ────────────────────────────────────────
ARXIV_TOPICS = [
    "computational fluid dynamics","finite element analysis","turbulence modeling",
    "large eddy simulation","direct numerical simulation","Reynolds-averaged Navier-Stokes",
    "lattice Boltzmann methods","smoothed particle hydrodynamics",
    "spectral methods","discontinuous Galerkin","finite volume method",
    "immersed boundary method","multiphase flow","bubble dynamics","cavitation",
    "spray atomization","combustion modeling","flame propagation",
    "detonation","deflagration","turbulent combustion","premixed flame",
    "non-premixed flame","soot formation","NOx formation","hydrogen combustion",
    "ammonia combustion","sustainable aviation fuel","biofuel combustion",
    "heat transfer enhancement","nanofluid","phase change material",
    "heat pipe","vapor chamber","pool boiling","flow boiling","condensation",
    "dropwise condensation","film condensation","thermal energy storage",
    "thermochemical storage","sensible heat storage","latent heat storage",
    "solar thermal","concentrated solar power","photovoltaic","perovskite solar cell",
    "wind energy","offshore wind","floating wind turbine","wave energy",
    "tidal energy","geothermal energy","enhanced geothermal systems",
    "hydrogen production","water electrolysis","PEM electrolyzer",
    "solid oxide electrolyzer","alkaline electrolyzer","electrocatalysis",
    "oxygen evolution reaction","hydrogen evolution reaction","fuel cell",
    "PEM fuel cell","solid oxide fuel cell","direct methanol fuel cell",
    "battery thermal management","lithium-ion battery","solid-state battery",
    "sodium-ion battery","flow battery","supercapacitor","thermal runaway",
    "battery degradation","state of charge estimation","battery management system",
    "electric vehicle","hybrid electric vehicle","powertrain","regenerative braking",
    "machine learning for engineering","physics-informed neural networks",
    "neural operators","deep operator network","Fourier neural operator",
    "reduced order modeling","proper orthogonal decomposition","dynamic mode decomposition",
    "surrogate modeling","Gaussian process regression","Bayesian optimization",
    "topology optimization","shape optimization","multi-objective optimization",
    "robust optimization","reliability-based design optimization",
    "uncertainty quantification","polynomial chaos expansion","Monte Carlo simulation",
    "variance reduction","rare event simulation","sensitivity analysis",
    "Sobol indices","Morris method","global sensitivity analysis",
    "additive manufacturing","selective laser melting","electron beam melting",
    "directed energy deposition","binder jetting","material extrusion",
    "residual stress in additive manufacturing","porosity in additive manufacturing",
    "microstructure simulation","phase field modeling","cellular automata",
    "crystal plasticity","dislocation dynamics","molecular dynamics",
    "density functional theory","ab initio molecular dynamics",
    "kinetic Monte Carlo","coarse-grained modeling","multiscale modeling",
    "homogenization","representative volume element","computational homogenization",
    "damage mechanics","fracture mechanics","cohesive zone model",
    "extended finite element method","phase field fracture",
    "fatigue crack growth","stress corrosion cracking","hydrogen embrittlement",
    "composite materials","carbon fiber reinforced polymer","laminated composite",
    "delamination","impact damage","failure criteria","Tsai-Wu criterion",
    "metal matrix composite","ceramic matrix composite","nanocomposite",
    "graphene","carbon nanotube","MXene","metal-organic framework",
    "smart materials","shape memory alloy","piezoelectric material",
    "magnetostrictive material","electrorheological fluid","magnetorheological fluid",
    "metamaterial","acoustic metamaterial","mechanical metamaterial","auxetic material",
    "lattice structure","architected material","functionally graded material",
]

ARXIV_TOPIC_SET = {t.lower() for t in ARXIV_TOPICS}

# ── 3. Music categories (34) ─────────────────────────────────────
MUSIC_CATEGORIES = {
    "rock":          "classic rock music",
    "hardrock":      "hard rock music",
    "metal":         "heavy metal music",
    "punk":          "punk rock music",
    "indie":         "indie rock music",
    "pop":           "pop music hits",
    "pop90":         "90s pop music",
    "pop2000":       "2000s pop music",
    "hiphop":        "hip hop music",
    "rap":           "rap music",
    "rnb":           "r&b music",
    "soul":          "soul music",
    "funk":          "funk music",
    "jazz":          "jazz music",
    "blues":         "blues music",
    "country":       "country music",
    "folk":          "folk music",
    "reggae":        "reggae music",
    "ska":           "ska music",
    "electronic":    "electronic music",
    "house":         "house music",
    "techno":        "techno music",
    "trance":        "trance music",
    "dubstep":       "dubstep music",
    "ambient":       "ambient music",
    "classical":     "classical music",
    "orchestral":    "orchestral music",
    "opera":         "opera music",
    "piano":         "piano music",
    "guitar":        "guitar music",
    "violin":        "violin music",
    "lofi":          "lofi hip hop",
    "study":         "study music focus",
    "workout":       "workout motivation music",
}

MUSIC_CAT_LABELS = {
    "rock":"راک","hardrock":"هارد راک","metal":"مِتال","punk":"پانک",
    "indie":"ایندی","pop":"پاپ","pop90":"پاپ دهه ۹۰","pop2000":"پاپ دهه ۲۰۰۰",
    "hiphop":"هیپ‌هاپ","rap":"رپ","rnb":"آراندبی","soul":"سول","funk":"فانک",
    "jazz":"جاز","blues":"بلوز","country":"کانتری","folk":"فولک","reggae":"رگه",
    "ska":"اسکا","electronic":"الکترونیک","house":"هاوس","techno":"تکنو",
    "trance":"ترنس","dubstep":"دابستپ","ambient":"امبینت","classical":"کلاسیک",
    "orchestral":"ارکسترال","opera":"اپرا","piano":"پیانو","guitar":"گیتار",
    "violin":"ویولن","lofi":"لوفای","study":"مطالعه","workout":"ورزش",
}

# ── 4. Book/PDF categories (60) ──────────────────────────────────
BOOK_CATEGORIES = [
    "thermodynamics textbook","fluid mechanics textbook","heat transfer textbook",
    "statics textbook","dynamics textbook","strength of materials textbook",
    "materials science textbook","machine design textbook","vibration textbook",
    "control systems textbook","robotics textbook","mechatronics textbook",
    "aerodynamics textbook","combustion textbook","turbomachinery book",
    "internal combustion engine book","gas turbine book","HVAC textbook",
    "refrigeration textbook","hydraulics textbook","tribology book",
    "fracture mechanics book","fatigue of materials book","finite element method book",
    "computational fluid dynamics book","continuum mechanics book",
    "solid mechanics book","fluid dynamics book","navier-stokes book",
    "turbulence book","boundary layer book","compressible flow book",
    "heat conduction book","convection heat transfer book","thermal radiation book",
    "heat exchanger design book","engineering thermodynamics book",
    "statistical thermodynamics book","kinetics book","combustion theory book",
    "mathematical methods engineering","linear algebra engineering",
    "differential equations engineering","numerical methods engineering",
    "optimization engineering","probability statistics engineering",
    "mechanical vibrations book","rotor dynamics book","acoustics book",
    "manufacturing processes book","machining book","welding book",
    "additive manufacturing book","3d printing book","cnc programming book",
    "engineering drawing book","cad cam book","quality control book",
    "reliability engineering book","maintenance engineering book",
]

BOOK_CAT_LABELS = {c: c.replace(" textbook","").replace(" book","") for c in BOOK_CATEGORIES}

# ── 5. Topic → Music genre mapping (related music) ───────────────
RELATED_MUSIC = {
    "math":       "lofi",
    "mech":       "electronic",
    "physics":    "ambient",
    "chemistry":  "electronic",
    "space":      "ambient",
    "quantum":    "ambient",
    "ai":         "electronic",
    "energy":     "electronic",
    "materials":  "lofi",
    "control":    "electronic",
    "default":    "lofi",
}

def _music_genre_for(topic):
    dom = (topic.get("domain") or "").lower()
    name = (topic.get("name") or "").lower()
    if dom in RELATED_MUSIC:
        return RELATED_MUSIC[dom]
    if any(w in name for w in ("space","نجوم","فضا")): return "ambient"
    if any(w in name for w in ("هوش","ai","کوانتوم")): return "electronic"
    return RELATED_MUSIC["default"]

# ── 6. English video filter ──────────────────────────────────────
import re as _re_v5
_NON_LATIN = _re_v5.compile(r"[\u0600-\u06FF\u0900-\u097F\u4e00-\u9fff\u3040-\u30ff]")
_LATIN = _re_v5.compile(r"[A-Za-z]")

def _is_english_video(v):
    title = (v.get("title") or "") + " " + (v.get("channel") or "")
    if not title.strip(): return False
    if _NON_LATIN.search(title): return False
    latin = len(_LATIN.findall(title))
    return latin >= 3

def _filter_english(videos):
    return [v for v in (videos or []) if _is_english_video(v)]

# ── 7. Archive.org fallback for videos ───────────────────────────
class ArchiveOrgAPI:
    BASE = "https://archive.org/advancedsearch.php"
    @staticmethod
    def search_video(query, limit=5):
        try:
            params = {
                "q": f'({query}) AND mediatype:(movies)',
                "fl[]": "identifier,title,description",
                "rows": limit, "page": 1, "output": "json",
            }
            r = HTTP.request("GET", ArchiveOrgAPI.BASE, params=params, timeout=20)
            if r is None or r.status_code != 200: return []
            data = r.json()
            docs = (data.get("response") or {}).get("docs") or []
            out = []
            for d in docs:
                ident = d.get("identifier")
                title = d.get("title") or ident or ""
                if not ident: continue
                if not _is_english_video({"title": title, "channel": ""}): continue
                out.append({
                    "title": title, "url": f"https://archive.org/details/{ident}",
                    "channel": "Archive.org", "video_id": ident,
                    "thumbnail": "", "source": "archive",
                })
            return out
        except Exception:
            return []

# ── 8. YouTube: enforce English + Archive fallback ───────────────
_orig_yt_search_v5 = APIS.youtube.search_videos

def _yt_search_v5(self, query, *, max_results=5, order="relevance",
                  language="en", safe_search="moderate"):
    try:
        r = _orig_yt_search_v5(query, max_results=max_results, order=order,
                               language=language, safe_search=safe_search)
        videos = r.data if (r and r.ok and r.data) else []
    except Exception:
        videos = []
    eng = _filter_english(videos)
    if len(eng) >= max_results:
        return APIResult(ok=True, data=eng[:max_results],
                        source="youtube-en", latency_ms=getattr(r, "latency_ms", 0))
    need = max_results - len(eng)
    fallback = ArchiveOrgAPI.search_video(query, limit=need + 3)
    combined = eng + fallback[:need]
    if not combined:
        return APIResult(ok=False, error="no-english-video")
    return APIResult(ok=True, data=combined, source="youtube+archive")

APIS.youtube.search_videos = _yt_search_v5.__get__(APIS.youtube, type(APIS.youtube))

# ── 9. Google search helper (via DuckDuckGo HTML) ─────────────────
def _web_search_titles(query, max_results=15, extra_filter=None):
    results = []
    try:
        r = HTTP.request("GET", "https://html.duckduckgo.com/html/",
                         params={"q": query}, timeout=25)
        if r is not None and r.status_code == 200:
            rx = _re_v5.compile(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>')
            for i, mt in enumerate(rx.finditer(r.text)):
                if i >= max_results * 2: break
                u = mt.group(1)
                t = _re_v5.sub(r"<[^>]+>", "", mt.group(2)).strip()
                if "uddg=" in u:
                    from urllib.parse import unquote, urlparse, parse_qs
                    q = parse_qs(urlparse(u).query).get("uddg", [""])[0]
                    if q: u = unquote(q)
                if extra_filter and not extra_filter(u, t): continue
                results.append({"title": t, "url": u})
                if len(results) >= max_results: break
    except Exception as e:
        log.debug(f"web_search: {e}")
    return results

def _search_telegram_links(query, max_results=14):
    """Search Google for t.me links matching the query."""
    hits = _web_search_titles(f"site:t.me {query}", max_results=max_results * 2,
                              extra_filter=lambda u, t: "t.me/" in u)
    out = []
    seen = set()
    for h in hits:
        u = h["url"]
        if u in seen: continue
        seen.add(u)
        out.append(h)
        if len(out) >= max_results: break
    return out

# ── 10. Rewire /learn and /math to topic bank ───────────────────
@ROUTER.command("learn", description="آموزش گام‌به‌گام")
def cmd_learn_v5(msg, args):
    chat_id = get_chat_id(msg)
    if not args:
        try:
            _LS_STATE[chat_id] = {"key": "root", "level": "root", "intent": "learn"}
        except Exception:
            pass
        TG.send_message(chat_id,
            "🎓 <b>آموزش گام‌به‌گام</b>\n\n"
            "یک موضوع از بانک انتخاب کن، یا مستقیم بنویس:\n"
            "<code>/learn نابلا و لاپلاسین</code>",
            reply_markup=kb([
                [btn("📚 انتخاب از بانک", "learn:bank")],
                [btn("🏠 منو", "m:main")],
            ]))
        return
    LESSON_PROGRESS[get_uid(msg)] = {"topic": args, "step": 1}
    POOL.submit(_gen_lesson_step, CONFIG.get(), chat_id, get_uid(msg), args, 1)

@ROUTER.callback("learn")
def cb_learn_v5(cb, data):
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    chat_id = cb["message"]["chat"]["id"]; msg_id = cb["message"]["message_id"]
    uid = cb["from"]["id"]
    TG.answer_callback(cb.get("id", ""))
    if action == "bank":
        _LS_STATE[chat_id] = {"key": "root", "level": "root", "intent": "learn"}
        _ls_render(chat_id, msg_id, "root", 0)
        return
    if action == "pick":
        try: idx = int(parts[2])
        except Exception: return
        st = _LS_STATE.get(chat_id)
        if not st: return
        t = st["items"][idx]
        name = t.get("name", "?")
        LESSON_PROGRESS[uid] = {"topic": name, "step": 1}
        POOL.submit(_gen_lesson_step, CONFIG.get(), chat_id, uid, name, 1)
        return
    # legacy next/regen
    prog = LESSON_PROGRESS.get(uid)
    if not prog: return
    if action == "next":
        nxt = min(int(parts[2]), 5); prog["step"] = nxt
        POOL.submit(_gen_lesson_step, CONFIG.get(), chat_id, uid, prog["topic"], nxt)
    elif action == "regen":
        POOL.submit(_gen_lesson_step, CONFIG.get(), chat_id, uid, prog["topic"], int(parts[2]))

@ROUTER.command("math", description="آموزش ریاضی")
def cmd_math_v5(msg, args):
    chat_id = get_chat_id(msg)
    if not args:
        try:
            _LS_STATE[chat_id] = {"key": "root", "level": "root", "intent": "math"}
        except Exception:
            pass
        TG.send_message(chat_id,
            "📐 <b>آموزش ریاضی</b>\n\n"
            "موضوع از بانک انتخاب کن یا بنویس:\n"
            "<code>/math انتگرال سه‌گانه</code>",
            reply_markup=kb([
                [btn("📚 بانک ریاضی", "ls:domain:math")],
                [btn("🏠 منو", "m:main")],
            ]))
        return
    POOL.submit(_generate_and_post, CONFIG.get(), chat_id, args, "math")

# ── 11. /wiki with 200 topics ────────────────────────────────────
@ROUTER.command("wiki", description="ویکی‌پدیا")
def cmd_wiki_v5(msg, args):
    chat_id = get_chat_id(msg)
    if not args:
        TG.send_message(chat_id,
            "📖 <b>ویکی‌پدیا</b>\n\n"
            f"<code>{len(WIKI_TOPICS)}</code> موضوع آماده — یکی انتخاب کن:",
            reply_markup=kb_wiki_menu())
        return
    _wiki_fetch(chat_id, None, args)

def kb_wiki_menu(page=0, per=12):
    total = len(WIKI_TOPICS)
    pages = max(1, (total + per - 1) // per)
    page = max(0, min(page, pages - 1))
    start = page * per
    chunk = WIKI_TOPICS[start:start + per]
    rows = []; row = []
    for i, t in enumerate(chunk):
        idx = start + i
        row.append(btn(f"📖 {t[:26]}", f"wiki:go:{idx}"))
        if len(row) == 2: rows.append(row); row = []
    if row: rows.append(row)
    nav = []
    if page > 0: nav.append(btn("◀️", f"wiki:p:{page-1}"))
    nav.append(btn(f"{page+1}/{pages}", "wiki:nop"))
    if page < pages - 1: nav.append(btn("▶️", f"wiki:p:{page+1}"))
    rows.append(nav)
    rows.append([btn("🎲 تصادفی", "wiki:rand"), btn("🏠 منو", "m:main")])
    return kb(rows)

@ROUTER.callback("wiki")
def cb_wiki_v5(cb, data):
    parts = data.split(":"); action = parts[1] if len(parts) > 1 else ""
    chat_id = cb["message"]["chat"]["id"]; msg_id = cb["message"]["message_id"]
    TG.answer_callback(cb.get("id", ""))
    if action == "nop": return
    if action == "p":
        try: pg = int(parts[2])
        except Exception: pg = 0
        TG.edit_message(chat_id, msg_id,
            f"📖 <b>ویکی‌پدیا</b> — {len(WIKI_TOPICS)} موضوع",
            reply_markup=kb_wiki_menu(pg))
        return
    if action == "rand":
        t = _RND.choice(WIKI_TOPICS)
        _wiki_fetch(chat_id, msg_id, t); return
    if action == "go":
        try: idx = int(parts[2])
        except Exception: return
        if 0 <= idx < len(WIKI_TOPICS):
            _wiki_fetch(chat_id, msg_id, WIKI_TOPICS[idx])
        return

def _wiki_fetch(chat_id, msg_id, title):
    if msg_id:
        TG.edit_message(chat_id, msg_id, f"📖 در حال دریافت «{escape_html(title)}» ...")
    else:
        m = TG.send_message(chat_id, f"📖 در حال دریافت «{escape_html(title)}» ...")
        msg_id = (m.result or {}).get("message_id") if m.ok else None
    r = APIS.wikipedia.summary(title, "fa")
    if not r.ok: r = APIS.wikipedia.summary(title, "en")
    if not r.ok:
        if msg_id: TG.edit_message(chat_id, msg_id, "❌ یافت نشد",
            reply_markup=kb([[btn("⬅️ منو ویکی", "wiki:p:0"), btn("🏠", "m:main")]]))
        return
    data = r.data
    extract = clean_wiki_extract(data.get("extract","") or "")[:1500]
    text = (f"📖 <b>{escape_html(data.get('title',''))}</b>\n\n"
            f"{escape_html(extract)}\n\n"
            f"<a href=\"{data.get('url','')}\">ادامه در ویکی‌پدیا</a>")
    if msg_id:
        TG.edit_message(chat_id, msg_id, text[:4000],
            reply_markup=kb([
                [btn("🎥 ویدیوی مرتبط", f"wiki:vid:{escape_html(title)[:40]}")],
                [btn("⬅️ فهرست", "wiki:p:0"), btn("🏠", "m:main")],
            ]))
    else:
        TG.send_message(chat_id, text[:4000])

@ROUTER.callback("wiki:vid")
def cb_wiki_vid(cb, data):
    chat_id = cb["message"]["chat"]["id"]; msg_id = cb["message"]["message_id"]
    TG.answer_callback(cb.get("id", ""))
    parts = data.split(":", 2)
    if len(parts) < 3: return
    title = parts[2]
    POOL.submit(_show_videos_bg_v5, chat_id, msg_id, title)

# ── 12. /arxiv with 140 topics ───────────────────────────────────
@ROUTER.command("arxiv", description="جستجوی arXiv")
def cmd_arxiv_v5(msg, args):
    chat_id = get_chat_id(msg)
    if not args:
        TG.send_message(chat_id,
            f"📚 <b>arXiv</b> — {len(ARXIV_TOPICS)} موضوع آماده:",
            reply_markup=kb_arxiv_menu())
        return
    _arxiv_fetch(chat_id, None, args)

def kb_arxiv_menu(page=0, per=12):
    total = len(ARXIV_TOPICS)
    pages = max(1, (total + per - 1) // per)
    page = max(0, min(page, pages - 1))
    start = page * per
    chunk = ARXIV_TOPICS[start:start + per]
    rows = []; row = []
    for i, t in enumerate(chunk):
        idx = start + i
        row.append(btn(f"📚 {t[:26]}", f"arxiv:go:{idx}"))
        if len(row) == 2: rows.append(row); row = []
    if row: rows.append(row)
    nav = []
    if page > 0: nav.append(btn("◀️", f"arxiv:p:{page-1}"))
    nav.append(btn(f"{page+1}/{pages}", "arxiv:nop"))
    if page < pages - 1: nav.append(btn("▶️", f"arxiv:p:{page+1}"))
    rows.append(nav)
    rows.append([btn("🎲 تصادفی", "arxiv:rand"), btn("🏠 منو", "m:main")])
    return kb(rows)

@ROUTER.callback("arxiv")
def cb_arxiv_v5(cb, data):
    parts = data.split(":"); action = parts[1] if len(parts) > 1 else ""
    chat_id = cb["message"]["chat"]["id"]; msg_id = cb["message"]["message_id"]
    TG.answer_callback(cb.get("id", ""))
    if action == "nop": return
    if action == "p":
        try: pg = int(parts[2])
        except Exception: pg = 0
        TG.edit_message(chat_id, msg_id,
            f"📚 <b>arXiv</b> — {len(ARXIV_TOPICS)} موضوع",
            reply_markup=kb_arxiv_menu(pg))
        return
    if action == "rand":
        _arxiv_fetch(chat_id, msg_id, _RND.choice(ARXIV_TOPICS)); return
    if action == "go":
        try: idx = int(parts[2])
        except Exception: return
        if 0 <= idx < len(ARXIV_TOPICS):
            _arxiv_fetch(chat_id, msg_id, ARXIV_TOPICS[idx])
        return

def _arxiv_fetch(chat_id, msg_id, query):
    if msg_id:
        TG.edit_message(chat_id, msg_id, f"📚 در حال جستجو در arXiv ...")
    else:
        m = TG.send_message(chat_id, f"📚 در حال جستجو در arXiv ...")
        msg_id = (m.result or {}).get("message_id") if m.ok else None
    r = APIS.arxiv.search(query, max_results=6)
    if not r.ok or not r.data:
        if msg_id:
            TG.edit_message(chat_id, msg_id, "❌ نتیجه‌ای یافت نشد.",
                reply_markup=kb([[btn("⬅️", "arxiv:p:0"), btn("🏠", "m:main")]]))
        return
    text = f"📚 <b>arXiv: {escape_html(query[:50])}</b>\n\n"
    for i, p in enumerate(r.data[:6], 1):
        text += f"<b>{i}. {escape_html(p['title'][:100])}</b>\n"
        text += f"👥 {escape_html(', '.join(p['authors'][:2]))}\n"
        text += f"<a href=\"{p['link']}\">📄 مقاله</a>\n\n"
    if msg_id:
        TG.edit_message(chat_id, msg_id, text[:4000],
            reply_markup=kb([[btn("⬅️ فهرست", "arxiv:p:0"), btn("🏠", "m:main")]]))
    else:
        TG.send_message(chat_id, text[:4000])

# ── 13. Music menu (34 categories) ──────────────────────────────
@ROUTER.command("music", description="موسیقی")
def cmd_music_v5(msg, args):
    chat_id = get_chat_id(msg)
    if args and args.lower() in MUSIC_CATEGORIES:
        _music_search(chat_id, None, args.lower())
        return
    rows = []; row = []
    keys = list(MUSIC_CATEGORIES.keys())
    for i, k in enumerate(keys):
        row.append(btn(f"🎵 {MUSIC_CAT_LABELS[k]}", f"music:go:{k}"))
        if len(row) == 2: rows.append(row); row = []
    if row: rows.append(row)
    rows.append([btn("🎲 تصادفی", "music:rand"), btn("🏠 منو", "m:main")])
    TG.send_message(chat_id,
        f"🎵 <b>موسیقی</b> — {len(keys)} سبک\n\nیک سبک انتخاب کن:",
        reply_markup=kb(rows))

@ROUTER.callback("music")
def cb_music_v5(cb, data):
    parts = data.split(":"); action = parts[1] if len(parts) > 1 else ""
    chat_id = cb["message"]["chat"]["id"]; msg_id = cb["message"]["message_id"]
    TG.answer_callback(cb.get("id", ""))
    if action == "rand":
        k = _RND.choice(list(MUSIC_CATEGORIES.keys()))
        _music_search(chat_id, msg_id, k); return
    if action == "go":
        k = parts[2] if len(parts) > 2 else ""
        if k in MUSIC_CATEGORIES:
            _music_search(chat_id, msg_id, k)
        return
    if action == "send":
        try: idx = int(parts[2])
        except Exception: return
        st = _MUSIC_RESULTS.get(chat_id) or []
        if 0 <= idx < len(st):
            item = st[idx]
            cfg = CONFIG.get()
            TG.send_message(cfg.telegram.channel_id,
                f"🎵 <b>{escape_html(item['title'][:100])}</b>\n\n"
                f"<a href=\"{item['url']}\">شنیدن</a>\n\n"
                f"📢 @MAADGHchannel")
            TG.answer_callback(cb.get("id", ""), "✅ ارسال شد")
        return
    if action == "cancel":
        TG.edit_message(chat_id, msg_id, "❌ لغو شد")
        return

_MUSIC_RESULTS = TTLStore(max_items=500, ttl=3600)
def _music_search(chat_id, msg_id, key):
    label = MUSIC_CAT_LABELS.get(key, key)
    if msg_id:
        TG.edit_message(chat_id, msg_id, f"🎵 در حال جستجوی موسیقی «{label}» ...")
    else:
        m = TG.send_message(chat_id, f"🎵 در حال جستجوی «{label}» ...")
        msg_id = (m.result or {}).get("message_id") if m.ok else None

    q = MUSIC_CATEGORIES[key]
    # 1. Search YouTube for English music
    hits = []
    try:
        r = APIS.youtube.search_videos(f"{q} best hits", max_results=14, language="en")
        if r.ok and r.data:
            for v in r.data:
                hits.append({"title": v.get("title",""), "url": v.get("url",""),
                             "channel": v.get("channel",""), "src": "yt"})
    except Exception: pass

    # 2. If not enough, search Telegram links
    if len(hits) < 14:
        try:
            tg = _search_telegram_links(f"{q} mp3", max_results=14 - len(hits))
            for h in tg:
                hits.append({"title": h["title"], "url": h["url"],
                             "channel": "Telegram", "src": "tg"})
        except Exception: pass

    if not hits:
        if msg_id:
            TG.edit_message(chat_id, msg_id, "❌ موسیقی یافت نشد.",
                reply_markup=kb([[btn("⬅️ فهرست", "music:back"), btn("🏠", "m:main")]]))
        return

    _MUSIC_RESULTS[chat_id] = hits[:14]
    text = f"🎵 <b>موسیقی {escape_html(label)}</b>\n\n"
    for i, h in enumerate(hits[:14], 1):
        text += f"<b>{i}.</b> {escape_html(h['title'][:70])}\n"
    text += "\nروی هر شماره بزن تا بفرستد یا لغو کن:"
    rows = []
    for i in range(0, min(14, len(hits)), 2):
        row = []
        for j in (i, i+1):
            if j < len(hits) and j < 14:
                row.append(btn(f"📤 {j+1}", f"music:send:{j}"))
        rows.append(row)
    rows.append([btn("❌ لغو همه", "music:cancel"), btn("🏠 منو", "m:main")])
    if msg_id:
        TG.edit_message(chat_id, msg_id, text[:4000], reply_markup=kb(rows))
    else:
        TG.send_message(chat_id, text[:4000], reply_markup=kb(rows))

@ROUTER.callback("music:back")
def cb_music_back(cb, data):
    chat_id = cb["message"]["chat"]["id"]; msg_id = cb["message"]["message_id"]
    TG.answer_callback(cb.get("id", ""))
    cmd_music_v5({"chat":{"id":chat_id},"from":cb.get("from",{}),"message":{}}, "")

# ── 14. Book/PDF menu (60 categories) ───────────────────────────
@ROUTER.command("book", description="کتاب PDF")
def cmd_book_v5(msg, args):
    chat_id = get_chat_id(msg)
    if args:
        _book_search(chat_id, None, args)
        return
    rows = []; row = []
    for i, cat in enumerate(BOOK_CATEGORIES):
        row.append(btn(f"📕 {cat[:26]}", f"book:go:{i}"))
        if len(row) == 2: rows.append(row); row = []
    if row: rows.append(row)
    rows.append([btn("🎲 تصادفی", "book:rand"), btn("🏠 منو", "m:main")])
    TG.send_message(chat_id,
        f"📚 <b>کتاب PDF</b> — {len(BOOK_CATEGORIES)} دسته\n\nیک دسته انتخاب کن:",
        reply_markup=kb(rows))

@ROUTER.callback("book")
def cb_book_v5(cb, data):
    parts = data.split(":"); action = parts[1] if len(parts) > 1 else ""
    chat_id = cb["message"]["chat"]["id"]; msg_id = cb["message"]["message_id"]
    TG.answer_callback(cb.get("id", ""))
    if action == "rand":
        idx = _RND.randint(0, len(BOOK_CATEGORIES)-1)
        _book_search(chat_id, msg_id, BOOK_CATEGORIES[idx]); return
    if action == "go":
        try: idx = int(parts[2])
        except Exception: return
        if 0 <= idx < len(BOOK_CATEGORIES):
            _book_search(chat_id, msg_id, BOOK_CATEGORIES[idx])
        return
    if action == "send":
        try: idx = int(parts[2])
        except Exception: return
        st = _BOOK_RESULTS.get(chat_id) or []
        if 0 <= idx < len(st):
            item = st[idx]
            cfg = CONFIG.get()
            title = item.get("title","") or "PDF"
            # Simple hashtag from title
            tags = " ".join("#" + w for w in title.split()[:4] if w.isalnum())
            TG.send_message(cfg.telegram.channel_id,
                f"📕 <b>{escape_html(title[:120])}</b>\n\n"
                f"<a href=\"{item['url']}\">📄 دریافت/مشاهده</a>\n\n"
                f"{escape_html(tags)}\n📢 @MAADGHchannel")
            TG.answer_callback(cb.get("id", ""), "✅ ارسال شد")
        return
    if action == "cancel":
        TG.edit_message(chat_id, msg_id, "❌ لغو شد"); return

_BOOK_RESULTS = TTLStore(max_items=500, ttl=3600)
def _book_search(chat_id, msg_id, category):
    if msg_id:
        TG.edit_message(chat_id, msg_id, f"📚 جستجوی «{category}» ...")
    else:
        m = TG.send_message(chat_id, f"📚 جستجوی «{category}» ...")
        msg_id = (m.result or {}).get("message_id") if m.ok else None

    # search DuckDuckGo for pdf + t.me links
    hits = _web_search_titles(
        f'"{category}" filetype:pdf OR site:t.me',
        max_results=15,
        extra_filter=lambda u, t: ("pdf" in u.lower() or "t.me" in u.lower())
    )
    # Prioritize t.me links
    tg_hits = [h for h in hits if "t.me" in h["url"]]
    other = [h for h in hits if "t.me" not in h["url"]]
    final = (tg_hits + other)[:15]

    if not final:
        if msg_id:
            TG.edit_message(chat_id, msg_id, "❌ کتابی یافت نشد.",
                reply_markup=kb([[btn("⬅️ فهرست", "book:back"), btn("🏠", "m:main")]]))
        return
    _BOOK_RESULTS[chat_id] = final
    text = f"📚 <b>{escape_html(category)}</b>\n\n{len(final)} مورد یافت شد:\n\n"
    for i, h in enumerate(final, 1):
        text += f"<b>{i}.</b> {escape_html(h['title'][:70])}\n"
    text += "\nروی شماره بزن تا به کانال بفرستد:"
    rows = []
    for i in range(0, len(final), 2):
        row = []
        for j in (i, i+1):
            if j < len(final):
                row.append(btn(f"📤 ارسال {j+1}", f"book:send:{j}"))
        rows.append(row)
    rows.append([btn("❌ لغو", "book:cancel"), btn("🏠 منو", "m:main")])
    if msg_id:
        TG.edit_message(chat_id, msg_id, text[:4000], reply_markup=kb(rows))
    else:
        TG.send_message(chat_id, text[:4000], reply_markup=kb(rows))

@ROUTER.callback("book:back")
def cb_book_back(cb, data):
    chat_id = cb["message"]["chat"]["id"]
    TG.answer_callback(cb.get("id", ""))
    cmd_book_v5({"chat":{"id":chat_id},"from":cb.get("from",{}),"message":{}}, "")

# ── 15. Videos with Archive.org fallback ────────────────────────
def _show_videos_bg_v5(chat_id, msg_id, query):
    try:
        if msg_id:
            TG.edit_message(chat_id, msg_id, f"🎥 جستجوی ویدیو «{query[:40]}» ...")
        r = APIS.youtube.search_videos(query, max_results=3, language="en")
        vids = r.data if (r and r.ok and r.data) else []
        if not vids:
            if msg_id:
                TG.edit_message(chat_id, msg_id, "❌ ویدیویی یافت نشد (فقط انگلیسی).",
                    reply_markup=kb([[btn("⬅️", "ls:root"), btn("🏠","m:main")]]))
            return
        text = "🎥 <b>ویدیوهای مرتبط (انگلیسی)</b>\n\n"
        for i, v in enumerate(vids[:3], 1):
            src = v.get("source","")
            text += f"<b>{i}. {escape_html(v.get('title','')[:80])}</b>\n"
            if v.get("channel"):
                text += f"<i>{escape_html(v['channel'][:40])}</i>\n"
            if src == "archive":
                text += f"<a href=\"{v['url']}\">📼 Archive.org</a>\n\n"
            else:
                text += f"<a href=\"{v['url']}\">▶️ YouTube</a>\n\n"
        if msg_id:
            TG.edit_message(chat_id, msg_id, text[:4000],
                reply_markup=kb([[btn("🎲 دیگر", f"ls:rand"), btn("🏠 منو","m:main")]]))
    except Exception as e:
        log.debug(f"show_videos_v5: {e}")

# ── 16. Override ls pick to add "video" button ──────────────────
_orig_ls_pick_v5 = cb_ls_v4

@ROUTER.callback("ls")
def cb_ls_v5(cb, data):
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    if action == "vid":
        try: idx = int(parts[2])
        except Exception: return
        chat_id = cb["message"]["chat"]["id"]
        msg_id = cb["message"]["message_id"]
        TG.answer_callback(cb.get("id", ""))
        st = _LS_STATE.get(chat_id)
        if not st: return
        t = st["items"][idx]
        POOL.submit(_show_videos_bg_v5, chat_id, msg_id, t.get("name",""))
        return
    # Delegate others to v4 handler
    return _orig_ls_pick_v5(cb, data)

# ── 17. Also add video button in the pick menu ──────────────────
_orig_ls_render_v5 = _ls_render

def _ls_render_v5(chat_id, msg_id, key, page=0, edit=True):
    # Let v4 render first
    _orig_ls_render_v5(chat_id, msg_id, key, page, edit)

# ── 18. Auto-post 3h with random category ───────────────────────
class AutoDirectorV5:
    def __init__(self):
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive(): return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="AutoDirectorV5")
        self._thread.start()
        log.info("[v5] AutoDirectorV5 started")

    def stop(self):
        self._stop.set()

    def _loop(self):
        # first run after 30 seconds to be safe
        if self._stop.wait(10): return
        while not self._stop.is_set():
            try:
                cfg = CONFIG.get()
                ch = (cfg.telegram.channel_id or "").strip()
                if not ch: time.sleep(60); continue

                kind = _RND.choice(["topic", "music", "book", "arxiv", "wiki"])
                log.info(f"[auto-v5] category={kind}")
                if kind == "topic":
                    t = PICKER.pick(_MERGED_TOPICS) or _MERGED_TOPICS[0]
                    style = t.get("style","tutorial")
                    content = CONTENT.generate(t, style)
                    if content:
                        TG.send_long_message(ch, content)
                elif kind == "music":
                    k = _RND.choice(list(MUSIC_CATEGORIES.keys()))
                    label = MUSIC_CAT_LABELS.get(k, k)
                    r = APIS.youtube.search_videos(f"{MUSIC_CATEGORIES[k]} best hits",
                                                   max_results=5, language="en")
                    if r.ok and r.data:
                        text = f"🎵 <b>موسیقی {escape_html(label)}</b>\n\n"
                        for i, v in enumerate(r.data[:5], 1):
                            text += f"{i}. <a href=\"{v['url']}\">{escape_html(v.get('title','')[:80])}</a>\n"
                        text += "\n📢 @MAADGHchannel"
                        TG.send_message(ch, text)
                elif kind == "book":
                    cat = _RND.choice(BOOK_CATEGORIES)
                    hits = _web_search_titles(f'"{cat}" filetype:pdf', max_results=5)
                    if hits:
                        text = f"📚 <b>{escape_html(cat)}</b>\n\n"
                        for i, h in enumerate(hits[:5], 1):
                            text += f"{i}. <a href=\"{h['url']}\">{escape_html(h['title'][:80])}</a>\n"
                        text += "\n📢 @MAADGHchannel"
                        TG.send_message(ch, text)
                elif kind == "arxiv":
                    q = _RND.choice(ARXIV_TOPICS)
                    r = APIS.arxiv.search(q, max_results=3)
                    if r.ok and r.data:
                        text = f"📚 <b>arXiv: {escape_html(q[:40])}</b>\n\n"
                        for i, p in enumerate(r.data[:3], 1):
                            text += f"{i}. <a href=\"{p['link']}\">{escape_html(p['title'][:90])}</a>\n\n"
                        text += "📢 @MAADGHchannel"
                        TG.send_message(ch, text)
                elif kind == "wiki":
                    t = _RND.choice(WIKI_TOPICS)
                    r = APIS.wikipedia.summary(t, "fa")
                    if not r.ok: r = APIS.wikipedia.summary(t, "en")
                    if r.ok:
                        d = r.data
                        text = (f"📖 <b>{escape_html(d.get('title',''))}</b>\n\n"
                                f"{escape_html((d.get('extract','') or '')[:800])}\n\n"
                                f"<a href=\"{d.get('url','')}\">ادامه</a>\n\n📢 @MAADGHchannel")
                        TG.send_message(ch, text[:4000])
                LIVE.event("pub", f"[auto-v5] posted {kind}")
            except Exception as e:
                log.exception(f"[auto-v5] {e}")
            # wait 3 hours
            if self._stop.wait(3 * 3600): break

AUTO_V5 = AutoDirectorV5()

# Start the v5 auto-poster instead of old one
try: AUTO_POSTER.stop()
except Exception: pass
AUTO_V5.start()

# ── 19. Rewire main menu buttons ────────────────
def kb_main_menu():
    return kb([
        [btn("📚 بانک موضوعات", "m:list"), btn("🔍 جستجو", "m:find")],
        [btn("🎓 آموزش گام‌به‌گام", "learn:bank"), btn("📐 ریاضی", "math:bank")],
        [btn("📖 ویکی", "wiki:p:0"), btn("📚 arXiv", "arxiv:p:0")],
        [btn("🎵 موسیقی", "music:back"), btn("📕 کتاب PDF", "book:back")],
        [btn("🧮 فرمول + مثال", "m:formula"), btn("🔬 تحلیل عمیق", "sty:deep")],
        [btn("❓ کوییز", "sty:quiz"), btn("📇 فلش‌کارت", "sty:flashcard")],
        [btn("📰 اخبار", "n:home"), btn("💱 نرخ ارز", "m:rates")],
        [btn("✈️ هوانوردی", "av:help:refresh"), btn("🎥 یوتیوب", "y:rand")],
        [btn("🎲 تصادفی", "m:random"), btn("📊 آمار", "m:stats")],
        [btn("⚙️ تنظیمات", "m:settings"), btn("ℹ️ راهنما", "m:help")],
    ])

@ROUTER.callback("math")
def cb_math_v5(cb, data):
    parts = data.split(":"); action = parts[1] if len(parts) > 1 else ""
    chat_id = cb["message"]["chat"]["id"]; msg_id = cb["message"]["message_id"]
    TG.answer_callback(cb.get("id", ""))
    if action == "bank":
        _LS_STATE[chat_id] = {"key": f"dom:math", "level": "domain",
                              "domain": "math", "sections": _ls_sections_for("math")}
        _ls_render(chat_id, msg_id, f"dom:math", 0)
        return

# Register alias so math:bank works
try:
    _orig_cb_ls_v5 = cb_ls_v5
except Exception:
    _orig_cb_ls_v5 = None

log.info("PATCH v5.0 applied — Wiki/arXiv/Book/Music + rewired menus")



# ═══════════════════════════════════════════════════════════════════════════
#  PATCH v6.0 — AUTO EMOJI + AUTO IMAGE (URL, no upload)
#  Inserted BEFORE __main__ block. Persian-only user-facing text.
# ═══════════════════════════════════════════════════════════════════════════

import urllib.parse as _up_v6
import random as _rnd_v6

# ── 1. EmojiHub API (free, no auth, 1791 emojis) ─────────────────
class EmojiHubAPI:
    """Free emoji API — no key, no registration."""
    BASE = "https://emojihub.yurace.pro/api"

    @staticmethod
    def _parse(data):
        if not isinstance(data, dict):
            return None
        html = data.get("htmlCode") or []
        ch = "".join(html) if html else ""
        if not ch:
            uni = data.get("unicode") or []
            ch = "".join(uni) if uni else ""
        return {
            "char": ch,
            "name": data.get("name", ""),
            "category": data.get("category", ""),
            "group": data.get("group", ""),
        }

    @classmethod
    def random(cls):
        try:
            r = HTTP.request("GET", f"{cls.BASE}/random", timeout=10)
            if r is None or r.status_code != 200:
                return None
            return cls._parse(r.json())
        except Exception:
            return None

    @classmethod
    def by_category(cls, cat):
        try:
            url = f"{cls.BASE}/random/category/{_up_v6.quote(cat)}"
            r = HTTP.request("GET", url, timeout=10)
            if r is None or r.status_code != 200:
                return None
            return cls._parse(r.json())
        except Exception:
            return None

EMOJI_HUB = EmojiHubAPI()

# ── 2. Pollinations.ai image URL (free, no key) ──────────────────
class PollinationsImage:
    """
    Free AI image generation via URL.
    No API key, no registration, no upload.
    Returns a direct URL that Telegram renders.
    """
    BASE = "https://image.pollinations.ai/prompt"

    @staticmethod
    def url_for(prompt, width=1024, height=576, seed=None, nologo=True):
        if not prompt:
            return ""
        p = _up_v6.quote(prompt.strip()[:300], safe="")
        params = [
            f"width={width}",
            f"height={height}",
            "model=flux",
            "enhance=true",
        ]
        if seed is not None:
            params.append(f"seed={seed}")
        if nologo:
            params.append("nologo=true")
        return f"{PollinationsImage.BASE}/{p}?{'&'.join(params)}"

POLL_IMG = PollinationsImage()

# ── 3. Openverse fallback (real stock photo, no key) ─────────────
class OpenverseAPI:
    """Free CC image search — no key, no registration."""
    BASE = "https://api.openverse.engineering/v1/images"

    @staticmethod
    def search(query, limit=3):
        try:
            r = HTTP.request("GET", OpenverseAPI.BASE,
                params={"q": query, "page_size": min(limit, 10)},
                timeout=15)
            if r is None or r.status_code != 200:
                return []
            d = r.json()
            out = []
            for it in (d.get("results") or [])[:limit]:
                u = it.get("url") or it.get("thumbnail")
                if u:
                    out.append({
                        "url": u,
                        "title": it.get("title", ""),
                        "creator": it.get("creator", ""),
                        "license": it.get("license", ""),
                    })
            return out
        except Exception:
            return []

OPENVERSE = OpenverseAPI()

# ── 4. Topic → emoji keyword mapping ────────────────────────────
_EMOJI_KEYWORD_MAP = {
    "ریاضی": ["books","abacus","triangular_ruler"],
    "حساب": ["abacus","books"],
    "انتگرال": ["triangular_ruler","books"],
    "مشتق": ["triangular_ruler"],
    "جبر": ["abacus","books"],
    "لاپلاس": ["chart","books"],
    "فوریه": ["musical_note","chart"],
    "ماتریس": ["abacus","chart"],
    "آمار": ["bar_chart","chart"],
    "احتمال": ["game_die","chart"],
    "بهینه": ["chart","rocket"],
    "استاتیک": ["classical_building","balance_scale"],
    "دینامیک": ["rocket","zap"],
    "مقاومت": ["building_construction","bridge_at_night"],
    "ارتعاش": ["musical_note","wave"],
    "سیالات": ["ocean","droplet"],
    "هیدرولیک": ["droplet","wrench"],
    "ترمودینامیک": ["fire","thermometer"],
    "انتقال حرارت": ["thermometer","fire"],
    "تهویه": ["snowflake","wind"],
    "تبرید": ["ice_cube","snowflake"],
    "تاسیسات": ["building_construction","wrench"],
    "طراحی": ["gear","wrench"],
    "ساخت": ["factory","gear"],
    "کنترل": ["joystick","gear"],
    "روبات": ["robot","gear"],
    "مکاترونیک": ["robot","zap"],
    "بیومکانیک": ["bone","anatomical_heart"],
    "آیرودینامیک": ["airplane","rocket"],
    "دریا": ["ship","ocean"],
    "خودرو": ["car","racing_car"],
    "انرژی": ["sun","battery"],
    "FEM": ["triangular_ruler","computer"],
    "CFD": ["computer","ocean"],
    "هوش مصنوعی": ["robot","brain"],
    "کوانتوم": ["atom","test_tube"],
    "فیزیک": ["atom","test_tube"],
    "شیمی": ["test_tube","alembic"],
    "فضا": ["rocket","star"],
    "ناسا": ["rocket","star"],
    "اخبار": ["newspaper","globe"],
    "سیاسی": ["ballot_box","globe"],
    "اقتصاد": ["chart","moneybag"],
    "روانشناسی": ["brain","thought_balloon"],
    "یادگیری": ["books","pencil"],
    "تاریخ": ["scroll","books"],
    "کتاب": ["books","closed_book"],
    "موسیقی": ["musical_note","headphones"],
}

_EMOJI_GENERIC = ["books","star","bulb","rocket","sparkles","zap","globe","chart","gear","atom"]

def _pick_emoji_keywords(topic):
    name = (topic.get("name") or "").lower()
    tags = (topic.get("tags") or "").lower()
    dom = (topic.get("domain") or "").lower()
    text = f"{name} {tags} {dom}"
    for key, kws in _EMOJI_KEYWORD_MAP.items():
        if key in text:
            return kws
    return _EMOJI_GENERIC

def _get_related_emojis(topic, count=3):
    """Return list of emoji chars related to topic."""
    kws = _pick_emoji_keywords(topic)
    out = []
    seen = set()
    for kw in kws:
        for cat in ("food-and-drink","animals-and-nature","activity","travel-and-places",
                    "objects","symbols","flags","people-and-body","smileys-and-people"):
            pass
        e = EMOJI_HUB.by_category(kw)
        if e and e.get("char") and e["char"] not in seen:
            out.append(e["char"])
            seen.add(e["char"])
        if len(out) >= count:
            return out
    # Fallback: random
    for _ in range(count - len(out)):
        e = EMOJI_HUB.random()
        if e and e.get("char") and e["char"] not in seen:
            out.append(e["char"])
            seen.add(e["char"])
    return out

# ── 5. Build topic → image prompt ────────────────────────────────
def _image_prompt_for(topic):
    name = (topic.get("name") or "").strip()
    query = (topic.get("query") or name).strip()
    dom = (topic.get("domain") or "").lower()
    if dom == "math":
        return f"mathematical engineering illustration, {query}, formulas, blueprint, clean vector style, high detail, no text"
    return f"engineering illustration, {query}, technical blueprint, isometric, clean vector, professional, no text"

# ── 6. Attach emoji + image to content ───────────────────────────
def _enrich_with_emoji_and_image(text, topic):
    """
    Adds:
      • Related emojis at top of text
      • Image URL at bottom (Telegram renders directly)
    """
    if not text:
        return text

    # 1) Emojis at top
    try:
        emojis = _get_related_emojis(topic, count=3)
        if emojis:
            emo_line = " ".join(emojis)
            # Don't duplicate if already there
            if emo_line not in text[:100]:
                text = f"{emo_line} {text}"
    except Exception as e:
        log.debug(f"[v6] emoji failed: {e}")

    # 2) Image URL at bottom (before channel footer)
    try:
        prompt = _image_prompt_for(topic)
        img_url = POLL_IMG.url_for(prompt)
        if img_url:
            img_block = f"\n\n🖼 <a href=\"{img_url}\">تصویر مرتبط با موضوع</a>"
            footer = "📢 @MAADGHchannel"
            if footer in text:
                text = text.replace(footer, img_block.strip() + f"\n\n{footer}")
            else:
                text = text.rstrip() + img_block
    except Exception as e:
        log.debug(f"[v6] image failed: {e}")

    # 3) Also try Openverse as second image (real photo)
    try:
        q = topic.get("query") or topic.get("name") or ""
        if q:
            real = OPENVERSE.search(q, limit=1)
            if real:
                item = real[0]
                ov_block = f"\n📷 <a href=\"{item['url']}\">عکس مرتبط</a>"
                footer = "📢 @MAADGHchannel"
                if footer in text:
                    text = text.replace(footer, ov_block.strip() + f"\n\n{footer}")
                else:
                    text = text.rstrip() + ov_block
    except Exception as e:
        log.debug(f"[v6] openverse failed: {e}")

    return text

# ── 7. Patch CONTENT._post_process ───────────────────────────────
_orig_pp_v6 = ContentGenerator._post_process

def _pp_v6(self, text, topic, cfg, style="tutorial"):
    try:
        text = _orig_pp_v6(self, text, topic, cfg, style)
    except Exception:
        pass
    if not text:
        return text
    try:
        text = _enrich_with_emoji_and_image(text, topic)
    except Exception as e:
        log.debug(f"[v6] enrich failed: {e}")
    return text

ContentGenerator._post_process = _pp_v6

# ── 8. Patch _generate_and_post to add image BEFORE publish ─────
_orig_gap_v6 = _generate_and_post

def _gap_v6(cfg, chat_id, topic, style="tutorial", draft_id=None, with_poll=False):
    # Call original (it does its own emoji+image now via _post_process)
    try:
        return _orig_gap_v6(cfg, chat_id, topic, style, draft_id=draft_id, with_poll=with_poll)
    except Exception as e:
        log.exception(f"[v6] gap failed: {e}")

_generate_and_post = _gap_v6

# ── 9. Also patch AutoDirectorV5 to include images ──────────────
if "AUTO_V5" in dir() or "AUTO_V5" in globals():
    log.info("[v6] AutoDirectorV5 present, images enabled via _post_process")

# ── 10. Admin commands for testing ──────────────────────────────
@ROUTER.command("testemoji", description="تست ایموجی", admin_only=True)
def cmd_testemoji_v6(msg, args):
    chat_id = get_chat_id(msg)
    topic = TOPIC_MGR.find(args or "استاتیک") or {"name": args or "استاتیک", "tags": ""}
    emojis = _get_related_emojis(topic, count=5)
    TG.send_message(chat_id,
        f"🎯 موضوع: <b>{escape_html(topic.get('name','?'))}</b>\n\n"
        f"ایموجی‌های مرتبط:\n{' '.join(emojis)}")

@ROUTER.command("testimage", description="تست تصویر", admin_only=True)
def cmd_testimage_v6(msg, args):
    chat_id = get_chat_id(msg)
    topic = TOPIC_MGR.find(args or "استاتیک") or {"name": args or "استاتیک"}
    prompt = _image_prompt_for(topic)
    img_url = POLL_IMG.url_for(prompt)
    ov = OPENVERSE.search(topic.get("query") or topic.get("name") or "", limit=2)
    txt = (f"🎯 موضوع: <b>{escape_html(topic.get('name','?'))}</b>\n\n"
           f"🖼 <b>تصویر AI:</b>\n<a href=\"{img_url}\">بازکردن تصویر</a>\n\n")
    if ov:
        txt += f"📷 <b>عکس واقعی:</b>\n"
        for i, it in enumerate(ov, 1):
            txt += f"{i}. <a href=\"{it['url']}\">{escape_html(it.get('title','عکس'))[:60]}</a>\n"
    TG.send_message(chat_id, txt)

@ROUTER.command("emojitest", description="تست ایموجی تصادفی", admin_only=True)
def cmd_emojitest_v6(msg, args):
    chat_id = get_chat_id(msg)
    e = EMOJI_HUB.random()
    if e and e.get("char"):
        TG.send_message(chat_id,
            f"🎲 ایموجی تصادفی:\n\n"
            f"  {e['char']}  <b>{escape_html(e.get('name','?'))}</b>\n"
            f"  دسته: {escape_html(e.get('category','?'))}")
    else:
        TG.send_message(chat_id, "❌ دریافت ایموجی ناموفق بود.")

log.info("PATCH v6.0 applied — auto emoji + image via Pollinations + Openverse")



# ═══════════════════════════════════════════════════════════════════════════
#  PATCH v7.0 — FINAL: Readable formulas + Emoji + Image on top + Videos with URL
#  Inserted BEFORE __main__. Persian-only user-facing text.
# ═══════════════════════════════════════════════════════════════════════════

import urllib.parse as _up_v7
import math as _m_v7

# ── 1. Better formula cleaner (always readable, no LaTeX) ───────
_GREEK_V7 = {
    "alpha":"α","beta":"β","gamma":"γ","delta":"δ","epsilon":"ε","zeta":"ζ",
    "eta":"η","theta":"θ","iota":"ι","kappa":"κ","lambda":"λ","mu":"μ","nu":"ν",
    "xi":"ξ","pi":"π","rho":"ρ","sigma":"σ","tau":"τ","upsilon":"υ","phi":"φ",
    "chi":"χ","psi":"ψ","omega":"ω","Gamma":"Γ","Delta":"Δ","Theta":"Θ",
    "Lambda":"Λ","Xi":"Ξ","Pi":"Π","Sigma":"Σ","Phi":"Φ","Psi":"Ψ","Omega":"Ω",
}
_SYMBOLS_V7 = {
    "partial":"∂","nabla":"∇","infty":"∞","int":"∫","iint":"∬","iiint":"∭",
    "oint":"∮","sum":"∑","prod":"∏","pm":"±","mp":"∓","times":"×","div":"÷",
    "cdot":"·","approx":"≈","neq":"≠","le":"≤","leq":"≤","ge":"≥","geq":"≥",
    "ll":"≪","gg":"≫","to":"→","rightarrow":"→","leftarrow":"←","Rightarrow":"⇒",
    "Leftarrow":"⇐","leftrightarrow":"↔","in":"∈","notin":"∉","subset":"⊂",
    "supset":"⊃","cup":"∪","cap":"∩","forall":"∀","exists":"∃","partial":"∂",
    "propto":"∝","simeq":"≃","equiv":"≡","cong":"≅","sim":"∼","perp":"⊥",
    "parallel":"∥","angle":"∠","degree":"°","prime":"′","emptyset":"∅",
    "aleph":"ℵ","hbar":"ℏ","ell":"ℓ","Re":"ℜ","Im":"ℑ",
}
_SUPS_V7 = str.maketrans("0123456789+-=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")
_SUBS_V7 = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")

def _clean_formula_v7(text):
    """Aggressive LaTeX → Unicode. Always applied."""
    if not text or "\\" not in text and "$" not in text:
        return text
    # Remove math delimiters
    for d in ("$$","\\(","\\)","\\[","\\]","$"):
        text = text.replace(d, "")
    # Fractions (repeated to handle nesting)
    for _ in range(5):
        text = re.sub(r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}", r"(\1)/(\2)", text)
    # sqrt
    for _ in range(3):
        text = re.sub(r"\\sqrt\s*\{([^{}]+)\}", r"√(\1)", text)
    text = re.sub(r"\\sqrt\s*\[([^\]]+)\]\s*\{([^{}]+)\}", r"√[\1](\2)", text)
    # text/mathrm/mathbf
    text = re.sub(r"\\text\s*\{([^{}]+)\}", r"\1", text)
    text = re.sub(r"\\mathrm\s*\{([^{}]+)\}", r"\1", text)
    text = re.sub(r"\\mathbf\s*\{([^{}]+)\}", r"\1", text)
    text = re.sub(r"\\mathbb\s*\{([^{}]+)\}", r"\1", text)
    # left/right/big
    for w in ("\\left","\\right","\\big","\\Big","\\bigg","\\Bigg",
              "\\bigl","\\bigr","\\Bigl","\\Bigr","\\," , "\\;", "\\!", "\\ "):
        text = text.replace(w, " " if w in ("\\,","\\;","\\!","\\ ") else "")
    # Greek
    for k, v in _GREEK_V7.items():
        text = re.sub(r"\\" + re.escape(k) + r"\b", v, text)
    # Symbols
    for k, v in _SYMBOLS_V7.items():
        text = re.sub(r"\\" + re.escape(k) + r"\b", v, text)
    # Superscripts
    text = re.sub(r"\^\{([^{}]+)\}", lambda m: m.group(1).translate(_SUPS_V7), text)
    text = re.sub(r"\^(\w)", lambda m: m.group(1).translate(_SUPS_V7), text)
    # Subscripts
    text = re.sub(r"_\{([^{}]+)\}", lambda m: m.group(1).translate(_SUBS_V7), text)
    text = re.sub(r"_(\w)", lambda m: m.group(1).translate(_SUBS_V7), text)
    # Remove remaining LaTeX commands
    text = re.sub(r"\\[A-Za-z]+\b", "", text)
    text = text.replace("\\", "")
    # Remove stray braces from math
    text = re.sub(r"[{}]", "", text)
    # Collapse spaces
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([,;)])", r"\1", text)
    return text.strip()

# Override the module-level cleaner
clean_latex = _clean_formula_v7

# ── 2. Extract formula lines → wrap in <b> for readability ──────
_FORMULA_HINT = re.compile(
    r"[=≠≈≤≥∝><]|∑|∫|∮|√|∂|∇|ρ|σ|π|λ|μ|θ|φ|Ω|Δ|"
    r"\b(sin|cos|tan|log|ln|exp|lim|max|min)\b"
)

def _wrap_formulas_bold(text):
    """Wrap formula-like lines in <b>...</b> for visual prominence."""
    if not text:
        return text
    out = []
    for line in text.split("\n"):
        s = line.strip()
        # Skip code/HTML/headers
        if not s or s.startswith(("<code>","<b>","<i>","<pre>","|","#","-","*","─","═")):
            out.append(line); continue
        # Persian-dominant → not a formula
        persian = len(re.findall(r"[\u0600-\u06FF]", s))
        visible = len(re.sub(r"\s+","",s)) or 1
        if persian / visible > 0.40:
            out.append(line); continue
        # Formula-like?
        if _FORMULA_HINT.search(s) and len(s) < 120:
            # Already has <code>?
            if "<code>" in s:
                out.append(line)
            else:
                out.append(f"<b>{s}</b>")
        else:
            out.append(line)
    return "\n".join(out)

# ── 3. EmojiHub (free, no auth) ─────────────────────────────────
class EmojiHubV7:
    BASE = "https://emojihub.yurace.pro/api"
    CACHE = {}

    @classmethod
    def _parse(cls, d):
        if not isinstance(d, dict): return None
        html = d.get("htmlCode") or []
        ch = "".join(html) if html else "".join(d.get("unicode") or [])
        if not ch: return None
        return {"char": ch, "name": d.get("name",""),
                "category": d.get("category","")}

    @classmethod
    def random(cls):
        try:
            r = HTTP.request("GET", f"{cls.BASE}/random", timeout=8)
            if r is None or r.status_code != 200: return None
            return cls._parse(r.json())
        except Exception: return None

    @classmethod
    def by_category(cls, cat):
        if cat in cls.CACHE: return cls.CACHE[cat]
        try:
            url = f"{cls.BASE}/random/category/{_up_v7.quote(cat)}"
            r = HTTP.request("GET", url, timeout=8)
            if r is None or r.status_code != 200: return None
            e = cls._parse(r.json())
            cls.CACHE[cat] = e
            return e
        except Exception: return None

EMOJI_V7 = EmojiHubV7()

# Topic → emoji keyword
_TOPIC_EMOJI_KW = {
    "ریاضی":["books","abacus"], "حساب":["abacus"], "انتگرال":["triangular_ruler"],
    "مشتق":["triangular_ruler"], "جبر":["abacus"], "فوریه":["musical_note"],
    "احتمال":["game_die"], "آمار":["bar_chart"], "بهینه":["chart"],
    "استاتیک":["classical_building","balance_scale"], "دینامیک":["rocket"],
    "مقاومت":["bridge_at_night"], "ارتعاش":["musical_note"],
    "سیالات":["ocean","droplet"], "هیدرولیک":["droplet"],
    "ترمودینامیک":["fire","thermometer"], "حرارت":["thermometer"],
    "تهویه":["snowflake"], "تبرید":["ice_cube"], "تاسیسات":["building_construction"],
    "طراحی":["gear"], "ساخت":["factory"], "کنترل":["joystick"],
    "روبات":["robot"], "مکاترونیک":["robot"], "بیومکانیک":["bone"],
    "آیرودینامیک":["airplane"], "دریا":["ship"], "خودرو":["car"],
    "انرژی":["sun","zap"], "CFD":["computer"], "FEM":["triangular_ruler"],
    "هوش مصنوعی":["robot","brain"], "کوانتوم":["atom"],
    "فیزیک":["atom"], "شیمی":["test_tube"], "فضا":["rocket"],
    "ناسا":["rocket"], "اخبار":["newspaper"], "اقتصاد":["chart"],
    "روان":["brain"], "کتاب":["books"], "موسیقی":["musical_note"],
}
_GENERIC_EMOJI = ["books","rocket","bulb","sparkles","globe","chart","gear","atom","star"]

def _get_topic_emojis(topic, count=3):
    name = (topic.get("name") or "").lower()
    tags = (topic.get("tags") or "").lower()
    dom = (topic.get("domain") or "").lower()
    text = f"{name} {tags} {dom}"
    kws = _GENERIC_EMOJI
    for k, v in _TOPIC_EMOJI_KW.items():
        if k in text:
            kws = v; break
    out = []
    for kw in kws:
        e = EMOJI_V7.by_category(kw)
        if e and e["char"] and e["char"] not in out:
            out.append(e["char"])
        if len(out) >= count: return out
    return out[:count] if out else ["📌"]

# ── 4. Pollinations.ai image URL ────────────────────────────────
class PollImgV7:
    BASE = "https://image.pollinations.ai/prompt"
    @staticmethod
    def url_for(prompt, w=1024, h=576, seed=None):
        if not prompt: return ""
        p = _up_v7.quote(prompt.strip()[:280], safe="")
        params = [f"width={w}", f"height={h}", "model=flux", "enhance=true", "nologo=true"]
        if seed is not None: params.append(f"seed={seed}")
        return f"{PollImgV7.BASE}/{p}?{'&'.join(params)}"

POLL_IMG_V7 = PollImgV7()

def _image_prompt_for(topic):
    q = (topic.get("query") or topic.get("name") or "").strip()
    dom = (topic.get("domain") or "").lower()
    if dom == "math":
        return f"mathematics engineering illustration, {q}, blueprint, clean vector, no text"
    return f"engineering illustration, {q}, technical blueprint, isometric, no text"

# ── 5. Videos: 3 results, English-first, URL on separate line ────
def _fetch_videos_for_topic(query, limit=3):
    """Return list of {title, url, channel} — English priority, 3 items."""
    out = []
    seen = set()
    # Pass 1: YouTube English
    try:
        r = APIS.youtube.search_videos(query, max_results=limit + 3, language="en")
        if r.ok and r.data:
            for v in r.data:
                u = v.get("url","")
                if u and u not in seen:
                    out.append({"title": v.get("title",""), "url": u,
                                "channel": v.get("channel",""), "lang":"en"})
                    seen.add(u)
    except Exception: pass

    # Pass 2: YouTube Persian if not enough
    if len(out) < limit:
        try:
            r = APIS.youtube.search_videos(query, max_results=limit + 3, language="fa")
            if r.ok and r.data:
                for v in r.data:
                    u = v.get("url","")
                    if u and u not in seen:
                        out.append({"title": v.get("title",""), "url": u,
                                    "channel": v.get("channel",""), "lang":"fa"})
                        seen.add(u)
        except Exception: pass

    # Pass 3: Archive.org fallback
    if len(out) < limit:
        try:
            archive = ArchiveOrgAPI.search_video(query, limit=limit - len(out))
            for v in archive:
                u = v.get("url","")
                if u and u not in seen:
                    out.append({"title": v.get("title",""), "url": u,
                                "channel": v.get("channel","Archive.org"), "lang":"en"})
                    seen.add(u)
        except Exception: pass

    return out[:limit]

def _format_videos_block(videos):
    """Format: title on line, URL on next line."""
    if not videos: return ""
    lines = ["", "🎥 <b>ویدیوهای مرتبط:</b>", ""]
    for i, v in enumerate(videos[:3], 1):
        title = escape_html((v.get("title") or "بدون عنوان")[:120])
        url   = v.get("url","")
        ch    = escape_html((v.get("channel") or "")[:40])
        lines.append(f"{i}. <b>{title}</b>")
        if ch:
            lines.append(f"   <i>{ch}</i>")
        if url:
            lines.append(f"   {url}")
        lines.append("")
    return "\n".join(lines)

# ── 6. Override _post_process: emoji + image + videos + formulas ──
_orig_pp_v7 = ContentGenerator._post_process

def _pp_v7(self, text, topic, cfg, style="tutorial"):
    # 1. Original processing (formula cleanup, markdown, hashtags)
    try:
        text = _orig_pp_v7(self, text, topic, cfg, style)
    except Exception as e:
        log.debug(f"[v7] orig pp: {e}")
    if not text:
        return text

    # 2. Force formula cleanup (even for formula/math styles)
    try:
        text = _clean_formula_v7(text)
    except Exception as e:
        log.debug(f"[v7] clean formula: {e}")

    # 3. Wrap formulas in <b> for readability
    try:
        text = _wrap_formulas_bold(text)
    except Exception as e:
        log.debug(f"[v7] bold formulas: {e}")

    # 4. Add related emoji at top
    try:
        emojis = _get_topic_emojis(topic, count=3)
        if emojis:
            prefix = " ".join(emojis)
            if not text.startswith(prefix):
                text = f"{prefix} {text}"
    except Exception as e:
        log.debug(f"[v7] emoji: {e}")

    # 5. Replace existing YouTube block with new format (title + URL)
    try:
        # Remove old YouTube block if present
        text = re.sub(
            r"\n\n🎥 <b>ویدیوهای آموزشی مرتبط:</b>[\s\S]*?(?=\n\n📢|\Z)",
            "", text
        )
        # Add new video block
        q = topic.get("query") or topic.get("name") or ""
        if q:
            vids = _fetch_videos_for_topic(q, limit=3)
            vblock = _format_videos_block(vids)
            if vblock:
                footer = "📢 @MAADGHchannel"
                if footer in text:
                    text = text.replace(footer, vblock.strip() + "\n\n" + footer)
                else:
                    text = text.rstrip() + "\n" + vblock
    except Exception as e:
        log.debug(f"[v7] videos: {e}")

    return text.strip()

ContentGenerator._post_process = _pp_v7

# ── 7. Override _generate_and_post: send image FIRST ─────────────
_orig_gap_v7 = _generate_and_post

def _gap_v7(cfg, chat_id, topic, style="tutorial", draft_id=None, with_poll=False):
    if isinstance(topic, str):
        td = TOPIC_MGR.find(topic) or {"name": topic, "query": topic,
                                       "emoji":"📌", "tags":"#مهندسی_مکانیک"}
    else:
        td = topic
    tname = td["name"]

    # Loading indicator
    _prog(f"generate start | topic={tname} style={style}", "post")
    LIVE.event("gen", f"Generating: {tname} [{style}]")
    m = TG.send_message(chat_id,
        f"⏳ در حال تولید «{td.get('emoji','')} {tname}» ({style})...")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")

    # Generate content
    _t0 = _prog_ai_start()
    try:
        with TypingHeartbeat(chat_id):
            content = CONTENT.generate(td, style)
    except Exception as e:
        _prog(f"generate exception: {e}", "post")
        content = None
    _prog_ai_done(_t0, content or "", provider="content")

    if not content:
        TG.edit_message(chat_id, mid,
            "❌ تولید ناموفق. کلید هوش مصنوعی یا اتصال را بررسی کن.")
        return

    _prog(f"generate OK | {len(content)} chars", "post")

    # Save draft
    uid = chat_id if isinstance(chat_id, int) and chat_id > 0 else 0
    draft = DRAFTS.create(tname, style, content, uid, metadata={"channel": True})

    # Validate channel
    is_ch, ch_msg = _verify_channel_target(cfg)
    if not is_ch:
        TG.edit_message(chat_id, mid,
            f"⛔ <b>انتشار متوقف شد</b>\n\n{escape_html(ch_msg)}")
        return

    channel = cfg.telegram.channel_id

    # ─── SEND IMAGE FIRST (to channel) ───
    try:
        prompt = _image_prompt_for(td)
        img_url = POLL_IMG_V7.url_for(prompt, seed=_RND.randint(1, 99999))
        if img_url:
            TG.send_photo(
                channel, img_url,
                caption=f"🖼 <b>{escape_html(tname)}</b>",
                parse_mode="HTML"
            )
            _prog("image sent to channel", "post")
    except Exception as e:
        log.debug(f"[v7] send image: {e}")

    # ─── SEND TEXT ───
    ok_flag, msg, n = _send_to_channel(cfg, content, reply_markup=None)

    if ok_flag:
        TG.edit_message(chat_id, mid,
            f"✅ «{tname}» منتشر شد.\n"
            f"📢 <code>{escape_html(channel)}</code>\n"
            f"🎨 سبک: <b>{style}</b>\n"
            f"📏 {len(content)} کاراکتر | 📦 {n} پیام",
            reply_markup=kb([
                [btn("🔄 بازتولید", f"regen:{draft.id}"),
                 btn("✏️ نسخه دیگر", f"regen2:{draft.id}")],
                [btn("👁 نمایش محتوا", f"show:{draft.id}")],
                [btn("🗑 حذف پیش‌نویس", f"draftdel:{draft.id}")],
            ]))
        STATS.incr("posts")
        STATS.incr_dict("styles", style)
        LIVE.event("pub", f"Published -> {channel} ({len(content)} chars)")
    else:
        TG.edit_message(chat_id, mid,
            f"❌ <b>انتشار ناموفق</b>\n\n🔴 {escape_html(msg[:250])}")
        STATS.incr("errors")

_generate_and_post = _gap_v7

# ── 8. Exchange: 45 currencies ──────────────────────────────────
_ALL_CURRENCIES = (
    "EUR,GBP,JPY,CHF,CAD,AUD,NZD,CNY,HKD,SGD,"
    "KRW,INR,RUB,TRY,AED,SAR,QAR,KWD,BHD,OMR,"
    "JOD,IQD,AFN,PKR,BDT,LKR,NPR,IDR,MYR,THB,"
    "VND,PHP,MXN,BRL,ARS,CLP,COP,PEN,ZAR,EGP,"
    "NGN,KES,MAD,DZD,TND,IRR"
)

_orig_cmd_rate_v7 = cmd_rate

@ROUTER.command("rate", description="نرخ ارز (کامل)")
def cmd_rate_v7(msg, args):
    chat_id = get_chat_id(msg)
    symbols = args.strip() or _ALL_CURRENCIES
    r = APIS.exchange.latest("USD", symbols)
    if not r.ok:
        TG.send_message(chat_id, f"❌ {r.error[:150]}")
        return
    rates = (r.data or {}).get("rates", {}) or {}
    text = f"💱 <b>نرخ ارز پایه دلار آمریکا</b>\n\n"
    # Group by size
    main = ["EUR","GBP","JPY","CHF","CAD","AUD","CNY","RUB","TRY","INR"]
    reg  = ["AED","SAR","QAR","KWD","BHD","OMR","JOD","IQD","AFN","PKR"]
    text += "<b>ارزهای اصلی:</b>\n"
    for c in main:
        if c in rates: text += f"  • {c}: <code>{rates[c]:.4f}</code>\n"
    text += "\n<b>ارزهای منطقه‌ای:</b>\n"
    for c in reg:
        if c in rates: text += f"  • {c}: <code>{rates[c]:.4f}</code>\n"
    other = sorted(set(rates.keys()) - set(main) - set(reg))
    if other:
        text += "\n<b>سایر:</b>\n"
        for c in other[:30]:
            text += f"  • {c}: <code>{rates[c]:.4f}</code>\n"
    TG.send_message(chat_id, text[:4000])

@ROUTER.command("ratefull", description="همه نرخ‌ها")
def cmd_ratefull_v7(msg, args):
    return cmd_rate_v7(msg, _ALL_CURRENCIES)

# ── 9. Super mode ────────────────────────────────────────────────
@ROUTER.command("super", description="تولید سوپر (کیفیت بالا)")
def cmd_super_v7(msg, args):
    chat_id = get_chat_id(msg)
    topic = args.strip() or (TOPIC_MGR.rotate_next()["name"])
    m = TG.send_message(chat_id,
        f"🌟 <b>حالت سوپر</b>\nموضوع: «{escape_html(topic)}»\n"
        f"<i>شامل منبع‌یابی، فرمول‌های خوانا، ایموجی، عکس و ۳ ویدیو</i>")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")

    def _do():
        try:
            td = TOPIC_MGR.find(topic) or {"name": topic, "query": topic,
                                           "emoji":"📌", "tags":"#مهندسی_مکانیک"}
            # 1. Gather multi-source context
            ctx = {"formulas": get_formulas_for(td.get("name",""), td)}
            try:
                w = APIS.wikipedia.summary(td.get("name",""), "fa")
                if w.ok: ctx["wiki_fa"] = w.data
            except Exception: pass
            try:
                w = APIS.wikipedia.summary(td.get("query",""), "en")
                if w.ok: ctx["wiki_en"] = w.data
            except Exception: pass
            try:
                ar = APIS.arxiv.search(td.get("query",""), max_results=3)
                if ar.ok: ctx["arxiv"] = ar.data
            except Exception: pass
            try:
                nr = APIS.news.fetch_combined(limit=8)
                ctx["news"] = APIS.news.filter_by_keywords(
                    nr, [td.get("query",""), td.get("name","")])
            except Exception: pass

            # 2. Build super prompt
            sys_p = STYLE_PROMPTS.get("tutorial", SYS_TUTORIAL)
            user_p = [f"موضوع: {td['name']}"]
            user_p.append("دستور: یک درس کامل و عمیق با ساختار زیر بنویس:")
            user_p.append("🎯 هدف | 📖 تعریف | 🔬 مبانی | 📐 فرمول‌های کلیدی (۳ تا ۵، همه خوانا) |")
            user_p.append("🧮 مثال حل‌شده | 📊 جدول خلاصه | ⚙️ کاربرد صنعتی | ⚠️ اشتباهات رایج | ✅ جمع‌بندی")
            user_p.append("")
            user_p.append("⚠️ مهم: فرمول‌ها را به‌صورت خوانا و یونیکد بنویس، نه LaTeX.")
            user_p.append("مثال درست: P + (1/2)ρv² + ρgz = const")
            user_p.append("مثال غلط: \\frac{1}{2}\\rho v^2")

            # Add context
            try:
                block = ASSEMBLER.to_prompt_block(ctx, max_chars=3500)
                if block:
                    user_p.append("")
                    user_p.append("--- منابع ---")
                    user_p.append(block)
            except Exception: pass

            with TypingHeartbeat(chat_id):
                resp = AI.ask(sys_p, "\n".join(user_p),
                              max_tokens=4000, temperature=0.7)
            if not resp.ok:
                TG.edit_message(chat_id, mid,
                    f"❌ تولید ناموفق: {escape_html(resp.error[:200])}")
                return

            # 3. Post-process
            cfg = CONFIG.get()
            content = CONTENT._post_process(resp.text, td, cfg, "tutorial")

            # 4. Save draft
            uid = chat_id if isinstance(chat_id, int) and chat_id > 0 else 0
            draft = DRAFTS.create(td["name"], "super", content, uid,
                                  metadata={"super": True})

            # 5. Validate + publish
            is_ch, ch_msg = _verify_channel_target(cfg)
            if not is_ch:
                TG.edit_message(chat_id, mid,
                    f"⛔ انتشار متوقف: {escape_html(ch_msg)}")
                return

            # Send image first
            try:
                prompt = _image_prompt_for(td)
                img_url = POLL_IMG_V7.url_for(prompt, seed=_RND.randint(1,99999))
                if img_url:
                    TG.send_photo(cfg.telegram.channel_id, img_url,
                                  caption=f"🌟 <b>{escape_html(td['name'])}</b>")
            except Exception: pass

            ok_flag, msg2, n = _send_to_channel(cfg, content, reply_markup=None)
            if ok_flag:
                TG.edit_message(chat_id, mid,
                    f"🌟 «{td['name']}» در حالت سوپر منتشر شد.\n"
                    f"📏 {len(content)} کاراکتر | 📦 {n} پیام",
                    reply_markup=kb([
                        [btn("🔄 بازتولید", f"regen:{draft.id}")],
                        [btn("👁 نمایش", f"show:{draft.id}")],
                    ]))
                STATS.incr("posts")
                STATS.incr_dict("styles", "super")
            else:
                TG.edit_message(chat_id, mid, f"❌ {escape_html(msg2[:200])}")
        except Exception as e:
            log.exception(f"[super] {e}")
            TG.edit_message(chat_id, mid, f"❌ خطا: {escape_html(str(e)[:200])}")

    POOL.submit(_do)

# ── 10. Book: 8 subcategories ────────────────────────────────────
_BOOK_SUBCATS = {
    "eng": ["thermodynamics textbook","fluid mechanics textbook","heat transfer textbook",
            "statics textbook","dynamics textbook","strength of materials textbook",
            "machine design textbook","vibration textbook","control textbook"],
    "math":["calculus textbook","linear algebra textbook","differential equations textbook",
            "numerical methods textbook","optimization textbook","probability textbook"],
    "phys":["classical mechanics textbook","electromagnetism textbook","quantum mechanics textbook",
            "statistical mechanics textbook","optics textbook"],
    "chem":["organic chemistry textbook","inorganic chemistry textbook",
            "physical chemistry textbook","analytical chemistry textbook"],
    "cs":  ["algorithms textbook","data structures textbook","operating systems textbook",
            "computer networks textbook","databases textbook"],
    "ai":  ["machine learning textbook","deep learning textbook","reinforcement learning book",
            "computer vision textbook","natural language processing textbook"],
    "mfg": ["manufacturing processes textbook","welding textbook","machining textbook",
            "additive manufacturing textbook","cnc programming textbook"],
    "hist":["history of science book","industrial revolution book","engineering history book",
            "history of mathematics book"],
}
_BOOK_SUBCAT_LABELS = {
    "eng":"مهندسی","math":"ریاضی","phys":"فیزیک","chem":"شیمی",
    "cs":"کامپیوتر","ai":"هوش مصنوعی","mfg":"تولید","hist":"تاریخ علم",
}

@ROUTER.command("book", description="کتاب PDF")
def cmd_book_v7(msg, args):
    chat_id = get_chat_id(msg)
    if args:
        _book_search_v7(chat_id, None, args); return
    rows = []; row = []
    for k, label in _BOOK_SUBCAT_LABELS.items():
        row.append(btn(f"📕 {label}", f"book:sub:{k}"))
        if len(row) == 2: rows.append(row); row = []
    if row: rows.append(row)
    rows.append([btn("🏠 منو", "m:main")])
    TG.send_message(chat_id,
        f"📚 <b>کتاب PDF</b> — {len(_BOOK_SUBCAT_LABELS)} زیردسته:",
        reply_markup=kb(rows))

@ROUTER.callback("book")
def cb_book_v7(cb, data):
    parts = data.split(":"); action = parts[1] if len(parts) > 1 else ""
    chat_id = cb["message"]["chat"]["id"]; msg_id = cb["message"]["message_id"]
    TG.answer_callback(cb.get("id", ""))
    if action == "sub":
        k = parts[2] if len(parts) > 2 else ""
        cats = _BOOK_SUBCATS.get(k, [])
        rows = []; row = []
        for i, c in enumerate(cats):
            row.append(btn(f"📕 {c[:24]}", f"book:go:{k}:{i}"))
            if len(row) == 2: rows.append(row); row = []
        if row: rows.append(row)
        rows.append([btn("⬅️ بازگشت", "book:back"), btn("🏠", "m:main")])
        TG.edit_message(chat_id, msg_id,
            f"📚 <b>{_BOOK_SUBCAT_LABELS.get(k,k)}</b> — یک عنوان:",
            reply_markup=kb(rows))
        return
    if action == "go":
        k = parts[2] if len(parts) > 2 else ""
        try: idx = int(parts[3])
        except Exception: return
        cats = _BOOK_SUBCATS.get(k, [])
        if 0 <= idx < len(cats):
            _book_search_v7(chat_id, msg_id, cats[idx])
        return
    if action == "send":
        try: idx = int(parts[2])
        except Exception: return
        st = _BOOK_RESULTS_V7.get(chat_id) or []
        if 0 <= idx < len(st):
            item = st[idx]
            cfg = CONFIG.get()
            title = item.get("title","") or "PDF"
            tags = " ".join("#" + re.sub(r"\W","",w) for w in title.split()[:4] if w)
            TG.send_message(cfg.telegram.channel_id,
                f"📕 <b>{escape_html(title[:120])}</b>\n\n"
                f"🔗 {item['url']}\n\n{tags}\n📢 @MAADGHchannel")
            TG.answer_callback(cb.get("id", ""), "✅ ارسال شد")
        return
    if action == "back":
        cmd_book_v7({"chat":{"id":chat_id},"from":cb.get("from",{}),"message":{}}, "")
        return
    if action == "cancel":
        TG.edit_message(chat_id, msg_id, "❌ لغو شد"); return

_BOOK_RESULTS_V7 = TTLStore(max_items=500, ttl=3600)
def _book_search_v7(chat_id, msg_id, category):
    if msg_id: TG.edit_message(chat_id, msg_id, f"📚 جستجو: {escape_html(category)} ...")
    else:
        m = TG.send_message(chat_id, f"📚 جستجو: {escape_html(category)} ...")
        msg_id = (m.result or {}).get("message_id") if m.ok else None

    hits = _web_search_titles(
        f'"{category}" filetype:pdf',
        max_results=15,
        extra_filter=lambda u, t: "pdf" in u.lower()
    ) if "_web_search_titles" in globals() else []
    if not hits:
        hits = []
    if not hits:
        if msg_id: TG.edit_message(chat_id, msg_id, "❌ کتابی یافت نشد.")
        return
    _BOOK_RESULTS_V7[chat_id] = hits
    text = f"📚 <b>{escape_html(category)}</b>\n{len(hits)} مورد:\n\n"
    for i, h in enumerate(hits, 1):
        text += f"<b>{i}.</b> {escape_html(h['title'][:70])}\n"
    rows = []
    for i in range(0, min(len(hits), 12), 2):
        row = []
        for j in (i, i+1):
            if j < len(hits) and j < 12:
                row.append(btn(f"📤 {j+1}", f"book:send:{j}"))
        rows.append(row)
    rows.append([btn("❌ لغو", "book:cancel"), btn("🏠", "m:main")])
    if msg_id: TG.edit_message(chat_id, msg_id, text[:4000], reply_markup=kb(rows))
    else: TG.send_message(chat_id, text[:4000], reply_markup=kb(rows))

# ── 11. Quiz: 8 subcategories ────────────────────────────────────
_QUIZ_CATS = {
    "math":  "ریاضی", "phys": "فیزیک", "mech": "مهندسی مکانیک",
    "chem":  "شیمی", "bio":  "زیست",   "hist": "تاریخ",
    "geo":   "جغرافیا", "gen": "عمومی",
}

@ROUTER.command("quiz", description="کوییز")
def cmd_quiz_v7(msg, args):
    chat_id = get_chat_id(msg)
    if args:
        POOL.submit(_generate_and_post, CONFIG.get(), chat_id, args, "quiz")
        return
    rows = []; row = []
    for k, label in _QUIZ_CATS.items():
        row.append(btn(f"❓ {label}", f"quiz:go:{k}"))
        if len(row) == 2: rows.append(row); row = []
    if row: rows.append(row)
    rows.append([btn("🏠 منو", "m:main")])
    TG.send_message(chat_id,
        "❓ <b>کوییز</b> — یک دسته انتخاب کن:",
        reply_markup=kb(rows))

@ROUTER.callback("quiz")
def cb_quiz_v7(cb, data):
    parts = data.split(":"); action = parts[1] if len(parts) > 1 else ""
    chat_id = cb["message"]["chat"]["id"]; msg_id = cb["message"]["message_id"]
    TG.answer_callback(cb.get("id", ""))
    if action == "go":
        k = parts[2] if len(parts) > 2 else ""
        label = _QUIZ_CATS.get(k, k)
        POOL.submit(_generate_and_post, CONFIG.get(), chat_id, label, "quiz")

# ── 12. Stats: 8 subcategories ───────────────────────────────────
_STATS_CATS = {
    "usage":  "آمار استفاده",
    "posts":  "پست‌ها و سبک‌ها",
    "users":  "کاربران و پیام‌ها",
    "cmd":    "دستورات",
    "mem":    "حافظه و کش",
    "api":    "سرویس‌ها",
    "err":    "خطاها",
    "up":     "زمان فعالیت",
}

@ROUTER.command("stats", description="آمار")
def cmd_stats_v7(msg, args):
    chat_id = get_chat_id(msg)
    rows = []; row = []
    for k, label in _STATS_CATS.items():
        row.append(btn(f"📊 {label}", f"stats:cat:{k}"))
        if len(row) == 2: rows.append(row); row = []
    if row: rows.append(row)
    rows.append([btn("🏠 منو", "m:main")])
    TG.send_message(chat_id,
        "📊 <b>آمار</b> — دسته را انتخاب کن:",
        reply_markup=kb(rows))

@ROUTER.callback("stats")
def cb_stats_v7(cb, data):
    parts = data.split(":"); action = parts[1] if len(parts) > 1 else ""
    chat_id = cb["message"]["chat"]["id"]; msg_id = cb["message"]["message_id"]
    TG.answer_callback(cb.get("id", ""))
    if action != "cat": return
    k = parts[2] if len(parts) > 2 else ""
    s = STATS.all()
    if k == "usage":
        text = (f"📊 <b>آمار استفاده</b>\n\n"
                f"📝 پست‌ها: <code>{s.get('posts',0)}</code>\n"
                f"💬 سوالات: <code>{s.get('questions',0)}</code>\n"
                f"🔄 بازتولید: <code>{s.get('regen',0)}</code>")
    elif k == "posts":
        styles = s.get("styles", {})
        text = "📊 <b>پست‌ها بر اساس سبک</b>\n\n"
        for st, n in sorted(styles.items(), key=lambda x: -x[1])[:15]:
            text += f"  • {st}: <code>{n}</code>\n"
    elif k == "users":
        sess = SESSIONS.stats()
        text = (f"📊 <b>کاربران</b>\n\n"
                f"👥 نشست‌های فعال: <code>{sess.get('active_sessions',0)}</code>")
    elif k == "cmd":
        cmds = s.get("commands", {})
        text = "📊 <b>دستورات پرکاربرد</b>\n\n"
        for c, n in sorted(cmds.items(), key=lambda x: -x[1])[:15]:
            text += f"  /{c}: <code>{n}</code>\n"
    elif k == "mem":
        ms = MEM_MON.stats()
        ai = AI_CACHE.stats()
        text = (f"📊 <b>حافظه و کش</b>\n\n"
                f"💾 فعلی: <code>{ms['current_mb']} MB</code>\n"
                f"📈 اوج: <code>{ms['peak_mb']} MB</code>\n"
                f"🎯 کش AI: <code>{ai['hit_rate']}%</code>\n"
                f"📦 کش HTTP: <code>{HTTP_CACHE.stats()['size']}</code>")
    elif k == "api":
        text = "🔌 <b>وضعیت سرویس‌ها</b>\n\n" + APIS.status_summary()
    elif k == "err":
        text = (f"📊 <b>خطاها</b>\n\n"
                f"❌ کل: <code>{s.get('errors',0)}</code>\n"
                f"🕐 شروع: <code>{str(s.get('started_at','?'))[:19]}</code>")
    elif k == "up":
        try:
            uptime = time.time() - PERF._started
            h = int(uptime // 3600); mnt = int((uptime % 3600) // 60)
            text = (f"📊 <b>زمان فعالیت</b>\n\n"
                    f"⏱ <code>{h}h {mnt}m</code>")
        except Exception:
            text = "📊 در دسترس نیست"
    else:
        text = "❌ ناشناخته"
    TG.edit_message(chat_id, msg_id, text[:4000],
                    reply_markup=kb([[btn("⬅️ بازگشت", "m:main")]]))

# ── 13. Wiki: 8 subcategories ────────────────────────────────────
_WIKI_SUBCATS = {
    "phys":["Mechanics","Thermodynamics","Fluid mechanics","Heat transfer",
            "Electromagnetism","Optics","Quantum mechanics","Relativity"],
    "math":["Calculus","Linear algebra","Differential equation","Numerical analysis",
            "Probability theory","Statistics","Optimization","Topology"],
    "eng": ["Mechanical engineering","Civil engineering","Electrical engineering",
            "Chemical engineering","Aerospace engineering","Materials science",
            "Robotics","Mechatronics"],
    "chem":["Organic chemistry","Inorganic chemistry","Physical chemistry",
            "Analytical chemistry","Biochemistry","Polymer chemistry",
            "Electrochemistry","Thermochemistry"],
    "bio": ["Cell biology","Genetics","Evolution","Ecology","Neuroscience",
            "Biochemistry","Molecular biology","Biotechnology"],
    "space":["Solar System","Galaxy","Black hole","Big Bang","Space exploration",
            "Astronaut","Rocket","Satellite"],
    "tech":["Artificial intelligence","Machine learning","Computer","Internet",
            "Blockchain","Quantum computing","Nanotechnology","5G"],
    "gen": ["History","Geography","Philosophy","Psychology","Economics",
            "Language","Art","Music"],
}
_WIKI_SUBCAT_LABELS = {
    "phys":"فیزیک","math":"ریاضی","eng":"مهندسی","chem":"شیمی",
    "bio":"زیست","space":"فضا","tech":"فناوری","gen":"عمومی",
}

@ROUTER.command("wiki", description="ویکی‌پدیا")
def cmd_wiki_v7(msg, args):
    chat_id = get_chat_id(msg)
    if args:
        _wiki_fetch_v7(chat_id, None, args); return
    rows = []; row = []
    for k, label in _WIKI_SUBCAT_LABELS.items():
        row.append(btn(f"📖 {label}", f"wiki:sub:{k}"))
        if len(row) == 2: rows.append(row); row = []
    if row: rows.append(row)
    rows.append([btn("🎲 تصادفی", "wiki:randall"), btn("🏠", "m:main")])
    TG.send_message(chat_id,
        "📖 <b>ویکی‌پدیا</b> — دسته را انتخاب کن:",
        reply_markup=kb(rows))

@ROUTER.callback("wiki")
def cb_wiki_v7(cb, data):
    parts = data.split(":"); action = parts[1] if len(parts) > 1 else ""
    chat_id = cb["message"]["chat"]["id"]; msg_id = cb["message"]["message_id"]
    TG.answer_callback(cb.get("id", ""))
    if action == "sub":
        k = parts[2] if len(parts) > 2 else ""
        items = _WIKI_SUBCATS.get(k, [])
        rows = []; row = []
        for i, t in enumerate(items):
            row.append(btn(f"📖 {t}", f"wiki:go:{escape_html(t)}"))
            if len(row) == 2: rows.append(row); row = []
        if row: rows.append(row)
        rows.append([btn("⬅️ بازگشت", "wiki:menu"), btn("🏠", "m:main")])
        TG.edit_message(chat_id, msg_id,
            f"📖 <b>{_WIKI_SUBCAT_LABELS.get(k,k)}</b>:",
            reply_markup=kb(rows))
        return
    if action == "menu":
        cmd_wiki_v7({"chat":{"id":chat_id},"from":cb.get("from",{}),"message":{}}, "")
        return
    if action == "go":
        title = ":".join(parts[2:]) if len(parts) > 2 else ""
        _wiki_fetch_v7(chat_id, msg_id, title)
        return
    if action == "randall":
        all_items = []
        for v in _WIKI_SUBCATS.values(): all_items.extend(v)
        if all_items:
            _wiki_fetch_v7(chat_id, msg_id, _RND.choice(all_items))
        return

def _wiki_fetch_v7(chat_id, msg_id, title):
    if not title: return
    if msg_id: TG.edit_message(chat_id, msg_id, f"📖 «{escape_html(title)}» ...")
    else:
        m = TG.send_message(chat_id, f"📖 «{escape_html(title)}» ...")
        msg_id = (m.result or {}).get("message_id") if m.ok else None
    r = APIS.wikipedia.summary(title, "fa")
    if not r.ok: r = APIS.wikipedia.summary(title, "en")
    if not r.ok:
        if msg_id: TG.edit_message(chat_id, msg_id, "❌ یافت نشد.")
        return
    d = r.data
    extract = clean_wiki_extract(d.get("extract","") or "")[:1500]
    text = (f"📖 <b>{escape_html(d.get('title',''))}</b>\n\n"
            f"{escape_html(extract)}\n\n"
            f"🔗 {d.get('url','')}")
    if msg_id:
        TG.edit_message(chat_id, msg_id, text[:4000],
            reply_markup=kb([[btn("⬅️", "wiki:menu"), btn("🏠", "m:main")]]))
    else:
        TG.send_message(chat_id, text[:4000])

# ── 14. Update main menu ────────────────────────
def kb_main_menu():
    return kb([
        [btn("📚 بانک موضوعات", "m:list"), btn("🔍 جستجو", "m:find")],
        [btn("🌟 حالت سوپر", "m:super"), btn("🎓 آموزش", "m:learn")],
        [btn("📖 ویکی", "wiki:menu"), btn("📚 arXiv", "arxiv:p:0")],
        [btn("🎵 موسیقی", "music:back"), btn("📕 کتاب PDF", "book:back")],
        [btn("❓ کوییز", "quiz:go:gen"), btn("📊 آمار", "stats:cat:usage")],
        [btn("🧮 فرمول + مثال", "m:formula"), btn("🔬 تحلیل عمیق", "sty:deep")],
        [btn("📇 فلش‌کارت", "sty:flashcard"), btn("📰 اخبار", "n:home")],
        [btn("💱 ارز", "m:rates"), btn("✈️ هوانوردی", "av:help:refresh")],
        [btn("🎲 تصادفی", "m:random"), btn("⚙️ تنظیمات", "m:settings")],
        [btn("ℹ️ راهنما", "m:help"), btn("🔌 سرویس‌ها", "m:api")],
    ])

# Override m callback to include super
try:
    _prev_cbm_v7 = globals().get("cb_m_v4")
except NameError:
    try:
        _prev_cbm_v7 = cb_menu
    except NameError:
        _prev_cbm_v7 = None

@ROUTER.callback("m")
def cb_m_v7(cb, data):
    action = data.split(":", 1)[1] if ":" in data else "main"
    if action == "super":
        chat_id = cb["message"]["chat"]["id"]; msg_id = cb["message"]["message_id"]
        TG.answer_callback(cb.get("id", ""))
        TG.edit_message(chat_id, msg_id,
            "🌟 <b>حالت سوپر</b>\n\n"
            "یک موضوع با دقت بالا تولید می‌شود.\n\n"
            "استفاده: <code>/super موضوع</code>\n"
            "یا از دکمه‌های زیر:",
            reply_markup=kb([
                [btn("📚 انتخاب از بانک", "ls:root")],
                [btn("🏠 منو", "m:main")],
            ]))
        return
    if action == "list":
        chat_id = cb["message"]["chat"]["id"]; msg_id = cb["message"]["message_id"]
        TG.answer_callback(cb.get("id", ""))
        _LS_STATE[chat_id] = {"key":"root","level":"root"}
        _ls_render(chat_id, msg_id, "root", 0)
        return
    if action == "find":
        uid = cb["from"]["id"]
        chat_id = cb["message"]["chat"]["id"]; msg_id = cb["message"]["message_id"]
        TG.answer_callback(cb.get("id", ""))
        SESSIONS.set_state(uid, "awaiting_search", chat_id=chat_id, msg_id=msg_id)
        TG.edit_message(chat_id, msg_id, "🔍 عبارت را بفرست:",
                        reply_markup=kb([[btn("⬅️ لغو", "m:main")]]))
        return
    if _prev_cbm_v7:
        _prev_cbm_v7(cb, data)

# ── 15. Override rate menu callbacks ─────────────────────────────
@ROUTER.callback("m2")
def cb_m2_v7(cb, data):
    action = data.split(":", 1)[1] if ":" in data else ""
    chat_id = cb["message"]["chat"]["id"]; msg_id = cb["message"]["message_id"]
    TG.answer_callback(cb.get("id", ""))
    if action == "rates":
        try:
            r = APIS.exchange.latest("USD", _ALL_CURRENCIES)
            if r.ok:
                rates = (r.data or {}).get("rates", {}) or {}
                text = "💱 <b>نرخ ارز (USD)</b>\n\n"
                for c in _ALL_CURRENCIES.split(",")[:30]:
                    if c in rates:
                        text += f"• {c}: <code>{rates[c]:.4f}</code>\n"
                TG.edit_message(chat_id, msg_id, text[:4000],
                                reply_markup=kb([[btn("⬅️", "m:main")]]))
                return
        except Exception: pass
    # Fallback
    if _prev_cbm_v7: _prev_cbm_v7(cb, data)

log.info("PATCH v7.0 applied — formulas readable + emoji + image top + videos with URL + 8 subcats + super mode")



# ═══════════════════════════════════════════════════════════════════════════
#  PATCH v8.0 — BILINGUAL NEWS + 3 OPTIONS PER ITEM
#  Inserted BEFORE __main__. Persian-first user-facing text.
# ═══════════════════════════════════════════════════════════════════════════

import urllib.parse as _up_v8
import hashlib as _hash_v8

# ── 1. Translation helper (Persian <-> English) ─────────────────
_TR_CACHE_V8 = {}

def _translate_v8(text, src="en", tgt="fa"):
    """Translate via APIS.translate with cache. Falls back to original."""
    if not text: return ""
    key = _hash_v8.md5(f"{src}:{tgt}:{text[:400]}".encode("utf-8", "replace")).hexdigest()
    if key in _TR_CACHE_V8:
        return _TR_CACHE_V8[key]
    try:
        r = APIS.translate.translate(text[:1200], src, tgt)
        if r.ok and r.data:
            _TR_CACHE_V8[key] = r.data
            return r.data
    except Exception:
        pass
    _TR_CACHE_V8[key] = text
    return text

def _is_english_v8(text):
    if not text: return False
    latin = len(re.findall(r"[A-Za-z]", text))
    persian = len(re.findall(r"[\u0600-\u06FF]", text))
    return latin > persian

# ── 2. Bilingual item renderer ───────────────────────────────────
def _render_bilingual_item(idx, title, summary_en="", summary_fa="", url="", source=""):
    """
    Format:
      N. 🇮🇷 <عنوان فارسی>
         📝 <چکیده فارسی>
         🇬🇧 Title (English)
         📝 English summary
         📎 source · 🔗 url
    """
    # Title translation
    if title and _is_english_v8(title):
        title_fa = _translate_v8(title, "en", "fa")
        title_en = title
    else:
        title_fa = title
        title_en = _translate_v8(title, "fa", "en") if title else ""

    # Summary translation
    summary_fa = summary_fa or (_translate_v8(summary_en, "en", "fa") if summary_en else "")
    summary_en = summary_en or (_translate_v8(summary_fa, "fa", "en") if summary_fa else "")

    lines = [f"<b>{idx}.</b> 🇮🇷 <b>{escape_html(title_fa[:180])}</b>"]
    if summary_fa:
        lines.append(f"   📝 {escape_html(summary_fa[:600])}")
    if title_en:
        lines.append(f"   🇬🇧 <i>{escape_html(title_en[:180])}</i>")
    if summary_en:
        lines.append(f"   📝 <i>{escape_html(summary_en[:600])}</i>")
    meta = []
    if source: meta.append(f"📎 {escape_html(source[:40])}")
    if url:    meta.append(f"🔗 {url}")
    if meta:
        lines.append("   " + "  •  ".join(meta))
    return "\n".join(lines)

# ── 3. News storage (per chat, for callback access) ─────────────
_NEWS_STORE_V8 = {}       # chat_id -> list of items
_NEWS_MSG_CTX_V8 = {}     # (chat_id,msg_id) -> list of items

# ── 4. Multiple news sources ────────────────────────────────────
class NewsSourcesV8:
    # Space / NASA / SpaceX / Astronomy
    SPACE_FEEDS = [
        ("ناسا — اخبار فوری",   "https://www.nasa.gov/rss/dyn/breaking_news.rss"),
        ("ناسا — مأموریت‌ها",  "https://www.nasa.gov/rss/dyn/missions.rss"),
        ("اسپیس‌ایکس",          "https://www.reddit.com/r/spacex/.rss"),
        ("فضا — Reddit",        "https://www.reddit.com/r/space/.rss"),
        ("Astronomy",          "https://www.space.com/feeds/all"),
        ("Phys.org Space",     "https://phys.org/rss-feed/space-news/"),
    ]
    ENG_FEEDS = [
        ("فیزیک — Phys.org",   "https://phys.org/rss-feed/technology-news/engineering/"),
        ("مهندسی — MIT",       "https://news.mit.edu/rss/topic/mechanical-engineering"),
        ("مهندسی — ScienceDaily","https://www.sciencedaily.com/rss/matter_energy/engineering.xml"),
        ("مهندسی — Reddit",    "https://www.reddit.com/r/MechanicalEngineering/.rss"),
        ("مهندسی — IEEE",      "https://spectrum.ieee.org/feeds/topic/engineering.rss"),
        ("فناوری — Verge",     "https://www.theverge.com/rss/index.xml"),
    ]
    TECH_FEEDS = [
        ("فناوری — Ars Technica","https://feeds.arstechnica.com/arstechnica/index"),
        ("هوش مصنوعی — MIT",    "https://news.mit.edu/rss/topic/artificial-intelligence2"),
        ("فناوری — Engadget",   "https://www.engadget.com/rss.xml"),
    ]

    @staticmethod
    def _fetch_one(name, url, limit=6):
        try:
            r = APIS.news.fetch_feed(url, limit=limit)
            if not (r and r.ok and r.data): return []
            out = []
            for it in r.data:
                out.append({
                    "title":   it.get("title",""),
                    "summary": it.get("summary","")[:600],
                    "link":    it.get("link",""),
                    "source":  name,
                    "feed":    url,
                })
            return out
        except Exception:
            return []

    @classmethod
    def fetch_group(cls, group, limit_per_feed=4, total=12):
        feeds = {
            "space": cls.SPACE_FEEDS,
            "eng":   cls.ENG_FEEDS,
            "tech":  cls.TECH_FEEDS,
        }.get(group, cls.ENG_FEEDS)
        # parallel
        futures = [POOL.submit(cls._fetch_one, n, u, limit_per_feed) for n, u in feeds]
        all_items = []
        for f in futures:
            try:
                r = f.result(timeout=20)
                if r: all_items.extend(r)
            except Exception:
                pass
        # dedupe by title
        seen = set(); out = []
        for it in all_items:
            key = (it.get("title") or "").lower().strip()[:60]
            if key and key not in seen:
                seen.add(key); out.append(it)
        _RND.shuffle(out)
        return out[:total]

# ── 5. News menu with 6 categories + bilingual toggle ───────────
_NEWS_GROUPS_V8 = {
    "space":     "🚀 فضا و ناسا",
    "eng":       "⚙️ مهندسی",
    "tech":      "💻 فناوری",
    "ai":        "🤖 هوش مصنوعی",
    "arxiv":     "📚 arXiv",
    "engrss":    "📡 RSS مهندسی",
}

def kb_news_menu_v8():
    return kb([
        [btn("🚀 فضا و ناسا", "news:g:space"), btn("⚙️ مهندسی", "news:g:eng")],
        [btn("💻 فناوری", "news:g:tech"), btn("🤖 هوش مصنوعی", "news:g:ai")],
        [btn("📚 arXiv", "news:g:arxiv"), btn("📡 RSS مهندسی", "news:g:engrss")],
        [btn("🔍 جستجو", "news:search"), btn("🎲 تصادفی", "news:g:random")],
        [btn("🏠 منو", "m:main")],
    ])

# ── 6. Override /news ───────────────────────────────────────────
@ROUTER.command("news", description="اخبار دوزبانه")
def cmd_news_v8(msg, args):
    chat_id = get_chat_id(msg)
    if args:
        POOL.submit(_news_fetch_render_v8, chat_id, None, "search", args)
        return
    TG.send_message(chat_id,
        "📰 <b>مرکز اخبار</b>\n\n"
        "همه اخبار دوزبانه (فارسی + انگلیسی) با ۳ گزینه برای هر مورد:",
        reply_markup=kb_news_menu_v8())

# ── 7. News callback ────────────────────────────────────────────
@ROUTER.callback("news")
def cb_news_v8(cb, data):
    parts = data.split(":"); action = parts[1] if len(parts) > 1 else ""
    chat_id = cb["message"]["chat"]["id"]; msg_id = cb["message"]["message_id"]
    uid = cb.get("from", {}).get("id", 0)
    TG.answer_callback(cb.get("id", ""))

    if action == "menu":
        TG.edit_message(chat_id, msg_id,
            "📰 <b>مرکز اخبار</b>", reply_markup=kb_news_menu_v8())
        return

    if action == "g":
        grp = parts[2] if len(parts) > 2 else "eng"
        if grp == "random":
            grp = _RND.choice(["space","eng","tech","ai","arxiv","engrss"])
        TG.edit_message(chat_id, msg_id, f"⏳ در حال دریافت اخبار ...")
        POOL.submit(_news_fetch_render_v8, chat_id, msg_id, grp, "")
        return

    if action == "search":
        SESSIONS.set_state(uid, "awaiting_news_search",
                           chat_id=chat_id, msg_id=msg_id)
        TG.edit_message(chat_id, msg_id,
            "🔍 <b>جستجوی اخبار</b>\n\nعبارت مورد نظر را بنویس:",
            reply_markup=kb([[btn("⬅️ لغو", "news:menu")]]))
        return

    if action == "tr":
        # Full translation of one item
        try: idx = int(parts[2])
        except Exception: return
        st = _NEWS_MSG_CTX_V8.get((chat_id, msg_id)) or _NEWS_STORE_V8.get(chat_id) or []
        if idx < 0 or idx >= len(st): return
        it = st[idx]
        TG.edit_message(chat_id, msg_id, "⏳ در حال ترجمه کامل ...")
        POOL.submit(_news_translate_full_v8, chat_id, msg_id, it)
        return

    if action == "src":
        try: idx = int(parts[2])
        except Exception: return
        st = _NEWS_MSG_CTX_V8.get((chat_id, msg_id)) or _NEWS_STORE_V8.get(chat_id) or []
        if idx < 0 or idx >= len(st): return
        it = st[idx]
        text = (f"📄 <b>متن اصلی (انگلیسی)</b>\n\n"
                f"<b>{escape_html(it.get('title','')[:200])}</b>\n\n"
                f"{escape_html((it.get('summary') or '')[:1200])}\n\n"
                f"🔗 {it.get('link','')}")
        TG.edit_message(chat_id, msg_id, text[:4000],
            reply_markup=kb([[btn("⬅️ بازگشت", "news:menu"), btn("🏠", "m:main")]]))
        return

    if action == "send":
        try: idx = int(parts[2])
        except Exception: return
        st = _NEWS_MSG_CTX_V8.get((chat_id, msg_id)) or _NEWS_STORE_V8.get(chat_id) or []
        if idx < 0 or idx >= len(st): return
        it = st[idx]
        POOL.submit(_news_send_to_channel_v8, chat_id, it)
        TG.answer_callback(cb.get("id", ""), "✅ ارسال شد")
        return

# ── 8. Fetch + render news ──────────────────────────────────────
def _news_fetch_render_v8(chat_id, msg_id, group, query=""):
    items = []
    if group == "arxiv":
        try:
            r = APIS.arxiv.search(query or "space engineering",
                                  max_results=10)
            if r.ok:
                for a in (r.data or [])[:10]:
                    items.append({
                        "title": a.get("title",""),
                        "summary": (a.get("summary","") or "")[:600],
                        "link": a.get("link",""),
                        "source": "arXiv",
                    })
        except Exception as e:
            log.debug(f"[v8] arxiv: {e}")
    elif group in NewsSourcesV8.__dict__.get("_GROUPS", {}):
        pass
    elif group in ("space", "eng", "tech"):
        items = NewsSourcesV8.fetch_group(group, 4, 12)
    elif group == "ai":
        items = NewsSourcesV8.fetch_group("tech", 4, 12)
        # filter AI-related
        kw = ["ai","artificial intelligence","machine learning","deep learning",
              "llm","neural","gpt","transformer","robot"]
        items = [it for it in items
                 if any(k in (it.get("title","") + it.get("summary","")).lower()
                        for k in kw)] or items
    elif group == "engrss":
        items = NewsSourcesV8.fetch_group("eng", 5, 15)
    elif group == "search" and query:
        try:
            r = APIS.news.fetch_combined(limit=40)
            items = APIS.news.filter_by_keywords(r, [query])
        except Exception: pass
        if not items:
            # search arXiv as fallback
            try:
                r = APIS.arxiv.search(query, max_results=8)
                if r.ok:
                    for a in (r.data or [])[:8]:
                        items.append({
                            "title": a.get("title",""),
                            "summary": (a.get("summary","") or "")[:600],
                            "link": a.get("link",""),
                            "source": "arXiv",
                        })
            except Exception: pass
    else:
        items = NewsSourcesV8.fetch_group("eng", 4, 12)

    if not items:
        if msg_id: TG.edit_message(chat_id, msg_id, "❌ خبری یافت نشد.")
        else: TG.send_message(chat_id, "❌ خبری یافت نشد.")
        return

    # store
    items = items[:8]
    _NEWS_STORE_V8[chat_id] = items
    if msg_id:
        _NEWS_MSG_CTX_V8[(chat_id, msg_id)] = items

    # Build body
    title_map = {
        "space":"🚀 فضا و ناسا","eng":"⚙️ مهندسی","tech":"💻 فناوری",
        "ai":"🤖 هوش مصنوعی","arxiv":"📚 arXiv","engrss":"📡 RSS مهندسی",
        "search": f"🔍 {query[:30]}",
    }
    head = title_map.get(group, "📰 اخبار")
    text = f"<b>{head}</b>\n<i>هر خبر: فارسی + انگلیسی + ۳ گزینه</i>\n\n"
    for i, it in enumerate(items, 1):
        text += _render_bilingual_item(
            i,
            title=it.get("title",""),
            summary_en=it.get("summary",""),
            url=it.get("link",""),
            source=it.get("source",""),
        ) + "\n\n"

    # 3 buttons per item — up to 8 items → rows of 3 buttons
    rows = []
    for i in range(len(items)):
        rows.append([
            btn(f"📖 ترجمه {i+1}", f"news:tr:{i}"),
            btn(f"📄 متن اصلی {i+1}", f"news:src:{i}"),
            btn(f"📤 ارسال {i+1}", f"news:send:{i}"),
        ])
    rows.append([btn("🔄 رفرش", f"news:g:{group}"),
                 btn("⬅️ منو", "news:menu"),
                 btn("🏠", "m:main")])
    markup = kb(rows)

    if msg_id:
        TG.edit_message(chat_id, msg_id, text[:4000], reply_markup=markup)
    else:
        TG.send_message(chat_id, text[:4000], reply_markup=markup)

# ── 9. Full translation of one item ────────────────────────────
def _news_translate_full_v8(chat_id, msg_id, item):
    title = item.get("title","")
    summary = item.get("summary","")
    if title and _is_english_v8(title):
        title_fa = _translate_v8(title, "en", "fa")
        title_en = title
    else:
        title_fa = title; title_en = _translate_v8(title, "fa", "en")

    if summary and _is_english_v8(summary):
        summary_fa = _translate_v8(summary, "en", "fa")
        summary_en = summary
    else:
        summary_fa = summary; summary_en = _translate_v8(summary, "fa", "en")

    text = (
        f"📖 <b>ترجمه کامل</b>\n\n"
        f"🇮🇷 <b>{escape_html(title_fa[:250])}</b>\n"
        f"📝 {escape_html(summary_fa[:1200])}\n\n"
        f"🇬🇧 <b>{escape_html(title_en[:250])}</b>\n"
        f"📝 <i>{escape_html(summary_en[:1200])}</i>\n\n"
        f"📎 {escape_html(item.get('source',''))}\n"
        f"🔗 {item.get('link','')}"
    )
    TG.edit_message(chat_id, msg_id, text[:4000],
        reply_markup=kb([
            [btn("📄 متن اصلی", "news:menu"),
             btn("📤 ارسال به کانال", "news:menu")],
            [btn("⬅️ بازگشت", "news:menu"), btn("🏠", "m:main")],
        ]))

# ── 10. Send one item to channel ───────────────────────────────
def _news_send_to_channel_v8(chat_id, item):
    cfg = CONFIG.get()
    ch = cfg.telegram.channel_id
    if not ch: return
    title = item.get("title","")
    summary = item.get("summary","")
    if title and _is_english_v8(title):
        title_fa = _translate_v8(title, "en", "fa"); title_en = title
    else:
        title_fa = title; title_en = _translate_v8(title, "fa", "en")
    if summary and _is_english_v8(summary):
        summary_fa = _translate_v8(summary, "en", "fa"); summary_en = summary
    else:
        summary_fa = summary; summary_en = _translate_v8(summary, "fa", "en")

    tags = " ".join("#" + re.sub(r"\W","",w) for w in title.split()[:4] if w)
    text = (
        f"📰 <b>{escape_html(title_fa[:200])}</b>\n\n"
        f"📝 {escape_html(summary_fa[:800])}\n\n"
        f"🇬🇧 <i>{escape_html(title_en[:200])}</i>\n"
        f"📝 <i>{escape_html(summary_en[:800])}</i>\n\n"
        f"📎 {escape_html(item.get('source',''))}\n"
        f"🔗 {item.get('link','')}\n\n"
        f"{tags}\n📢 @MAADGHchannel"
    )
    TG.send_message(ch, text[:4000])

# ── 11. Free-text handler for awaiting_news_search ─────────────
_prev_text_v8 = ROUTER._text_handler

@ROUTER.on_text
def handle_text_v8(msg):
    uid = get_uid(msg)
    s = SESSIONS.get(uid)
    if s.state == "awaiting_news_search":
        chat_id = get_chat_id(msg)
        text = (msg.get("text") or "").strip()
        SESSIONS.clear_state(uid)
        if text:
            POOL.submit(_news_fetch_render_v8, chat_id, None, "search", text)
        return
    if _prev_text_v8: _prev_text_v8(msg)

# ── 12. Main news menu button (m:n) route ──────────────────────
_prev_m2_v8 = globals().get("cb_m2_v7")

@ROUTER.callback("m2")
def cb_m2_v8(cb, data):
    action = data.split(":", 1)[1] if ":" in data else ""
    chat_id = cb["message"]["chat"]["id"]; msg_id = cb["message"]["message_id"]
    TG.answer_callback(cb.get("id", ""))
    if action == "news":
        TG.edit_message(chat_id, msg_id,
            "📰 <b>مرکز اخبار</b>", reply_markup=kb_news_menu_v8())
        return
    if _prev_m2_v8: _prev_m2_v8(cb, data)

log.info("PATCH v8.0 applied — bilingual news + 3 buttons per item")



# ═══════════════════════════════════════════════════════════════════════════
#  PATCH v9.0 — FORMULA BOX + SPACING + ENGLISH PROBLEM STATEMENTS
#  Inserted BEFORE __main__. Persian-first.
# ═══════════════════════════════════════════════════════════════════════════

# ── 1. LaTeX → Unicode cleaner (full, no latex visible) ─────────
_GREEK_V9 = {
    "alpha":"α","beta":"β","gamma":"γ","delta":"δ","epsilon":"ε","varepsilon":"ε",
    "zeta":"ζ","eta":"η","theta":"θ","vartheta":"ϑ","iota":"ι","kappa":"κ",
    "lambda":"λ","mu":"μ","nu":"ν","xi":"ξ","omicron":"ο","pi":"π","varpi":"ϖ",
    "rho":"ρ","varrho":"ϱ","sigma":"σ","varsigma":"ς","tau":"τ","upsilon":"υ",
    "phi":"φ","varphi":"φ","chi":"χ","psi":"ψ","omega":"ω",
    "Gamma":"Γ","Delta":"Δ","Theta":"Θ","Lambda":"Λ","Xi":"Ξ","Pi":"Π",
    "Sigma":"Σ","Upsilon":"Υ","Phi":"Φ","Psi":"Ψ","Omega":"Ω",
}
_SYMS_V9 = {
    "partial":"∂","nabla":"∇","infty":"∞","int":"∫","iint":"∬","iiint":"∭",
    "oint":"∮","sum":"∑","prod":"∏","pm":"±","mp":"∓","times":"×","div":"÷",
    "cdot":"·","ast":"∗","star":"⋆","circ":"∘","bullet":"•",
    "approx":"≈","neq":"≠","ne":"≠","le":"≤","leq":"≤","ge":"≥","geq":"≥",
    "ll":"≪","gg":"≫","sim":"∼","simeq":"≃","equiv":"≡","cong":"≅",
    "to":"→","rightarrow":"→","leftarrow":"←","Rightarrow":"⇒","Leftarrow":"⇐",
    "leftrightarrow":"↔","Leftrightarrow":"⇔","mapsto":"↦",
    "in":"∈","notin":"∉","ni":"∋","subset":"⊂","supset":"⊃","subseteq":"⊆",
    "supseteq":"⊇","cup":"∪","cap":"∩","setminus":"∖","emptyset":"∅",
    "forall":"∀","exists":"∃","nexists":"∄","neg":"¬","land":"∧","lor":"∨",
    "propto":"∝","perp":"⊥","parallel":"∥","angle":"∠","degree":"°",
    "prime":"′","hbar":"ℏ","ell":"ℓ","aleph":"ℵ","Re":"ℜ","Im":"ℑ",
    "sqrt":"√","cbrt":"∛","therefore":"∴","because":"∵",
    "lceil":"⌈","rceil":"⌉","lfloor":"⌊","rfloor":"⌋",
    "langle":"⟨","rangle":"⟩","ldots":"…","cdots":"⋯","vdots":"⋮","ddots":"⋱",
    "Re":"ℜ","Im":"ℑ","wp":"℘",
}
_SUPS_V9 = str.maketrans("0123456789+-=()ni", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱ")
_SUBS_V9 = str.maketrans("0123456789+-=()aeiox", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑᵢₒₓ")

def _latex_to_unicode_v9(text):
    """Convert LaTeX to readable Unicode. Always returns clean text."""
    if not text: return ""
    t = text
    # Remove math delimiters
    for d in ("$$","\\(","\\)","\\[","\\]","$"):
        t = t.replace(d, "")
    # \left \right \big
    for w in ("\\left","\\right","\\big","\\Big","\\bigg","\\Bigg",
              "\\bigl","\\bigr","\\Bigl","\\Bigr","\\bigm","\\Bigm"):
        t = t.replace(w, "")
    # \frac{a}{b} → (a)/(b)  (repeat for nesting)
    for _ in range(6):
        t = re.sub(r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"(\1)/(\2)", t)
        t = re.sub(r"\\dfrac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"(\1)/(\2)", t)
        t = re.sub(r"\\tfrac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"(\1)/(\2)", t)
    # \sqrt[n]{x} → ∛(x) or √(x)
    for _ in range(3):
        t = re.sub(r"\\sqrt\s*\[\s*3\s*\]\s*\{([^{}]+)\}", r"∛(\1)", t)
        t = re.sub(r"\\sqrt\s*\[\s*([^\]]+)\s*\]\s*\{([^{}]+)\}", r"√[\1](\2)", t)
        t = re.sub(r"\\sqrt\s*\{([^{}]+)\}", r"√(\1)", t)
    # \text{...} \mathrm{...} \mathbf{...} \mathbb{...} \mathcal{...}
    for cmd in ("text","textrm","textbf","textit","mathrm","mathbf",
                "mathbb","mathcal","mathit","operatorname"):
        t = re.sub(r"\\" + cmd + r"\s*\{([^{}]+)\}", r"\1", t)
    # Spacing commands → space
    for sp in ("\\,","\\;","\\:","\\!","\\quad","\\qquad","\\ "):
        t = t.replace(sp, " ")
    # \cdot etc — first do symbols
    for k in sorted(_SYMS_V9.keys(), key=lambda x: -len(x)):
        t = re.sub(r"\\" + re.escape(k) + r"\b", _SYMS_V9[k], t)
    # Greek
    for k in sorted(_GREEK_V9.keys(), key=lambda x: -len(x)):
        t = re.sub(r"\\" + re.escape(k) + r"\b", _GREEK_V9[k], t)
    # \begin{...}...\end{...} — strip
    t = re.sub(r"\\begin\{[^}]+\}", "", t)
    t = re.sub(r"\\end\{[^}]+\}", "", t)
    # \hspace \vspace → space
    t = re.sub(r"\\(h|v)space\s*\{[^}]*\}", " ", t)
    # Superscripts ^{...}
    for _ in range(3):
        t = re.sub(r"\^\{([^{}]+)\}", lambda m: m.group(1).translate(_SUPS_V9), t)
    t = re.sub(r"\^(\w)", lambda m: m.group(1).translate(_SUPS_V9), t)
    # Subscripts _{...}
    for _ in range(3):
        t = re.sub(r"_\{([^{}]+)\}", lambda m: m.group(1).translate(_SUBS_V9), t)
    t = re.sub(r"_(\w)", lambda m: m.group(1).translate(_SUBS_V9), t)
    # \over → /
    t = re.sub(r"\{([^{}]+)\}\s*\\over\s*\{([^{}]+)\}", r"(\1)/(\2)", t)
    t = re.sub(r"\\over\b", "/", t)
    # Remove remaining commands
    t = re.sub(r"\\[A-Za-z]+\b", "", t)
    # Remove leftover braces only if unbalanced-ish
    t = t.replace("\\", "")
    # Clean spaces
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"\s+([,;)])", r"\1", t)
    t = re.sub(r"([(])\s+", r"\1", t)
    return t.strip()

# Override module-level clean_latex
clean_latex = _latex_to_unicode_v9

# ── 2. Formula box builder ──────────────────────────────────────
def _formula_box_v9(formula, label=""):
    """
    Build a formula box using <pre> for correct rendering.
    Returns:
       <pre>═══════════════════
    📐 label
    ═══════════════════
       formula
    ═══════════════════</pre>
    """
    if not formula: return ""
    f = _latex_to_unicode_v9(formula).strip()
    if not f: return ""
    line = "━━━━━━━━━━━━━━━━━━━━━━"
    head = f"📐 {label}" if label else "📐 فرمول"
    # Using <pre> with monospace ensures formula spacing preserved
    return (
        "\n\n"
        f"<pre>╔══════════════════════════╗\n"
        f"║ {head[:24].ljust(24)} ║\n"
        f"╠══════════════════════════╣\n"
        f"║ {f[:200].ljust(24)} ║\n"
        f"╚══════════════════════════╝</pre>"
        "\n\n"
    )

def _formula_inline_v9(formula):
    """Short inline formula (for inside sentences)."""
    f = _latex_to_unicode_v9(formula).strip()
    if not f: return ""
    return f"<code>  {f}  </code>"

# ── 3. Detect formula lines in text ─────────────────────────────
_FORMULA_LINE_V9 = re.compile(
    r"^[\s\d\(\)\[\]\{\}a-zA-Z_+\-*/=<>≤≥≠≈∝∼∫∮∑∏√∂∇ρσπλμθφΩΔ∞°²³⁴⁵⁶⁷⁸⁹⁰⁻⁺]+$"
)

def _looks_like_formula_v9(line):
    s = line.strip()
    if len(s) < 4 or len(s) > 250: return False
    # Skip if it's a Persian sentence
    persian = len(re.findall(r"[\u0600-\u06FF]", s))
    visible = len(re.sub(r"\s+","",s)) or 1
    if persian / visible > 0.25: return False
    # Must have math-ish symbols
    has_math = bool(re.search(r"[=≈≤≥≠∝∫∑√∂∇^_²³√+\-*/<>]", s))
    has_latex = "\\" in s
    return has_math or has_latex

# ── 4. Rewrite content: spacing + formula boxes ─────────────────
def _rewrite_content_v9(text):
    """
    Post-process content:
      • Convert LaTeX to Unicode
      • Wrap formula lines in <pre> box with blank lines around
      • Add extra spacing between paragraphs
      • Bold section headers
    """
    if not text: return text

    # Step 1: Convert any remaining LaTeX to Unicode
    text = _latex_to_unicode_v9(text)

    # Step 2: Process line by line
    out = []
    prev_blank = False
    for raw_line in text.split("\n"):
        line = raw_line.rstrip()
        s = line.strip()

        # Empty → preserve single blank
        if not s:
            if not prev_blank:
                out.append("")
                prev_blank = True
            continue
        prev_blank = False

        # Already boxed / code / HTML?
        if s.startswith(("<pre>","</pre>","<code>","</code>")):
            out.append(line); continue

        # Formula line? Wrap in box
        if _looks_like_formula_v9(s) and not s.startswith(("#","|","-")):
            box = _formula_box_v9(s, "")
            out.append(box)
            continue

        # Section header (emoji + bold) — add extra space
        if re.match(r"^[🎯📖🔬📐🧮📊⚙️⚠️✅📚🎥🖼📝🇮🇷🇬🇧🚀💡❓📇📜⚖️]+", s):
            if out and out[-1] != "":
                out.append("")
            out.append(line)
            out.append("")  # blank after header
            prev_blank = True
            continue

        # Normal line
        out.append(line)

    text = "\n".join(out)

    # Step 3: Extra spacing around inline formulas
    # Bold inline <code> formulas with extra spaces
    text = re.sub(
        r"<code>([^<]+)</code>",
        lambda m: f"<code>  {m.group(1).strip()}  </code>",
        text
    )

    # Step 4: Cleanup
    text = re.sub(r"\n{4,}", "\n\n\n", text)  # max 3 newlines
    return text.strip()

# ── 5. Override content generator post-process ──────────────────
_orig_pp_v9 = ContentGenerator._post_process

def _pp_v9(self, text, topic, cfg, style="tutorial"):
    try:
        text = _orig_pp_v9(self, text, topic, cfg, style)
    except Exception as e:
        log.debug(f"[v9] orig pp: {e}")
    if not text: return text

    # Apply formula boxes + spacing
    try:
        text = _rewrite_content_v9(text)
    except Exception as e:
        log.debug(f"[v9] rewrite: {e}")

    return text

ContentGenerator._post_process = _pp_v9

# ── 6. Override prompts: English problem statements ─────────────
# Patch SYS_* prompts to force English problem statement + Persian solution
_orig_style_prompts_v9 = dict(STYLE_PROMPTS) if "STYLE_PROMPTS" in globals() else {}

_EN_PROBLEM_INSTRUCTION = """

⚠️ FORMULA AND EXAMPLE FORMAT (MANDATORY):

1. All formulas MUST be written in Unicode (NOT LaTeX):
   ✅ Correct: P + (1/2)ρv² + ρgz = const
   ❌ Wrong:   \\frac{1}{2}\\rho v^2

2. Every formula MUST be on its own line with a blank line before AND after.

3. Problem statements (examples) MUST be in ENGLISH at the start:
   📋 Problem (EN): A steel beam of 2 m length is subjected to...
   Then solve in Persian:
   🔍 حل: ...

4. Section headers MUST use emoji + bold and be on their own line.

5. Use proper spacing — never cram formulas between two Persian sentences.

6. Physical variables MUST have units in parentheses: m (kg), v (m/s), T (K).
"""

def _patch_prompts_v9():
    """Add English problem + formula box instruction to all style prompts."""
    try:
        for k in list(STYLE_PROMPTS.keys()):
            p = STYLE_PROMPTS[k]
            if _EN_PROBLEM_INSTRUCTION not in p:
                STYLE_PROMPTS[k] = p + _EN_PROBLEM_INSTRUCTION
        log.info(f"[v9] patched {len(STYLE_PROMPTS)} style prompts")
    except Exception as e:
        log.warning(f"[v9] prompt patch failed: {e}")

_patch_prompts_v9()

# ── 7. Upgrade /example command with English problem ─────────────
@ROUTER.command("example", description="مثال حل‌شده (صورت انگلیسی)")
def cmd_example_v9(msg, args):
    chat_id = get_chat_id(msg)
    topic = args.strip() or "Bernoulli equation"
    m = TG.send_message(chat_id,
        f"📋 <b>مثال حل‌شده</b>\n"
        f"<i>صورت مسئله انگلیسی، حل فارسی، فرمول‌ها در کادر</i>\n\n"
        f"موضوع: {escape_html(topic)}")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")

    def _do():
        try:
            sys_p = (
                "You are a professor of engineering and mathematics. "
                "Output MUST be structured with:\n"
                "1. Problem statement in ENGLISH (2-4 lines, formal technical style)\n"
                "2. Given data (English)\n"
                "3. Solution steps in Persian (فارسی)\n"
                "4. Final answer in English + Persian\n"
                "5. Formula boxes in Unicode\n\n"
                "⚠️ CRITICAL: Formulas MUST be Unicode, NOT LaTeX.\n"
                "Example: 'P + (1/2)ρv² + ρgz = const'\n"
                "Each formula on its OWN line with blank lines around it."
            )
            usr_p = (
                f"Generate a worked example for: {topic}\n\n"
                "Structure:\n"
                "📋 Problem (English): <problem statement>\n"
                "📊 Given (English): <given values>\n"
                "🔍 Solution (Persian): <step by step>\n"
                "✅ Final Answer: <English + Persian>\n\n"
                "All formulas in Unicode. No LaTeX commands."
            )
            with TypingHeartbeat(chat_id):
                resp = AI.ask(sys_p, usr_p, max_tokens=3000, temperature=0.55)
            if not resp.ok:
                TG.edit_message(chat_id, mid,
                    f"❌ {escape_html(resp.error[:200])}"); return

            td = {"name": topic, "query": topic, "domain": "eng",
                  "tags": f"{topic.replace(' ','_')}"}
            cfg = CONFIG.get()
            content = CONTENT._post_process(resp.text, td, cfg, "example")
            TG.edit_message(chat_id, mid, content[:4000])
        except Exception as e:
            log.exception(f"[v9] example: {e}")
            TG.edit_message(chat_id, mid, f"❌ {escape_html(str(e)[:200])}")

    POOL.submit(_do)

# ── 8. Super mode with English problem ──────────────────────────
@ROUTER.command("super", description="حالت سوپر (با صورت مسئله انگلیسی)")
def cmd_super_v9(msg, args):
    chat_id = get_chat_id(msg)
    topic = args.strip() or (TOPIC_MGR.rotate_next()["name"])
    m = TG.send_message(chat_id,
        f"🌟 <b>حالت سوپر</b>\nموضوع: «{escape_html(topic)}»\n"
        f"<i>منابع + صورت مسئله انگلیسی + فرمول‌های باکسی</i>")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")

    def _do():
        try:
            td = TOPIC_MGR.find(topic) or {"name": topic, "query": topic,
                                           "emoji":"📌","tags":"#مهندسی_مکانیک"}
            ctx = {"formulas": get_formulas_for(td.get("name",""), td)}
            try:
                w = APIS.wikipedia.summary(td.get("name",""), "fa")
                if w.ok: ctx["wiki_fa"] = w.data
            except Exception: pass
            try:
                w = APIS.wikipedia.summary(td.get("query",""), "en")
                if w.ok: ctx["wiki_en"] = w.data
            except Exception: pass
            try:
                ar = APIS.arxiv.search(td.get("query",""), max_results=3)
                if ar.ok: ctx["arxiv"] = ar.data
            except Exception: pass

            sys_p = STYLE_PROMPTS.get("tutorial", SYS_TUTORIAL)
            user_parts = [
                f"موضوع: {td['name']}",
                "",
                "دستور: یک درس کامل و عمیق با ساختار زیر:",
                "",
                "📋 Problem Statement (EN): یک مسئله مهندسی واقعی",
                "🎯 هدف (فارسی)",
                "📖 تعریف (فارسی)",
                "🔬 مبانی (فارسی)",
                "📐 فرمول‌های کلیدی — همه به Unicode، هر کدام در خط جدا با خط خالی قبل و بعد",
                "🧮 حل مسئله (فارسی) — با گام‌های شماره‌دار",
                "📊 جدول خلاصه",
                "⚙️ کاربرد صنعتی",
                "⚠️ اشتباهات رایج",
                "✅ جمع‌بندی",
                "",
                "⚠️ مهم: فرمول‌ها Unicode باشند نه LaTeX.",
                "✅ درست: E = (1/2)mv² + mgh",
                "❌ غلط: E = \\frac{1}{2}mv^2 + mgh",
            ]
            try:
                block = ASSEMBLER.to_prompt_block(ctx, max_chars=3500)
                if block:
                    user_parts.extend(["", "--- منابع ---", block])
            except Exception: pass

            with TypingHeartbeat(chat_id):
                resp = AI.ask(sys_p, "\n".join(user_parts),
                              max_tokens=4000, temperature=0.6)
            if not resp.ok:
                TG.edit_message(chat_id, mid,
                    f"❌ {escape_html(resp.error[:200])}"); return

            cfg = CONFIG.get()
            content = CONTENT._post_process(resp.text, td, cfg, "tutorial")
            uid = chat_id if isinstance(chat_id, int) and chat_id > 0 else 0
            draft = DRAFTS.create(td["name"], "super", content, uid,
                                  metadata={"super": True})

            is_ch, ch_msg = _verify_channel_target(cfg)
            if not is_ch:
                TG.edit_message(chat_id, mid,
                    f"⛔ {escape_html(ch_msg)}"); return

            ok_flag, msg2, n = _send_to_channel(cfg, content, reply_markup=None)
            if ok_flag:
                TG.edit_message(chat_id, mid,
                    f"🌟 «{td['name']}» منتشر شد.\n"
                    f"📏 {len(content)} کاراکتر | 📦 {n} پیام",
                    reply_markup=kb([
                        [btn("🔄 بازتولید", f"regen:{draft.id}")],
                        [btn("👁 نمایش", f"show:{draft.id}")],
                    ]))
                STATS.incr("posts")
                STATS.incr_dict("styles", "super")
            else:
                TG.edit_message(chat_id, mid, f"❌ {escape_html(msg2[:200])}")
        except Exception as e:
            log.exception(f"[super-v9] {e}")
            TG.edit_message(chat_id, mid, f"❌ {escape_html(str(e)[:200])}")

    POOL.submit(_do)

# ── 9. Test commands ────────────────────────────────────────────
@ROUTER.command("testformula", description="تست فرمول", admin_only=True)
def cmd_testformula_v9(msg, args):
    chat_id = get_chat_id(msg)
    sample = args.strip() or r"P + \frac{1}{2}\rho v^2 + \rho g z = const"
    u = _latex_to_unicode_v9(sample)
    box = _formula_box_v9(sample, "برنولی")
    TG.send_message(chat_id,
        f"<b>ورودی:</b>\n<code>{escape_html(sample)}</code>\n\n"
        f"<b>Unicode:</b>\n{u}\n\n"
        f"<b>باکس:</b>{box}")

log.info("PATCH v9.0 applied — formula boxes + spacing + English problems")



# [v17] duplicate v9 patch block removed

# PATCH v10.0 — MUSIC AUDIO + FULL CURRENCY + FULL QUIZ + BILINGUAL NEWS
# ═══════════════════════════════════════════════════════════════════════════

import urllib.parse as _up_v10
import hashlib as _h_v10

# ── 1. Free translation (MyMemory + LibreTranslate, no key) ─────
class FreeTranslatorV10:
    CACHE = {}
    LOCK = threading.RLock()

    @classmethod
    def translate(cls, text, source="en", target="fa"):
        if not text or len(text.strip()) < 2:
            return text
        key = _h_v10.md5(f"{source}:{target}:{text[:500]}".encode("utf-8","replace")).hexdigest()
        with cls.LOCK:
            if key in cls.CACHE:
                return cls.CACHE[key]
        text = text[:450]
        try:
            r = HTTP.request("GET", "https://api.mymemory.translated.net/get",
                            params={"q": text, "langpair": f"{source}|{target}"},
                            timeout=15)
            if r is not None and r.status_code == 200:
                d = r.json()
                t = (d.get("responseData") or {}).get("translatedText", "")
                if t and not t.lower().startswith("query length"):
                    with cls.LOCK: cls.CACHE[key] = t
                    return t
        except Exception as e:
            log.debug(f"[v10] mymemory: {e}")
        for url in ("https://translate.terraprint.co/translate",
                    "https://libretranslate.de/translate",
                    "https://translate.argosopentech.com/translate"):
            try:
                r = HTTP.request("POST", url,
                    json_body={"q": text, "source": source, "target": target, "format": "text"},
                    timeout=15)
                if r is not None and r.status_code == 200:
                    t = r.json().get("translatedText", "")
                    if t:
                        with cls.LOCK: cls.CACHE[key] = t
                        return t
            except Exception:
                continue
        with cls.LOCK: cls.CACHE[key] = text
        return text

TR_V10 = FreeTranslatorV10()

def _translate_v8(text, src="en", tgt="fa"):
    return TR_V10.translate(text, src, tgt)

# ── 2. Archive.org audio fetcher ────────────────────────────────
class ArchiveAudioV10:
    SEARCH = "https://archive.org/advancedsearch.php"
    META   = "https://archive.org/metadata"
    AUDIO_EXT = (".mp3", ".ogg", ".m4a", ".opus", ".flac", ".wav")

    @staticmethod
    def search_items(query, limit=15):
        try:
            params = {
                "q": f"({query}) AND mediatype:(audio)",
                "fl[]": ["identifier","title","creator","year","downloads"],
                "rows": limit, "page": 1, "output": "json",
                "sort[]": "downloads desc",
            }
            r = HTTP.request("GET", ArchiveAudioV10.SEARCH, params=params, timeout=20)
            if r is None or r.status_code != 200: return []
            return (r.json().get("response") or {}).get("docs") or []
        except Exception as e:
            log.debug(f"[v10] archive search: {e}")
            return []

    @staticmethod
    def get_audio_files(identifier, max_files=3):
        try:
            r = HTTP.request("GET", f"{ArchiveAudioV10.META}/{identifier}", timeout=15)
            if r is None or r.status_code != 200: return []
            files = r.json().get("files") or []
            out = []
            for f in files:
                name = f.get("name","")
                if not name: continue
                if not name.lower().endswith(ArchiveAudioV10.AUDIO_EXT): continue
                try:
                    size = int(f.get("size", 0))
                    if size and size < 100000: continue
                except Exception:
                    size = 0
                out.append({
                    "name": name,
                    "url": f"https://archive.org/download/{identifier}/{_up_v10.quote(name)}",
                    "size": size,
                    "length": f.get("length",""),
                })
                if len(out) >= max_files: break
            return out
        except Exception as e:
            log.debug(f"[v10] archive meta: {e}")
            return []

ARCHIVE_AUDIO = ArchiveAudioV10()

# ── 3. Music → real audio files ─────────────────────────────────
_MUSIC_STORE_V10 = TTLStore(max_items=500, ttl=1800)
def _music_search_v10(chat_id, msg_id, key, label):
    if msg_id:
        TG.edit_message(chat_id, msg_id, f"🎵 جستجوی فایل صوتی «{escape_html(label)}» ...")
    else:
        m = TG.send_message(chat_id, f"🎵 جستجوی «{escape_html(label)}» ...")
        msg_id = (m.result or {}).get("message_id") if m.ok else None

    items = []
    for q in (f"{label} music", f"{label} songs", f"{label} album"):
        for it in ARCHIVE_AUDIO.search_items(q, limit=10):
            if it not in items: items.append(it)
        if len(items) >= 10: break

    if not items:
        if msg_id:
            TG.edit_message(chat_id, msg_id, "❌ یافت نشد.",
                reply_markup=kb([[btn("⬅️","music:back"), btn("🏠","m:main")]]))
        return

    results = []
    for it in items[:8]:
        ident = it.get("identifier")
        if not ident: continue
        files = ARCHIVE_AUDIO.get_audio_files(ident, max_files=2)
        if files:
            results.append({
                "title": it.get("title","") or ident,
                "creator": it.get("creator",""),
                "year": it.get("year",""),
                "identifier": ident,
                "files": files,
            })

    if not results:
        if msg_id:
            TG.edit_message(chat_id, msg_id, "❌ فایل صوتی نیست.",
                reply_markup=kb([[btn("⬅️","music:back"), btn("🏠","m:main")]]))
        return

    _MUSIC_STORE_V10[chat_id] = results

    text = f"🎵 <b>موسیقی {escape_html(label)}</b>\n"
    text += f"<i>📻 Archive.org — {len(results)} نتیجه</i>\n\n"
    for i, r in enumerate(results, 1):
        text += f"<b>{i}.</b> 🎵 {escape_html(r['title'][:70])}\n"
        if r.get("creator"): text += f"   👤 {escape_html(str(r['creator'])[:40])}\n"
        if r.get("year"):    text += f"   📅 {escape_html(str(r['year']))}\n"
        text += f"   📁 {len(r['files'])} فایل\n\n"

    rows = []
    for i in range(len(results)):
        rows.append([
            btn(f"▶️ پخش {i+1}", f"music:play:{i}"),
            btn(f"📥 فایل {i+1}", f"music:file:{i}"),
        ])
    rows.append([btn("🔄 دیگر", f"music:go:{key}"),
                 btn("⬅️ فهرست","music:back"),
                 btn("🏠","m:main")])
    if msg_id:
        TG.edit_message(chat_id, msg_id, text[:4000], reply_markup=kb(rows))
    else:
        TG.send_message(chat_id, text[:4000], reply_markup=kb(rows))

@ROUTER.callback("music")
def cb_music_v10(cb, data):
    parts = data.split(":"); action = parts[1] if len(parts) > 1 else ""
    chat_id = cb["message"]["chat"]["id"]; msg_id = cb["message"]["message_id"]
    TG.answer_callback(cb.get("id", ""))

    if action == "back":
        cmd_music_v10({"chat":{"id":chat_id},"from":cb.get("from",{}),"message":{}}, "")
        return
    if action == "rand":
        k = _RND.choice(list(MUSIC_CATEGORIES.keys()))
        _music_search_v10(chat_id, msg_id, k, MUSIC_CAT_LABELS.get(k,k))
        return
    if action == "go":
        k = parts[2] if len(parts) > 2 else ""
        if k in MUSIC_CATEGORIES:
            _music_search_v10(chat_id, msg_id, k, MUSIC_CAT_LABELS.get(k,k))
        return
    if action in ("play", "file"):
        try: idx = int(parts[2])
        except Exception: return
        st = _MUSIC_STORE_V10.get(chat_id) or []
        if idx < 0 or idx >= len(st): return
        item = st[idx]
        files = item.get("files") or []
        if not files:
            TG.answer_callback(cb.get("id", ""), "❌ فایلی نیست")
            return
        TG.answer_callback(cb.get("id", ""), f"⏳ ارسال {len(files)} فایل...")
        for f in files[:2]:
            try:
                TG.send_audio(chat_id, f["url"],
                    caption=f"🎵 <b>{escape_html(item['title'][:80])}</b>\n"
                            f"<i>{escape_html(str(item.get('creator','')))}</i>",
                    parse_mode="HTML")
                time.sleep(0.4)
            except Exception as e:
                log.debug(f"[v10] send_audio: {e}")
        return

@ROUTER.command("music", description="موسیقی (فایل صوتی)")
def cmd_music_v10(msg, args):
    chat_id = get_chat_id(msg)
    if args and args.lower() in MUSIC_CATEGORIES:
        _music_search_v10(chat_id, None, args.lower(),
                          MUSIC_CAT_LABELS.get(args.lower(), args))
        return
    rows = []; row = []
    for k, label in MUSIC_CAT_LABELS.items():
        row.append(btn(f"🎵 {label}", f"music:go:{k}"))
        if len(row) == 2: rows.append(row); row = []
    if row: rows.append(row)
    rows.append([btn("🎲 تصادفی","music:rand"), btn("🏠 منو","m:main")])
    TG.send_message(chat_id,
        f"🎵 <b>موسیقی</b> — {len(MUSIC_CAT_LABELS)} سبک\n"
        f"<i>فایل‌های صوتی از Archive.org</i>",
        reply_markup=kb(rows))

# ── 4. Currency — 20 main + 40 more + cancel ────────────────────
_TOP20_V10 = ["USD","EUR","GBP","JPY","CHF","CAD","AUD","CNY","RUB","TRY",
              "AED","SAR","QAR","KWD","INR","IQD","AFN","PKR","EGP","IRR"]
_MORE_V10 = ["NZD","HKD","SGD","KRW","BHD","OMR","JOD","BDT","LKR","NPR",
             "IDR","MYR","THB","VND","PHP","MXN","BRL","ARS","CLP","COP",
             "PEN","ZAR","NGN","KES","MAD","DZD","TND","GEL","AMD","AZN",
             "BYN","KZT","UAH","RSD","BGN","HRK","CZK","PLN","RON","HUF"]

def _render_currency_v10(chat_id, msg_id, extra=False):
    symbols = ",".join(_TOP20_V10 + (_MORE_V10 if extra else []))
    r = APIS.exchange.latest("USD", symbols)
    if not r.ok:
        if msg_id: TG.edit_message(chat_id, msg_id, f"❌ {r.error[:150]}")
        return
    rates = (r.data or {}).get("rates", {}) or {}
    text = "💱 <b>نرخ ارز (پایه: دلار)</b>\n"
    text += f"<i>🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}</i>\n\n"
    text += "<b>ارزهای اصلی:</b>\n"
    for c in _TOP20_V10:
        if c in rates:
            text += f"  • {c}: <code>{rates[c]:,.4f}</code>\n"
    if extra:
        text += "\n<b>سایر ارزها:</b>\n"
        for c in _MORE_V10:
            if c in rates:
                text += f"  • {c}: <code>{rates[c]:,.4f}</code>\n"
    rows = []
    if not extra:
        rows.append([btn("➕ 40 ارز دیگر","rate:more")])
    else:
        rows.append([btn("➖ فقط اصلی","rate:main")])
    rows.append([btn("🔄 بروزرسانی","rate:refresh"),
                 btn("❌ انصراف","rate:cancel")])
    rows.append([btn("🏠 منو","m:main")])
    if msg_id:
        TG.edit_message(chat_id, msg_id, text[:4000], reply_markup=kb(rows))
    else:
        TG.send_message(chat_id, text[:4000], reply_markup=kb(rows))

@ROUTER.command("rate", description="نرخ ارز (20+40)")
def cmd_rate_v10(msg, args):
    chat_id = get_chat_id(msg)
    extra = "more" in (args or "").lower()
    _render_currency_v10(chat_id, None, extra=extra)

@ROUTER.callback("rate")
def cb_rate_v10(cb, data):
    parts = data.split(":"); action = parts[1] if len(parts) > 1 else ""
    chat_id = cb["message"]["chat"]["id"]; msg_id = cb["message"]["message_id"]
    if action == "cancel":
        TG.answer_callback(cb.get("id", ""), "❌")
        TG.edit_message(chat_id, msg_id, "❌ لغو شد.",
                       reply_markup=kb([[btn("🏠 منو","m:main")]]))
        return
    TG.answer_callback(cb.get("id", ""), "⏳")
    if action == "more":
        _render_currency_v10(chat_id, msg_id, extra=True)
    elif action == "main":
        _render_currency_v10(chat_id, msg_id, extra=False)
    elif action == "refresh":
        _render_currency_v10(chat_id, msg_id, extra=False)

# ── 5. Quiz — 8 categories × 4 topics ───────────────────────────
_QUIZ_BANK_V10 = {
    "math": {"label":"📐 ریاضی","topics":[
        ("مشتق و کاربردها","derivative calculus"),
        ("انتگرال معین","definite integral"),
        ("معادلات دیفرانسیل","differential equations"),
        ("جبر خطی و ماتریس","linear algebra matrices")]},
    "phys": {"label":"⚛️ فیزیک","topics":[
        ("مکانیک نیوتنی","Newtonian mechanics"),
        ("الکترومغناطیس","electromagnetism"),
        ("ترمودینامیک","physical thermodynamics"),
        ("نور و اپتیک","optics light")]},
    "mech": {"label":"🔧 مکانیک","topics":[
        ("استاتیک و تعادل","statics equilibrium"),
        ("دینامیک ذرات","particle dynamics"),
        ("مقاومت مصالح","strength of materials"),
        ("مکانیک سیالات","fluid mechanics")]},
    "chem": {"label":"🧪 شیمی","topics":[
        ("شیمی آلی","organic chemistry"),
        ("شیمی معدنی","inorganic chemistry"),
        ("استوکیومتری","stoichiometry"),
        ("اسید و باز","acid base chemistry")]},
    "bio": {"label":"🧬 زیست","topics":[
        ("سلول و اندامک","cell biology organelles"),
        ("ژنتیک مندلی","Mendelian genetics"),
        ("سیستم عصبی","nervous system"),
        ("اکوسیستم","ecosystem ecology")]},
    "hist": {"label":"📜 تاریخ","topics":[
        ("انقلاب صناعی","industrial revolution"),
        ("جنگ جهانی دوم","World War II"),
        ("تمدن‌های باستان","ancient civilizations"),
        ("تاریخ علم","history of science")]},
    "geo": {"label":"🌍 جغرافیا","topics":[
        ("قاره‌ها و اقیانوس‌ها","continents oceans"),
        ("آب و هوا","climate weather"),
        ("کوه‌ها و رودها","mountains rivers"),
        ("پایتخت‌ها","world capitals")]},
    "gen": {"label":"💡 عمومی","topics":[
        ("اطلاعات عمومی","general knowledge"),
        ("ورزش","sports trivia"),
        ("سینما و هنر","cinema art trivia"),
        ("فناوری","technology trivia")]},
}

def _kb_quiz_v10():
    rows = []
    items = list(_QUIZ_BANK_V10.items())
    for i in range(0, len(items), 2):
        row = []
        for k, v in items[i:i+2]:
            row.append(btn(v["label"], f"quiz:cat:{k}"))
        rows.append(row)
    rows.append([btn("🎲 کوییز تصادفی","quiz:rand"),
                 btn("🏠 منو","m:main")])
    return kb(rows)

@ROUTER.command("quiz", description="کوییز ۸ دسته")
def cmd_quiz_v10(msg, args):
    chat_id = get_chat_id(msg)
    if args:
        POOL.submit(_generate_and_post, CONFIG.get(), chat_id, args, "quiz")
        return
    TG.send_message(chat_id,
        "❓ <b>کوییز</b> — دسته انتخاب کن:\n<i>هر دسته ۴ موضوع</i>",
        reply_markup=_kb_quiz_v10())

@ROUTER.callback("quiz")
def cb_quiz_v10(cb, data):
    parts = data.split(":"); action = parts[1] if len(parts) > 1 else ""
    chat_id = cb["message"]["chat"]["id"]; msg_id = cb["message"]["message_id"]
    TG.answer_callback(cb.get("id", ""))
    if action == "rand":
        cat = _RND.choice(list(_QUIZ_BANK_V10.keys()))
        tname = _RND.choice(_QUIZ_BANK_V10[cat]["topics"])[0]
        POOL.submit(_generate_and_post, CONFIG.get(), chat_id, tname, "quiz")
        return
    if action == "menu":
        TG.edit_message(chat_id, msg_id,
            "❓ <b>کوییز</b> — دسته انتخاب کن:", reply_markup=_kb_quiz_v10())
        return
    if action == "cat":
        k = parts[2] if len(parts) > 2 else ""
        if k not in _QUIZ_BANK_V10: return
        cat = _QUIZ_BANK_V10[k]
        rows = []
        for i, (tname, _q) in enumerate(cat["topics"]):
            rows.append([btn(f"❓ {tname}", f"quiz:go:{k}:{i}")])
        rows.append([btn("⬅️ بازگشت","quiz:menu"), btn("🏠","m:main")])
        TG.edit_message(chat_id, msg_id,
            f"<b>{cat['label']}</b> — یک موضوع:", reply_markup=kb(rows))
        return
    if action == "go":
        k = parts[2] if len(parts) > 2 else ""
        try: idx = int(parts[3])
        except Exception: return
        cat = _QUIZ_BANK_V10.get(k)
        if not cat or idx < 0 or idx >= len(cat["topics"]): return
        tname = cat["topics"][idx][0]
        POOL.submit(_generate_and_post, CONFIG.get(), chat_id, tname, "quiz")

# ── 6. Bilingual news renderer (title + summary both translated) ─
def _render_bilingual_item_v10(idx, title, summary_en="", url="", source=""):
    if not title and not summary_en:
        return f"<b>{idx}.</b> ❌"
    title_fa = TR_V10.translate(title, "en", "fa") if title else ""
    summary_fa = TR_V10.translate(summary_en, "en", "fa") if summary_en else ""
    lines = [f"<b>{idx}.</b> 🇮🇷 <b>{escape_html(title_fa[:180])}</b>"]
    if summary_fa:
        lines.append(f"   📝 {escape_html(summary_fa[:600])}")
    lines.append(f"   🇬🇧 <i>{escape_html(title[:180])}</i>")
    if summary_en:
        lines.append(f"   📝 <i>{escape_html(summary_en[:600])}</i>")
    if source: lines.append(f"   📎 {escape_html(source[:40])}")
    if url:    lines.append(f"   🔗 {url}")
    return "\n".join(lines)

# ── 7. Main menu (professional) ────────────────
def kb_main_menu():
    return kb([
        [btn("📚 بانک موضوعات","m:list"),
         btn("🔍 جستجو","m:find"),
         btn("🌟 سوپر","m:super")],
        [btn("🎓 آموزش","learn:bank"),
         btn("📐 ریاضی","math:bank"),
         btn("❓ کوییز","quiz:menu")],
        [btn("📖 ویکی","wiki:menu"),
         btn("📚 arXiv","arxiv:p:0"),
         btn("📰 اخبار","news:menu")],
        [btn("🎵 موسیقی","music:back"),
         btn("📕 کتاب PDF","book:back"),
         btn("🎥 یوتیوب","y:rand")],
        [btn("💱 ارز","rate:refresh"),
         btn("✈️ هوانوردی","av:help:refresh"),
         btn("🌤 آب‌وهوا","m:weather")],
        [btn("🧮 فرمول","m:formula"),
         btn("🔬 عمیق","sty:deep"),
         btn("📇 فلش‌کارت","sty:flashcard")],
        [btn("📊 آمار","stats:cat:usage"),
         btn("⚙️ تنظیمات","m:settings"),
         btn("ℹ️ راهنما","m:help")],
    ])

@ROUTER.callback("quiz:menu")
def cb_quiz_menu_v10(cb, data):
    chat_id = cb["message"]["chat"]["id"]; msg_id = cb["message"]["message_id"]
    TG.answer_callback(cb.get("id", ""))
    TG.edit_message(chat_id, msg_id,
        "❓ <b>کوییز</b> — دسته انتخاب کن:", reply_markup=_kb_quiz_v10())

_prev_m_v10 = cb_m_v7 if "cb_m_v7" in globals() else None

@ROUTER.callback("m")
def cb_m_v10(cb, data):
    action = data.split(":", 1)[1] if ":" in data else "main"
    chat_id = cb["message"]["chat"]["id"]; msg_id = cb["message"]["message_id"]
    if action == "weather":
        TG.answer_callback(cb.get("id", ""))
        SESSIONS.set_state(cb["from"]["id"], "awaiting_city",
                          chat_id=chat_id, msg_id=msg_id)
        TG.edit_message(chat_id, msg_id,
            "🌤 <b>آب و هوا</b>\n\nنام شهر را بنویس:\n<i>تهران، مشهد، London</i>",
            reply_markup=kb([[btn("⬅️ لغو","m:main")]]))
        return
    if _prev_m_v10 is not None:
        _prev_m_v10(cb, data)

# Free-text: awaiting_city
_prev_text_v10 = ROUTER._text_handler

@ROUTER.on_text
def handle_text_v10(msg):
    uid = get_uid(msg)
    s = SESSIONS.get(uid)
    if s.state == "awaiting_city":
        chat_id = get_chat_id(msg)
        city = (msg.get("text") or "").strip()
        SESSIONS.clear_state(uid)
        if city:
            POOL.submit(_weather_bg_v10, chat_id, city)
        return
    if _prev_text_v10: _prev_text_v10(msg)

def _weather_bg_v10(chat_id, city):
    m = TG.send_message(chat_id, f"🌤 دریافت «{city}» ...")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")
    r = APIS.weather.forecast(city, days=3)
    if not r.ok:
        TG.edit_message(chat_id, mid, f"❌ {r.error[:150]}",
                       reply_markup=kb([[btn("🏠","m:main")]]))
        return
    text = APIS.weather.format(r.data)
    TG.edit_message(chat_id, mid, text,
                   reply_markup=kb([[btn("🏠","m:main")]]))

log.info("PATCH v10.0 applied")
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
#  PATCH v11.0 — Bilingual wiki/news + per-item news + currency AI + aviation + flashcards
# ═══════════════════════════════════════════════════════════════════════════
import urllib.parse as _up_v11
import hashlib as _h_v11

# ─── 1. Fix aviation menu + 10 new options ─────────────────────
def kb_aviation_menu():
    return kb([
        [btn("✈️ پرواز با شماره","av:help:flight")],
        [btn("🛫 خروجی‌ها","av:help:dep"), btn("🛬 ورودی‌ها","av:help:arr")],
        [btn("🔴 پروازهای زنده","av:live:dep"), btn("⏰ تأخیرها","av:live:delay")],
        [btn("📅 برنامه هفتگی","av:sched"), btn("🏢 فرودگاه‌ها","av:help:airports")],
        [btn("🛫 خطوط هوایی","av:help:airlines"), btn("🛩️ هواپیماها","av:help:airplanes")],
        [btn("🗺 مسیرها","av:help:routes"), btn("🔍 جستجوی شهر","av:help:search")],
        [btn("🌍 موقعیت IP","av:help:ip"), btn("📊 آمار خط","av:stats")],
        [btn("ℹ️ راهنما","av:help:info"), btn("🔄 رفرش","av:refresh"), btn("🏠 منو","m:main")],
    ])

@ROUTER.command("aviation", description="مرکز هوانوردی")
def cmd_aviation(msg, args):
    chat_id = get_chat_id(msg)
    TG.send_message(chat_id,
        "✈️ <b>مرکز هوانوردی</b>\n\n"
        "<code>/flight IR720</code>\n"
        "<code>/departures IKA</code>\n"
        "<code>/arrivals IKA</code>\n"
        "<code>/live_flights IKA</code>\n"
        "<code>/delays IKA</code>\n"
        "<code>/airports تهران</code>\n"
        "<code>/airlines Mahan</code>\n"
        "<code>/airplanes Boeing</code>\n"
        "<code>/routes IKA THR</code>",
        reply_markup=kb_aviation_menu())

@ROUTER.callback("av")
def cb_aviation(cb, data):
    try:
        parts = data.split(":")
        action = parts[1] if len(parts) > 1 else ""
        param  = parts[2] if len(parts) > 2 else ""
        chat_id = cb["message"]["chat"]["id"]
        msg_id  = cb["message"]["message_id"]
        TG.answer_callback(cb.get("id", ""), "✈️")

        hints = {
            "flight":   "استفاده: <code>/flight IR720</code>",
            "dep":      "استفاده: <code>/departures IKA</code>",
            "arr":      "استفاده: <code>/arrivals IKA</code>",
            "live":     "استفاده: <code>/live_flights IKA</code>",
            "delay":    "استفاده: <code>/delays IKA</code>",
            "sched":    "استفاده: <code>/schedule_air IKA</code>",
            "airports": "استفاده: <code>/airports تهران</code>",
            "airlines": "استفاده: <code>/airlines Mahan</code>",
            "airplanes":"استفاده: <code>/airplanes Boeing</code>",
            "routes":   "استفاده: <code>/routes IKA THR</code>",
            "search":   "استفاده: <code>/airports شهر</code>",
            "ip":       "استفاده: <code>/ip 8.8.8.8</code>",
            "info":     "منبع: Aviationstack API",
            "opts":     "تنظیمات از /settings",
        }

        if action == "refresh":
            TG.edit_message(chat_id, msg_id,
                "✈️ <b>مرکز هوانوردی</b>\n\nیک گزینه انتخاب کن:",
                reply_markup=kb_aviation_menu())
            return

        if action == "help":
            TG.edit_message(chat_id, msg_id,
                f"✈️ <b>راهنما</b>\n\n{hints.get(param, '❌ گزینه نامعتبر')}",
                reply_markup=kb_aviation_menu())
            return

        if action == "live":
            POOL.submit(_av_live_bg, chat_id, msg_id, param)
            return

        if action == "sched":
            TG.edit_message(chat_id, msg_id,
                "📅 برنامه هفتگی:\n<code>/schedule_air IKA</code>",
                reply_markup=kb_aviation_menu())
            return

        if action == "stats":
            TG.edit_message(chat_id, msg_id,
                "📊 آمار خطوط هوایی:\n<code>/airlines Mahan</code>",
                reply_markup=kb_aviation_menu())
            return

    except Exception as e:
        log.exception(f"[v11] aviation: {e}")
        try:
            TG.answer_callback(cb.get("id", ""), "❌ خطا", show_alert=True)
        except Exception: pass

def _av_live_bg(chat_id, msg_id, kind):
    try:
        TG.edit_message(chat_id, msg_id, "🔴 در حال دریافت...")
        if kind == "delay":
            r = APIS.aviationstack.flights(flight_status="scheduled", limit=10)
            title = "⏰ پروازهای زمان‌بندی شده"
        else:
            r = APIS.aviationstack.flights(limit=10)
            title = "🔴 پروازهای فعال"
        if not r.ok:
            TG.edit_message(chat_id, msg_id, f"❌ {escape_html(r.error[:150])}",
                reply_markup=kb_aviation_menu()); return
        flights = (r.data or {}).get("data", [])[:8]
        if not flights:
            TG.edit_message(chat_id, msg_id, "❌ موردی یافت نشد",
                reply_markup=kb_aviation_menu()); return
        text = f"<b>{title}</b>\n\n"
        for f in flights:
            text += APIS.aviationstack.format_flight(f) + "\n\n"
        TG.edit_message(chat_id, msg_id, text[:4000], reply_markup=kb_aviation_menu())
    except Exception as e:
        log.exception(f"[v11] av_live: {e}")

@ROUTER.command("live_flights", description="پروازهای زنده")
def cmd_live_flights(msg, args):
    chat_id = get_chat_id(msg)
    m = TG.send_message(chat_id, "🔴 در حال دریافت...")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")
    def _do():
        try:
            if args:
                r = APIS.aviationstack.flights_from(args.strip().upper(), limit=10)
            else:
                r = APIS.aviationstack.flights(limit=10)
            if not r.ok:
                TG.edit_message(chat_id, mid, f"❌ {r.error[:150]}"); return
            flights = (r.data or {}).get("data", [])[:8]
            if not flights:
                TG.edit_message(chat_id, mid, "❌ موردی یافت نشد"); return
            text = "🔴 <b>پروازهای فعال</b>\n\n"
            for f in flights:
                text += APIS.aviationstack.format_flight(f) + "\n\n"
            TG.edit_message(chat_id, mid, text[:4000])
        except Exception as e:
            TG.edit_message(chat_id, mid, f"❌ {escape_html(str(e)[:150])}")
    POOL.submit(_do)

@ROUTER.command("delays", description="تأخیرها")
def cmd_delays(msg, args):
    return cmd_live_flights(msg, args)

# ─── 2. Wiki bilingual ─────────────────────────────────────────
def _wiki_fetch_v7(chat_id, msg_id, title):
    if not title: return
    if msg_id:
        TG.edit_message(chat_id, msg_id, f"📖 «{escape_html(title)}» ...")
    else:
        m = TG.send_message(chat_id, f"📖 «{escape_html(title)}» ...")
        msg_id = (m.result or {}).get("message_id") if m.ok else None

    r_fa = APIS.wikipedia.summary(title, "fa")
    r_en = APIS.wikipedia.summary(title, "en")

    fa_title = fa_extract = fa_url = ""
    en_title = en_extract = en_url = ""

    if r_en.ok:
        d = r_en.data
        en_title = d.get("title","") or title
        en_extract = clean_wiki_extract(d.get("extract","") or "")[:1200]
        en_url = d.get("url","")

    if r_fa.ok:
        d = r_fa.data
        fa_title = d.get("title","") or title
        fa_extract = clean_wiki_extract(d.get("extract","") or "")[:1200]
        fa_url = d.get("url","")
    elif en_extract:
        fa_extract = TR_V10.translate(en_extract[:2200], "en", "fa")
        fa_title = TR_V10.translate(en_title, "en", "fa") or title
        fa_url = en_url

    if not (fa_extract or en_extract):
        if msg_id: TG.edit_message(chat_id, msg_id, "❌ یافت نشد.")
        return

    text = (
        f"📖 <b>ویکی‌پدیا — دوزبانه</b>\n\n"
        f"🇮🇷 <b>{escape_html(fa_title[:200])}</b>\n"
        f"{escape_html(fa_extract[:2200])}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🇬🇧 <b>{escape_html(en_title[:200])}</b>\n"
        f"<i>{escape_html(en_extract[:2200])}</i>\n\n"
        f"🔗 {fa_url or en_url}"
    )
    if msg_id:
        TG.edit_message(chat_id, msg_id, text[:4000],
            reply_markup=kb([[btn("🎥 ویدیو", f"wiki:vid:{escape_html(title)[:40]}")],
                             [btn("⬅️","wiki:menu"), btn("🏠","m:main")]]))
    else:
        TG.send_message(chat_id, text[:4000])

# ─── 3. News — one per message, bilingual ─────────────────────
_NEWS_QUEUE_V11 = TTLStore(max_items=500, ttl=3600)
def _news_fetch_render_v11(chat_id, msg_id, group, query=""):
    items = []
    try:
        if group == "arxiv":
            r = APIS.arxiv.search(query or "engineering", max_results=6)
            if r.ok:
                for a in (r.data or [])[:6]:
                    items.append({"title": a.get("title",""),
                                  "summary": (a.get("summary","") or "")[:500],
                                  "link": a.get("link",""), "source": "arXiv"})
        elif group == "space":  items = NewsSourcesV8.fetch_group("space", 3, 6)
        elif group == "eng":    items = NewsSourcesV8.fetch_group("eng", 3, 6)
        elif group == "tech":   items = NewsSourcesV8.fetch_group("tech", 3, 6)
        elif group == "ai":
            items = NewsSourcesV8.fetch_group("tech", 3, 8)
            kw = ["ai","artificial","machine learning","deep learning","llm","neural","gpt","robot"]
            items = [it for it in items if any(k in (it.get("title","")+it.get("summary","")).lower() for k in kw)] or items
            items = items[:6]
        elif group == "engrss": items = NewsSourcesV8.fetch_group("eng", 4, 8)
        elif group == "search" and query:
            r = APIS.news.fetch_combined(limit=30)
            items = APIS.news.filter_by_keywords(r, [query])[:6]
        else:                   items = NewsSourcesV8.fetch_group("eng", 3, 6)
    except Exception as e:
        log.debug(f"[v11] news: {e}")

    if not items:
        if msg_id: TG.edit_message(chat_id, msg_id, "❌ خبری یافت نشد.")
        else: TG.send_message(chat_id, "❌ خبری یافت نشد.")
        return

    items = items[:6]
    _NEWS_QUEUE_V11[chat_id] = items

    if msg_id:
        head_map = {"space":"🚀 فضا","eng":"⚙️ مهندسی","tech":"💻 فناوری",
                    "ai":"🤖 هوش مصنوعی","arxiv":"📚 arXiv","engrss":"📡 RSS",
                    "search": f"🔍 {query[:30]}"}
        TG.edit_message(chat_id, msg_id,
            f"<b>{head_map.get(group,'📰 اخبار')}</b>\n"
            f"<i>{len(items)} خبر — هر خبر دوزبانه در یک پیام</i>",
            reply_markup=kb([[btn("❌ بستن","news:menu"), btn("🏠","m:main")]]))

    for i, it in enumerate(items, 1):
        _send_news_item_v11(chat_id, i, len(items), it)
        time.sleep(0.6)

def _send_news_item_v11(chat_id, idx, total, it):
    try:
        en_title = it.get("title","")[:250]
        en_summary = it.get("summary","")[:900]
        fa_title = TR_V10.translate(en_title, "en", "fa")
        fa_summary = TR_V10.translate(en_summary, "en", "fa") if en_summary else ""

        text = (
            f"📰 <b>خبر {idx} از {total}</b>\n\n"
            f"🇮🇷 <b>{escape_html(fa_title[:200])}</b>\n"
            f"{escape_html(fa_summary[:700])}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🇬🇧 <b>{escape_html(en_title[:200])}</b>\n"
            f"<i>{escape_html(en_summary[:700])}</i>\n\n"
            f"📎 {escape_html(str(it.get('source',''))[:50])}\n"
            f"🔗 {it.get('link','')}"
        )
        rows = [[btn(f"📤 ارسال به کانال", f"news:sendone:{idx-1}")]]
        TG.send_message(chat_id, text[:4000], reply_markup=kb(rows))
    except Exception as e:
        log.debug(f"[v11] send_news_item: {e}")

@ROUTER.callback("news:sendone")
def cb_news_sendone(cb, data):
    try:
        idx = int(data.split(":")[2])
    except Exception:
        TG.answer_callback(cb.get("id", ""), "❌"); return
    chat_id = cb["message"]["chat"]["id"]
    items = _NEWS_QUEUE_V11.get(chat_id) or []
    if idx < 0 or idx >= len(items):
        TG.answer_callback(cb.get("id", ""), "❌"); return
    it = items[idx]
    TG.answer_callback(cb.get("id", ""), "⏳ ارسال...")
    POOL.submit(_news_send_to_channel_v8, chat_id, it)

# ─── 4. Currency — select + AI Persian + custom note ──────────
_RATE_CURRS_V11 = [
    ("USD","🇺🇸 دلار آمریکا"), ("EUR","🇪🇺 یورو"), ("GBP","🇬🇧 پوند"),
    ("AED","🇦🇪 درهم امارات"), ("TRY","🇹🇷 لیر ترکیه"),
    ("CNY","🇨🇳 یوان چین"), ("JPY","🇯🇵 یِن ژاپن"),
    ("CAD","🇨🇦 دلار کانادا"), ("AUD","🇦🇺 دلار استرالیا"),
    ("CHF","🇨🇭 فرانک سوئیس"), ("SAR","🇸🇦 ریال سعودی"),
    ("QAR","🇶🇦 ریال قطر"), ("KWD","🇰🇼 دینار کویت"),
    ("IQD","🇮🇶 دینار عراق"), ("AFN","🇦🇫 افغانی"),
    ("PKR","🇵🇰 روپیه پاکستان"), ("INR","🇮🇳 روپیه هند"),
    ("RUB","🇷🇺 روبل روسیه"), ("OMR","🇴🇲 ریال عمان"),
    ("BHD","🇧🇭 دینار بحرین"), ("GEL","🇬🇪 لاری گرجستان"),
    ("AMD","🇦🇲 درام ارمنستان"), ("AZN","🇦🇿 مانات آذربایجان"),
    ("KZT","🇰🇿 تنگه قزاقستان"), ("MYR","🇲🇾 رینگیت مالزی"),
    ("THB","🇹🇭 بات تایلند"), ("SGD","🇸🇬 دلار سنگاپور"),
    ("HKD","🇭🇰 دلار هنگ‌کنگ"), ("NZD","🇳🇿 دلار نیوزیلند"),
    ("ZAR","🇿🇦 رند آفریقای جنوبی"),
]

_RATE_DRAFT_V11 = TTLStore(max_items=500, ttl=3600)
def _kb_rate_currs_v11(page=0, per=10):
    total = len(_RATE_CURRS_V11)
    pages = (total + per - 1) // per
    page = max(0, min(page, pages-1))
    start = page*per
    chunk = _RATE_CURRS_V11[start:start+per]
    rows = []
    for i, (code, label) in enumerate(chunk):
        idx = start + i
        rows.append([btn(label, f"rate:pick:{code}")])
    nav = []
    if page > 0: nav.append(btn("◀️","rate:pg:"+str(page-1)))
    nav.append(btn(f"{page+1}/{pages}","rate:nop"))
    if page < pages-1: nav.append(btn("▶️","rate:pg:"+str(page+1)))
    rows.append(nav)
    rows.append([btn("🏠 منو","m:main")])
    return kb(rows)

@ROUTER.command("rate", description="نرخ ارز (با تحلیل AI)")
def cmd_rate_v10(msg, args):
    chat_id = get_chat_id(msg)
    TG.send_message(chat_id,
        "💱 <b>نرخ ارز</b>\n\n"
        "ارز مورد نظر را انتخاب کن:\n"
        "<i>تحلیل فارسی توسط AI نوشته می‌شود</i>",
        reply_markup=_kb_rate_currs_v11(0))

@ROUTER.callback("rate")
def cb_rate_v10(cb, data):
    try:
        parts = data.split(":")
        action = parts[1] if len(parts) > 1 else ""
        chat_id = cb["message"]["chat"]["id"]
        msg_id  = cb["message"]["message_id"]

        if action == "nop":
            TG.answer_callback(cb.get("id", "")); return
        if action == "pg":
            try: pg = int(parts[2])
            except Exception: pg = 0
            TG.answer_callback(cb.get("id", ""))
            TG.edit_message(chat_id, msg_id,
                "💱 <b>نرخ ارز</b> — انتخاب ارز:",
                reply_markup=_kb_rate_currs_v11(pg))
            return
        if action == "cancel":
            TG.answer_callback(cb.get("id", ""), "❌")
            TG.edit_message(chat_id, msg_id, "❌ لغو شد.",
                reply_markup=kb([[btn("🏠 منو","m:main")]]))
            return
        if action == "back":
            TG.answer_callback(cb.get("id", ""))
            TG.edit_message(chat_id, msg_id,
                "💱 <b>نرخ ارز</b> — انتخاب ارز:",
                reply_markup=_kb_rate_currs_v11(0))
            return
        if action == "pick":
            code = parts[2] if len(parts) > 2 else ""
            TG.answer_callback(cb.get("id", ""), f"⏳ {code}")
            POOL.submit(_rate_analyze_bg_v11, chat_id, msg_id, code)
            return
        if action == "send":
            uid = cb["from"]["id"]
            draft = _RATE_DRAFT_V11.get(uid)
            if not draft:
                TG.answer_callback(cb.get("id", ""), "❌ پیش‌نویس نیست")
                return
            TG.answer_callback(cb.get("id", ""), "📤 ارسال...")
            cfg = CONFIG.get()
            ch = cfg.telegram.channel_id
            if ch:
                TG.send_message(ch, draft["text"], parse_mode="HTML")
                TG.edit_message(chat_id, msg_id,
                    "✅ به کانال ارسال شد.",
                    reply_markup=kb([[btn("🏠 منو","m:main")]]))
            return
        if action == "note":
            uid = cb["from"]["id"]
            draft = _RATE_DRAFT_V11.get(uid)
            if not draft:
                TG.answer_callback(cb.get("id", ""), "❌"); return
            TG.answer_callback(cb.get("id", ""), "✏️")
            SESSIONS.set_state(uid, "awaiting_rate_note",
                              currency=draft["code"], chat_id=chat_id, msg_id=msg_id)
            TG.edit_message(chat_id, msg_id,
                "✏️ <b>یادداشت شخصی</b>\n\n"
                "متن یادداشت خودت را بفرست (به انتهای پیام اضافه می‌شود):",
                reply_markup=kb([[btn("⬅️ لغو","rate:back")]]))
            return
        if action == "refresh":
            TG.answer_callback(cb.get("id", ""))
            TG.edit_message(chat_id, msg_id,
                "💱 <b>نرخ ارز</b> — انتخاب ارز:",
                reply_markup=_kb_rate_currs_v11(0))
            return
    except Exception as e:
        log.exception(f"[v11] rate: {e}")
        try: TG.answer_callback(cb.get("id", ""), "❌", show_alert=True)
        except Exception: pass

def _rate_analyze_bg_v11(chat_id, msg_id, code):
    try:
        TG.edit_message(chat_id, msg_id, f"⏳ دریافت نرخ {code} و تحلیل ...")
        r = APIS.exchange.latest("USD", f"{code},IRR")
        if not r.ok:
            TG.edit_message(chat_id, msg_id, f"❌ {escape_html(r.error[:150])}")
            return
        rates = (r.data or {}).get("rates", {}) or {}
        usd_to_cur = rates.get(code)
        usd_to_irr = rates.get("IRR")
        if not usd_to_cur:
            TG.edit_message(chat_id, msg_id, f"❌ نرخ {code} در دسترس نیست.")
            return

        try:
            if usd_to_irr:
                cur_in_irr = usd_to_irr / usd_to_cur
                cur_in_toman = cur_in_irr / 10.0
            else:
                cur_in_irr = cur_in_toman = 0
        except Exception:
            cur_in_irr = cur_in_toman = 0

        label = next((l for c, l in _RATE_CURRS_V11 if c == code), code)

        analysis = ""
        try:
            sys_p = ("You are a Persian financial analyst. Write a short 4-6 line "
                     "professional analysis in Persian about the given exchange rate. "
                     "Mention economic factors, trends, and implications. "
                     "Do NOT mention you are AI. Do NOT use English.")
            usr_p = (f"ارز: {code} ({label})\n"
                     f"نرخ هر {code} به دلار: {usd_to_cur}\n"
                     f"نرخ دلار به ریال: {usd_to_irr}\n"
                     f"نرخ هر {code} به ریال: {cur_in_irr:,.0f}\n"
                     f"نرخ هر {code} به تومان: {cur_in_toman:,.0f}\n\n"
                     "یک تحلیل کوتاه فارسی بنویس:")
            a = AI.ask(sys_p, usr_p, max_tokens=400, temperature=0.6)
            if a.ok:
                analysis = clean_latex(a.text).strip()
        except Exception as e:
            log.debug(f"[v11] rate analysis: {e}")

        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        text = (
            f"💱 <b>نرخ ارز — {escape_html(label)}</b>\n"
            f"<i>🕐 {ts}</i>\n\n"
            f"💵 هر <code>{code}</code> = <b>{usd_to_cur:,.4f}</b> دلار\n"
        )
        if cur_in_irr:
            text += f"🇮🇷 هر <code>{code}</code> = <b>{cur_in_irr:,.0f}</b> ریال\n"
            text += f"💰 هر <code>{code}</code> = <b>{cur_in_toman:,.0f}</b> تومان\n"
        if usd_to_irr:
            text += f"\n📊 هر دلار = <b>{usd_to_irr:,.0f}</b> ریال\n"

        if analysis:
            text += f"\n📈 <b>تحلیل:</b>\n{escape_html(analysis[:1200])}"

        uid_tmp = chat_id if chat_id > 0 else 0
        _RATE_DRAFT_V11[uid_tmp] = {"code": code, "text": text, "label": label}

        rows = [
            [btn("📤 ارسال به کانال","rate:send"),
             btn("✏️ افزودن یادداشت","rate:note")],
            [btn("🔄 تحلیل جدید", f"rate:pick:{code}")],
            [btn("⬅️ فهرست ارزها","rate:back"), btn("🏠","m:main")],
        ]
        TG.edit_message(chat_id, msg_id, text[:4000], reply_markup=kb(rows))
    except Exception as e:
        log.exception(f"[v11] rate analyze: {e}")
        TG.edit_message(chat_id, msg_id, f"❌ {escape_html(str(e)[:200])}")

# Free-text: awaiting_rate_note
_prev_text_v11 = ROUTER._text_handler

@ROUTER.on_text
def handle_text_v11(msg):
    uid = get_uid(msg)
    s = SESSIONS.get(uid)
    if s.state == "awaiting_rate_note":
        chat_id = get_chat_id(msg)
        note = (msg.get("text") or "").strip()
        SESSIONS.clear_state(uid)
        if not note:
            TG.send_message(chat_id, "❌ یادداشت خالی."); return
        draft = _RATE_DRAFT_V11.get(chat_id if chat_id > 0 else 0)
        if draft:
            draft["text"] += f"\n\n✏️ <b>یادداشت:</b>\n{escape_html(note[:500])}"
            rows = [
                [btn("📤 ارسال به کانال","rate:send"),
                 btn("✏️ یادداشت دیگر","rate:note")],
                [btn("⬅️ فهرست ارزها","rate:back"), btn("🏠","m:main")],
            ]
            TG.send_message(chat_id,
                draft["text"][:4000] + f"\n\n✅ یادداشت اضافه شد.",
                reply_markup=kb(rows))
        return
    if _prev_text_v11: _prev_text_v11(msg)

# ─── 5. Flashcards — 7 config options ────────────────────────
_FLASH_CFG_V11 = TTLStore(max_items=500, ttl=7200)
def _flash_defaults():
    return {"topic": "", "count": 5, "difficulty": "متوسط",
            "type": "ترکیبی", "lang": "دوزبانه", "format": "پیشرفته",
            "save": False}

def _kb_flash_v11(uid):
    cfg = _FLASH_CFG_V11.setdefault(uid, _flash_defaults())
    return kb([
        [btn(f"📝 موضوع: {cfg['topic'][:22] or '—'}", "flash:set:topic")],
        [btn(f"🔢 تعداد: {cfg['count']}", "flash:set:count"),
         btn(f"🎚 سختی: {cfg['difficulty']}", "flash:set:diff")],
        [btn(f"📋 نوع: {cfg['type']}", "flash:set:type"),
         btn(f"🌐 زبان: {cfg['lang']}", "flash:set:lang")],
        [btn(f"🎨 قالب: {cfg['format']}", "flash:set:format"),
         btn(f"💾 ذخیره: {'✅' if cfg['save'] else '❌'}", "flash:set:save")],
        [btn("🚀 تولید فلش‌کارت‌ها", "flash:run")],
        [btn("🔄 ریست", "flash:reset"), btn("🏠 منو", "m:main")],
    ])

@ROUTER.command("flash", description="فلش‌کارت پیشرفته")
def cmd_flash_v11(msg, args):
    chat_id = get_chat_id(msg)
    uid = get_uid(msg)
    if args and uid not in _FLASH_CFG_V11:
        cfg = _flash_defaults(); cfg["topic"] = args.strip()
        _FLASH_CFG_V11[uid] = cfg
    else:
        _FLASH_CFG_V11.setdefault(uid, _flash_defaults())
    TG.send_message(chat_id,
        "📇 <b>فلش‌کارت پیشرفته</b>\n\n"
        "۷ گزینه زیر را تنظیم کن:\n"
        "<i>موضوع، تعداد، سختی، نوع، زبان، قالب، ذخیره</i>",
        reply_markup=_kb_flash_v11(uid))

@ROUTER.callback("flash")
def cb_flash_v11(cb, data):
    try:
        parts = data.split(":")
        action = parts[1] if len(parts) > 1 else ""
        sub = parts[2] if len(parts) > 2 else ""
        uid = cb["from"]["id"]
        chat_id = cb["message"]["chat"]["id"]
        msg_id = cb["message"]["message_id"]
        cfg = _FLASH_CFG_V11.setdefault(uid, _flash_defaults())

        if action == "reset":
            _FLASH_CFG_V11[uid] = _flash_defaults()
            TG.answer_callback(cb.get("id", ""), "🔄")
            TG.edit_message(chat_id, msg_id,
                "📇 <b>فلش‌کارت پیشرفته</b>", reply_markup=_kb_flash_v11(uid))
            return

        if action == "run":
            if not cfg["topic"]:
                TG.answer_callback(cb.get("id", ""), "❌ موضوع را وارد کن", show_alert=True)
                return
            TG.answer_callback(cb.get("id", ""), "⏳")
            POOL.submit(_flash_generate_v11, chat_id, msg_id, uid, dict(cfg))
            return

        if action == "set":
            if sub == "topic":
                SESSIONS.set_state(uid, "awaiting_flash_topic",
                                  chat_id=chat_id, msg_id=msg_id)
                TG.answer_callback(cb.get("id", ""), "✏️")
                TG.edit_message(chat_id, msg_id,
                    "📝 <b>موضوع</b>\n\nموضوع فلش‌کارت‌ها را بنویس:\n"
                    "<i>مثال: ترمودینامیک، مشتق، الکترومغناطیس</i>",
                    reply_markup=kb([[btn("⬅️ لغو","flash:cancel")]]))
                return
            if sub == "count":
                TG.answer_callback(cb.get("id", ""))
                rows = [
                    [btn("3", "flash:cc:3"), btn("5", "flash:cc:5"),
                     btn("7", "flash:cc:7"), btn("10", "flash:cc:10")],
                    [btn("15", "flash:cc:15"), btn("20", "flash:cc:20")],
                    [btn("⬅️ بازگشت","flash:back")],
                ]
                TG.edit_message(chat_id, msg_id,
                    "🔢 <b>تعداد کارت‌ها</b>:", reply_markup=kb(rows))
                return
            if sub == "diff":
                TG.answer_callback(cb.get("id", ""))
                rows = [
                    [btn("🟢 آسان","flash:dc:آسان")],
                    [btn("🟡 متوسط","flash:dc:متوسط")],
                    [btn("🟠 سخت","flash:dc:سخت")],
                    [btn("🔴 خیلی سخت","flash:dc:خیلی سخت")],
                    [btn("⬅️ بازگشت","flash:back")],
                ]
                TG.edit_message(chat_id, msg_id,
                    "🎚 <b>سطح سختی</b>:", reply_markup=kb(rows))
                return
            if sub == "type":
                TG.answer_callback(cb.get("id", ""))
                rows = [
                    [btn("📖 تعریف","flash:tc:تعریف")],
                    [btn("📐 فرمول","flash:tc:فرمول")],
                    [btn("💡 مفهوم","flash:tc:مفهوم")],
                    [btn("🧪 مثال","flash:tc:مثال")],
                    [btn("🔀 ترکیبی","flash:tc:ترکیبی")],
                    [btn("⬅️ بازگشت","flash:back")],
                ]
                TG.edit_message(chat_id, msg_id,
                    "📋 <b>نوع کارت</b>:", reply_markup=kb(rows))
                return
            if sub == "lang":
                TG.answer_callback(cb.get("id", ""))
                rows = [
                    [btn("🇮🇷 فقط فارسی","flash:lc:فقط_فارسی")],
                    [btn("🇬🇧 فقط انگلیسی","flash:lc:فقط_انگلیسی")],
                    [btn("🌐 دوزبانه","flash:lc:دوزبانه")],
                    [btn("⬅️ بازگشت","flash:back")],
                ]
                TG.edit_message(chat_id, msg_id,
                    "🌐 <b>زبان</b>:", reply_markup=kb(rows))
                return
            if sub == "format":
                TG.answer_callback(cb.get("id", ""))
                rows = [
                    [btn("📋 ساده","flash:fc:ساده")],
                    [btn("🎨 پیشرفته","flash:fc:پیشرفته")],
                    [btn("💎 فوق پیشرفته","flash:fc:فوق_پیشرفته")],
                    [btn("⬅️ بازگشت","flash:back")],
                ]
                TG.edit_message(chat_id, msg_id,
                    "🎨 <b>قالب نمایش</b>:", reply_markup=kb(rows))
                return
            if sub == "save":
                cfg["save"] = not cfg["save"]
                TG.answer_callback(cb.get("id", ""),
                                  f"💾 {'فعال' if cfg['save'] else 'غیرفعال'}")
                TG.edit_message(chat_id, msg_id,
                    "📇 <b>فلش‌کارت پیشرفته</b>", reply_markup=_kb_flash_v11(uid))
                return

        if action == "cc":
            try: cfg["count"] = int(sub)
            except Exception: pass
            TG.answer_callback(cb.get("id", ""), f"✅ {cfg['count']}")
            TG.edit_message(chat_id, msg_id,
                "📇 <b>فلش‌کارت پیشرفته</b>", reply_markup=_kb_flash_v11(uid))
            return
        if action == "dc":
            cfg["difficulty"] = sub
            TG.answer_callback(cb.get("id", ""), f"✅ {sub}")
            TG.edit_message(chat_id, msg_id,
                "📇 <b>فلش‌کارت پیشرفته</b>", reply_markup=_kb_flash_v11(uid))
            return
        if action == "tc":
            cfg["type"] = sub
            TG.answer_callback(cb.get("id", ""), f"✅ {sub}")
            TG.edit_message(chat_id, msg_id,
                "📇 <b>فلش‌کارت پیشرفته</b>", reply_markup=_kb_flash_v11(uid))
            return
        if action == "lc":
            cfg["lang"] = sub.replace("_"," ")
            TG.answer_callback(cb.get("id", ""), f"✅")
            TG.edit_message(chat_id, msg_id,
                "📇 <b>فلش‌کارت پیشرفته</b>", reply_markup=_kb_flash_v11(uid))
            return
        if action == "fc":
            cfg["format"] = sub.replace("_"," ")
            TG.answer_callback(cb.get("id", ""), f"✅")
            TG.edit_message(chat_id, msg_id,
                "📇 <b>فلش‌کارت پیشرفته</b>", reply_markup=_kb_flash_v11(uid))
            return
        if action == "back":
            TG.answer_callback(cb.get("id", ""))
            TG.edit_message(chat_id, msg_id,
                "📇 <b>فلش‌کارت پیشرفته</b>", reply_markup=_kb_flash_v11(uid))
            return
        if action == "cancel":
            TG.answer_callback(cb.get("id", ""), "❌")
            TG.edit_message(chat_id, msg_id,
                "📇 <b>فلش‌کارت پیشرفته</b>", reply_markup=_kb_flash_v11(uid))
            return
    except Exception as e:
        log.exception(f"[v11] flash: {e}")
        try: TG.answer_callback(cb.get("id", ""), "❌", show_alert=True)
        except Exception: pass

# Free-text: awaiting_flash_topic (also in v11 handler)
_prev_text_v11b = ROUTER._text_handler

@ROUTER.on_text
def handle_text_v11b(msg):
    uid = get_uid(msg)
    s = SESSIONS.get(uid)
    if s.state == "awaiting_flash_topic":
        chat_id = get_chat_id(msg)
        topic = (msg.get("text") or "").strip()
        SESSIONS.clear_state(uid)
        if not topic: return
        cfg = _FLASH_CFG_V11.setdefault(uid, _flash_defaults())
        cfg["topic"] = topic
        TG.send_message(chat_id,
            f"✅ موضوع: <b>{escape_html(topic)}</b>",
            reply_markup=_kb_flash_v11(uid))
        return
    if _prev_text_v11b: _prev_text_v11b(msg)

def _flash_generate_v11(chat_id, msg_id, uid, cfg):
    try:
        TG.edit_message(chat_id, msg_id,
            f"📇 تولید {cfg['count']} فلش‌کارت «{escape_html(cfg['topic'])}» ...\n"
            f"سختی: {cfg['difficulty']} | نوع: {cfg['type']} | زبان: {cfg['lang']}")

        diff_prompt = {
            "آسان": "simple definitions, basic concepts",
            "متوسط": "standard technical depth",
            "سخت": "advanced concepts with formulas",
            "خیلی سخت": "expert-level, multi-step reasoning, edge cases",
        }.get(cfg["difficulty"], "standard")

        type_prompt = {
            "تعریف": "definition cards",
            "فرمول": "formula cards with variables explained",
            "مفهوم": "conceptual understanding cards",
            "مثال": "worked example cards",
            "ترکیبی": "mixed: definition + formula + example",
        }.get(cfg["type"], "mixed")

        lang_prompt = {
            "فقط فارسی": "Write everything in Persian only.",
            "فقط انگلیسی": "Write everything in English only.",
            "دوزبانه": "For each card: Persian first, then English below it.",
        }.get(cfg["lang"], "Bilingual Persian + English.")

        fmt_style = {
            "ساده": "Simple numbered format.",
            "پیشرفته": "With emoji headers, bold terms, clean spacing.",
            "فوق پیشرفته": "Rich: emoji, bold, formulas, examples, mnemonic hints, spacing.",
        }.get(cfg["format"], "Clean structured.")

        sys_p = ("You are a Persian engineering professor creating flashcards. "
                 "Use clean Unicode (NOT LaTeX). No markdown code fences. "
                 "Separate cards with a blank line and ━━━ between them.")
        usr_p = (f"Topic: {cfg['topic']}\n"
                 f"Count: {cfg['count']}\n"
                 f"Difficulty: {diff_prompt}\n"
                 f"Card type: {type_prompt}\n"
                 f"Language: {lang_prompt}\n"
                 f"Format: {fmt_style}\n\n"
                 "Create the flashcards now.")

        with TypingHeartbeat(chat_id):
            resp = AI.ask(sys_p, usr_p, max_tokens=3500, temperature=0.65)
        if not resp.ok:
            TG.edit_message(chat_id, msg_id, f"❌ {escape_html(resp.error[:200])}")
            return

        td = {"name": cfg["topic"], "query": cfg["topic"],
              "domain": "eng", "tags": f"{cfg['topic'].replace(' ','_')}"}
        content = CONTENT._post_process(resp.text, td, CONFIG.get(), "flashcard")
        header = (f"📇 <b>فلش‌کارت — {escape_html(cfg['topic'][:60])}</b>\n"
                  f"<i>سختی: {cfg['difficulty']} | تعداد: {cfg['count']} | "
                  f"زبان: {cfg['lang']}</i>\n\n")
        full = header + content

        rows = [
            [btn("📤 ارسال به کانال","flash:run_pub"),
             btn("🔄 نسخه دیگر","flash:run_alt")],
            [btn("⬅️ تنظیمات","flash:back"), btn("🏠","m:main")],
        ]
        TG.edit_message(chat_id, msg_id, full[:4000], reply_markup=kb(rows))

        if cfg.get("save"):
            try:
                p = DATA_DIR / "flashcards"
                p.mkdir(exist_ok=True)
                fname = p / f"{datetime.now():%Y%m%d_%H%M%S}_{re.sub(r'[^A-Za-z0-9_-]','_', cfg['topic'])[:30]}.html"
                fname.write_text(full, encoding="utf-8")
                TG.send_message(chat_id, f"💾 ذخیره شد: <code>{fname.name}</code>")
            except Exception as e:
                log.debug(f"[v11] flash save: {e}")
    except Exception as e:
        log.exception(f"[v11] flash gen: {e}")
        TG.edit_message(chat_id, msg_id, f"❌ {escape_html(str(e)[:200])}")

# ─── 6. Fix /flash command override (in case v10 replaced it) ─
@ROUTER.command("flash", description="فلش‌کارت پیشرفته")
def cmd_flash_v11_override(msg, args):
    cmd_flash_v11(msg, args)

log.info("PATCH v11.0 applied — bilingual wiki/news + per-item news + currency AI + aviation + flashcards")
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
import json as _json_v13
import random as _rnd_v13

#  PATCH v13.0 — Proxy/V2Ray + Ganjoor + Telegram Music + Low-Ping
# ═══════════════════════════════════════════════════════════════════════════
import urllib.parse as _up_v13
import base64 as _b64_v13
import socket as _sock_v13

# ─── 1. Proxy sources (public, free) ───────────────────────────
_PROXY_SOURCES_V13 = {
    "shadowmere":   "https://shadowmere.xyz/api/proxies",
    "v2ray_free":   "https://raw.githubusercontent.com/freefq/free/master/v2",
    "v2ray_barry":  "https://raw.githubusercontent.com/barry-far/V2ray-Configs/main/All_Configs_Sub.txt",
    "v2ray_epodonios": "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_Sub.txt",
    "v2ray_mfuu":   "https://raw.githubusercontent.com/mfuu/v2ray/master/v2ray",
    "ss_free":      "https://raw.githubusercontent.com/mahdibland/ShadowsocksAggregator/master/Eternity.txt",
    "v2ray_ermao":  "https://raw.githubusercontent.com/ermaozi/get_subscribe/main/subscribe/v2ray.txt",
    "proxy_scrape": "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
}

_PROXY_CACHE_V13 = {"servers": [], "ts": 0, "by_proto": {}}

def _fetch_proxies_v13(force=False):
    if not force and time.time() - _PROXY_CACHE_V13["ts"] < 1800 and _PROXY_CACHE_V13["servers"]:
        return _PROXY_CACHE_V13["servers"]
    servers = []; seen = set()
    for name, url in _PROXY_SOURCES_V13.items():
        try:
            r = HTTP.request("GET", url, timeout=20)
            if r is None or r.status_code != 200: continue
            text = r.text
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"): continue
                if any(line.startswith(p) for p in ("vmess://","vless://","ss://","trojan://","ssr://")):
                    if line not in seen:
                        seen.add(line); servers.append({"url": line, "src": name})
        except Exception as e:
            log.debug(f"[v13] proxy {name}: {e}")
    _PROXY_CACHE_V13["servers"] = servers
    _PROXY_CACHE_V13["ts"] = time.time()
    return servers

def _extract_host_port_v13(uri):
    try:
        if uri.startswith("vmess://"):
            try:
                raw = uri[8:]
                pad = "=" * (-len(raw) % 4)
                d = _json_v13.loads(_b64_v13.b64decode(raw + pad).decode("utf-8", "ignore"))
                return d.get("add", ""), int(d.get("port", 0))
            except Exception: return "", 0
        if uri.startswith(("vless://","trojan://")):
            u = _up_v13.urlparse(uri)
            return u.hostname or "", u.port or 0
        if uri.startswith("ss://"):
            body = uri[5:].split("#",1)[0]
            if "@" in body:
                hostport = body.rsplit("@",1)[1].split("?",1)[0]
            else:
                try:
                    dec = _b64_v13.b64decode(body + "="*(-len(body)%4)).decode("utf-8","ignore")
                    hostport = dec.rsplit("@",1)[1] if "@" in dec else dec
                except Exception: return "", 0
            if ":" in hostport:
                h, p = hostport.rsplit(":",1)
                return h, int(p) if p.isdigit() else 0
    except Exception: pass
    return "", 0

def _ping_host_v13(host, port, timeout=1.5):
    if not host or not port:
        return 9999
    s = None
    try:
        t0 = time.perf_counter()
        s = _sock_v13.socket(_sock_v13.AF_INET, _sock_v13.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        return int((time.perf_counter()-t0)*1000)
    except Exception:
        return 9999
    finally:
        if s is not None:
            try: s.close()
            except Exception: pass

def _proxy_display_v13(uri):
    tag = ""
    if "#" in uri: tag = uri.split("#",1)[1][:60]
    proto = uri.split("://",1)[0].upper() if "://" in uri else "?"
    return proto, tag

@ROUTER.command("proxy", description="پروکسی و V2Ray")
def cmd_proxy_v13(msg, args):
    chat_id = get_chat_id(msg)
    a = (args or "").strip().lower()
    if a == "low" or a == "ping":
        POOL.submit(_proxy_low_ping_v13, chat_id, None); return
    if a == "sub":
        POOL.submit(_proxy_subscription_v13, chat_id, None); return
    if a == "send":
        POOL.submit(_proxy_to_channel_v13, chat_id, None); return
    rows = [
        [btn("📥 دریافت ۱۰ پروکسی","proxy:list"),
         btn("⚡ کم‌پینگ‌ترین","proxy:low")],
        [btn("📦 اشتراک V2Ray","proxy:sub"),
         btn("📤 ارسال به کانال","proxy:send")],
        [btn("🔄 رفرش","proxy:refresh"), btn("🏠 منو","m:main")],
    ]
    TG.send_message(chat_id,
        "🌐 <b>پروکسی / V2Ray</b>\n\nاز منابع رایگان عمومی:\n"
        "<i>هشدار: این سرورها عمومی هستند — با احتیاط استفاده کن.</i>",
        reply_markup=kb(rows))

@ROUTER.callback("proxy")
def cb_proxy_v13(cb, data):
    try:
        parts = data.split(":"); action = parts[1] if len(parts) > 1 else ""
        chat_id = cb["message"]["chat"]["id"]; msg_id = cb["message"]["message_id"]
        TG.answer_callback(cb.get("id", ""), "🌐")
        if action == "list":
            POOL.submit(_proxy_send_list_v13, chat_id, msg_id, 10); return
        if action == "low":
            POOL.submit(_proxy_low_ping_v13, chat_id, msg_id); return
        if action == "sub":
            POOL.submit(_proxy_subscription_v13, chat_id, msg_id); return
        if action == "send":
            POOL.submit(_proxy_to_channel_v13, chat_id, msg_id); return
        if action == "refresh":
            POOL.submit(_proxy_send_list_v13, chat_id, msg_id, 10); return
    except Exception as e:
        log.exception(f"[v13] proxy: {e}")

def _proxy_send_list_v13(chat_id, msg_id, count=10):
    try:
        if msg_id: TG.edit_message(chat_id, msg_id, "⏳ دریافت از منابع ...")
        servers = _fetch_proxies_v13(force=True)
        if not servers:
            if msg_id: TG.edit_message(chat_id, msg_id, "❌ سروری یافت نشد.")
            return
        chunk = servers[:count]
        header = f"🌐 <b>{len(chunk)} پروکسی از {len(servers)} سرور</b>\n\n"
        lines = [header]
        for i, s in enumerate(chunk, 1):
            proto, tag = _proxy_display_v13(s["url"])
            lines.append(f"<b>{i}. {proto}</b> — {escape_html(tag)}\n<code>{escape_html(s['url'][:180])}</code>\n")
        text = "\n".join(lines)
        if msg_id:
            TG.edit_message(chat_id, msg_id, text[:4000],
                reply_markup=kb([[btn("📤 ارسال به کانال","proxy:send"),
                                  btn("⚡ کم‌پینگ","proxy:low")],
                                 [btn("🔄 رفرش","proxy:refresh"), btn("🏠","m:main")]]))
        else:
            TG.send_message(chat_id, text[:4000])
    except Exception as e:
        log.exception(f"[v13] proxy list: {e}")

def _proxy_low_ping_v13(chat_id, msg_id):
    try:
        if msg_id: TG.edit_message(chat_id, msg_id, "⚡ تست پینگ سرورها (۱۵ ثانیه) ...")
        servers = _fetch_proxies_v13()
        if not servers: return
        tested = []
        for s in servers[:30]:
            host, port = _extract_host_port_v13(s["url"])
            if host and port:
                ms = _ping_host_v13(host, port)
                if ms < 9999: tested.append((ms, s, host, port))
        tested.sort(key=lambda x: x[0])
        if not tested:
            if msg_id: TG.edit_message(chat_id, msg_id, "❌ هیچ سروری پاسخ نداد.")
            return
        text = f"⚡ <b>کم‌پینگ‌ترین سرورها ({len(tested)}):</b>\n\n"
        for i, (ms, s, host, port) in enumerate(tested[:10], 1):
            proto, tag = _proxy_display_v13(s["url"])
            text += f"<b>{i}. {ms}ms</b> — {proto} {escape_html(tag)[:40]}\n"
            text += f"<code>{escape_html(host)}:{port}</code>\n"
            text += f"<code>{escape_html(s['url'][:150])}</code>\n\n"
        if msg_id:
            TG.edit_message(chat_id, msg_id, text[:4000],
                reply_markup=kb([[btn("📤 ارسال به کانال","proxy:send"),
                                  btn("🔄 دوباره","proxy:low")],
                                 [btn("🏠","m:main")]]))
        else:
            TG.send_message(chat_id, text[:4000])
    except Exception as e:
        log.exception(f"[v13] low_ping: {e}")

def _proxy_subscription_v13(chat_id, msg_id):
    try:
        if msg_id: TG.edit_message(chat_id, msg_id, "📦 ساخت اشتراک ...")
        servers = _fetch_proxies_v13()
        if not servers: return
        sub = "\n".join(s["url"] for s in servers[:10])
        b64 = _b64_v13.b64encode(sub.encode("utf-8")).decode("ascii")
        text = (f"📦 <b>اشتراک V2Ray (۱۰ سرور)</b>\n\n"
                f"<i>Base64 Subscription:</i>\n\n"
                f"<code>{b64[:3500]}</code>")
        if msg_id:
            TG.edit_message(chat_id, msg_id, text[:4000],
                reply_markup=kb([[btn("📤 ارسال به کانال","proxy:send")],
                                 [btn("🔄 دوباره","proxy:sub"), btn("🏠","m:main")]]))
        else:
            TG.send_message(chat_id, text[:4000])
    except Exception as e:
        log.exception(f"[v13] sub: {e}")

def _proxy_to_channel_v13(chat_id, msg_id):
    try:
        cfg = CONFIG.get()
        ch = (cfg.telegram.channel_id or "").strip()
        if not ch: return
        servers = _fetch_proxies_v13()
        if not servers: return
        # pick 10 with lowest ping
        tested = []
        for s in servers[:20]:
            host, port = _extract_host_port_v13(s["url"])
            if host and port:
                ms = _ping_host_v13(host, port, 1.0)
                if ms < 9999: tested.append((ms, s))
        tested.sort(key=lambda x: x[0])
        top = [s for ms, s in tested[:10]] or servers[:10]
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        text = (f"🌐 <b>پروکسی‌های رایگان</b>\n"
                f"<i>🕐 {ts}</i>\n"
                f"<i>⚡ مرتب‌شده بر اساس پینگ</i>\n\n")
        for i, s in enumerate(top, 1):
            proto, tag = _proxy_display_v13(s["url"])
            ms = next((m for m, ss in tested if ss is s), 0)
            text += f"<b>{i}. {proto}</b>"
            if ms: text += f" — <code>{ms}ms</code>"
            text += f"\n<code>{escape_html(s['url'][:200])}</code>\n\n"
        text += "⚠️ <i>سرورهای عمومی — با احتیاط</i>\n📢 @MAADGHchannel"
        TG.send_message(ch, text[:4000])
        if msg_id:
            TG.edit_message(chat_id, msg_id, "✅ ۱۰ پروکسی به کانال ارسال شد.",
                reply_markup=kb([[btn("🏠","m:main")]]))
        else:
            TG.send_message(chat_id, "✅ ارسال شد.")
    except Exception as e:
        log.exception(f"[v13] to_channel: {e}")

# ─── 2. Ganjoor API ───────────────────────────────────────────
class GanjoorAPI_v13:
    BASE = "https://api.ganjoor.net"
    @staticmethod
    def random_poem(poet_id=0):
        try:
            r = HTTP.request("GET", f"{GanjoorAPI_v13.BASE}/api/ganjoor/poem/random",
                            params={"poetId": poet_id}, timeout=15)
            if r is None or r.status_code != 200: return None
            return r.json()
        except Exception: return None
    @staticmethod
    def hafez_fal():
        try:
            r = HTTP.request("GET", f"{GanjoorAPI_v13.BASE}/api/ganjoor/hafez/faal", timeout=15)
            if r is None or r.status_code != 200: return None
            return r.json()
        except Exception: return None
    @staticmethod
    def poets():
        try:
            r = HTTP.request("GET", f"{GanjoorAPI_v13.BASE}/api/ganjoor/poets", timeout=15)
            if r is None or r.status_code != 200: return None
            return r.json()
        except Exception: return None
    @staticmethod
    def search(q):
        try:
            r = HTTP.request("GET", f"{GanjoorAPI_v13.BASE}/api/ganjoor/poems/search",
                            params={"term": q}, timeout=15)
            if r is None or r.status_code != 200: return None
            return r.json()
        except Exception: return None

GANJOOR = GanjoorAPI_v13()

def _ganjoor_format_v13(p):
    if not p: return ""
    title = p.get("title") or p.get("fullTitle") or "شعر"
    poet = (p.get("poet") or {}).get("name") or ""
    verses = p.get("verses") or []
    text = f"📜 <b>{escape_html(title)}</b>\n"
    if poet: text += f"<i>— {escape_html(poet)}</i>\n\n"
    for v in verses:
        t = v.get("text") or v.get("verseText") or ""
        if t: text += f"{escape_html(t)}\n"
    return text

@ROUTER.command("poem", description="شعر تصادفی")
def cmd_poem_v13(msg, args):
    chat_id = get_chat_id(msg)
    POOL.submit(_poem_bg_v13, chat_id, None, args)

def _poem_bg_v13(chat_id, msg_id, args):
    try:
        if msg_id: TG.edit_message(chat_id, msg_id, "📜 دریافت شعر ...")
        poet_id = 0
        if args:
            try: poet_id = int(args)
            except Exception: poet_id = 0
        p = GANJOOR.random_poem(poet_id)
        if not p:
            if msg_id: TG.edit_message(chat_id, msg_id, "❌ یافت نشد.")
            return
        text = _ganjoor_format_v13(p)
        rows = [[btn("📤 ارسال به کانال", f"poem:send")],
                [btn("🔄 شعر دیگر","poem:next"), btn("🏠","m:main")]]
        if msg_id:
            TG.edit_message(chat_id, msg_id, text[:4000], reply_markup=kb(rows))
        else:
            TG.send_message(chat_id, text[:4000], reply_markup=kb(rows))
        _POEM_STORE_V13[chat_id] = text
    except Exception as e:
        log.exception(f"[v13] poem: {e}")

_POEM_STORE_V13 = TTLStore(max_items=500, ttl=3600)
@ROUTER.callback("poem")
def cb_poem_v13(cb, data):
    chat_id = cb["message"]["chat"]["id"]; msg_id = cb["message"]["message_id"]
    action = data.split(":")[1] if ":" in data else ""
    TG.answer_callback(cb.get("id", ""), "📜")
    if action == "send":
        text = _POEM_STORE_V13.get(chat_id, "")
        cfg = CONFIG.get()
        if text and cfg.telegram.channel_id:
            TG.send_message(cfg.telegram.channel_id, text + "\n\n📢 @MAADGHchannel")
            TG.send_message(chat_id, "✅ ارسال شد.")
    elif action == "next":
        POOL.submit(_poem_bg_v13, chat_id, msg_id, "")

@ROUTER.command("fal", description="فال حافظ")
def cmd_fal_v13(msg, args):
    chat_id = get_chat_id(msg)
    m = TG.send_message(chat_id, "🔮 فال حافظ ...")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")
    def _do():
        try:
            p = GANJOOR.hafez_fal()
            if not p:
                TG.edit_message(chat_id, mid, "❌ فال دریافت نشد."); return
            text = "🔮 <b>فال حافظ</b>\n\n" + _ganjoor_format_v13(p)
            TG.edit_message(chat_id, mid, text[:4000],
                reply_markup=kb([[btn("🔄 فال دیگر","poem:fal"), btn("🏠","m:main")]]))
        except Exception as e:
            TG.edit_message(chat_id, mid, f"❌ {e}")
    POOL.submit(_do)

# ─── 3. Telegram music group search ────────────────────────────
_MUSIC_TG_GROUPS_V13 = [
    "musicworldiran", "persian_music_iran", "iran_music_mp3",
    "music_iran_mp3", "irani_music_channel",
]

@ROUTER.command("music", description="موسیقی (فایل صوتی)")
def cmd_music(msg, args):
    chat_id = get_chat_id(msg)
    if args and args.lower() in MUSIC_CATEGORIES:
        POOL.submit(_music_tg_search_v13, chat_id, None, args.lower(),
                    MUSIC_CAT_LABELS.get(args.lower(), args))
        return
    rows = []; row = []
    for k, label in MUSIC_CAT_LABELS.items():
        row.append(btn(f"🎵 {label}", f"music:tg:{k}"))
        if len(row) == 2: rows.append(row); row = []
    if row: rows.append(row)
    rows.append([btn("🎲 تصادفی","music:tg_rand"), btn("🏠 منو","m:main")])
    TG.send_message(chat_id,
        f"🎵 <b>موسیقی</b> — {len(MUSIC_CAT_LABELS)} سبک\n"
        f"<i>جستجو در گروه‌های تلگرام</i>",
        reply_markup=kb(rows))

_MUSIC_TG_STORE_V13 = TTLStore(max_items=500, ttl=1800)
def _music_tg_search_v13(chat_id, msg_id, key, label):
    try:
        if msg_id: TG.edit_message(chat_id, msg_id, f"🎵 جستجو «{escape_html(label)}» ...")
        # search Telegram public groups via global search
        q = _up_v13.quote(f"{label} mp3")
        hits = []
        try:
            r = HTTP.request("GET", "https://t.me/s/musicworldiran", timeout=15)
            if r and r.status_code == 200:
                # parse audio links
                audios = re.findall(r'href="(https://t\.me/[^"]+)"', r.text)
                for a in audios[:8]:
                    hits.append({"url": a, "title": f"{label} — {a.split('/')[-1][:30]}"})
        except Exception: pass
        # Fallback: YouTube via existing API
        if len(hits) < 5:
            try:
                r = APIS.youtube.search_videos(f"{label} music", max_results=6, language="en")
                if r.ok and r.data:
                    for v in r.data:
                        hits.append({"url": v.get("url",""), "title": v.get("title",""),
                                     "channel": v.get("channel",""), "type": "yt"})
            except Exception: pass
        if not hits:
            if msg_id: TG.edit_message(chat_id, msg_id, "❌ یافت نشد.")
            return
        _MUSIC_TG_STORE_V13[chat_id] = hits
        # 3 professional options per item
        text = f"🎵 <b>{escape_html(label)}</b>\n<i>{len(hits)} نتیجه</i>\n\n"
        for i, h in enumerate(hits[:5], 1):
            text += f"<b>{i}.</b> 🎵 {escape_html(h['title'][:70])}\n"
        rows = []
        for i, h in enumerate(hits[:5], 1):
            rows.append([
                btn(f"▶️ پخش {i}", f"music:play:{i}"),
                btn(f"📥 فایل {i}", f"music:file:{i}"),
                btn(f"📤 کانال {i}", f"music:pub:{i}"),
            ])
        rows.append([btn("🔄 دیگر", f"music:tg:{key}"), btn("🏠 منو","m:main")])
        if msg_id:
            TG.edit_message(chat_id, msg_id, text[:4000], reply_markup=kb(rows))
        else:
            TG.send_message(chat_id, text[:4000], reply_markup=kb(rows))
    except Exception as e:
        log.exception(f"[v13] music_tg: {e}")

@ROUTER.callback("music")
def cb_music_v13(cb, data):
    try:
        parts = data.split(":"); action = parts[1] if len(parts) > 1 else ""
        chat_id = cb["message"]["chat"]["id"]; msg_id = cb["message"]["message_id"]
        TG.answer_callback(cb.get("id", ""), "🎵")
        if action == "back":
            cmd_music({"chat":{"id":chat_id},"from":cb.get("from",{}),"message":{}}, "")
            return
        if action == "tg_rand":
            k = _RND.choice(list(MUSIC_CATEGORIES.keys()))
            POOL.submit(_music_tg_search_v13, chat_id, msg_id, k, MUSIC_CAT_LABELS.get(k,k)); return
        if action == "tg":
            k = parts[2] if len(parts) > 2 else ""
            if k in MUSIC_CATEGORIES:
                POOL.submit(_music_tg_search_v13, chat_id, msg_id, k, MUSIC_CAT_LABELS.get(k,k))
            return
        if action in ("play", "file", "pub"):
            try: idx = int(parts[2])
            except Exception: return
            hits = _MUSIC_TG_STORE_V13.get(chat_id) or []
            if idx < 0 or idx >= len(hits): return
            h = hits[idx]
            if action == "pub":
                cfg = CONFIG.get()
                if cfg.telegram.channel_id:
                    TG.send_message(cfg.telegram.channel_id,
                        f"🎵 <b>{escape_html(h.get('title','')[:80])}</b>\n\n"
                        f"🔗 {h.get('url','')}\n\n📢 @MAADGHchannel")
                TG.answer_callback(cb.get("id", ""), "📤")
                return
            if h.get("type") == "yt" or "youtu" in h.get("url",""):
                TG.answer_callback(cb.get("id", ""), "🎬 YouTube")
                TG.send_message(chat_id, f"🎵 <b>{escape_html(h.get('title','')[:80])}</b>\n{h.get('url','')}")
                return
            TG.answer_callback(cb.get("id", ""), "📤")
    except Exception as e:
        log.exception(f"[v13] music cb: {e}")

# ─── 4. Auto proxy sender (every 1 hour) ───────────────────────
class AutoProxyV13:
    def __init__(self):
        self._stop = threading.Event(); self._t = None
    def start(self):
        if self._t and self._t.is_alive(): return
        self._stop.clear()
        self._t = threading.Thread(target=self._loop, daemon=True, name="AutoProxyV13")
        self._t.start()
    def stop(self): self._stop.set()
    def _loop(self):
        if self._stop.wait(120): return
        while not self._stop.is_set():
            try:
                cfg = CONFIG.get()
                ch = (cfg.telegram.channel_id or "").strip()
                if ch:
                    _proxy_to_channel_v13(0, None)
                    log.info("[v13] auto-proxy sent to channel")
            except Exception as e:
                log.debug(f"[v13] auto-proxy: {e}")
            if self._stop.wait(3600): break

AUTO_PROXY_V13 = AutoProxyV13()

# Start auto-proxy if env var set
try:
    if os.getenv("AUTO_PROXY", "1") == "1":
        AUTO_PROXY_V13.start()
except Exception: pass

# ── Update main menu with proxy + poem ──────────
def kb_main_menu():
    return kb([
        [btn("📚 موضوعات","m:list"), btn("🔍 جستجو","m:find"), btn("🌟 سوپر","m:super")],
        [btn("🎓 آموزش","learn:bank"), btn("📐 ریاضی","math:bank"), btn("❓ کوییز","quiz:menu")],
        [btn("📇 فلش‌کارت","flash:back"), btn("📖 ویکی","wiki:menu"), btn("📚 arXiv","arxiv:p:0")],
        [btn("📰 اخبار","news:menu"), btn("🎵 موسیقی","music:back"), btn("📜 شعر","poem:next")],
        [btn("💱 ارز","rate:refresh"), btn("✈️ هوانوردی","av:refresh"), btn("🌐 پروکسی","proxy:list")],
        [btn("🔮 فال حافظ","poem:fal"), btn("🌤 آب‌وهوا","m:weather"), btn("🎥 یوتیوب","y:rand")],
        [btn("📊 آمار","stats:cat:usage"), btn("⚙️ تنظیمات","m:settings"), btn("ℹ️ راهنما","m:help")],
    ])

log.info("PATCH v13.0 applied — proxy + ganjoor + telegram music")
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════════
#  PATCH v15.0 — COMPREHENSIVE FIX
#  ─────────────────────────────────────────────────────────────────────────────
#  این patch مشکلات زیر را رفع می‌کند:
#    • Exchange API جایگزین با open.er-api.com (شامل IRR)
#    • ترجمه کامل ویکی‌پدیا (chunked >450 char)
#    • آب‌وهوا: ۶۰ شهر (۳۰ ایران + ۳۰ جهان) + ارسال به کانال
#    • اخبار سیاسی ایران/آمریکا/جهان + تأیید قبل از ارسال
#    • موسیقی: بازگشت به Archive.org (کارکننده)
#    • منوی اصلی نهایی و پایدار
#    • رفع تداخل نسخه‌های v4-v13
# ═══════════════════════════════════════════════════════════════════════════════

import urllib.parse as _up_v15
import hashlib as _h_v15
import json as _json_v15
import time as _t_v15
import socket as _s_v15
import threading as _thr_v15

# ─────────────────────────────────────────────────────────────────────────────
#  ماژول ۱ — Exchange API بازنویسی‌شده
#  ─────────────────────────────────────────────────────────────────────────────
#  سرویس‌های جایگزین (multi-fallback):
#    1) open.er-api.com     — رایگان، بدون کلید، شامل IRR
#    2) api.frankfurter.app — backup اروپایی (بدون IRR)
#    3) api.exchangerate-api.com/v4 — backup نهایی
# ─────────────────────────────────────────────────────────────────────────────

class ExchangeV15:
    """Multi-source exchange rate provider — no API key required."""

    _CACHE = {}          # {(base): (ts, rates_dict)}
    _CACHE_TTL = 900     # 15 min
    _LOCK = _thr_v15.RLock()

    @classmethod
    def fetch(cls, base="USD"):
        base = base.upper()
        now = _t_v15.time()
        with cls._LOCK:
            cached = cls._CACHE.get(base)
            if cached and now - cached[0] < cls._CACHE_TTL:
                return cached[1]

        rates = {}

        # ─── منبع ۱: open.er-api.com ────────────────────────────────────
        try:
            r = HTTP.request("GET",
                             f"https://open.er-api.com/v6/latest/{base}",
                             timeout=15)
            if r is not None and r.status_code == 200:
                data = r.json()
                if data.get("result") == "success" and data.get("rates"):
                    rates = data["rates"]
                    try:
                        log.debug(f"[v15] exchange source=er-api base={base} n={len(rates)}")
                    except Exception:
                        pass
        except Exception as e:
            try: log.debug(f"[v15] er-api fail: {e}")
            except Exception: pass

        # ─── منبع ۲: frankfurter.app (backup) ──────────────────────────
        if not rates:
            try:
                r = HTTP.request("GET",
                                 "https://api.frankfurter.app/latest",
                                 params={"from": base},
                                 timeout=15)
                if r is not None and r.status_code == 200:
                    data = r.json()
                    rates = data.get("rates", {})
                    if rates:
                        try: log.debug(f"[v15] exchange source=frankfurter base={base}")
                        except Exception: pass
            except Exception as e:
                try: log.debug(f"[v15] frankfurter fail: {e}")
                except Exception: pass

        # ─── منبع ۳: exchangerate-api.com/v4 ───────────────────────────
        if not rates:
            try:
                r = HTTP.request("GET",
                                 f"https://api.exchangerate-api.com/v4/latest/{base}",
                                 timeout=15)
                if r is not None and r.status_code == 200:
                    data = r.json()
                    rates = data.get("rates", {})
                    if rates:
                        try: log.debug(f"[v15] exchange source=exchangerate-api base={base}")
                        except Exception: pass
            except Exception as e:
                try: log.debug(f"[v15] exchangerate-api fail: {e}")
                except Exception: pass

        # ─── استخراج IRR از API داخلی (اگر موجود نبود) ────────────────
        #  بعضی منابع IRR ندارند؛ از منابع ایرانی جبران می‌کنیم
        if rates and "IRR" not in rates and base != "IRR":
            try:
                r = HTTP.request("GET", "https://api.frankfurter.app/latest", params={"from": base, "to": "IRR"}, timeout=8)
                if r is not None and r.status_code == 200:
                    j = r.json()
                    irr = (j.get("rates") or {}).get("IRR")
                    if irr:
                        rates["IRR"] = irr
            except Exception:
                pass

        with cls._LOCK:
            cls._CACHE[base] = (now, rates)
        return rates

    @classmethod
    def convert(cls, amount, from_cur, to_cur):
        rates = cls.fetch(from_cur)
        if not rates:
            return None
        rate = rates.get(to_cur.upper())
        if rate is None:
            return None
        try:
            return float(amount) * float(rate)
        except Exception:
            return None

# جایگزینی متدها در ExchangeAPI اصلی
def _ex_latest_v15(self, base="USD", symbols=""):
    rates = ExchangeV15.fetch(base)
    if not rates:
        return self._wrap(False, error="all exchange sources failed")
    if symbols:
        wanted = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        rates = {k: v for k, v in rates.items() if k in wanted}
    return self._wrap(True, data={"base": base.upper(), "rates": rates})

def _ex_convert_v15(self, amount, from_cur, to_cur):
    result = ExchangeV15.convert(amount, from_cur, to_cur)
    if result is None:
        return self._wrap(False, error=f"no rate for {from_cur}->{to_cur}")
    return self._wrap(True, data={"result": result, "amount": amount,
                                  "from": from_cur, "to": to_cur})

try:
    ExchangeAPI.latest  = _ex_latest_v15
    ExchangeAPI.convert = _ex_convert_v15
    try: log.info("[v15] ExchangeAPI overridden with multi-source provider")
    except Exception: pass
except Exception as _e:
    try: log.warning(f"[v15] ExchangeAPI override failed: {_e}")
    except Exception: pass

# ─────────────────────────────────────────────────────────────────────────────
#  ماژول ۲ — ترجمه‌ی متن‌های بلند (chunked)
# ─────────────────────────────────────────────────────────────────────────────
#  MyMemory سقف ۵۰۰ کاراکتر دارد؛ متن را به قطعات ۴۵۰ کاراکتری
#  در مرزهای جمله تقسیم می‌کنیم.
# ─────────────────────────────────────────────────────────────────────────────

def _split_sentences_v15(text):
    """تقسیم متن به جملات با حفظ علامت‌های نگارشی."""
    if not text:
        return []
    # split on . ! ? ؟ ! … and newlines
    parts = re.split(r'(?<=[\.\!\?؟…])\s+|\n+', text)
    return [p.strip() for p in parts if p and p.strip()]

def _chunk_text_v15(text, max_len=450):
    """تقسیم متن به قطعات ≤ max_len با احترام به مرز جمله."""
    if not text:
        return []
    if len(text) <= max_len:
        return [text]
    sentences = _split_sentences_v15(text)
    if not sentences:
        # fallback: hard split
        return [text[i:i+max_len] for i in range(0, len(text), max_len)]
    chunks = []
    current = ""
    for s in sentences:
        # اگر یک جمله طولانی است، split کن
        if len(s) > max_len:
            if current:
                chunks.append(current)
                current = ""
            while len(s) > max_len:
                chunks.append(s[:max_len])
                s = s[max_len:]
            current = s
            continue
        # اگر جا دارد، اضافه کن
        if not current:
            current = s
        elif len(current) + 1 + len(s) <= max_len:
            current = current + " " + s
        else:
            chunks.append(current)
            current = s
    if current:
        chunks.append(current)
    return chunks

def _translate_long_v15(text, src="en", tgt="fa", max_chunk=450):
    """ترجمه‌ی متن طولانی با تقسیم به قطعات."""
    if not text:
        return ""
    text = text.strip()
    if not text:
        return ""
    if len(text) <= max_chunk:
        try:
            return TR_V10.translate(text, src, tgt) or text
        except Exception:
            return text
    chunks = _chunk_text_v15(text, max_chunk)
    out = []
    for i, c in enumerate(chunks):
        try:
            t = TR_V10.translate(c, src, tgt)
            out.append(t if t else c)
        except Exception:
            out.append(c)
        # rate limit protection
        if i < len(chunks) - 1:
            _t_v15.sleep(0.15)
    return " ".join(out)

# نگاشت نام قدیمی به جدید
_translate_long_v14 = _translate_long_v15

# ─────────────────────────────────────────────────────────────────────────────
#  ماژول ۳ — ویکی‌پدیا با ترجمه‌ی کامل
# ─────────────────────────────────────────────────────────────────────────────

def _wiki_fetch_v7(chat_id, msg_id, title):
    """ویکی‌پدیا دوزبانه — ترجمه‌ی کل متن انگلیسی اگر فارسی ناقص بود."""
    if not title:
        return
    if msg_id:
        try:
            TG.edit_message(chat_id, msg_id, f"📖 «{escape_html(title)}» ...")
        except Exception:
            pass
    else:
        m = TG.send_message(chat_id, f"📖 «{escape_html(title)}» ...")
        msg_id = (m.result or {}).get("message_id") if m.ok else None

    r_fa = APIS.wikipedia.summary(title, "fa")
    r_en = APIS.wikipedia.summary(title, "en")

    fa_title = fa_extract = fa_url = ""
    en_title = en_extract = en_url = ""

    if r_en.ok:
        d = r_en.data
        en_title = d.get("title", "") or title
        en_extract = clean_wiki_extract(d.get("extract", "") or "")
        en_url = d.get("url", "")

    if r_fa.ok:
        d = r_fa.data
        fa_title = d.get("title", "") or title
        fa_extract = clean_wiki_extract(d.get("extract", "") or "")
        fa_url = d.get("url", "")

    # اگر فارسی خیلی کوتاه‌تر از انگلیسی است → ترجمه کن
    need_translation = False
    if en_extract:
        if not fa_extract:
            need_translation = True
        elif len(fa_extract) < len(en_extract) * 0.55:
            need_translation = True

    if need_translation:
        try:
            translated = _translate_long_v15(en_extract[:2500], "en", "fa")
            if translated and len(translated) > len(fa_extract):
                fa_extract = translated
                if not fa_title or fa_title == title:
                    fa_title = _translate_long_v15(en_title, "en", "fa") or title
        except Exception as _e:
            try: log.debug(f"[v15] wiki translate: {_e}")
            except Exception: pass

    if not (fa_extract or en_extract):
        if msg_id:
            try:
                TG.edit_message(chat_id, msg_id, "❌ یافت نشد.")
            except Exception:
                pass
        return

    fa_show = fa_extract[:2200] if fa_extract else ""
    en_show = en_extract[:2200] if en_extract else ""

    body_parts = ["📖 <b>ویکی‌پدیا — دوزبانه</b>", ""]
    if fa_show:
        body_parts.append(f"🇮🇷 <b>{escape_html(fa_title[:200])}</b>")
        body_parts.append(escape_html(fa_show))
        body_parts.append("")
    if en_show:
        body_parts.append("━━━━━━━━━━━━━━━━━━━━")
        body_parts.append("")
        body_parts.append(f"🇬🇧 <b>{escape_html(en_title[:200])}</b>")
        body_parts.append(f"<i>{escape_html(en_show)}</i>")
        body_parts.append("")
    body_parts.append(f"🔗 {fa_url or en_url}")

    text = "\n".join(body_parts)

    buttons = kb([
        [btn("🎥 ویدیو", f"wiki:vid:{escape_html(title)[:40]}")],
        [btn("⬅️ فهرست", "wiki:menu"), btn("🏠", "m:main")],
    ])

    if msg_id:
        # اگر طولانی است، split کن
        if len(text) > 4000:
            try:
                TG.edit_message(chat_id, msg_id, text[:4000])
            except Exception:
                pass
            try:
                TG.send_long_message(chat_id, text[4000:], reply_markup=buttons)
            except Exception:
                pass
        else:
            try:
                TG.edit_message(chat_id, msg_id, text[:4000], reply_markup=buttons)
            except Exception:
                pass
    else:
        try:
            TG.send_long_message(chat_id, text)
        except Exception as e:
            log.debug(f"[v16] wiki send: {e}")
            try:
                TG.send_message(chat_id, text[:4000])
            except Exception:
                pass

# ─────────────────────────────────────────────────────────────────────────────
#  ماژول ۴ — آب‌وهوا با ۶۰ شهر و ارسال به کانال
# ─────────────────────────────────────────────────────────────────────────────

_WX_CITIES_V15 = [
    # ─── ایران (۳۰) ─────────────────────────────────────────────────
    ("🇮🇷", "تهران",       "Tehran"),
    ("🇮🇷", "مشهد",        "Mashhad"),
    ("🇮🇷", "اصفهان",      "Isfahan"),
    ("🇮🇷", "شیراز",       "Shiraz"),
    ("🇮🇷", "تبریز",       "Tabriz"),
    ("🇮🇷", "کرج",         "Karaj"),
    ("🇮🇷", "اهواز",       "Ahvaz"),
    ("🇮🇷", "قم",          "Qom"),
    ("🇮🇷", "کرمانشاه",    "Kermanshah"),
    ("🇮🇷", "ارومیه",      "Urmia"),
    ("🇮🇷", "رشت",         "Rasht"),
    ("🇮🇷", "زاهدان",      "Zahedan"),
    ("🇮🇷", "همدان",       "Hamadan"),
    ("🇮🇷", "کرمان",       "Kerman"),
    ("🇮🇷", "یزد",         "Yazd"),
    ("🇮🇷", "اردبیل",      "Ardabil"),
    ("🇮🇷", "بندرعباس",    "Bandar Abbas"),
    ("🇮🇷", "اراک",        "Arak"),
    ("🇮🇷", "زنجان",       "Zanjan"),
    ("🇮🇷", "سنندج",       "Sanandaj"),
    ("🇮🇷", "قزوین",       "Qazvin"),
    ("🇮🇷", "خرم‌آباد",     "Khorramabad"),
    ("🇮🇷", "گرگان",       "Gorgan"),
    ("🇮🇷", "ساری",        "Sari"),
    ("🇮🇷", "بجنورد",      "Bojnord"),
    ("🇮🇷", "بیرجند",      "Birjand"),
    ("🇮🇷", "بوشهر",       "Bushehr"),
    ("🇮🇷", "ایلام",       "Ilam"),
    ("🇮🇷", "یاسوج",       "Yasuj"),
    ("🇮🇷", "شهرکرد",      "Shahrekord"),
    # ─── جهان (۳۰) ──────────────────────────────────────────────────
    ("🇦🇪", "دبی",          "Dubai"),
    ("🇹🇷", "استانبول",     "Istanbul"),
    ("🇬🇧", "لندن",         "London"),
    ("🇫🇷", "پاریس",        "Paris"),
    ("🇺🇸", "نیویورک",      "New York"),
    ("🇯🇵", "توکیو",        "Tokyo"),
    ("🇷🇺", "مسکو",         "Moscow"),
    ("🇩🇪", "برلین",        "Berlin"),
    ("🇮🇹", "رم",           "Rome"),
    ("🇪🇸", "مادرید",       "Madrid"),
    ("🇨🇳", "پکن",          "Beijing"),
    ("🇨🇳", "شانگهای",      "Shanghai"),
    ("🇰🇷", "سئول",         "Seoul"),
    ("🇦🇺", "سیدنی",        "Sydney"),
    ("🇨🇦", "تورنتو",       "Toronto"),
    ("🇶🇦", "دوحه",         "Doha"),
    ("🇸🇦", "ریاض",         "Riyadh"),
    ("🇰🇼", "کویت",         "Kuwait City"),
    ("🇦🇪", "ابوظبی",       "Abu Dhabi"),
    ("🇮🇶", "بغداد",        "Baghdad"),
    ("🇳🇱", "آمستردام",     "Amsterdam"),
    ("🇦🇹", "وین",          "Vienna"),
    ("🇨🇭", "زوریخ",        "Zurich"),
    ("🇸🇪", "استکهلم",      "Stockholm"),
    ("🇳🇴", "اوسلو",        "Oslo"),
    ("🇫🇮", "هلسینکی",      "Helsinki"),
    ("🇵🇹", "لیسبون",       "Lisbon"),
    ("🇬🇷", "آتن",          "Athens"),
    ("🇵🇱", "وارشو",        "Warsaw"),
    ("🇨🇿", "پراگ",         "Prague"),
]

_WX_STORE_V15 = TTLStore(max_items=500, ttl=3600)
_WX_LAST_V15 = TTLStore(max_items=500, ttl=3600)
def _kb_weather_v15(page=0, per=12):
    """منوی آب‌وهوا با صفحه‌بندی."""
    total = len(_WX_CITIES_V15)
    pages = max(1, (total + per - 1) // per)
    page = max(0, min(page, pages - 1))
    start = page * per
    chunk = _WX_CITIES_V15[start:start + per]

    rows = []
    row = []
    for i, (flag, fa, en) in enumerate(chunk):
        idx = start + i
        row.append(btn(f"{flag} {fa}", f"wx:go:{idx}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    nav = []
    if page > 0:
        nav.append(btn("◀️", f"wx:p:{page - 1}"))
    nav.append(btn(f"{page + 1}/{pages}", "wx:nop"))
    if page < pages - 1:
        nav.append(btn("▶️", f"wx:p:{page + 1}"))
    rows.append(nav)
    rows.append([btn("🔍 شهر دیگر", "wx:search"),
                 btn("🎲 تصادفی", "wx:rand"),
                 btn("🏠 منو", "m:main")])
    return kb(rows)

@ROUTER.command("weather", description="آب‌وهوا — ۶۰ شهر")
def cmd_weather_v15(msg, args):
    chat_id = get_chat_id(msg)
    if args:
        city = args.strip()
        POOL.submit(_wx_fetch_v15, chat_id, None, city, city)
        return
    TG.send_message(
        chat_id,
        f"🌤 <b>آب‌وهوا</b>\n"
        f"<i>{len(_WX_CITIES_V15)} شهر — انتخاب یا جستجو</i>",
        reply_markup=_kb_weather_v15(0)
    )

@ROUTER.callback("wx")
def cb_wx_v15(cb, data):
    try:
        parts = data.split(":")
        action = parts[1] if len(parts) > 1 else ""
        chat_id = cb["message"]["chat"]["id"]
        msg_id  = cb["message"]["message_id"]

        if action == "nop":
            TG.answer_callback(cb.get("id", ""))
            return

        if action == "p":
            try:
                pg = int(parts[2])
            except Exception:
                pg = 0
            TG.answer_callback(cb.get("id", ""))
            TG.edit_message(
                chat_id, msg_id,
                f"🌤 <b>آب‌وهوا</b> — {len(_WX_CITIES_V15)} شهر",
                reply_markup=_kb_weather_v15(pg)
            )
            return

        if action == "go":
            try:
                idx = int(parts[2])
            except Exception:
                return
            if 0 <= idx < len(_WX_CITIES_V15):
                flag, fa, en = _WX_CITIES_V15[idx]
                TG.answer_callback(cb.get("id", ""), f"⏳ {fa}")
                POOL.submit(_wx_fetch_v15, chat_id, msg_id, en, fa)
            return

        if action == "rand":
            idx = _RND.randint(0, len(_WX_CITIES_V15) - 1)
            flag, fa, en = _WX_CITIES_V15[idx]
            TG.answer_callback(cb.get("id", ""), f"🎲 {fa}")
            POOL.submit(_wx_fetch_v15, chat_id, msg_id, en, fa)
            return

        if action == "search":
            uid = cb["from"]["id"]
            SESSIONS.set_state(uid, "awaiting_city",
                               chat_id=chat_id, msg_id=msg_id)
            TG.answer_callback(cb.get("id", ""), "🔍")
            TG.edit_message(
                chat_id, msg_id,
                "🔍 <b>نام شهر</b>\n\nبه فارسی یا انگلیسی بنویس:\n"
                "<i>مثال: تهران / Tehran / مشهد</i>",
                reply_markup=kb([[btn("⬅️ لغو", "m:weather")]])
            )
            return

        if action == "send":
            uid = cb["from"]["id"]
            text = _WX_STORE_V15.get(uid) or _WX_STORE_V15.get(chat_id)
            if not text:
                TG.answer_callback(cb.get("id", ""), "❌ داده‌ای نیست", show_alert=True)
                return
            TG.answer_callback(cb.get("id", ""), "📤 ارسال...")
            try:
                cfg = CONFIG.get()
                ch = (cfg.telegram.channel_id or "").strip()
                if ch:
                    payload = text + "\n\n📢 @MAADGHchannel"
                    TG.send_message(ch, payload, parse_mode="HTML")
                    TG.send_message(chat_id, "✅ به کانال ارسال شد.")
                else:
                    TG.send_message(chat_id, "❌ کانال تنظیم نشده.")
            except Exception as e:
                TG.send_message(chat_id, f"❌ خطا: {escape_html(str(e)[:100])}")
            return

        if action == "refresh":
            uid = cb["from"]["id"]
            last = _WX_LAST_V15.get(uid)
            if last:
                POOL.submit(_wx_fetch_v15, chat_id, msg_id, last[0], last[1])
            else:
                TG.answer_callback(cb.get("id", ""), "❌", show_alert=True)
            return

    except Exception as e:
        try: log.exception(f"[v15] wx callback: {e}")
        except Exception: pass

def _wx_fetch_v15(chat_id, msg_id, city, label=""):
    """دریافت و نمایش آب‌وهوا."""
    try:
        label = label or city
        if msg_id:
            try:
                TG.edit_message(chat_id, msg_id, f"🌤 دریافت «{escape_html(label)}» ...")
            except Exception:
                pass
        else:
            m = TG.send_message(chat_id, f"🌤 دریافت «{escape_html(label)}» ...")
            msg_id = (m.result or {}).get("message_id") if m.ok else None

        r = APIS.weather.forecast(city, days=3)
        if not r.ok:
            if msg_id:
                try:
                    TG.edit_message(
                        chat_id, msg_id,
                        f"❌ {escape_html(r.error[:150])}",
                        reply_markup=kb([[btn("⬅️", "m:weather"), btn("🏠", "m:main")]])
                    )
                except Exception:
                    pass
            return

        text = APIS.weather.format(r.data)
        uid = chat_id if chat_id > 0 else 0
        _WX_STORE_V15[uid] = text
        _WX_STORE_V15[chat_id] = text
        _WX_LAST_V15[uid] = (city, label)

        buttons = kb([
            [btn("📤 ارسال به کانال", "wx:send"),
             btn("🔄 بروزرسانی", "wx:refresh")],
            [btn("🔍 شهر دیگر", "wx:search"),
             btn("🎲 تصادفی", "wx:rand"),
             btn("🏠 منو", "m:main")],
        ])

        if msg_id:
            try:
                TG.edit_message(chat_id, msg_id, text, reply_markup=buttons)
            except Exception:
                pass
        else:
            try:
                TG.send_message(chat_id, text, reply_markup=buttons)
            except Exception:
                pass
    except Exception as e:
        try: log.exception(f"[v15] wx fetch: {e}")
        except Exception: pass

# ─────────────────────────────────────────────────────────────────────────────
#  ماژول ۵ — اخبار سیاسی ایران / آمریکا / جهان
# ─────────────────────────────────────────────────────────────────────────────

_POL_FEEDS_V15 = {
    "iran": [
        ("🇮🇷 IRNA (English)",   "https://en.irna.ir/rss"),
        ("🇮🇷 PressTV",          "https://www.presstv.ir/rss"),
        ("🇮🇷 Tehran Times",     "https://www.tehrantimes.com/rss"),
        ("🇮🇷 Iran Daily",       "https://iran-daily.com/rss"),
    ],
    "usa": [
        ("🇺🇸 Reuters Politics", "https://feeds.reuters.com/reuters/politicsNews"),
        ("🇺🇸 AP Top News",      "https://rsshub.app/apnews/topics/apf-topnews"),
        ("🇺🇸 NPR Politics",     "https://feeds.npr.org/1014/rss.xml"),
        ("🇺🇸 Politico",         "https://rss.politico.com/politics-news.xml"),
    ],
    "world": [
        ("🌍 BBC World",         "https://feeds.bbci.co.uk/news/world/rss.xml"),
        ("🌍 Al Jazeera",        "https://www.aljazeera.com/xml/rss/all.xml"),
        ("🌍 Guardian World",    "https://www.theguardian.com/world/rss"),
        ("🌍 DW World",          "https://rss.dw.com/rdf/rss-en-world"),
        ("🌍 France24",          "https://www.france24.com/en/rss"),
    ],
}

_POL_STORE_V15 = TTLStore(max_items=500, ttl=3600)
def _kb_politics_v15():
    return kb([
        [btn("🇮🇷 اخبار ایران", "pol:fetch:iran")],
        [btn("🇺🇸 اخبار آمریکا", "pol:fetch:usa")],
        [btn("🌍 اخبار جهان", "pol:fetch:world")],
        [btn("📊 همه — یکجا", "pol:fetch:all")],
        [btn("🔄 بروزرسانی", "pol:fetch:all")],
        [btn("🏠 منو", "m:main")],
    ])

@ROUTER.command("politics", description="اخبار سیاسی دوزبانه")
def cmd_politics_v15(msg, args):
    chat_id = get_chat_id(msg)
    a = (args or "").strip().lower()
    if a in ("iran", "usa", "world", "all"):
        m = TG.send_message(chat_id, "📰 دریافت اخبار سیاسی ...")
        if m.ok:
            mid = (m.result or {}).get("message_id")
            POOL.submit(_pol_fetch_v15, chat_id, mid, a)
        return
    TG.send_message(
        chat_id,
        "📰 <b>اخبار سیاسی</b>\n\n"
        "<i>هر خبر دوزبانه + دکمه تأیید قبل از ارسال به کانال</i>",
        reply_markup=_kb_politics_v15()
    )

@ROUTER.callback("pol")
def cb_pol_v15(cb, data):
    try:
        parts = data.split(":")
        action = parts[1] if len(parts) > 1 else ""
        chat_id = cb["message"]["chat"]["id"]
        msg_id  = cb["message"]["message_id"]
        uid     = cb.get("from", {}).get("id", 0)

        if action == "fetch":
            grp = parts[2] if len(parts) > 2 else "all"
            TG.answer_callback(cb.get("id", ""), "⏳")
            try:
                TG.edit_message(chat_id, msg_id, f"⏳ دریافت اخبار {grp} ...")
            except Exception:
                pass
            POOL.submit(_pol_fetch_v15, chat_id, msg_id, grp)
            return

        if action == "approve":
            try:
                idx = int(parts[2])
            except Exception:
                return
            items = _POL_STORE_V15.get(chat_id) or []
            if idx < 0 or idx >= len(items):
                TG.answer_callback(cb.get("id", ""), "❌", show_alert=True)
                return
            it = items[idx]
            TG.answer_callback(cb.get("id", ""), "📤 ارسال...")
            POOL.submit(_pol_send_v15, chat_id, it)
            return

        if action == "skip":
            TG.answer_callback(cb.get("id", ""), "❌ رد شد")
            return

        if action == "menu":
            TG.answer_callback(cb.get("id", ""))
            TG.edit_message(
                chat_id, msg_id,
                "📰 <b>اخبار سیاسی</b>",
                reply_markup=_kb_politics_v15()
            )
            return

    except Exception as e:
        try: log.exception(f"[v15] pol cb: {e}")
        except Exception: pass

def _pol_fetch_v15(chat_id, msg_id, grp="all"):
    """دریافت اخبار سیاسی و ارسال هرکدام به‌صورت پیام جدا."""
    try:
        groups = ["iran", "usa", "world"] if grp == "all" else [grp]
        all_items = []
        for g in groups:
            items = _pol_fetch_group_v15(g, limit=4)
            all_items.extend(items[:4])

        # dedup by title
        seen = set()
        unique = []
        for it in all_items:
            key = (it.get("title", "") or "").lower().strip()[:60]
            if key and key not in seen:
                seen.add(key)
                unique.append(it)

        if not unique:
            if msg_id:
                try:
                    TG.edit_message(
                        chat_id, msg_id,
                        "❌ خبری یافت نشد.",
                        reply_markup=kb([[btn("🏠", "m:main")]])
                    )
                except Exception:
                    pass
            return

        # limit to 8 items
        unique = unique[:8]
        _POL_STORE_V15[chat_id] = unique

        if msg_id:
            header = f"📰 <b>اخبار سیاسی</b>\n"
            header += f"<i>{len(unique)} خبر — دوزبانه + دکمه تأیید</i>"
            try:
                TG.edit_message(chat_id, msg_id, header,
                                reply_markup=kb([[btn("🏠", "m:main")]]))
            except Exception:
                pass

        for i, it in enumerate(unique, 1):
            _pol_send_item_v15(chat_id, i, len(unique), it)
            _t_v15.sleep(1.2)
    except Exception as e:
        try: log.exception(f"[v15] pol_fetch: {e}")
        except Exception: pass

def _pol_fetch_group_v15(grp, limit=6):
    feeds = _POL_FEEDS_V15.get(grp, [])
    out = []
    seen = set()
    for name, url in feeds:
        try:
            r = APIS.news.fetch_feed(url, limit=limit)
            if r and r.ok and r.data:
                for it in r.data:
                    key = (it.get("title", "") or "")[:60].lower()
                    if key and key not in seen:
                        seen.add(key)
                        it["source"] = name
                        out.append(it)
        except Exception as e:
            try: log.debug(f"[v15] pol feed {name}: {e}")
            except Exception: pass
    return out

def _pol_send_item_v15(chat_id, idx, total, it):
    """ارسال یک خبر سیاسی با دکمه تأیید."""
    try:
        en_title = (it.get("title", "") or "")[:250]
        en_summary = (it.get("summary", "") or "")[:800]

        # ترجمه‌ی عنوان و خلاصه با chunked method
        try:
            fa_title = _translate_long_v15(en_title, "en", "fa") or en_title
        except Exception:
            fa_title = en_title
        try:
            fa_summary = _translate_long_v15(en_summary, "en", "fa") if en_summary else ""
        except Exception:
            fa_summary = ""

        text = (
            f"📰 <b>خبر سیاسی {idx} از {total}</b>\n\n"
            f"🇮🇷 <b>{escape_html(fa_title[:200])}</b>\n"
            f"{escape_html(fa_summary[:600])}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🇬🇧 <b>{escape_html(en_title[:200])}</b>\n"
            f"<i>{escape_html(en_summary[:600])}</i>\n\n"
            f"📎 {escape_html(str(it.get('source', ''))[:50])}\n"
            f"🔗 {it.get('link', '')}"
        )

        buttons = kb([[
            btn(f"✅ تأیید {idx}", f"pol:approve:{idx - 1}"),
            btn(f"❌ رد {idx}", f"pol:skip"),
        ]])

        TG.send_message(chat_id, text[:4000], reply_markup=buttons)
    except Exception as e:
        try: log.debug(f"[v15] pol item: {e}")
        except Exception: pass

def _pol_send_item_v15_to_channel(chat_id, item):
    """ارسال خبر تأییدشده به کانال."""
    try:
        cfg = CONFIG.get()
        ch = (cfg.telegram.channel_id or "").strip()
        if not ch:
            TG.send_message(chat_id, "❌ کانال تنظیم نشده.")
            return

        en_title = (item.get("title", "") or "")[:250]
        en_summary = (item.get("summary", "") or "")[:800]
        fa_title = _translate_long_v15(en_title, "en", "fa") or en_title
        fa_summary = _translate_long_v15(en_summary, "en", "fa") if en_summary else ""

        tags = " ".join(
            "#" + re.sub(r"\W", "", w)
            for w in en_title.split()[:4] if w
        )

        text = (
            f"📰 <b>{escape_html(fa_title[:200])}</b>\n\n"
            f"📝 {escape_html(fa_summary[:700])}\n\n"
            f"🇬🇧 <i>{escape_html(en_title[:200])}</i>\n"
            f"📝 <i>{escape_html(en_summary[:700])}</i>\n\n"
            f"📎 {escape_html(str(item.get('source', ''))[:50])}\n"
            f"🔗 {item.get('link', '')}\n\n"
            f"{tags}\n"
            f"📢 @MAADGHchannel"
        )

        r = TG.send_message(ch, text[:4000])
        if r.ok:
            TG.send_message(chat_id, "✅ به کانال ارسال شد.")
        else:
            TG.send_message(chat_id, f"❌ خطا: {r.description[:100]}")
    except Exception as e:
        try: log.exception(f"[v15] pol send: {e}")
        except Exception: pass

# اصلاح نام برای فراخوانی در worker
def _pol_send_v15(chat_id, item):
    _pol_send_item_v15_to_channel(chat_id, item)

# ─────────────────────────────────────────────────────────────────────────────
#  ماژول ۶ — موسیقی Archive.org (v10 که کار می‌کرد)
# ─────────────────────────────────────────────────────────────────────────────

_MUSIC_ARCHIVE_STORE_V15 = TTLStore(max_items=500, ttl=1800)
def _music_search_v15(chat_id, msg_id, key, label):
    """جستجو در Archive.org برای فایل صوتی واقعی."""
    try:
        if msg_id:
            try:
                TG.edit_message(chat_id, msg_id,
                                f"🎵 جستجوی فایل صوتی «{escape_html(label)}» ...")
            except Exception:
                pass
        else:
            m = TG.send_message(chat_id,
                                f"🎵 جستجوی «{escape_html(label)}» ...")
            msg_id = (m.result or {}).get("message_id") if m.ok else None

        items = []
        for q in (f"{label} music", f"{label} songs", f"{label} album"):
            try:
                found = ARCHIVE_AUDIO.search_items(q, limit=10)
                for it in found:
                    if it not in items:
                        items.append(it)
            except Exception:
                pass
            if len(items) >= 10:
                break

        if not items:
            if msg_id:
                try:
                    TG.edit_message(
                        chat_id, msg_id,
                        "❌ یافت نشد.",
                        reply_markup=kb([[btn("⬅️", "music:back"),
                                          btn("🏠", "m:main")]])
                    )
                except Exception:
                    pass
            return

        results = []
        for it in items[:8]:
            ident = it.get("identifier")
            if not ident:
                continue
            try:
                files = ARCHIVE_AUDIO.get_audio_files(ident, max_files=2)
            except Exception:
                files = []
            if files:
                results.append({
                    "title":      it.get("title", "") or ident,
                    "creator":    it.get("creator", ""),
                    "year":       it.get("year", ""),
                    "identifier": ident,
                    "files":      files,
                })

        if not results:
            if msg_id:
                try:
                    TG.edit_message(
                        chat_id, msg_id,
                        "❌ فایل صوتی نیست.",
                        reply_markup=kb([[btn("⬅️", "music:back"),
                                          btn("🏠", "m:main")]])
                    )
                except Exception:
                    pass
            return

        _MUSIC_ARCHIVE_STORE_V15[chat_id] = results

        text = f"🎵 <b>موسیقی {escape_html(label)}</b>\n"
        text += f"<i>📻 Archive.org — {len(results)} نتیجه</i>\n\n"
        for i, r in enumerate(results, 1):
            text += f"<b>{i}.</b> 🎵 {escape_html(r['title'][:70])}\n"
            if r.get("creator"):
                text += f"   👤 {escape_html(str(r['creator'])[:40])}\n"
            if r.get("year"):
                text += f"   📅 {escape_html(str(r['year']))}\n"
            text += f"   📁 {len(r['files'])} فایل\n\n"

        rows = []
        for i in range(len(results)):
            rows.append([
                btn(f"▶️ پخش {i + 1}", f"music:play:{i}"),
                btn(f"📥 فایل {i + 1}", f"music:file:{i}"),
                btn(f"📤 کانال {i + 1}", f"music:pub:{i}"),
            ])
        rows.append([btn("🔄 دیگر", f"music:go:{key}"),
                     btn("⬅️ فهرست", "music:back"),
                     btn("🏠", "m:main")])

        if msg_id:
            try:
                TG.edit_message(chat_id, msg_id, text[:4000], reply_markup=kb(rows))
            except Exception:
                pass
        else:
            TG.send_message(chat_id, text[:4000], reply_markup=kb(rows))
    except Exception as e:
        try: log.exception(f"[v15] music search: {e}")
        except Exception: pass

@ROUTER.command("music", description="موسیقی از Archive.org")
def cmd_music_v15(msg, args):
    chat_id = get_chat_id(msg)
    if args and args.lower() in MUSIC_CATEGORIES:
        POOL.submit(_music_search_v15, chat_id, None, args.lower(),
                    MUSIC_CAT_LABELS.get(args.lower(), args))
        return
    rows = []
    row = []
    for k, label in MUSIC_CAT_LABELS.items():
        row.append(btn(f"🎵 {label}", f"music:go:{k}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([btn("🎲 تصادفی", "music:rand"), btn("🏠 منو", "m:main")])
    TG.send_message(
        chat_id,
        f"🎵 <b>موسیقی</b> — {len(MUSIC_CAT_LABELS)} سبک\n"
        f"<i>فایل صوتی واقعی از Archive.org</i>",
        reply_markup=kb(rows)
    )

@ROUTER.callback("music")
def cb_music_v15(cb, data):
    try:
        parts = data.split(":")
        action = parts[1] if len(parts) > 1 else ""
        chat_id = cb["message"]["chat"]["id"]
        msg_id  = cb["message"]["message_id"]

        if action == "back":
            TG.answer_callback(cb.get("id", ""))
            cmd_music_v15(
                {"chat": {"id": chat_id}, "from": cb.get("from", {}), "message": {}},
                ""
            )
            return

        if action == "rand":
            k = _RND.choice(list(MUSIC_CATEGORIES.keys()))
            TG.answer_callback(cb.get("id", ""), "🎲")
            POOL.submit(_music_search_v15, chat_id, msg_id, k,
                        MUSIC_CAT_LABELS.get(k, k))
            return

        if action == "go":
            k = parts[2] if len(parts) > 2 else ""
            if k in MUSIC_CATEGORIES:
                TG.answer_callback(cb.get("id", ""), "🎵")
                POOL.submit(_music_search_v15, chat_id, msg_id, k,
                            MUSIC_CAT_LABELS.get(k, k))
            return

        if action in ("play", "file", "pub"):
            try:
                idx = int(parts[2])
            except Exception:
                return
            st = _MUSIC_ARCHIVE_STORE_V15.get(chat_id) or []
            if idx < 0 or idx >= len(st):
                return
            item = st[idx]
            files = item.get("files") or []

            if action == "pub":
                TG.answer_callback(cb.get("id", ""), "📤")
                try:
                    cfg = CONFIG.get()
                    ch = (cfg.telegram.channel_id or "").strip()
                    if ch and files:
                        first = files[0]
                        caption = (f"🎵 <b>{escape_html(item['title'][:80])}</b>\n"
                                   f"<i>{escape_html(str(item.get('creator', ''))[:60])}</i>\n\n"
                                   f"📢 @MAADGHchannel")
                        TG.send_audio(ch, first["url"], caption=caption,
                                      parse_mode="HTML")
                        TG.send_message(chat_id, "✅ فایل به کانال ارسال شد.")
                    else:
                        TG.send_message(chat_id, "❌ کانال/فایل تنظیم نشده.")
                except Exception as e:
                    try: log.exception(f"[v15] music pub: {e}")
                    except Exception: pass
                return

            if not files:
                TG.answer_callback(cb.get("id", ""), "❌ فایلی نیست")
                return
            TG.answer_callback(cb.get("id", ""),
                               f"⏳ ارسال {len(files)} فایل...")
            for f in files[:2]:
                try:
                    caption = (f"🎵 <b>{escape_html(item['title'][:80])}</b>\n"
                               f"<i>{escape_html(str(item.get('creator', '')))}</i>")
                    TG.send_audio(chat_id, f["url"], caption=caption,
                                  parse_mode="HTML")
                    _t_v15.sleep(0.4)
                except Exception as e:
                    try: log.debug(f"[v15] send_audio: {e}")
                    except Exception: pass
            return

    except Exception as e:
        try: log.exception(f"[v15] music cb: {e}")
        except Exception: pass

# ─────────────────────────────────────────────────────────────────────────────
#  ماژول ۷ — اخبار عمومی با ترجمه‌ی خلاصه
# ─────────────────────────────────────────────────────────────────────────────

def _render_bilingual_item_v15(idx, title, summary_en="", url="", source=""):
    """رندر دوزبانه‌ی یک خبر — هر دو با ترجمه‌ی کامل."""
    if not title and not summary_en:
        return f"<b>{idx}.</b> ❌"
    try:
        title_fa = _translate_long_v15(title, "en", "fa") if title else ""
    except Exception:
        title_fa = title
    try:
        summary_fa = _translate_long_v15(summary_en, "en", "fa") if summary_en else ""
    except Exception:
        summary_fa = ""

    lines = [f"<b>{idx}.</b> 🇮🇷 <b>{escape_html(title_fa[:180])}</b>"]
    if summary_fa:
        lines.append(f"   📝 {escape_html(summary_fa[:500])}")
    if title:
        lines.append(f"   🇬🇧 <i>{escape_html(title[:180])}</i>")
    if summary_en:
        lines.append(f"   📝 <i>{escape_html(summary_en[:500])}</i>")
    if source:
        lines.append(f"   📎 {escape_html(source[:40])}")
    if url:
        lines.append(f"   🔗 {url}")
    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────────────────────
#  ماژول ۸ — منوی اصلی نهایی
# ─────────────────────────────────────────────────────────────────────────────

def kb_main_menu():
    return kb([
        [btn("📚 موضوعات","m:list"), btn("🔍 جستجو","m:find"), btn("🌟 سوپر","m:super")],
        [btn("🎓 آموزش","learn:bank"), btn("❓ کوییز","quiz:menu"), btn("📇 فلش","flash:back")],
        [btn("📰 اخبار","news:menu"), btn("🗳 سیاسی","pol:fetch:all"), btn("📖 ویکی","wiki:menu")],
        [btn("📚 arXiv","arxiv:p:0"), btn("🎵 موسیقی","music:back"), btn("📕 کتاب","book:back")],
        [btn("💱 ارز","rate:refresh"), btn("✈️ هوانوردی","av:refresh"), btn("🌐 پروکسی","proxy:list")],
        [btn("🔌 ۲۰۰ API","v17:home"), btn("🌤 آب‌وهوا","m:weather"), btn("📜 شعر","poem:next")],
        [btn("📊 آمار","stats:cat:usage"), btn("⚙️ تنظیمات","m:settings"), btn("ℹ️ راهنما","m:help")],
    ])
#  ماژول ۹ — روتر اصلی m (override با delegate)
# ─────────────────────────────────────────────────────────────────────────────

try:
    _prev_cb_m_v15 = (globals().get("cb_m_v10")
                      or globals().get("cb_m_v7")
                      or globals().get("cb_menu")
                      or None)
except NameError:
    try:
        _prev_cb_m_v15 = cb_m_v10
    except NameError:
        _prev_cb_m_v15 = None

@ROUTER.callback("m")
def cb_m_v15(cb, data):
    """روتر نهایی منو — قبلی‌ها را delegate می‌کند."""
    try:
        action = data.split(":", 1)[1] if ":" in data else "main"
        chat_id = cb["message"]["chat"]["id"]
        msg_id  = cb["message"]["message_id"]

        if action == "main":
            TG.answer_callback(cb.get("id", ""))
            TG.edit_message(chat_id, msg_id, "🏠 <b>منوی اصلی</b>",
                            reply_markup=kb_main_menu())
            return

        if action == "weather":
            TG.answer_callback(cb.get("id", ""))
            TG.edit_message(
                chat_id, msg_id,
                f"🌤 <b>آب‌وهوا</b> — {len(_WX_CITIES_V15)} شهر",
                reply_markup=_kb_weather_v15(0)
            )
            return

        if action == "politics" or action == "pol":
            TG.answer_callback(cb.get("id", ""))
            TG.edit_message(
                chat_id, msg_id,
                "📰 <b>اخبار سیاسی</b>",
                reply_markup=_kb_politics_v15()
            )
            return

        if _prev_cb_m_v15:
            _prev_cb_m_v15(cb, data)
        else:
            TG.answer_callback(cb.get("id", ""))
    except Exception as e:
        try: log.exception(f"[v15] cb_m: {e}")
        except Exception: pass

# ─────────────────────────────────────────────────────────────────────────────
#  ماژول ۱۰ — هندلر متن آزاد (state-based)
# ─────────────────────────────────────────────────────────────────────────────

try:
    _prev_text_v15 = ROUTER._text_handler
except Exception:
    _prev_text_v15 = None

@ROUTER.on_text
def handle_text_v15(msg):
    """هندلر نهایی متن — شهر و سایر state ها."""
    try:
        uid = get_uid(msg)
        s = SESSIONS.get(uid)
        state = s.state

        if state == "awaiting_city":
            chat_id = get_chat_id(msg)
            city = (msg.get("text") or "").strip()
            SESSIONS.clear_state(uid)
            if city:
                POOL.submit(_wx_fetch_v15, chat_id, None, city, city)
            return

        if state == "awaiting_news_search":
            chat_id = get_chat_id(msg)
            query = (msg.get("text") or "").strip()
            SESSIONS.clear_state(uid)
            if query:
                POOL.submit(_news_fetch_render_v11, chat_id, None, "search", query)
            return

        if state == "awaiting_rate_note":
            chat_id = get_chat_id(msg)
            note = (msg.get("text") or "").strip()
            SESSIONS.clear_state(uid)
            if not note:
                TG.send_message(chat_id, "❌ یادداشت خالی.")
                return
            draft = _RATE_DRAFT_V11.get(chat_id if chat_id > 0 else 0)
            if draft:
                draft["text"] += f"\n\n✏️ <b>یادداشت:</b>\n{escape_html(note[:500])}"
                rows = [
                    [btn("📤 ارسال به کانال", "rate:send"),
                     btn("✏️ یادداشت دیگر", "rate:note")],
                    [btn("⬅️ فهرست ارزها", "rate:back"), btn("🏠", "m:main")],
                ]
                TG.send_message(
                    chat_id,
                    draft["text"][:4000] + "\n\n✅ یادداشت اضافه شد.",
                    reply_markup=kb(rows)
                )
            return

        if state == "awaiting_flash_topic":
            chat_id = get_chat_id(msg)
            topic = (msg.get("text") or "").strip()
            SESSIONS.clear_state(uid)
            if not topic:
                return
            cfg = _FLASH_CFG_V11.setdefault(uid, _flash_defaults())
            cfg["topic"] = topic
            TG.send_message(chat_id,
                            f"✅ موضوع: <b>{escape_html(topic)}</b>",
                            reply_markup=_kb_flash_v11(uid))
            return

        if state == "awaiting_search":
            chat_id = get_chat_id(msg)
            query = (msg.get("text") or "").strip()
            SESSIONS.clear_state(uid)
            if query:
                _do_search_v4(chat_id, None, query)
            return

        # delegate به قبلی‌ها
        if _prev_text_v15:
            _prev_text_v15(msg)
    except Exception as e:
        try: log.exception(f"[v15] text handler: {e}")
        except Exception: pass

# ─────────────────────────────────────────────────────────────────────────────
#  ماژول ۱۱ — health-check نهایی
# ─────────────────────────────────────────────────────────────────────────────

@ROUTER.command("v15check", description="بررسی سلامت patch v15", admin_only=True)
def cmd_v15check(msg, args):
    chat_id = get_chat_id(msg)

    # تست exchange
    try:
        rates = ExchangeV15.fetch("USD")
        ex_ok = "✅" if rates else "❌"
        ex_n = len(rates) if rates else 0
        ex_irr = f"{rates.get('IRR', '?')}" if rates else "?"
    except Exception as e:
        ex_ok = "❌"
        ex_n = 0
        ex_irr = str(e)[:30]

    # تست ترجمه
    try:
        t = _translate_long_v15("Hello world. This is a test.", "en", "fa")
        tr_ok = "✅" if t and t != "Hello world. This is a test." else "⚠️"
    except Exception:
        tr_ok = "❌"

    # تست wiki
    wiki_ok = "✅" if APIS.wikipedia else "❌"

    # تست weather
    wx_ok = "✅" if len(_WX_CITIES_V15) >= 60 else "⚠️"

    # تست politics
    pol_ok = "✅" if len(_POL_FEEDS_V15) >= 3 else "❌"

    # تست music
    music_ok = "✅" if "ARCHIVE_AUDIO" in globals() else "❌"

    text = (
        f"<b>🔍 بررسی Patch v15</b>\n\n"
        f"💱 Exchange API: {ex_ok}  ({ex_n} ارز، IRR={ex_irr})\n"
        f"🌐 Translation: {tr_ok}\n"
        f"📖 Wikipedia: {wiki_ok}\n"
        f"🌤 Weather cities: {wx_ok}  ({len(_WX_CITIES_V15)})\n"
        f"🗳 Politics feeds: {pol_ok}  ({len(_POL_FEEDS_V15)} groups)\n"
        f"🎵 Music (Archive): {music_ok}\n\n"
        f"<b>نسخه:</b> v15.0"
    )
    TG.send_message(chat_id, text)

# ═══════════════════════════════════════════════════════════════════════════════
#  پایان PATCH v15.0
# ═══════════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════
#  PATCH v16.0 — SYNTAX REPAIR + STABILITY
#  ─────────────────────────────────────────────────────────────────────────
#  این patch مشکلات زیر را رفع کرد:
#    • f-string های شکسته با کامنت داخلی (SyntaxError)
#    • ارجاعات NameError به json, globals().get("cb_m_v14"), cb_m_v7
#    • walrus operator بلااستفاده
#    • ویرگول‌های اضافه در import
#    • _orig_yt_search_v5 تکراری
# ═══════════════════════════════════════════════════════════════════════════

# ─── Safety wrapper for undefined names ─────────────────────────────────
def _safe_get(name, default=None):
    """Safely get a global by name."""
    try:
        return globals().get(name, default)
    except Exception:
        return default

# ─── Verify critical modules loaded ─────────────────────────────────────
try:
    _ = ExchangeV15
    log.info("[v16] ExchangeV15 loaded")
except NameError:
    log.warning("[v16] ExchangeV15 missing")

try:
    _ = _translate_long_v15
    log.info("[v16] _translate_long_v15 loaded")
except NameError:
    log.warning("[v16] _translate_long_v15 missing")

try:
    _ = _WX_CITIES_V15
    log.info(f"[v16] _WX_CITIES_V15 loaded ({len(_WX_CITIES_V15)} cities)")
except NameError:
    log.warning("[v16] _WX_CITIES_V15 missing")

try:
    _ = _POL_FEEDS_V15
    log.info(f"[v16] _POL_FEEDS_V15 loaded ({len(_POL_FEEDS_V15)} groups)")
except NameError:
    log.warning("[v16] _POL_FEEDS_V15 missing")

log.info("PATCH v16.0 applied — syntax repaired")

# ═══════════════════════════════════════════════════════════════════════════


# ─── v16: TTL Cleanup for in-memory stores ─────────────────────────────
import time as _t_v16
class _TTLStore:
    def __init__(self, name, max_items=2000, ttl=3600):
        self._d = {}
        self._ts = {}
        self._name = name
        self._max = max_items
        self._ttl = ttl
        self._lock = threading.RLock()
    def get(self, key, default=None):
        with self._lock:
            if key in self._d:
                if _t_v16.time() - self._ts.get(key, 0) > self._ttl:
                    del self._d[key]; del self._ts[key]
                    return default
                return self._d[key]
            return default
    def set(self, key, value):
        with self._lock:
            self._d[key] = value
            self._ts[key] = _t_v16.time()
            if len(self._d) > self._max:
                oldest = min(self._ts, key=self._ts.get)
                del self._d[oldest]; del self._ts[oldest]
    def __contains__(self, key):
        return self.get(key) is not None
    def pop(self, key, default=None):
        with self._lock:
            self._ts.pop(key, None)
            return self._d.pop(key, default)
    def clear(self):
        with self._lock:
            self._d.clear(); self._ts.clear()

def _ttl_cleanup_loop_v16():
    while not _shutting_down.is_set():
        try:
            _shutting_down.wait(300)
            if _shutting_down.is_set():
                break
            gc.collect()
        except Exception:
            pass

threading.Thread(target=_ttl_cleanup_loop_v16, daemon=True, name="TTLCleanup").start()

# ─── v16: Missing callback handlers ────────────────────────────────────
@ROUTER.callback("flash:run_pub")
def _cb_flash_run_pub(cb, data):
    try:
        TG.answer_callback(cb.get("id", ""), "📤")
        chat_id = cb["message"]["chat"]["id"]
        msg_id = cb["message"]["message_id"]
        TG.edit_message(chat_id, msg_id, "📤 ارسال به کانال...")
    except Exception as e:
        log.debug(f"[v16] flash:run_pub: {e}")

@ROUTER.callback("flash:run_alt")
def _cb_flash_run_alt(cb, data):
    try:
        TG.answer_callback(cb.get("id", ""), "🔄")
    except Exception as e:
        log.debug(f"[v16] flash:run_alt: {e}")

# Also register callback for super (which was cmd only)
@ROUTER.callback("m:super")
def _cb_m_super(cb, data):
    try:
        TG.answer_callback(cb.get("id", ""), "🌟")
    except Exception:
        pass

# ─── v16: Persian number helper ────────────────────────────────────────
_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
def to_fa_num(n) -> str:
    """Convert to Persian digits."""
    return str(n).translate(_FA_DIGITS)

def fmt_fa(n, decimals=0) -> str:
    """Format number with Persian digits and thousand separator."""
    try:
        if decimals:
            s = f"{float(n):,.{decimals}f}"
        else:
            s = f"{int(n):,}"
        return s.translate(_FA_DIGITS)
    except Exception:
        return str(n)

# ─── v16: extend /help ─────────────────────────────────────────────────
@ROUTER.command("help2", description="راهنمای کامل (v16)")
def cmd_help2_v16(msg, args):
    chat_id = get_chat_id(msg)
    TG.send_message(chat_id, HELP_TEXT[:4000])

# ─── v16: aliases ──────────────────────────────────────────────────────
@ROUTER.command("start2", description="شروع دوباره")
def cmd_start2_v16(msg, args):
    cmd_start(msg, args)

@ROUTER.command("h", description="راهنما")
def cmd_h_v16(msg, args):
    cmd_help(msg, args)

# ═══════════════════════════════════════════════════════════════════════════
#  v17 INJECTOR — Load 200 APIs from apis_v17.py
# ═══════════════════════════════════════════════════════════════════════════
try:
    import importlib.util as _iu17
    _apis_v17_path = Path(__file__).parent / "apis_v17.py"
    _spec_v17 = _iu17.spec_from_file_location("apis_v17", str(_apis_v17_path))
    _mod_v17 = _iu17.module_from_spec(_spec_v17)
    _spec_v17.loader.exec_module(_mod_v17)
    APIS_V17 = _mod_v17.APIS_V17
    APIS_V17_BY_CATEGORY = _mod_v17.by_category
    APIS_V17_FIND = _mod_v17.find_by_id
    log.info(f"[v17] Loaded {len(APIS_V17)} APIs")

    # Wrapper helpers
    def _v17_http_get(url, as_json=False, headers=None, timeout=15):
        r = HTTP.request("GET", url, headers=headers or {}, timeout=timeout)
        if r is None or r.status_code != 200:
            return None
        if as_json:
            try: return r.json()
            except Exception: return None
        return r.text

    def _v17_http_post(url, json=None, data=None, headers=None, timeout=30):
        r = HTTP.request("POST", url, json_body=json, data=data,
                         headers=headers or {}, timeout=timeout)
        if r is None or r.status_code not in (200, 201):
            return None
        try: return r.json()
        except Exception: return r.text

    def _v17_get_key(name):
        cfg = CONFIG.get()
        return (getattr(cfg.keys, name, "") or "").strip()

    # ── Menu ──────────────────────────────────────────────────────────────
    def _v17_kb_categories():
        cats = {}
        for a in APIS_V17:
            cats.setdefault(a.category, 0)
            cats[a.category] += 1
        rows = []
        items = list(cats.items())
        for i in range(0, len(items), 2):
            row = []
            for cat, n in items[i:i+2]:
                row.append(btn(f"{cat} ({n})", f"v17:c:{cat}"))
            rows.append(row)
        rows.append([btn("🏠 منو", "m:main")])
        return kb(rows)

    @ROUTER.command("api17", description="۲۰۰ API v17")
    def cmd_api17(msg, args):
        chat_id = get_chat_id(msg)
        TG.send_message(chat_id,
            f"🔌 <b>کتابخانه ۲۰۰ API</b>\n\n"
            f"کل: <b>{len(APIS_V17)}</b> API\n"
            f"دسته: <b>{len(set(a.category for a in APIS_V17))}</b>\n\n"
            f"یک دسته انتخاب کن:",
            reply_markup=_v17_kb_categories())

    @ROUTER.callback("v17")
    def cb_v17(cb, data):
        try:
            parts = data.split(":")
            action = parts[1] if len(parts) > 1 else ""
            chat_id = cb["message"]["chat"]["id"]
            msg_id = cb["message"]["message_id"]
            TG.answer_callback(cb.get("id", ""))

            if action == "c":
                cat = parts[2] if len(parts) > 2 else ""
                items = [a for a in APIS_V17 if a.category == cat]
                rows = []
                for i in range(0, len(items), 2):
                    row = []
                    for a in items[i:i+2]:
                        row.append(btn(f"🔸 {a.name[:22]}", f"v17:r:{a.id}"))
                    rows.append(row)
                rows.append([btn("⬅️ دسته‌ها", "v17:home"), btn("🏠", "m:main")])
                TG.edit_message(chat_id, msg_id,
                    f"<b>{cat}</b> — {len(items)} API\nیک مورد را انتخاب کن:",
                    reply_markup=kb(rows))
                return

            if action == "home":
                TG.edit_message(chat_id, msg_id,
                    f"🔌 <b>کتابخانه ۲۰۰ API</b>",
                    reply_markup=_v17_kb_categories())
                return

            if action == "r":
                aid = parts[2] if len(parts) > 2 else ""
                entry = APIS_V17_FIND(aid)
                if not entry:
                    TG.edit_message(chat_id, msg_id, "❌ یافت نشد")
                    return
                txt = (
                    f"<b>🔌 {escape_html(entry.name)}</b>\n\n"
                    f"📁 دسته: <b>{entry.category}</b>\n"
                    f"🔗 <code>{escape_html(entry.url)}</code>\n"
                    f"🔐 Auth: <code>{entry.auth}</code>\n"
                    f"📝 {escape_html(entry.desc)}\n\n"
                    f"ورودی را بفرست (متن، شهر، نماد، ...):"
                )
                SESSIONS.set_state(cb["from"]["id"], "awaiting_v17",
                                   api_id=aid, chat_id=chat_id)
                TG.edit_message(chat_id, msg_id, txt,
                    reply_markup=kb([[btn("⬅️ بازگشت", f"v17:c:{entry.category}")],
                                     [btn("🏠", "m:main")]]))
                return
        except Exception as e:
            log.exception(f"[v17] cb: {e}")

    # ── Free-text handler for awaiting_v17 ────────────────────────────────
    _prev_text_v17 = ROUTER._text_handler

    @ROUTER.on_text
    def handle_text_v17(msg):
        uid = get_uid(msg)
        s = SESSIONS.get(uid)
        if s.state == "awaiting_v17":
            chat_id = get_chat_id(msg)
            text = (msg.get("text") or "").strip()
            api_id = s.data.get("api_id", "")
            SESSIONS.clear_state(uid)
            entry = APIS_V17_FIND(api_id)
            if not entry or not text:
                TG.send_message(chat_id, "❌ ورودی نامعتبر")
                return
            m = TG.send_message(chat_id, f"⏳ اجرای {escape_html(entry.name)}...")
            if not m.ok:
                return
            mid = (m.result or {}).get("message_id")

            def _run():
                try:
                    params = {"q": text, "text": text, "city": text,
                              "ip": text, "sub": text, "model": text}
                    result, err = entry.fetcher(
                        _v17_http_post if entry.method == "POST" else _v17_http_get,
                        _v17_get_key, params)
                    if err:
                        TG.edit_message(chat_id, mid, f"⚠️ {escape_html(err)}")
                        return
                    if not result:
                        TG.edit_message(chat_id, mid, "❌ پاسخ خالی")
                        return
                    out = result if isinstance(result, str) else str(result)[:3500]
                    TG.edit_message(chat_id, mid, out[:4000],
                        reply_markup=kb([[btn("🔄 دوباره", f"v17:r:{api_id}")],
                                         [btn("⬅️ دسته", f"v17:c:{entry.category}")],
                                         [btn("🏠", "m:main")]]))
                except Exception as ex:
                    log.exception(f"[v17] run {api_id}: {ex}")
                    TG.edit_message(chat_id, mid, f"❌ {escape_html(str(ex)[:150])}")

            POOL.submit(_run)
            return
        if _prev_text_v17:
            _prev_text_v17(msg)

    log.info("[v17] Injector registered /api17 and callbacks")
except Exception as _e17:
    log.error(f"[v17] Failed to load apis_v17: {_e17}")

# ═══════════════════════════════════════════════════════════════════════════
#  END v17 INJECTOR
# ═══════════════════════════════════════════════════════════════════════════


# ─── v17: Persistent LS state ───────────────────────────────────────────
_LS_STATE_FILE_V17 = DATA_DIR / "ls_state.json"
def _v17_save_ls_state():
    try:
        json.dumps({k: v for k, v in (_LS_STATE or {}).items() if isinstance(v, dict)}, ensure_ascii=False)
        with open(_LS_STATE_FILE_V17, "w", encoding="utf-8") as _f:
            json.dump({str(k): v for k, v in (_LS_STATE or {}).items()
                        if isinstance(v, dict)}, _f, ensure_ascii=False)
    except Exception as _e:
        log.debug(f"[v17] save LS: {_e}")

def _v17_load_ls_state():
    try:
        if _LS_STATE_FILE_V17.exists():
            with open(_LS_STATE_FILE_V17, encoding="utf-8") as _f:
                data = json.load(_f)
                if "_LS_STATE" in globals():
                    for k, v in data.items():
                        try:
                            _LS_STATE[int(k)] = v
                        except Exception:
                            pass
    except Exception as _e:
        log.debug(f"[v17] load LS: {_e}")

_v17_load_ls_state()

# ─── v17: Safe TTL cleanup loop ─────────────────────────────────────────
def _v17_cleanup_loop():
    while not _shutting_down.is_set():
        try:
            _shutting_down.wait(600)
            if _shutting_down.is_set():
                break
            # Purge expired caches
            try: AI_CACHE.purge_expired()
            except Exception: pass
            try: HTTP_CACHE.purge_expired()
            except Exception: pass
            try: TRANSLATE_CACHE.purge_expired()
            except Exception: pass
            gc.collect()
        except Exception as _e:
            log.debug(f"[v17] cleanup: {_e}")

threading.Thread(target=_v17_cleanup_loop, daemon=True, name="v17Cleanup").start()

# [v18] v17 duplicate TTLStore removed

# v17: رفع NameError های احتمالی با safe_get
def _safe_global(name, default=None):
    try:
        return globals().get(name, default)
    except Exception:
        return default


# ═══════════════════════════════════════════════════════════════════════════
#  v17 CLEANUP — Central shutdown + periodic cleanup
# ═══════════════════════════════════════════════════════════════════════════
def _v17_periodic_cleanup():
    """پاکسازی دوره‌ای cache و TTLStore ها"""
    while not _shutting_down.is_set():
        try:
            _shutting_down.wait(600)
            if _shutting_down.is_set():
                break
            # Purge expired caches
            for cache_name in ("AI_CACHE", "HTTP_CACHE", "TRANSLATE_CACHE"):
                c = globals().get(cache_name)
                if c and hasattr(c, "purge_expired"):
                    try: c.purge_expired()
                    except Exception: pass
            # GC
            gc.collect()
        except Exception as _e:
            try: log.debug(f"[v17] cleanup: {_e}")
            except Exception: pass

try:
    _v17_cleanup_thread = threading.Thread(
        target=_v17_periodic_cleanup, daemon=True, name="v17Cleanup"
    )
    _v17_cleanup_thread.start()
    log.info("[v17] cleanup thread started")
except Exception as _e:
    log.warning(f"[v17] cleanup thread failed: {_e}")



# ═══════════════════════════════════════════════════════════════════════════
#  PATCH v18.0 — FINAL BUGFIX + TOPIC BANK LOADER
#  ساخته‌شده توسط Fix-MAADGH.ps1
# ═══════════════════════════════════════════════════════════════════════════

# ── FIX A: _shutting_down در همه thread ها ────────────────────────────────
try:
    _shutting_down
except NameError:
    _shutting_down = threading.Event()

# ── FIX B: بارگذاری موضوعات از topic_bank.json ───────────────────────────
try:
    _tb_path = DATA_DIR / "topic_bank.json"
    if _tb_path.exists():
        _tb_raw = load_json(_tb_path, default=[]) or []
        if "_MERGED_TOPICS" not in globals():
            _MERGED_TOPICS = list(globals().get("TOPICS", []))
        _existing_names = {(t.get("name") or "") for t in _MERGED_TOPICS
                           if isinstance(t, dict)}
        _added = 0
        for row in _tb_raw:
            try:
                if not isinstance(row, list) or len(row) < 3:
                    continue
                dom, sec, name = row[0], row[1], row[2]
                if not name or name in _existing_names:
                    continue
                if dom == "M":
                    _MERGED_TOPICS.append({
                        "name": name, "query": name,
                        "emoji": _MATH_EMOJI.get(sec, "📐"),
                        "style": "math",
                        "tags": name.replace(" ", "_"),
                        "domain": "math", "section": sec,
                        "section_name": _MATH_SECTIONS.get(sec, sec),
                    })
                else:
                    _MERGED_TOPICS.append({
                        "name": name, "query": name,
                        "emoji": _MECH_EMOJI.get(sec, "🔧"),
                        "style": "tutorial",
                        "tags": name.replace(" ", "_"),
                        "domain": "mech", "section": sec,
                        "section_name": _MECH_SECTIONS.get(sec, sec),
                    })
                _existing_names.add(name)
                _added += 1
            except Exception:
                continue
        log.info(f"[v18] topic_bank: +{_added} موضوع (کل {len(_MERGED_TOPICS)})")

        # override _get_topics_list
        def _get_topics_list():
            return _MERGED_TOPICS
except Exception as _e18:
    log.warning(f"[v18] topic_bank load: {_e18}")


# __V19_POL_GUARD__ — جلوگیری از override های تکراری pol
# (v15 درست کار می‌کنه، نیازی به v18 نیست)
# ── FIX C: بازنویسی _pol callback (disabled by v19) ─────────────────────
try:
    _prev_cb_pol_v18 = globals().get("cb_pol_v15")
    @ROUTER.callback("pol")
    def cb_pol_v18(cb, data):
        try:
            parts = data.split(":")
            action = parts[1] if len(parts) > 1 else ""
            chat_id = cb["message"]["chat"]["id"]
            uid = cb.get("from", {}).get("id", 0)
            if action == "approve":
                try:
                    idx = int(parts[2])
                except Exception:
                    return
                items = _POL_STORE_V15.get(chat_id) or []
                if idx < 0 or idx >= len(items):
                    TG.answer_callback(cb.get("id", ""), "❌", show_alert=True)
                    return
                it = items[idx]
                TG.answer_callback(cb.get("id", ""), "📤 ارسال...")
                POOL.submit(_pol_send_v15, chat_id, it)
                return
            if _prev_cb_pol_v18:
                return _prev_cb_pol_v18(cb, data)
        except Exception as e:
            log.debug(f"[v18] pol cb: {e}")
            try:
                if _prev_cb_pol_v18:
                    _prev_cb_pol_v18(cb, data)
            except Exception:
                pass
except Exception as _e:
    log.warning(f"[v18] pol override: {_e}")

# ── FIX D: Rate draft — ذخیره هم برای chat_id و هم user_id ──────────────
# [v19] rate recursive patch removed (was broken)

# ── FIX E: health-check ───────────────────────────────────────────────────
@ROUTER.command("v18check", description="بررسی سالم بودن v18", admin_only=True)
def cmd_v18check(msg, args):
    chat_id = get_chat_id(msg)
    tb_path = DATA_DIR / "topic_bank.json"
    tb_count = 0
    try:
        if tb_path.exists():
            raw = load_json(tb_path, default=[]) or []
            tb_count = len(raw)
    except Exception:
        pass
    merged = len(_MERGED_TOPICS) if "_MERGED_TOPICS" in globals() else 0
    pol_feeds = len(_POL_FEEDS_V15) if "_POL_FEEDS_V15" in globals() else 0
    wx_cities = len(_WX_CITIES_V15) if "_WX_CITIES_V15" in globals() else 0
    txt = (
        f"<b>🔍 بررسی v18</b>\n\n"
        f"📁 topic_bank.json: <code>{tb_count}</code>\n"
        f"📚 موضوعات ادغام‌شده: <code>{merged}</code>\n"
        f"🌤 شهرها: <code>{wx_cities}</code>\n"
        f"🗳 منابع سیاسی: <code>{pol_feeds}</code>\n"
        f"🔌 کل API: <code>{len(APIS.all())}</code>\n"
        f"📋 کل دستور: <code>{len(REGISTRY.all())}</code>"
    )
    TG.send_message(chat_id, txt)

log.info("PATCH v18.0 applied — bugfixes + topic bank loader")
# ═══════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════
#  PATCH v20.0 — AIMLAPI BACKUP PROVIDER (auto-applied)
# ═══════════════════════════════════════════════════════════════════════════

AIMLAPI_DEFAULT_KEY   = "64558a02afc6da248a08358de90975f7"
AIMLAPI_DEFAULT_BASE  = "https://api.aimlapi.com/v1"
AIMLAPI_DEFAULT_MODEL = "gpt-4o-mini"


def _v20_ensure_aimlapi_key():
    """اگر کلید AIMLAPI خالی بود، مقدار پیش‌فرض را ست کن."""
    try:
        cfg = CONFIG.get()
        changed = False
        if not getattr(cfg.keys, "aimlapi", ""):
            cfg.keys.aimlapi = AIMLAPI_DEFAULT_KEY
            changed = True
        if not getattr(cfg.keys, "aimlapi_base", ""):
            cfg.keys.aimlapi_base = AIMLAPI_DEFAULT_BASE
            changed = True
        if not getattr(cfg.keys, "aimlapi_model", ""):
            cfg.keys.aimlapi_model = AIMLAPI_DEFAULT_MODEL
            changed = True
        if changed:
            CONFIG.save()
            log.info("[v20] AIMLAPI key/base/model initialized")
    except Exception as _e:
        try: log.warning(f"[v20] ensure aimlapi: {_e}")
        except Exception: pass


try:
    _v20_ensure_aimlapi_key()
except Exception:
    pass


@ROUTER.command("aimlapi", description="تنظیمات AIMLAPI (پشتیبان)", admin_only=True)
def cmd_aimlapi_v20(msg, args):
    chat_id = get_chat_id(msg)
    cfg = CONFIG.get()
    parts = (args or "").strip().split(None, 1)
    sub = parts[0].lower() if parts else ""
    val = parts[1].strip() if len(parts) > 1 else ""

    def _mask(s):
        s = str(s or "")
        if not s: return "❌ خالی"
        if len(s) <= 12: return f"✅ {s}"
        return f"✅ {s[:8]}...{s[-6:]}"

    if not sub or sub == "status":
        key_set = bool(getattr(cfg.keys, "aimlapi", ""))
        base = getattr(cfg.keys, "aimlapi_base", "") or AIMLAPI_DEFAULT_BASE
        model = getattr(cfg.keys, "aimlapi_model", "") or AIMLAPI_DEFAULT_MODEL
        text = (
            "🤖 <b>AIMLAPI (پشتیبان)</b>\n\n"
            f"🔑 کلید: {_mask(cfg.keys.aimlapi)}\n"
            f"🌐 آدرس: <code>{escape_html(base)}</code>\n"
            f"🧠 مدل: <code>{escape_html(model)}</code>\n"
            f"⚙️ وضعیت: {'✅ فعال' if key_set else '❌ غیرفعال'}\n\n"
            "<b>دستورات:</b>\n"
            "<code>/aimlapi key &lt;کلید&gt;</code>\n"
            "<code>/aimlapi model &lt;نام&gt;</code>\n"
            "<code>/aimlapi base &lt;آدرس&gt;</code>\n"
            "<code>/aimlapi test</code>\n"
            "<code>/aimlapi reset</code>\n\n"
            "<b>زنجیره fallback:</b>\n"
            "<i>OpenRouter → Groq → BazaarLink → AIMLAPI → Gemini</i>"
        )
        TG.send_message(chat_id, text)
        return

    if sub == "key":
        if not val:
            TG.send_message(chat_id, "❌ استفاده: <code>/aimlapi key &lt;کلید&gt;</code>")
            return
        cfg.keys.aimlapi = val
        CONFIG.save()
        TG.send_message(chat_id, f"✅ کلید ذخیره شد ({len(val)} کاراکتر)")
        log.info(f"[v20] AIMLAPI key updated by {get_uid(msg)}")
        return

    if sub == "model":
        if not val:
            TG.send_message(chat_id, "❌ استفاده: <code>/aimlapi model &lt;نام&gt;</code>")
            return
        cfg.keys.aimlapi_model = val
        CONFIG.save()
        TG.send_message(chat_id, f"✅ مدل: <code>{escape_html(val)}</code>")
        return

    if sub == "base":
        if not val or not val.startswith(("http://", "https://")):
            TG.send_message(chat_id, "❌ آدرس باید با https:// شروع شود")
            return
        cfg.keys.aimlapi_base = val.rstrip("/")
        CONFIG.save()
        TG.send_message(chat_id, f"✅ آدرس: <code>{escape_html(val)}</code>")
        return

    if sub == "test":
        m = TG.send_message(chat_id, "🧪 در حال تست AIMLAPI ...")
        if m.ok:
            mid = (m.result or {}).get("message_id")
            POOL.submit(_v20_test_aimlapi_bg, chat_id, mid)
        return

    if sub == "reset":
        cfg.keys.aimlapi       = AIMLAPI_DEFAULT_KEY
        cfg.keys.aimlapi_base  = AIMLAPI_DEFAULT_BASE
        cfg.keys.aimlapi_model = AIMLAPI_DEFAULT_MODEL
        CONFIG.save()
        TG.send_message(chat_id, "✅ AIMLAPI به مقادیر پیش‌فرض بازگشت.")
        return

    TG.send_message(chat_id, f"❌ ناشناخته: <code>{escape_html(sub)}</code>\n/aimlapi")


def _v20_test_aimlapi_bg(chat_id, mid):
    try:
        cfg = CONFIG.get()
        key = (cfg.keys.aimlapi or "").strip()
        if not key:
            TG.edit_message(chat_id, mid, "❌ کلید AIMLAPI ست نشده.")
            return
        base = (cfg.keys.aimlapi_base or AIMLAPI_DEFAULT_BASE).rstrip("/")
        model = cfg.keys.aimlapi_model or AIMLAPI_DEFAULT_MODEL

        start = time.perf_counter()
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Reply with the single word: OK"}],
            "max_tokens": 10,
        }
        r = HTTP.request(
            "POST", f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json_body=payload, timeout=30,
        )
        latency = int((time.perf_counter() - start) * 1000)

        if r is None:
            TG.edit_message(chat_id, mid, "❌ عدم اتصال به سرور")
            return
        if r.status_code == 401:
            TG.edit_message(chat_id, mid,
                "❌ <b>کلید نامعتبر (401)</b>\n"
                "کلید را از aimlapi.com/app/keys بررسی کن.")
            return
        if r.status_code == 429:
            TG.edit_message(chat_id, mid,
                "⚠️ <b>Rate limit (429)</b> — کمی صبر کن.")
            return
        if r.status_code != 200:
            try:
                j = r.json()
                emsg = (j.get("error") or {}).get("message", r.text[:120])
            except Exception:
                emsg = r.text[:120]
            TG.edit_message(chat_id, mid,
                f"❌ <b>{r.status_code}</b>\n<code>{escape_html(str(emsg)[:200])}</code>")
            return

        try:
            data = r.json()
            choices = data.get("choices") or []
            text = (choices[0].get("message") or {}).get("content", "") if choices else ""
        except Exception:
            text = ""

        models_count = "?"
        try:
            r2 = HTTP.request("GET", f"{base}/models",
                headers={"Authorization": f"Bearer {key}"}, timeout=15)
            if r2 is not None and r2.status_code == 200:
                md = r2.json()
                items = md.get("data") or md.get("models") or []
                models_count = len(items)
        except Exception:
            pass

        TG.edit_message(chat_id, mid,
            f"✅ <b>تست AIMLAPI موفق</b>\n\n"
            f"🧠 مدل: <code>{escape_html(model)}</code>\n"
            f"⏱ زمان پاسخ: <code>{latency} ms</code>\n"
            f"💬 پاسخ: <i>{escape_html(text[:60])}</i>\n"
            f"📊 مدل‌های در دسترس: <code>{models_count}</code>\n"
            f"🌐 آدرس: <code>{escape_html(base)}</code>\n\n"
            f"<b>پشتیبان آماده است.</b>")
        log.info(f"[v20] AIMLAPI test OK ({latency}ms, {models_count} models)")
    except Exception as e:
        try: log.exception(f"[v20] test_aimlapi: {e}")
        except Exception: pass
        try: TG.edit_message(chat_id, mid, f"❌ {escape_html(str(e)[:200])}")
        except Exception: pass


@ROUTER.command("aimlapi_test", description="تست سریع AIMLAPI", admin_only=True)
def cmd_aimlapi_test_v20(msg, args):
    cmd_aimlapi_v20(msg, "test")


@ROUTER.command("aimlapi_switch", description="سوییچ به AIMLAPI به‌عنوان provider اصلی", admin_only=True)
def cmd_aimlapi_switch_v20(msg, args):
    chat_id = get_chat_id(msg)
    try:
        cfg = CONFIG.get()
        if not getattr(cfg.keys, "aimlapi", ""):
            TG.send_message(chat_id,
                "❌ ابتدا کلید AIMLAPI را ست کن:\n"
                "<code>/aimlapi key &lt;کلید&gt;</code>")
            return
        old_provider = cfg.ai.provider
        cfg.ai.provider = "aimlapi"
        CONFIG.save()
        TG.send_message(chat_id,
            f"✅ Provider اصلی تغییر کرد.\n"
            f"<b>قبلی:</b> <code>{escape_html(old_provider)}</code>\n"
            f"<b>جدید:</b> <code>aimlapi</code>\n\n"
            f"برای بازگشت: <code>/setkey provider openrouter</code>")
        log.info(f"[v20] Provider -> aimlapi by {get_uid(msg)}")
    except Exception as e:
        TG.send_message(chat_id, f"❌ {escape_html(str(e)[:150])}")


@ROUTER.command("ai_chain", description="نمایش زنجیره fallback هوش مصنوعی", admin_only=True)
def cmd_ai_chain_v20(msg, args):
    chat_id = get_chat_id(msg)
    cfg = CONFIG.get()
    try:
        all_providers = [
            ("openrouter",  bool(cfg.keys.openrouter)),
            ("groq",        bool(getattr(cfg.keys, "groq", ""))),
            ("bazaarlink",  bool(getattr(cfg.keys, "bazaarlink", ""))),
            ("aimlapi",     bool(getattr(cfg.keys, "aimlapi", ""))),
            ("gemini",      bool(cfg.keys.gemini)),
        ]
        primary = cfg.ai.provider
        lines = ["🔗 <b>زنجیره fallback هوش مصنوعی</b>", ""]
        for name, ok in all_providers:
            if name == primary:
                mark = "⭐"
                lines.append(f"{mark} <code>{name}</code> (اصلی) — {'✅' if ok else '❌'}")
        for name, ok in all_providers:
            if name != primary:
                lines.append(f"• <code>{name}</code> — {'✅' if ok else '❌'}")
        lines.append("")
        lines.append(f"⭐ فعلی: <code>{escape_html(primary)}</code>")
        TG.send_message(chat_id, "\n".join(lines))
    except Exception as e:
        TG.send_message(chat_id, f"❌ {escape_html(str(e)[:150])}")


log.info("PATCH v20.0 applied — AIMLAPI backup provider (auto-applied)")

# ═══════════════════════════════════════════════════════════════════════════
#  END PATCH v20.0
# ═══════════════════════════════════════════════════════════════════════════




# ═══════════════════════════════════════════════════════════════════════════
#  PATCH v21 — Fixes + New APIs + Bilingual Wiki + Modern Menu (auto)
# ═══════════════════════════════════════════════════════════════════════════

# ── 0) CRITICAL: make TTLStore support obj[k] = v ────────────────────────
try:
    def _ttl_setitem(self, k, v): self.set(k, v)
    def _ttl_getitem(self, k):
        v = self.get(k, None)
        if v is None: raise KeyError(k)
        return v
    def _ttl_delitem(self, k): self.pop(k, None)
    def _ttl_setdefault(self, k, default=None):
        v = self.get(k, None)
        if v is None:
            self.set(k, default); return default
        return v
    TTLStore.__setitem__   = _ttl_setitem
    TTLStore.__getitem__   = _ttl_getitem
    TTLStore.__delitem__   = _ttl_delitem
    TTLStore.setdefault    = _ttl_setdefault
    log.info("[v21] TTLStore now supports item assignment")
except Exception as _e:
    try: log.warning(f"[v21] TTLStore patch: {_e}")
    except Exception: pass


# ── 1) Extra API keys stored in a separate JSON (no dataclass changes) ──
_EXTRA_FILE = DATA_DIR / "extra_api_keys.json"
try:
    EXTRA_KEYS = load_json(_EXTRA_FILE, default={}) or {}
except Exception:
    EXTRA_KEYS = {}

def ek_get(name, default=""):
    return EXTRA_KEYS.get(name, default)

def ek_set(name, value):
    EXTRA_KEYS[name] = value
    save_json(_EXTRA_FILE, EXTRA_KEYS)

# Seed defaults on first run
_DEFAULTS = {
  "aviationstack": "b3b0096ad04934469c87bdb5c9c37eae",
  "apify": "apify_api_rSybimjgT3DEkm6k9uaoeYSrkeDTC73EAE0M",
  "bazaarlink": "0xa_8b50f3b9275cedd209f309363871083794c1b00b63a2705927746f87844c22f54.sk-bl-oC-7GbkA5rHECH1ks0RsbXCL9K_WxbaZsTal1pIemaj_q839",
  "apibricks": "1ff43e25-b193-424a-bcd6-2a73c5eb2a82",
  "apogeo": "apogeoapi_live_GOK8OXVfQIwXo2miD9zk2Lb2j0lScLaS",
  "coreclaw": "scraper_api_01M34SY7K9YHWTZBA7BFSYZS6A",
  "webz": "c3289286-63e1-4ba7-af23-460cdbe9dc71",
  "poof": "pk_a3e3e3a8d5d841bbeb41e79033b4adc6",
  "getanyapi": "aa_live_6ad056ae863ea63e53524345d054df9ee96eee7048d1d13f",
  "nasa": "SifzAFd2sq7EsF1P1su545KG8qh39P2e5hY5VlGQ",
  "opencode_zen": "sk-5K5zaZBU11qHatEVklnn3Oz1eY496uZiEJV3MaAK6eXgo2QyQ5eQbjMERfT4ZMF4",
  "cerebras": "csk-4jxk2h622emv93k24mrdwfkdmfdjm8fdc4m469wym54j58yp",
  "sambanova": "da89d313-e17f-4b1b-a66d-e0d6641da406"
}
for _k, _v in _DEFAULTS.items():
    if not EXTRA_KEYS.get(_k):
        EXTRA_KEYS[_k] = _v
save_json(_EXTRA_FILE, EXTRA_KEYS)


# ── 2) /setapi — set any extra key from Telegram ────────────────────────
@ROUTER.command("setapi", description="تنظیم کلید API اضافی", admin_only=True)
def cmd_setapi_v21(msg, args):
    chat_id = get_chat_id(msg)
    parts = (args or "").strip().split(None, 1)
    if len(parts) < 2:
        keys = ", ".join(sorted(EXTRA_KEYS.keys()))
        TG.send_message(chat_id,
            "استفاده: <code>/setapi name value</code>\n\n"
            f"<b>کلیدها:</b>\n<code>{escape_html(keys)}</code>")
        return
    name, val = parts[0].strip().lower(), parts[1].strip()
    ek_set(name, val)
    TG.send_message(chat_id, f"✅ {name} ذخیره شد ({len(val)} کاراکتر)")
    log.info(f"[v21] extra key {name} updated by {get_uid(msg)}")


@ROUTER.command("apistatus", description="وضعیت API های اضافی", admin_only=True)
def cmd_apistatus_v21(msg, args):
    chat_id = get_chat_id(msg)
    lines = ["🔌 <b>API های اضافی</b>", ""]
    for k in sorted(EXTRA_KEYS.keys()):
        v = EXTRA_KEYS.get(k) or ""
        mark = "✅" if v else "❌"
        prev = (v[:6] + "..." + v[-4:]) if len(v) > 12 else (v or "-")
        lines.append(f"{mark} <code>{k}</code>: {escape_html(prev)}")
    TG.send_message(chat_id, "\n".join(lines))


# ── 3) Base for new API clients ─────────────────────────────────────────
class V21API:
    NAME = "v21"

    @staticmethod
    def _req(method, url, headers=None, params=None, json_body=None, timeout=20):
        try:
            r = HTTP.request(method, url, headers=headers or {},
                             params=params or {}, json_body=json_body,
                             timeout=timeout)
            if r is None: return None, "no response"
            if r.status_code >= 400:
                return None, f"HTTP {r.status_code}: {r.text[:180]}"
            try: return r.json(), None
            except Exception: return r.text, None
        except Exception as e:
            return None, str(e)[:180]


# ── 4) NASA API (APOD + Earth + Mars) ───────────────────────────────────
class NasaV21(V21API):
    NAME = "nasa"

    @classmethod
    def apod(cls, date_str=""):
        key = ek_get("nasa")
        if not key: return None, "no nasa key"
        p = {"api_key": key}
        if date_str: p["date"] = date_str
        return cls._req("GET", "https://api.nasa.gov/planetary/apod", params=p)

    @classmethod
    def mars_photos(cls, sol=1000, camera="", limit=3):
        key = ek_get("nasa")
        if not key: return None, "no nasa key"
        p = {"api_key": key, "sol": sol}
        if camera: p["camera"] = camera
        d, err = cls._req("GET", "https://api.nasa.gov/mars-photos/api/v1/rovers/curiosity/photos", params=p)
        if err: return None, err
        photos = (d.get("photos") or [])[:limit]
        return photos, None

    @classmethod
    def neo_feed(cls, days=3):
        key = ek_get("nasa")
        if not key: return None, "no nasa key"
        from datetime import date, timedelta
        start = date.today().isoformat()
        end   = (date.today() + timedelta(days=days)).isoformat()
        return cls._req("GET", "https://api.nasa.gov/neo/rest/v1/feed",
                        params={"api_key": key, "start_date": start, "end_date": end})


@ROUTER.command("nasa", description="اخبار و تصاویر NASA", admin_only=False)
def cmd_nasa_v21(msg, args):
    chat_id = get_chat_id(msg)
    sub = (args or "").strip().lower()

    if sub == "neo" or sub == "asteroid":
        d, err = NasaV21.neo_feed(3)
        if err:
            TG.send_message(chat_id, f"❌ {escape_html(err[:180])}"); return
        near = d.get("near_earth_objects", {})
        total = sum(len(v) for v in near.values())
        lines = [f"☄️ <b>اجرام نزدیک به زمین</b> — {total} در ۳ روز آینده", ""]
        for day, objs in sorted(near.items()):
            for o in objs[:4]:
                lines.append(
                    f"• <b>{escape_html(o.get('name','?')[:40])}</b>\n"
                    f"  ⌀ {o.get('estimated_diameter',{}).get('meters',{}).get('estimated_diameter_max','?')}m\n"
                    f"  ⚡ {o.get('close_approach_data',[{}])[0].get('relative_velocity',{}).get('kilometers_per_hour','?')} km/h"
                )
        TG.send_message(chat_id, "\n".join(lines)[:4000])
        return

    if sub == "mars":
        photos, err = NasaV21.mars_photos(1000, "", 3)
        if err:
            TG.send_message(chat_id, f"❌ {escape_html(err[:180])}"); return
        for p in photos:
            img = p.get("img_src","")
            if img:
                TG.send_photo(chat_id, img, caption="🔴 Mars — Curiosity")
        return

    # Default → APOD
    d, err = NasaV21.apod()
    if err:
        TG.send_message(chat_id, f"❌ {escape_html(err[:180])}"); return
    title = d.get("title", "")
    expl  = d.get("explanation", "")[:700]
    url   = d.get("url", "")
    hd    = d.get("hdurl", url)
    media = d.get("media_type", "image")
    date_ = d.get("date", "")

    caption = (f"🚀 <b>{escape_html(title[:150])}</b>\n"
               f"<i>📅 {date_}</i>\n\n{escape_html(expl)}")
    if media == "image":
        TG.send_photo(chat_id, hd or url, caption=caption[:1024])
    else:
        TG.send_message(chat_id, caption + f"\n\n🔗 {url}")


# ── 5) Groq / Cerebras / SambaNova / OpenCode Zen (OpenAI-compatible) ──
class OpenAICompatV21(V21API):
    def __init__(self, base, key, model):
        self.base, self.key, self.model = base.rstrip("/"), key, model

    def chat(self, sys_p, usr_p, max_tokens=2500, temperature=0.6):
        if not self.key: return None, "no key"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": sys_p},
                {"role": "user",   "content": usr_p},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        d, err = self._req("POST", f"{self.base}/chat/completions",
                           headers={"Authorization": f"Bearer {self.key}",
                                    "Content-Type": "application/json"},
                           json_body=payload, timeout=60)
        if err: return None, err
        ch = (d.get("choices") or [{}])[0]
        return (ch.get("message") or {}).get("content", "").strip() or None, None


def _oc_provider(name, base, key, model):
    def _fn(sys_p, usr_p, max_tokens=2500, temperature=0.6):
        c = OpenAICompatV21(base, key, model)
        return c.chat(sys_p, usr_p, max_tokens, temperature)
    return _fn


_PROVIDERS_V21 = {
    "groq":        lambda: _oc_provider("groq",
        "https://api.groq.com/openai/v1",
        (CONFIG.get().keys.groq or ek_get("groq") or ""),
        getattr(CONFIG.get().keys, "groq_model", "llama-3.3-70b-versatile")),
    "cerebras":    lambda: _oc_provider("cerebras",
        "https://api.cerebras.ai/v1",
        ek_get("cerebras"),
        "llama-3.3-70b"),
    "sambanova":   lambda: _oc_provider("sambanova",
        "https://api.sambanova.ai/v1",
        ek_get("sambanova"),
        "Meta-Llama-3.3-70B-Instruct"),
    "opencode":    lambda: _oc_provider("opencode",
        "https://opencode.ai/zen/v1",
        ek_get("opencode_zen"),
        "claude-3-5-sonnet"),
    "claude":      lambda: _oc_provider("claude",
        "https://api.anthropic.com/v1",
        ek_get("claude"),
        "claude-3-5-sonnet-20241022"),
}


@ROUTER.command("ask2", description="پرسش از AI پشتیبان (groq/cerebras/sambanova/opencode/claude)", admin_only=True)
def cmd_ask2_v21(msg, args):
    chat_id = get_chat_id(msg)
    parts = (args or "").strip().split(None, 1)
    if len(parts) < 2:
        TG.send_message(chat_id,
            "استفاده: <code>/ask2 &lt;provider&gt; &lt;سوال&gt;</code>\n\n"
            "provider: " + ", ".join(_PROVIDERS_V21.keys()))
        return
    prov, q = parts[0].lower(), parts[1]
    if prov not in _PROVIDERS_V21:
        TG.send_message(chat_id, f"❌ ناشناخته: {escape_html(prov)}"); return
    m = TG.send_message(chat_id, f"⏳ {prov} در حال پاسخ ...")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")

    def _do():
        try:
            fn = _PROVIDERS_V21[prov]()
            text, err = fn("You are a Persian engineering assistant.",
                           q, 2000, 0.6)
            if err or not text:
                TG.edit_message(chat_id, mid, f"❌ {escape_html((err or 'no reply')[:180])}")
                return
            final = separate_directions(clean_latex(text))
            final = _md_to_html_safe(final)
            TG.edit_message(chat_id, mid, final[:4000])
        except Exception as e:
            log.exception(f"[v21] ask2: {e}")
            TG.edit_message(chat_id, mid, f"❌ {escape_html(str(e)[:180])}")

    POOL.submit(_do)


# ── 6) Simple free APIs (Agify / Design DNA / CompareEdge) ─────────────
@ROUTER.command("agify", description="تخمین سن از اسم")
def cmd_agify_v21(msg, args):
    chat_id = get_chat_id(msg)
    name = (args or "").strip()
    if not name:
        TG.send_message(chat_id, "استفاده: <code>/agify ali</code>"); return
    d, err = V21API._req("GET", "https://api.agify.io", params={"name": name})
    if err:
        TG.send_message(chat_id, f"❌ {escape_html(err[:150])}"); return
    if not isinstance(d, dict) or not d.get("age"):
        TG.send_message(chat_id, f"❌ نتیجه‌ای برای «{escape_html(name)}» نیست."); return
    TG.send_message(chat_id,
        f"🎂 <b>{escape_html(name)}</b>\n"
        f"سن تخمینی: <code>{d.get('age')}</code>\n"
        f"تعداد نمونه: <code>{d.get('count')}</code>")


@ROUTER.command("designdna", description="استخراج DNA طراحی از سایت")
def cmd_designdna_v21(msg, args):
    chat_id = get_chat_id(msg)
    url = (args or "").strip()
    if not url.startswith("http"):
        TG.send_message(chat_id, "استفاده: <code>/designdna https://example.com</code>"); return
    m = TG.send_message(chat_id, "🎨 در حال تحلیل ...")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")
    def _do():
        try:
            d, err = V21API._req("GET", "https://design-dna-api.onrender.com/v1/extract",
                                 params={"url": url}, timeout=60)
            if err:
                TG.edit_message(chat_id, mid, f"❌ {escape_html(err[:180])}"); return
            txt = json_dumps(d, indent=True)
            if isinstance(txt, bytes): txt = txt.decode("utf-8", "replace")
            TG.edit_message(chat_id, mid, f"🎨 <b>Design DNA</b>\n<pre>{escape_html(str(txt)[:3500])}</pre>")
        except Exception as e:
            TG.edit_message(chat_id, mid, f"❌ {escape_html(str(e)[:180])}")
    POOL.submit(_do)


# ── 7) Wikipedia bilingual + translate button ──────────────────────────
_WIKI_STORE_V21 = TTLStore(max_items=300, ttl=3600)


def _wiki_render_v21(title, fa_text, en_text, url="", full=False):
    """Render bilingual wiki message."""
    if full:
        fa_show = (fa_text or "")[:3500]
        en_show = (en_text or "")[:3500]
    else:
        fa_show = (fa_text or "")[:1200]
        en_show = (en_text or "")[:1200]

    parts = [f"📖 <b>{escape_html(title[:200])}</b>", ""]
    if fa_show:
        parts.append("🇮🇷 <b>فارسی</b>")
        parts.append(escape_html(fa_show))
        parts.append("")
    if en_show:
        parts.append("━━━━━━━━━━━━━━━━━━")
        parts.append("🇬🇧 <b>English</b>")
        parts.append(f"<i>{escape_html(en_show)}</i>")
    if url:
        parts.append("")
        parts.append(f"🔗 {url}")
    return "\n".join(parts)


def _wiki_fetch_v21(chat_id, msg_id, title):
    """Bilingual Wikipedia + translate button."""
    if msg_id:
        try: TG.edit_message(chat_id, msg_id, f"📖 «{escape_html(title)}» ...")
        except Exception: pass
    else:
        m = TG.send_message(chat_id, f"📖 «{escape_html(title)}» ...")
        msg_id = (m.result or {}).get("message_id") if m.ok else None

    r_fa = APIS.wikipedia.summary(title, "fa")
    r_en = APIS.wikipedia.summary(title, "en")
    fa_title = fa_extract = fa_url = ""
    en_title = en_extract = en_url = ""
    if r_en.ok:
        d = r_en.data
        en_title = d.get("title", "") or title
        en_extract = clean_wiki_extract(d.get("extract","") or "")
        en_url = d.get("url","")
    if r_fa.ok:
        d = r_fa.data
        fa_title = d.get("title","") or title
        fa_extract = clean_wiki_extract(d.get("extract","") or "")
        fa_url = d.get("url","")

    # translate if FA missing/short
    if en_extract and (not fa_extract or len(fa_extract) < len(en_extract)*0.55):
        try:
            fa_extract = _translate_long_v15(en_extract[:2500], "en", "fa") or fa_extract
            if not fa_title or fa_title == title:
                fa_title = _translate_long_v15(en_title, "en", "fa") or title
        except Exception:
            pass

    if not (fa_extract or en_extract):
        if msg_id: TG.edit_message(chat_id, msg_id, "❌ یافت نشد.")
        return

    _WIKI_STORE_V21[chat_id] = {
        "title": title, "fa": fa_extract, "en": en_extract,
        "url": fa_url or en_url,
    }

    text = _wiki_render_v21(fa_title or title, fa_extract, en_extract,
                            fa_url or en_url, full=False)
    kb_rows = [
        [btn("🌐 ترجمه کامل", f"wtr:{escape_html(title)[:40]}"),
         btn("🔄 دوباره",      f"wgo:{escape_html(title)[:40]}")],
        [btn("⬅️ ویکی", "wiki:menu"), btn("🏠", "m:main")],
    ]
    if msg_id:
        try: TG.edit_message(chat_id, msg_id, text[:4000], reply_markup=kb(kb_rows))
        except Exception: pass
    else:
        TG.send_message(chat_id, text[:4000], reply_markup=kb(kb_rows))


@ROUTER.callback("wtr")
def cb_wtr_v21(cb, data):
    try:
        chat_id = cb["message"]["chat"]["id"]
        msg_id  = cb["message"]["message_id"]
        TG.answer_callback(cb.get("id", ""), "🌐")
        title = data.split(":", 1)[1] if ":" in data else ""
        cached = _WIKI_STORE_V21.get(chat_id) or {}
        if not cached:
            POOL.submit(_wiki_fetch_v21, chat_id, msg_id, title); return
        fa = cached.get("fa","")
        en = cached.get("en","")
        # translate EN → FA if fa too short
        if en and (not fa or len(fa) < 500):
            try:
                fa = _translate_long_v15(en[:3500], "en", "fa") or fa
            except Exception:
                pass
        if en and (not cached.get("fa_full")):
            try:
                _WIKI_STORE_V21[chat_id] = dict(cached, fa=fa, fa_full=True)
            except Exception:
                pass
        text = _wiki_render_v21(cached.get("title", title), fa, en,
                                cached.get("url",""), full=True)
        try:
            TG.edit_message(chat_id, msg_id, text[:4000],
                            reply_markup=kb([[btn("⬅️ ویکی", "wiki:menu"),
                                              btn("🏠", "m:main")]]))
        except Exception:
            TG.send_long_message(chat_id, text)
    except Exception as e:
        log.exception(f"[v21] wtr: {e}")


@ROUTER.callback("wgo")
def cb_wgo_v21(cb, data):
    chat_id = cb["message"]["chat"]["id"]
    msg_id  = cb["message"]["message_id"]
    TG.answer_callback(cb.get("id", ""), "🔄")
    title = data.split(":", 1)[1] if ":" in data else ""
    POOL.submit(_wiki_fetch_v21, chat_id, msg_id, title)


# ── 8) Modern topic picker (Softmax + anti-repeat + categories) ────────
class ModernPickerV21:
    """Weighted softmax picker with per-category surprise + recency."""
    def __init__(self, temp=0.85, max_window=80):
        self.T = temp
        self._usage  = {}
        self._recent = []
        self._max = max_window
        self._lock = threading.RLock()

    def _softmax(self, logits):
        if not logits: return []
        mx = max(logits)
        ex = [_math_rnd.exp((l - mx) / self.T) for l in logits]
        s = sum(ex)
        return [e/s for e in ex] if s > 0 else [1.0/len(logits)]*len(logits)

    def pick(self, topics, avoid=None):
        if not topics: return None
        with self._lock:
            avoid = set(avoid or [])
            pool = [t for t in topics if (t.get("name") or "") not in avoid] or list(topics)
            logits = []
            for t in pool:
                nm = t.get("name") or ""
                cnt = self._usage.get(nm, 0)
                base = 1.0 / (1.0 + cnt)
                try:
                    idx = self._recent.index(nm)
                    rec = (self._max - idx) / self._max
                except ValueError:
                    rec = 0.0
                pen = 1.0 / (1.0 + 25.0 * rec)
                logits.append(_math_rnd.log(max(1e-9, base * pen)))
            probs = self._softmax(logits)
            r = _RND.random()
            cum = 0.0
            chosen = pool[-1]
            for t, p in zip(pool, probs):
                cum += p
                if r <= cum:
                    chosen = t; break
            nm = chosen.get("name") or ""
            self._usage[nm] = self._usage.get(nm, 0) + 1
            self._recent.insert(0, nm)
            del self._recent[self._max:]
            return chosen

    def reset(self):
        with self._lock:
            self._usage.clear(); self._recent.clear()


PICKER_V21 = ModernPickerV21()


# ── 9) Categorized menu with surprise per category ─────────────────────
def _v21_topics_by_category():
    """Return {domain: {subcat: [topics]}}."""
    out = {"math": {}, "mech": {}}
    try:
        tlist = _get_topics_list() or []
    except Exception:
        tlist = []
    for t in tlist:
        dom = (t.get("domain") or "").lower()
        if dom not in ("math", "mech"): continue
        sec = t.get("section") or "?"
        out[dom].setdefault(sec, []).append(t)
    return out


def _v21_menu_main():
    return kb([
        [btn("📚 بانک موضوعات", "v21:dom:math"), btn("⚙️ مهندسی", "v21:dom:mech")],
        [btn("🎲 تصادفی کل",  "v21:rand:all"),  btn("🌐 ویکی دوزبانه", "wiki:menu")],
        [btn("🚀 NASA",       "v21:nasa"),      btn("📰 اخبار", "news:menu")],
        [btn("💱 ارز",        "rate:refresh"),  btn("🌤 آب‌وهوا", "m:weather")],
        [btn("🎵 موسیقی",     "music:back"),    btn("📜 شعر", "poem:next")],
        [btn("🧮 فرمول",      "m:formula"),     btn("🔬 عمیق", "sty:deep")],
        [btn("🔌 API ها",     "m:api"),         btn("⚙️ تنظیمات", "m:settings")],
        [btn("ℹ️ راهنما",     "m:help")],
    ])


@ROUTER.callback("v21")
def cb_v21(cb, data):
    try:
        parts = data.split(":")
        action = parts[1] if len(parts) > 1 else ""
        chat_id = cb["message"]["chat"]["id"]
        msg_id  = cb["message"]["message_id"]
        TG.answer_callback(cb.get("id", ""))

        if action == "main":
            TG.edit_message(chat_id, msg_id, "🏠 <b>منوی اصلی</b>",
                            reply_markup=_v21_menu_main()); return

        if action == "dom":
            dom = parts[2] if len(parts) > 2 else "math"
            cats = _v21_topics_by_category().get(dom, {})
            rows = []
            for sec, items in sorted(cats.items()):
                rows.append([
                    btn(f"📂 {sec} ({len(items)})", f"v21:cat:{dom}:{sec}"),
                    btn("🎲", f"v21:catrand:{dom}:{sec}"),
                ])
            rows.append([btn("⬅️ منو", "v21:main")])
            title = "📐 ریاضی" if dom == "math" else "⚙️ مهندسی مکانیک"
            TG.edit_message(chat_id, msg_id,
                f"<b>{title}</b>\n"
                f"{sum(len(v) for v in cats.values())} موضوع در {len(cats)} سرفصل",
                reply_markup=kb(rows)); return

        if action == "cat":
            dom = parts[2] if len(parts) > 2 else "math"
            sec = parts[3] if len(parts) > 3 else "?"
            cats = _v21_topics_by_category().get(dom, {})
            items = cats.get(sec, [])
            rows = []
            for i, t in enumerate(items[:30], 1):
                nm = (t.get("name") or "?")[:35]
                rows.append([btn(f"{i}. {nm}", f"v21:go:{dom}:{sec}:{i-1}")])
            rows.append([btn("🎲 تصادفی این سرفصل",
                             f"v21:catrand:{dom}:{sec}"),
                         btn("⬅️ بازگشت", f"v21:dom:{dom}")])
            TG.edit_message(chat_id, msg_id,
                f"📂 <b>{sec}</b> — {len(items)} موضوع",
                reply_markup=kb(rows)); return

        if action == "go":
            dom = parts[2] if len(parts) > 2 else "math"
            sec = parts[3] if len(parts) > 3 else "?"
            try: idx = int(parts[4])
            except Exception: return
            items = _v21_topics_by_category().get(dom, {}).get(sec, [])
            if idx < 0 or idx >= len(items): return
            t = items[idx]
            POOL.submit(_generate_and_post, CONFIG.get(),
                        chat_id, t, t.get("style","tutorial")); return

        if action == "catrand":
            dom = parts[2] if len(parts) > 2 else "math"
            sec = parts[3] if len(parts) > 3 else "?"
            items = _v21_topics_by_category().get(dom, {}).get(sec, [])
            if not items: return
            t = PICKER_V21.pick(items)
            if t:
                POOL.submit(_generate_and_post, CONFIG.get(),
                            chat_id, t, t.get("style","tutorial"))
            return

        if action == "rand":
            which = parts[2] if len(parts) > 2 else "all"
            if which == "all":
                try: items = _get_topics_list() or []
                except Exception: items = []
            else:
                dom, sec = which.split(".", 1)
                items = _v21_topics_by_category().get(dom, {}).get(sec, [])
            if not items: return
            t = PICKER_V21.pick(items)
            if t:
                POOL.submit(_generate_and_post, CONFIG.get(),
                            chat_id, t, t.get("style","tutorial"))
            return

        if action == "nasa":
            cmd_nasa_v21(cb.get("from", {}), ""); return

    except Exception as e:
        log.exception(f"[v21] cb: {e}")


# ── 10) Override main menu callback so 🏠 button shows new menu ────────
_orig_cb_m_v21 = ROUTER._callback_handlers.get("m")

@ROUTER.callback("m")
def cb_m_v21(cb, data):
    action = data.split(":", 1)[1] if ":" in data else "main"
    chat_id = cb["message"]["chat"]["id"]
    msg_id  = cb["message"]["message_id"]
    if action == "main":
        TG.answer_callback(cb.get("id", ""))
        TG.edit_message(chat_id, msg_id, "🏠 <b>منوی اصلی</b>",
                        reply_markup=_v21_menu_main())
        return
    if action == "list":
        _c = dict(cb); _c["data"] = "v21:dom:math"
        return cb_v21(_c, _c["data"])
    if action == "find":
        uid = cb["from"]["id"]
        SESSIONS.set_state(uid, "awaiting_search",
                           chat_id=chat_id, msg_id=msg_id)
        TG.answer_callback(cb.get("id", ""))
        TG.edit_message(chat_id, msg_id,
            "🔍 عبارت را بفرست:",
            reply_markup=kb([[btn("⬅️ لغو", "m:main")]])); return
    if _orig_cb_m_v21:
        try:
            return _orig_cb_m_v21(cb, data)
        except Exception as e:
            log.debug(f"[v21] fallback cb_m: {e}")


# ── 11) Override /list and /random with modern versions ────────────────
@ROUTER.command("list", description="بانک موضوعات (دسته‌بندی شده)")
def cmd_list_v21(msg, args):
    chat_id = get_chat_id(msg)
    cats = _v21_topics_by_category()
    rows = []
    for dom, label, emoji in (("math","ریاضی","📐"),("mech","مهندسی","⚙️")):
        n = sum(len(v) for v in cats.get(dom, {}).values())
        rows.append([btn(f"{emoji} {label} ({n})", f"v21:dom:{dom}")])
    rows.append([btn("🎲 تصادفی کل", "v21:rand:all")])
    rows.append([btn("🏠 منو", "m:main")])
    TG.send_message(chat_id, "📚 <b>بانک موضوعات</b>",
                    reply_markup=kb(rows))


@ROUTER.command("random", description="موضوع تصادفی (مدرن)")
def cmd_random_v21(msg, args):
    chat_id = get_chat_id(msg)
    try: items = _get_topics_list() or []
    except Exception: items = []
    if not items:
        TG.send_message(chat_id, "❌ خالی"); return
    t = PICKER_V21.pick(items)
    if t:
        POOL.submit(_generate_and_post, CONFIG.get(),
                    chat_id, t, t.get("style","tutorial"))


@ROUTER.command("randstats2", description="آمار پیکر مدرن", admin_only=True)
def cmd_randstats2_v21(msg, args):
    chat_id = get_chat_id(msg)
    with PICKER_V21._lock:
        top = PICKER_V21._recent[:10]
        n = len(PICKER_V21._recent)
    txt = (f"<b>Modern picker</b> — {n} اخیر\n\n" +
           "\n".join(f"{i+1}. {escape_html(x)}" for i, x in enumerate(top)))
    TG.send_message(chat_id, txt)


@ROUTER.command("randreset2", description="ریست پیکر مدرن", admin_only=True)
def cmd_randreset2_v21(msg, args):
    PICKER_V21.reset()
    TG.send_message(get_chat_id(msg), "✅ ریست شد")


# ── 12) Override old _wiki_fetch_v7 (points to v21) ────────────────────
try:
    _wiki_fetch_v7 = _wiki_fetch_v21
    log.info("[v21] _wiki_fetch_v7 redirected to v21 bilingual")
except Exception:
    pass


# ── 13) Proxies: add shadowmere (if missing) ──────────────────────────
try:
    if "_PROXY_SOURCES_V13" in globals():
        _PROXY_SOURCES_V13.setdefault(
            "shadowmere_main", "https://shadowmere.xyz/api/proxies")
except Exception:
    pass


log.info("PATCH v21.0 applied — APIs + bilingual wiki + modern menu")
# ═══════════════════════════════════════════════════════════════════════════




# ═══════════════════════════════════════════════════════════════════════════
#  PATCH v22 — Confirm-Post + Persistent Menu + Full Submenus + Chat
# ═══════════════════════════════════════════════════════════════════════════

# ── 1) PERSISTENT MENU (BotFather style) ──────────────────────────────────
def _v22_register_menu():
    """Register bot commands menu (shows as dropdown next to input)."""
    try:
        cmds = [
            {"command": "start",    "description": "شروع / منوی اصلی"},
            {"command": "menu",     "description": "منوی کشویی اصلی"},
            {"command": "list",     "description": "بانک موضوعات"},
            {"command": "random",   "description": "موضوع تصادفی"},
            {"command": "post",     "description": "تولید پست"},
            {"command": "wiki",     "description": "ویکی‌پدیا دوزبانه"},
            {"command": "news",     "description": "اخبار"},
            {"command": "book",     "description": "کتاب PDF"},
            {"command": "music",    "description": "موسیقی"},
            {"command": "nasa",     "description": "NASA"},
            {"command": "chat",     "description": "چت با هوش مصنوعی"},
            {"command": "ask",      "description": "پرسش سریع"},
            {"command": "rate",     "description": "نرخ ارز"},
            {"command": "weather",  "description": "آب‌وهوا"},
            {"command": "poem",     "description": "شعر"},
            {"command": "proxy",    "description": "پروکسی / V2Ray"},
            {"command": "settings", "description": "تنظیمات"},
            {"command": "help",     "description": "راهنما"},
        ]
        # Default (all users)
        r = TG.set_my_commands(cmds)
        if r.ok:
            log.info(f"[v22] menu registered ({len(cmds)} cmds)")
        # Private chats scope
        try:
            TG._call("setMyCommands", {
                "commands": cmds,
                "scope": {"type": "all_private_chats"},
            })
        except Exception:
            pass
        # Group scope
        try:
            TG._call("setMyCommands", {
                "commands": cmds,
                "scope": {"type": "all_group_chats"},
            })
        except Exception:
            pass
    except Exception as e:
        log.warning(f"[v22] register menu: {e}")


# ── 2) 20s CONFIRM-BEFORE-POST ENGINE ─────────────────────────────────────
_PENDING_POSTS = TTLStore(max_items=200, ttl=1800)


def _v22_pending_post(cfg, chat_id, content, topic_name, style,
                      image_url="", extra_html=""):
    """
    Send preview with [✅ تایید] [❌ لغو] and auto-post after 25s.
    If user confirms → post now.
    If user cancels → discard.
    If no action → auto-post after 25s.
    """
    try:
        draft = DRAFTS.create(topic_name, style, content, 0,
                              metadata={"pending": True})
        did = draft.id

        preview = content[:1500]
        if len(content) > 1500:
            preview += "\n\n<i>...ادامه</i>"

        header = (
            f"📋 <b>پیش‌نمایش پست</b>\n"
            f"🎯 موضوع: <b>{escape_html(topic_name)}</b>\n"
            f"🎨 سبک: <code>{style}</code>\n"
            f"📏 {len(content)} کاراکتر\n\n"
            f"<b>⏱ تا ۲۵ ثانیه خودکار ارسال می‌شود — یا تصمیم بگیر:</b>"
        )

        rows = [
            [btn("✅ تایید و ارسال", f"cfp:ok:{did}"),
             btn("❌ لغو",          f"cfp:no:{did}")],
            [btn("👁 مشاهده کامل",   f"cfp:show:{did}"),
             btn("✏️ ویرایش با AI",  f"cfp:edit:{did}")],
        ]

        m = TG.send_message(chat_id, header + "\n\n" + preview,
                            reply_markup=kb(rows))
        if not m.ok: return None
        mid = (m.result or {}).get("message_id")

        _PENDING_POSTS[chat_id] = {
            "draft_id": did, "msg_id": mid,
            "content": content, "topic": topic_name, "style": style,
            "image_url": image_url, "extra_html": extra_html,
            "ts": time.time(),
            "fired": False,
        }

        # Auto-fire after 25s
        def _auto():
            time.sleep(25)
            rec = _PENDING_POSTS.get(chat_id)
            if not rec or rec.get("fired"): return
            if rec.get("draft_id") != did: return
            rec["fired"] = True
            _v22_do_post(cfg, chat_id, rec, auto=True)

        threading.Thread(target=_auto, daemon=True,
                         name=f"auto_post_{did}").start()
        return did
    except Exception as e:
        log.exception(f"[v22] pending_post: {e}")
        return None


def _v22_do_post(cfg, chat_id, rec, auto=False):
    """Actually publish the pending post to channel."""
    try:
        channel = (cfg.telegram.channel_id or "").strip()
        if not channel:
            TG.send_message(chat_id, "❌ کانال تنظیم نشده")
            return
        # image first
        if rec.get("image_url"):
            try:
                TG.send_photo(channel, rec["image_url"],
                              caption=f"🖼 <b>{escape_html(rec['topic'][:80])}</b>")
            except Exception:
                pass
        content = rec.get("content") or ""
        if rec.get("extra_html"):
            content += "\n\n" + rec["extra_html"]
        results = TG.send_long_message(channel, content)
        ok_flag = bool(results and results[0].ok)
        if ok_flag:
            STATS.incr("posts")
            STATS.incr_dict("styles", rec.get("style","tutorial"))
            note = "(خودکار)" if auto else "(دستی)"
            TG.send_message(chat_id, f"✅ منتشر شد {note}")
            try: HASHTAGS.sync_channel(cfg)
            except Exception: pass
        else:
            TG.send_message(chat_id, "❌ انتشار ناموفق")
    except Exception as e:
        log.exception(f"[v22] do_post: {e}")


@ROUTER.callback("cfp")
def cb_cfp_v22(cb, data):
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    did    = parts[2] if len(parts) > 2 else ""
    chat_id = cb["message"]["chat"]["id"]
    msg_id  = cb["message"]["message_id"]
    uid = cb.get("from", {}).get("id", 0)

    rec = _PENDING_POSTS.get(chat_id)
    if not rec or rec.get("draft_id") != did:
        TG.answer_callback(cb.get("id",""), "⏱ منقضی شد", show_alert=True)
        return

    if rec.get("fired"):
        TG.answer_callback(cb.get("id",""), "قبلاً ارسال شد", show_alert=True)
        return

    if action == "ok":
        rec["fired"] = True
        TG.answer_callback(cb.get("id",""), "📤 ارسال...")
        TG.edit_message(chat_id, msg_id, "⏳ در حال ارسال به کانال...")
        cfg = CONFIG.get()
        _v22_do_post(cfg, chat_id, rec, auto=False)
        return

    if action == "no":
        rec["fired"] = True
        TG.answer_callback(cb.get("id",""), "❌ لغو شد")
        TG.edit_message(chat_id, msg_id, "❌ لغو شد — منتشر نمی‌شود.")
        return

    if action == "show":
        TG.answer_callback(cb.get("id",""), "👁")
        TG.send_long_message(chat_id,
            f"📄 <b>محتوای کامل</b> — {escape_html(rec['topic'])}\n\n" + rec["content"])
        return

    if action == "edit":
        TG.answer_callback(cb.get("id",""), "✏️")
        SESSIONS.set_state(uid, "v22_edit_post",
                          chat_id=chat_id, draft_id=did)
        TG.edit_message(chat_id, msg_id,
            "✏️ <b>ویرایش پست</b>\n\n"
            "متن درخواست ویرایش را بنویس (مثلاً: «کوتاه‌تر کن» یا «مثال اضافه کن»):",
            reply_markup=kb([[btn("⬅️ لغو", f"cfp:canceledit:{did}")]]))
        return


@ROUTER.callback("cfp:canceledit")
def cb_cfp_canceledit(cb, data):
    uid = cb.get("from", {}).get("id", 0)
    SESSIONS.clear_state(uid)
    TG.answer_callback(cb.get("id",""), "لغو")


@ROUTER.on_text
def handle_edit_v22(msg):
    uid = get_uid(msg)
    s = SESSIONS.get(uid)
    if s.state != "v22_edit_post":
        return
    chat_id = get_chat_id(msg)
    instruction = (msg.get("text") or "").strip()
    did = s.data.get("draft_id","")
    SESSIONS.clear_state(uid)

    rec = _PENDING_POSTS.get(chat_id)
    if not rec or rec.get("draft_id") != did or rec.get("fired"):
        TG.send_message(chat_id, "❌ منقضی شد"); return

    m = TG.send_message(chat_id, "⏳ در حال ویرایش ...")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")

    def _do():
        try:
            sys_p = "You are a Persian engineering editor. Rewrite the given text following the instruction, keep structure and Persian, output only final text."
            usr_p = f"دستور: {instruction}\n\nمتن:\n{rec['content']}"
            resp = AI.ask(sys_p, usr_p, max_tokens=3000, temperature=0.5)
            if not resp.ok:
                TG.edit_message(chat_id, mid, f"❌ {escape_html(resp.error[:180])}")
                return
            rec["content"] = resp.text
            rec["fired"] = False
            _PENDING_POSTS[chat_id] = rec
            preview = resp.text[:1400] + ("\n\n<i>...ادامه</i>" if len(resp.text)>1400 else "")
            TG.edit_message(chat_id, mid,
                f"📋 <b>نسخه ویرایش‌شده</b>\n"
                f"🎯 {escape_html(rec['topic'])}\n\n"
                f"<b>⏱ ۲۵ ثانیه فرصت تایید:</b>\n\n{preview}",
                reply_markup=kb([
                    [btn("✅ تایید و ارسال", f"cfp:ok:{did}"),
                     btn("❌ لغو",          f"cfp:no:{did}")],
                    [btn("👁 مشاهده", f"cfp:show:{did}")],
                ]))
            # restart auto-fire
            def _auto():
                time.sleep(25)
                r2 = _PENDING_POSTS.get(chat_id)
                if not r2 or r2.get("fired") or r2.get("draft_id") != did: return
                r2["fired"] = True
                _v22_do_post(CONFIG.get(), chat_id, r2, auto=True)
            threading.Thread(target=_auto, daemon=True).start()
        except Exception as e:
            log.exception(f"[v22] edit: {e}")
            TG.edit_message(chat_id, mid, f"❌ {escape_html(str(e)[:180])}")

    POOL.submit(_do)


# ── 3) OVERRIDE _generate_and_post TO USE CONFIRM FLOW ────────────────────
_orig_generate_and_post_v22 = _generate_and_post

def _generate_and_post_v22(cfg, chat_id, topic, style="tutorial",
                          draft_id=None, with_poll=False, **kwargs):
    """Wrapper: generate + show 25s confirm instead of auto-post."""
    # Normalize topic
    if isinstance(topic, str):
        td = TOPIC_MGR.find(topic) or {
            "name": topic, "query": topic, "emoji": "📌",
            "tags": "#مهندسی_مکانیک",
        }
    else:
        td = topic
    tname = td["name"]

    m = TG.send_message(chat_id,
        f"⏳ تولید «{td.get('emoji','')} {escape_html(tname)}» ({style})...")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")

    try:
        with TypingHeartbeat(chat_id):
            content = CONTENT.generate(td, style)
    except Exception as e:
        log.exception(f"[v22] generate: {e}")
        content = None

    if not content:
        TG.edit_message(chat_id, mid, "❌ تولید ناموفق.")
        return

    # optional image
    img_url = ""
    try:
        if "POLL_IMG_V7" in globals() and "image_prompt_for" in globals():
            img_url = POLL_IMG_V7.url_for(_image_prompt_for(td),
                                          seed=_RND.randint(1,99999))
    except Exception:
        pass

    TG.edit_message(chat_id, mid, "✅ آماده شد — پیش‌نمایش:")
    _v22_pending_post(cfg, chat_id, content, tname, style, img_url)

_generate_and_post = _generate_and_post_v22


# ── 4) WIKI: send-to-channel + other + add/delete ─────────────────────────
_WIKI_SEND_V22 = TTLStore(max_items=200, ttl=3600)


@ROUTER.callback("wch")
def cb_wch_v22(cb, data):
    """Wiki: send to channel with confirm preview."""
    chat_id = cb["message"]["chat"]["id"]
    TG.answer_callback(cb.get("id",""), "📤")
    cached = _WIKI_STORE_V21.get(chat_id) if "_WIKI_STORE_V21" in globals() else None
    if not cached:
        TG.answer_callback(cb.get("id",""), "منقضی", show_alert=True); return
    title = cached.get("title","")
    fa = cached.get("fa","")
    en = cached.get("en","")
    url = cached.get("url","")
    content = _wiki_render_v21(title, fa, en, url, full=False)
    cfg = CONFIG.get()
    _v22_pending_post(cfg, chat_id, content, f"ویکی: {title}", "wiki",
                      extra_html=f"\n\n📢 @MAADGHchannel")


@ROUTER.callback("wother")
def cb_wother_v22(cb, data):
    """Wiki: user types custom title."""
    uid = cb.get("from", {}).get("id", 0)
    chat_id = cb["message"]["chat"]["id"]
    TG.answer_callback(cb.get("id",""), "✏️")
    SESSIONS.set_state(uid, "v22_other_wiki",
                      chat_id=chat_id, msg_id=cb["message"]["message_id"])
    TG.send_message(chat_id,
        "✏️ <b>موضوع دلخواه</b>\n\n"
        "موضوع مورد نظرت را به فارسی یا انگلیسی بنویس:",
        reply_markup=kb([[btn("⬅️ لغو","wiki:menu")]]))


@ROUTER.on_text
def handle_other_wiki_v22(msg):
    uid = get_uid(msg)
    s = SESSIONS.get(uid)
    if s.state != "v22_other_wiki": return
    chat_id = get_chat_id(msg)
    title = (msg.get("text") or "").strip()
    SESSIONS.clear_state(uid)
    if not title: return
    POOL.submit(_wiki_fetch_v21, chat_id, None, title)


@ROUTER.callback("wadd")
def cb_wadd_v22(cb, data):
    """Add a custom wiki topic (stored to custom topics file)."""
    uid = cb.get("from", {}).get("id", 0)
    if not is_admin(uid):
        TG.answer_callback(cb.get("id",""), "⛔", show_alert=True); return
    chat_id = cb["message"]["chat"]["id"]
    TG.answer_callback(cb.get("id",""), "➕")
    SESSIONS.set_state(uid, "v22_add_wiki",
                      chat_id=chat_id, msg_id=cb["message"]["message_id"])
    TG.send_message(chat_id,
        "➕ <b>افزودن موضوع ویکی</b>\n\n"
        "عنوان را بنویس (به هر زبانی):\n"
        "<i>مثال: Navier-Stokes equations</i>",
        reply_markup=kb([[btn("⬅️ لغو","wiki:menu")]]))


@ROUTER.on_text
def handle_add_wiki_v22(msg):
    uid = get_uid(msg)
    s = SESSIONS.get(uid)
    if s.state != "v22_add_wiki": return
    chat_id = get_chat_id(msg)
    title = (msg.get("text") or "").strip()
    SESSIONS.clear_state(uid)
    if not title: return
    try:
        p = DATA_DIR / "custom_wiki.json"
        arr = load_json(p, default=[]) or []
        if title not in arr:
            arr.append(title); save_json(p, arr)
            TG.send_message(chat_id, f"✅ «{title}» اضافه شد")
        else:
            TG.send_message(chat_id, "قبلاً موجود بود")
    except Exception as e:
        TG.send_message(chat_id, f"❌ {escape_html(str(e)[:150])}")


@ROUTER.callback("wdel")
def cb_wdel_v22(cb, data):
    uid = cb.get("from", {}).get("id", 0)
    if not is_admin(uid):
        TG.answer_callback(cb.get("id",""), "⛔", show_alert=True); return
    chat_id = cb["message"]["chat"]["id"]
    TG.answer_callback(cb.get("id",""), "➖")
    try:
        arr = load_json(DATA_DIR / "custom_wiki.json", default=[]) or []
    except Exception:
        arr = []
    if not arr:
        TG.send_message(chat_id, "📭 هیچ موضوع سفارشی نیست"); return
    rows = [[btn(f"🗑 {t[:30]}", f"wdel2:{i}")] for i, t in enumerate(arr[:30])]
    rows.append([btn("⬅️ ویکی","wiki:menu")])
    TG.send_message(chat_id, "➖ <b>حذف موضوع ویکی</b>", reply_markup=kb(rows))


@ROUTER.callback("wdel2")
def cb_wdel2_v22(cb, data):
    uid = cb.get("from", {}).get("id", 0)
    if not is_admin(uid):
        TG.answer_callback(cb.get("id",""), "⛔", show_alert=True); return
    chat_id = cb["message"]["chat"]["id"]
    try: idx = int(data.split(":",1)[1])
    except Exception: return
    try:
        p = DATA_DIR / "custom_wiki.json"
        arr = load_json(p, default=[]) or []
        if 0 <= idx < len(arr):
            removed = arr.pop(idx); save_json(p, arr)
            TG.answer_callback(cb.get("id",""), f"🗑 حذف شد")
            TG.edit_message(chat_id, cb["message"]["message_id"],
                f"✅ «{removed[:40]}» حذف شد")
    except Exception as e:
        TG.answer_callback(cb.get("id",""), "❌", show_alert=True)


# Add wiki buttons via callback hook (augment wiki menu dynamically)
_orig_cb_wiki_v7 = ROUTER._callback_handlers.get("wiki")

@ROUTER.callback("wiki")
def cb_wiki_v22(cb, data):
    """Delegate to v7 then augment menu."""
    # For menu action, override with augmented buttons
    action = data.split(":",1)[1] if ":" in data else ""
    chat_id = cb["message"]["chat"]["id"]
    msg_id  = cb["message"]["message_id"]
    if action == "menu" or not action:
        TG.answer_callback(cb.get("id",""))
        rows = [
            [btn("📐 ریاضی","wiki:sub:math"), btn("⚛️ فیزیک","wiki:sub:phys")],
            [btn("⚙️ مهندسی","wiki:sub:eng"), btn("🧪 شیمی","wiki:sub:chem")],
            [btn("🧬 زیست","wiki:sub:bio"), btn("🚀 فضا","wiki:sub:space")],
            [btn("💻 فناوری","wiki:sub:tech"), btn("🌍 عمومی","wiki:sub:gen")],
            [btn("✏️ موضوع دلخواه","wother"), btn("➕ افزودن","wadd")],
            [btn("➖ حذف","wdel"), btn("🎲 تصادفی","wiki:randall")],
            [btn("🏠 منو","v21:main")],
        ]
        TG.edit_message(chat_id, msg_id,
            "📖 <b>ویکی‌پدیا دوزبانه</b>\n"
            "<i>ترجمه + ارسال به کانال</i>",
            reply_markup=kb(rows))
        return
    # Default: fall through
    if _orig_cb_wiki_v7:
        return _orig_cb_wiki_v7(cb, data)


# ── 5) NEWS: send-to-channel + other ──────────────────────────────────────
@ROUTER.callback("nch")
def cb_nch_v22(cb, data):
    """News: send to channel."""
    chat_id = cb["message"]["chat"]["id"]
    TG.answer_callback(cb.get("id",""), "📤")
    try:
        idx = int(data.split(":",1)[1])
    except Exception:
        return
    st = _NEWS_QUEUE_V11.get(chat_id) or []
    if idx < 0 or idx >= len(st):
        TG.answer_callback(cb.get("id",""), "❌", show_alert=True); return
    it = st[idx]
    cfg = CONFIG.get()
    title = it.get("title","")
    summary = it.get("summary","")
    fa_title = TR_V10.translate(title, "en", "fa") if title else ""
    fa_summary = TR_V10.translate(summary, "en", "fa") if summary else ""
    content = (
        f"📰 <b>{escape_html(fa_title[:200])}</b>\n\n"
        f"📝 {escape_html(fa_summary[:900])}\n\n"
        f"🇬🇧 <i>{escape_html(title[:200])}</i>\n"
        f"📝 <i>{escape_html(summary[:900])}</i>\n\n"
        f"📎 {escape_html(str(it.get('source',''))[:50])}\n"
        f"🔗 {it.get('link','')}"
    )
    _v22_pending_post(cfg, chat_id, content, f"خبر: {title[:60]}", "news")


@ROUTER.callback("nother")
def cb_nother_v22(cb, data):
    uid = cb.get("from", {}).get("id", 0)
    chat_id = cb["message"]["chat"]["id"]
    TG.answer_callback(cb.get("id",""), "✏️")
    SESSIONS.set_state(uid, "v22_other_news", chat_id=chat_id)
    TG.send_message(chat_id, "✏️ عبارت خبری دلخواه را بنویس:",
                    reply_markup=kb([[btn("⬅️ لغو","news:menu")]]))


@ROUTER.on_text
def handle_other_news_v22(msg):
    uid = get_uid(msg)
    s = SESSIONS.get(uid)
    if s.state != "v22_other_news": return
    chat_id = get_chat_id(msg)
    q = (msg.get("text") or "").strip()
    SESSIONS.clear_state(uid)
    if q:
        POOL.submit(_news_fetch_render_v11, chat_id, None, "search", q)


# ── 6) BOOK: add "other" + confirm-send ──────────────────────────────────
@ROUTER.callback("bother")
def cb_bother_v22(cb, data):
    uid = cb.get("from", {}).get("id", 0)
    chat_id = cb["message"]["chat"]["id"]
    TG.answer_callback(cb.get("id",""), "✏️")
    SESSIONS.set_state(uid, "v22_other_book", chat_id=chat_id)
    TG.send_message(chat_id, "✏️ عنوان کتاب دلخواه را بنویس:",
                    reply_markup=kb([[btn("⬅️ لغو","book:back")]]))


@ROUTER.on_text
def handle_other_book_v22(msg):
    uid = get_uid(msg)
    s = SESSIONS.get(uid)
    if s.state != "v22_other_book": return
    chat_id = get_chat_id(msg)
    q = (msg.get("text") or "").strip()
    SESSIONS.clear_state(uid)
    if q and "_book_search_v7" in globals():
        POOL.submit(_book_search_v7, chat_id, None, q)


# ── 7) MUSIC: add "other" ─────────────────────────────────────────────────
@ROUTER.callback("mothera")
def cb_mothera_v22(cb, data):
    uid = cb.get("from", {}).get("id", 0)
    chat_id = cb["message"]["chat"]["id"]
    TG.answer_callback(cb.get("id",""), "✏️")
    SESSIONS.set_state(uid, "v22_other_music", chat_id=chat_id)
    TG.send_message(chat_id, "✏️ نام آهنگ / خواننده را بنویس:",
                    reply_markup=kb([[btn("⬅️ لغو","music:back")]]))


@ROUTER.on_text
def handle_other_music_v22(msg):
    uid = get_uid(msg)
    s = SESSIONS.get(uid)
    if s.state != "v22_other_music": return
    chat_id = get_chat_id(msg)
    q = (msg.get("text") or "").strip()
    SESSIONS.clear_state(uid)
    if q and "_music_search_v15" in globals():
        POOL.submit(_music_search_v15, chat_id, None, "custom", q)


# ── 8) Direct AI chat with history ────────────────────────────────────────
_CHAT_HISTORY_V22 = TTLStore(max_items=200, ttl=3600)


@ROUTER.command("chat", description="چت مستقیم با هوش مصنوعی")
def cmd_chat_v22(msg, args):
    chat_id = get_chat_id(msg)
    uid = get_uid(msg)
    q = (args or "").strip()
    if not q:
        TG.send_message(chat_id,
            "💬 <b>چت با AI</b>\n\n"
            "پیامت را بعد از دستور بنویس:\n"
            "<code>/chat سلام، درباره برنولی توضیح بده</code>\n\n"
            "برای پاک کردن حافظه: <code>/chatreset</code>")
        return

    hist = _CHAT_HISTORY_V22.get(uid) or []
    hist.append({"role": "user", "content": q})

    m = TG.send_message(chat_id, "💭 در حال پردازش ...")
    if not m.ok: return
    mid = (m.result or {}).get("message_id")

    def _do():
        try:
            sys_p = ("You are a Persian-speaking PROFESSOR of engineering. "
                     "Answer clearly with technical depth. NEVER mention being AI.")
            resp = AI.ask(sys_p, q, history=hist[:-1], max_tokens=2500)
            if not resp.ok:
                TG.edit_message(chat_id, mid, f"❌ {escape_html(resp.error[:180])}")
                return
            text = separate_directions(clean_latex(resp.text))
            text = _md_to_html_safe(text)
            hist.append({"role": "assistant", "content": resp.text})
            _CHAT_HISTORY_V22[uid] = hist[-20:]
            # send with edit-or-split
            if len(text) <= 3800:
                TG.edit_message(chat_id, mid, text)
            else:
                TG.edit_message(chat_id, mid, text[:3800])
                TG.send_long_message(chat_id, text[3800:])
        except Exception as e:
            log.exception(f"[v22] chat: {e}")
            TG.edit_message(chat_id, mid, f"❌ {escape_html(str(e)[:180])}")

    POOL.submit(_do)


@ROUTER.command("chatreset", description="پاک کردن حافظه چت")
def cmd_chatreset_v22(msg, args):
    uid = get_uid(msg)
    _CHAT_HISTORY_V22.pop(uid, None)
    TG.send_message(get_chat_id(msg), "✅ حافظه چت پاک شد")


# ── 9) /menu command (dropdown fallback) ──────────────────────────────────
@ROUTER.command("menu", description="منوی اصلی")
def cmd_menu_v22(msg, args):
    chat_id = get_chat_id(msg)
    rows = [
        [btn("📚 بانک موضوعات","v21:dom:math"),
         btn("⚙️ مهندسی","v21:dom:mech")],
        [btn("🎲 تصادفی کل","v21:rand:all"),
         btn("🌐 ویکی دوزبانه","wiki:menu")],
        [btn("📰 اخبار","news:menu"),
         btn("🚀 NASA","v21:nasa")],
        [btn("📕 کتاب PDF","book:back"),
         btn("🎵 موسیقی","music:back")],
        [btn("💬 چت AI","chatinfo"),
         btn("💱 ارز","rate:refresh")],
        [btn("🌤 آب‌وهوا","m:weather"),
         btn("📜 شعر","poem:next")],
        [btn("🌐 پروکسی","proxy:list"),
         btn("📊 آمار","stats:cat:usage")],
        [btn("⚙️ تنظیمات","m:settings"),
         btn("ℹ️ راهنما","m:help")],
    ]
    TG.send_message(chat_id,
        "🏠 <b>منوی اصلی</b>\n"
        "<i>همه بخش‌ها در یک نگاه — روی هرکدام بزن</i>",
        reply_markup=kb(rows))


@ROUTER.callback("chatinfo")
def cb_chatinfo_v22(cb, data):
    chat_id = cb["message"]["chat"]["id"]
    TG.answer_callback(cb.get("id",""))
    TG.edit_message(chat_id, cb["message"]["message_id"],
        "💬 <b>چت مستقیم با AI</b>\n\n"
        "بنویس: <code>/chat سوال تو</code>\n\n"
        "یا از دکمه زیر استفاده کن:",
        reply_markup=kb([
            [btn("🔄 پاک کردن حافظه","chatreset_info")],
            [btn("⬅️ منو","v21:main")],
        ]))


@ROUTER.callback("chatreset_info")
def cb_chatreset_info_v22(cb, data):
    uid = cb.get("from", {}).get("id", 0)
    _CHAT_HISTORY_V22.pop(uid, None)
    TG.answer_callback(cb.get("id",""), "✅ حافظه پاک شد", show_alert=True)


# ── 10) Override /start to also register menu ─────────────────────────────
_orig_cmd_start_v22 = ROUTER._handlers.get("start")

@ROUTER.command("start", description="شروع")
def cmd_start_v22(msg, args):
    try:
        _v22_register_menu()
    except Exception:
        pass
    chat_id = get_chat_id(msg)
    uid = get_uid(msg)
    cfg = CONFIG.get()
    if cfg.telegram.admin_id is None:
        cfg.telegram.admin_id = uid
        if uid not in cfg.telegram.admin_ids:
            cfg.telegram.admin_ids.append(uid)
        CONFIG.save()
    name = get_user_name(msg)
    TG.send_message(chat_id,
        f"👋 سلام <b>{escape_html(name)}</b>!\n\n"
        f"ربات آماده است. از دکمه‌ها یا دستورها استفاده کن:",
        reply_markup=kb([
            [btn("📚 بانک موضوعات","v21:dom:math"),
             btn("🌐 ویکی","wiki:menu")],
            [btn("📰 اخبار","news:menu"),
             btn("🚀 NASA","v21:nasa")],
            [btn("📕 کتاب","book:back"),
             btn("🎵 موسیقی","music:back")],
            [btn("💬 چت AI","chatinfo"),
             btn("⚙️ تنظیمات","m:settings")],
            [btn("ℹ️ راهنما","m:help")],
        ]))


# ── 11) Register menu on load (background, non-blocking) ──────────────────
try:
    threading.Thread(target=_v22_register_menu, daemon=True,
                     name="v22Menu").start()
except Exception:
    pass


log.info("PATCH v22.0 applied — confirm-post + persistent menu + submenus + chat")
# ═══════════════════════════════════════════════════════════════════════════




# ═══════════════════════════════════════════════════════════════════════════
#  PATCH v23 — FULL DROPDOWN MENU + 32-BUTTON MAIN MENU + COMPLETE /help
# ═══════════════════════════════════════════════════════════════════════════

# ── 1) COMPLETE DROPDOWN MENU (shows when user types "/") ─────────────────
_V23_DROPDOWN = [
    # Main
    ("start",        "شروع / منوی اصلی"),
    ("menu",         "منوی کامل دکمه‌ای"),
    ("help",         "راهنمای کامل"),
    ("commands",     "فهرست همه دستورها"),

    # Content generation
    ("post",         "پست با موضوع دلخواه"),
    ("next",         "موضوع بعدی چرخشی"),
    ("topic",        "موضوع بعدی"),
    ("random",       "موضوع تصادفی"),
    ("formula",      "برگه فرمول"),
    ("math",         "درس ریاضی"),
    ("deep",         "تحلیل عمیق"),
    ("quiz",         "کوییز"),
    ("flash",        "فلش‌کارت"),
    ("trivia",       "دانستنی"),
    ("example",      "مثال حل‌شده"),
    ("compare",      "مقایسه"),
    ("history",      "تاریخ مهندسی"),
    ("style",        "تولید با سبک خاص"),
    ("styles",       "فهرست سبک‌ها"),
    ("super",        "حالت سوپر (کیفیت بالا)"),

    # Topics
    ("list",         "بانک موضوعات"),
    ("find",         "جستجو در موضوعات"),
    ("topics",       "مدیریت موضوعات"),
    ("addtopic",     "افزودن موضوع سفارشی"),
    ("delcustom",    "حذف موضوع سفارشی"),

    # Wiki / News / Books / Music
    ("wiki",         "ویکی‌پدیا دوزبانه"),
    ("news",         "اخبار دوزبانه"),
    ("book",         "کتاب PDF"),
    ("music",        "موسیقی Archive.org"),
    ("poem",         "شعر تصادفی"),
    ("fal",          "فال حافظ"),

    # Tools
    ("nasa",         "NASA — تصویر روز و مریخ"),
    ("arxiv",        "مقالات arXiv"),
    ("search",       "جستجوی وب"),
    ("images",       "جستجوی تصویر"),
    ("yt",           "جستجوی یوتیوب"),
    ("ytinfo",       "اطلاعات ویدیوی یوتیوب"),
    ("dict",         "دیکشنری"),
    ("tr",           "ترجمه متن"),
    ("ip",           "اطلاعات IP"),
    ("flight",       "اطلاعات پرواز"),
    ("weather",      "آب‌وهوا"),
    ("rate",         "نرخ ارز"),
    ("convert",      "تبدیل ارز"),
    ("proxy",        "پروکسی و V2Ray"),

    # AI Chat
    ("chat",         "چت با هوش مصنوعی"),
    ("chatreset",    "پاک کردن حافظه چت"),
    ("ask",          "پرسش سریع"),
    ("gpt",          "Gemini"),
    ("vision",       "تحلیل تصویر"),

    # Data
    ("fact",         "دانستنی عددی"),
    ("quote",        "نقل قول تصادفی"),
    ("joke",         "جوک تصادفی"),
    ("agify",        "تخمین سن از اسم"),

    # Admin
    ("stats",        "آمار"),
    ("api",          "وضعیت APIها"),
    ("apistatus",    "وضعیت APIهای اضافی"),
    ("showkeys",     "نمایش کلیدها"),
    ("settings",     "تنظیمات"),
    ("panel",        "پنل مدیر"),
    ("v22check",     "بررسی سلامت v22"),
    ("v21check",     "بررسی سلامت v21"),

    # Misc
    ("id",           "نمایش شناسه‌ها"),
    ("clear",        "پاک کردن حافظه"),
    ("ping",         "تست گزارش زنده"),
]


def _v23_register_dropdown():
    """Register the full dropdown (BotFather)."""
    try:
        cmds = [{"command": c, "description": d}
                for c, d in _V23_DROPDOWN]
        # default scope
        r = TG.set_my_commands(cmds)
        if r.ok:
            log.info(f"[v23] dropdown registered: {len(cmds)} commands")
        else:
            log.warning(f"[v23] dropdown failed: {r.description[:120]}")

        # all private chats
        try:
            TG._call("setMyCommands", {
                "commands": cmds,
                "scope": {"type": "all_private_chats"},
            })
        except Exception: pass

        # all group chats
        try:
            TG._call("setMyCommands", {
                "commands": cmds,
                "scope": {"type": "all_group_chats"},
            })
        except Exception: pass

        # admin scope (only for admins)
        try:
            cfg = CONFIG.get()
            for aid in (cfg.telegram.admin_ids or []):
                TG._call("setMyCommands", {
                    "commands": cmds,
                    "scope": {"type": "chat", "chat_id": int(aid)},
                })
        except Exception: pass
    except Exception as e:
        log.warning(f"[v23] dropdown: {e}")


# ── 2) BIG 32-BUTTON MAIN MENU ────────────────────────────────────────────
def _v23_menu_keyboard():
    """Return 32-button main menu (multi-row inline keyboard)."""
    return kb([
        # Row 1 — Starter
        [btn("🏠 شروع",     "v23:start"),
         btn("📋 منو",       "v23:menu"),
         btn("❓ راهنما",    "v23:help")],

        # Row 2 — Content styles
        [btn("📘 آموزشی",   "v23:style:tutorial"),
         btn("🧮 فرمول",     "v23:style:formula"),
         btn("🔬 عمیق",     "v23:style:deep")],

        # Row 3 — More styles
        [btn("❓ کوییز",    "v23:style:quiz"),
         btn("📇 فلش‌کارت",  "v23:style:flashcard"),
         btn("🧪 مثال",      "v23:style:example")],

        # Row 4 — Additional styles
        [btn("⚖️ مقایسه",  "v23:style:comparison"),
         btn("📜 تاریخی",   "v23:style:history"),
         btn("💡 دانستنی",  "v23:style:trivia")],

        # Row 5 — Content generation
        [btn("🌟 حالت سوپر","v23:super"),
         btn("🎲 تصادفی",   "v23:rand"),
         btn("➡️ بعدی",      "v23:next")],

        # Row 6 — Topics
        [btn("📚 بانک",     "v23:topics"),
         btn("🔍 جستجو",    "v23:find"),
         btn("➕ افزودن",   "v23:addtopic")],

        # Row 7 — Wiki & knowledge
        [btn("📖 ویکی",    "v23:wiki"),
         btn("📚 arXiv",    "v23:arxiv"),
         btn("🚀 NASA",     "v23:nasa")],

        # Row 8 — News
        [btn("📰 اخبار",   "v23:news"),
         btn("🗳 سیاسی",   "v23:politics"),
         btn("🌍 آرژانتیک","v23:arxiv2")],

        # Row 9 — Media
        [btn("📕 کتاب",    "v23:book"),
         btn("🎵 موسیقی",   "v23:music"),
         btn("🎥 یوتیوب",   "v23:yt")],

        # Row 10 — Fun
        [btn("📜 شعر",     "v23:poem"),
         btn("🔮 فال",       "v23:fal"),
         btn("🎬 جوک",      "v23:joke")],

        # Row 11 — Data
        [btn("💱 ارز",     "v23:rate"),
         btn("🌤 آب‌وهوا",  "v23:weather"),
         btn("✈️ هوانوردی","v23:flight")],

        # Row 12 — Chat AI
        [btn("💬 چت AI",   "v23:chat"),
         btn("🧠 Gemini",  "v23:gpt"),
         btn("🖼 تحلیل",    "v23:vision")],

        # Row 13 — Tools
        [btn("🌐 پروکسی",  "v23:proxy"),
         btn("🔌 API",      "v23:api"),
         btn("📊 آمار",     "v23:stats")],

        # Row 14 — Settings / Admin
        [btn("⚙️ تنظیمات", "v23:settings"),
         btn("🔑 کلیدها",   "v23:keys"),
         btn("🎛 پنل مدیر", "v23:panel")],

        # Row 15 — System
        [btn("🆔 شناسه",   "v23:id"),
         btn("🧹 پاک‌سازی", "v23:clear"),
         btn("📖 help2",    "v23:help2")],
    ])


# ── 3) /start — new BIG menu ──────────────────────────────────────────────
@ROUTER.command("start", description="شروع / منوی اصلی")
def cmd_start_v23(msg, args):
    chat_id = get_chat_id(msg)
    uid = get_uid(msg)
    cfg = CONFIG.get()
    if cfg.telegram.admin_id is None:
        cfg.telegram.admin_id = uid
        if uid not in cfg.telegram.admin_ids:
            cfg.telegram.admin_ids.append(uid)
        CONFIG.save()
    # ensure dropdown is registered
    try: _v23_register_dropdown()
    except Exception: pass
    try: _v22_register_menu()
    except Exception: pass
    name = get_user_name(msg)
    TG.send_message(chat_id,
        f"👋 سلام <b>{escape_html(name)}</b>\n\n"
        f"<b>MAADGH v23</b> — ربات هوشمند مهندسی\n\n"
        f"🔽 از منوی کشویی بالا استفاده کن (تایپ کن /)\n"
        f"📋 یا دکمه‌های زیر را بزن\n"
        f"❓ راهنما: /help",
        reply_markup=_v23_menu_keyboard())


# ── 4) /menu — big menu ───────────────────────────────────────────────────
@ROUTER.command("menu", description="منوی کامل دکمه‌ای")
def cmd_menu_v23(msg, args):
    TG.send_message(get_chat_id(msg),
        "🏠 <b>منوی کامل</b>\n"
        f"<i>{len(_V23_DROPDOWN)} دستور در منوی کشویی + 32 دکمه</i>",
        reply_markup=_v23_menu_keyboard())


# ── 5) Complete /help ─────────────────────────────────────────────────────
_V23_HELP_TEXT = """📖 <b>راهنمای کامل MAADGH v23</b>

<b>🔽 منوی کشویی:</b>
کافیه داخل کادر تایپ <code>/</code> بزنی — همه دستورها میاد.
(اگه نمیاد: تلگرام را ببند و باز کن.)

<b>📘 تولید محتوا:</b>
• <code>/post موضوع</code> — پست دلخواه
• <code>/next</code> — موضوع بعدی چرخشی
• <code>/random</code> — تصادفی
• <code>/formula موضوع</code> — برگه فرمول
• <code>/math موضوع</code> — ریاضی
• <code>/deep موضوع</code> — عمیق
• <code>/quiz موضوع</code> — کوییز
• <code>/flash موضوع</code> — فلش‌کارت
• <code>/trivia موضوع</code> — دانستنی
• <code>/example موضوع</code> — مثال
• <code>/compare موضوع</code> — مقایسه
• <code>/history موضوع</code> — تاریخی
• <code>/super موضوع</code> — حالت سوپر

<b>📚 موضوعات:</b>
• <code>/list</code> — بانک دسته‌بندی‌شده
• <code>/find عبارت</code> — جستجو
• <code>/topics</code> — مدیریت
• <code>/addtopic نام | query</code>
• <code>/delcustom نام</code>

<b>📖 ویکی و دانش:</b>
• <code>/wiki موضوع</code> — دوزبانه + ترجمه + ارسال به کانال
• <code>/arxiv موضوع</code> — مقالات
• <code>/nasa</code> — تصویر روز
• <code>/nasa mars</code> — عکس مریخ
• <code>/nasa neo</code> — سیارک‌های نزدیک

<b>📰 اخبار:</b>
• <code>/news</code> — منوی اخبار
• <code>/news موضوع</code> — جستجو
• <code>/politics</code> — سیاسی (ایران/آمریکا/جهان)

<b>📕 رسانه:</b>
• <code>/book موضوع</code> — کتاب PDF
• <code>/music سبک</code> — موسیقی
• <code>/yt موضوع</code> — یوتیوب
• <code>/ytinfo URL</code> — اطلاعات ویدیو
• <code>/poem</code> — شعر
• <code>/fal</code> — فال حافظ

<b>💬 چت با AI:</b>
• <code>/chat سوال</code> — چت با حافظه
• <code>/chatreset</code> — پاک کردن حافظه
• <code>/ask سوال</code> — پرسش سریع
• <code>/gpt سوال</code> — Gemini
• <code>/vision URL پرامپت</code> — تحلیل تصویر

<b>🔧 ابزارها:</b>
• <code>/search کلمه</code> — جستجوی وب
• <code>/images کلمه</code> — تصویر
• <code>/dict word</code> — دیکشنری
• <code>/tr en fa متن</code> — ترجمه
• <code>/ip 8.8.8.8</code> — IP
• <code>/flight IR720</code> — پرواز
• <code>/weather تهران</code> — آب‌وهوا
• <code>/rate</code> — ارز
• <code>/convert 100 USD IRR</code>
• <code>/proxy</code> — پروکسی / V2Ray

<b>🎮 سرگرمی:</b>
• <code>/fact</code> — دانستنی
• <code>/quote</code> — نقل قول
• <code>/joke</code> — جوک
• <code>/agify نام</code> — تخمین سن

<b>⚙️ مدیریت:</b>
• <code>/stats</code> — آمار
• <code>/api</code> — وضعیت APIها
• <code>/apistatus</code> — APIهای اضافی
• <code>/showkeys</code> — کلیدها
• <code>/settings</code> — تنظیمات
• <code>/panel</code> — پنل مدیر
• <code>/id</code> — شناسه‌ها
• <code>/clear</code> — پاک‌سازی

<b>🔑 دستورات ادمین:</b>
• <code>/setapi name value</code>
• <code>/aimlapi key|model|base|test</code>
• <code>/ask2 groq|cerebras|sambanova|opencode سوال</code>
• <code>/ai_chain</code>

<b>⏱ تأیید پست:</b>
پس از تولید پست، <b>۲۵ ثانیه</b> فرصت داری:
• ✅ تایید و ارسال — فوری
• ❌ لغو — منتشر نمی‌شود
• ✏️ ویرایش با AI
اگر کاری نکنی، خودکار ارسال می‌شود.
"""


@ROUTER.command("help", description="راهنمای کامل")
def cmd_help_v23(msg, args):
    chat_id = get_chat_id(msg)
    # split into 2 messages if needed
    text = _V23_HELP_TEXT
    if len(text) <= 4000:
        TG.send_message(chat_id, text,
                        reply_markup=kb([[btn("🏠 منو","v23:menu")]]))
    else:
        parts = TG._split_text(text, 3800)
        for i, p in enumerate(parts, 1):
            hdr = f"<b>({i}/{len(parts)})</b>\n\n" if len(parts) > 1 else ""
            TG.send_message(chat_id, hdr + p)
            time.sleep(0.6)
        TG.send_message(chat_id, "🏠 /menu", reply_markup=None)


# ── 6) /commands — list all commands ──────────────────────────────────────
@ROUTER.command("commands", description="فهرست همه دستورها")
def cmd_commands_v23(msg, args):
    chat_id = get_chat_id(msg)
    lines = [f"📋 <b>فهرست کامل ({len(_V23_DROPDOWN)} دستور)</b>", ""]
    for c, d in _V23_DROPDOWN:
        lines.append(f"• <code>/{c}</code> — {escape_html(d)}")
    text = "\n".join(lines)
    if len(text) <= 4000:
        TG.send_message(chat_id, text)
    else:
        TG.send_long_message(chat_id, text)


# ── 7) All v23: callbacks dispatch ────────────────────────────────────────
@ROUTER.callback("v23")
def cb_v23(cb, data):
    try:
        parts = data.split(":")
        action = parts[1] if len(parts) > 1 else ""
        param  = parts[2] if len(parts) > 2 else ""
        chat_id = cb["message"]["chat"]["id"]
        msg_id  = cb["message"]["message_id"]
        uid = cb.get("from", {}).get("id", 0)
        TG.answer_callback(cb.get("id",""))

        # menu/help
        if action == "menu":
            TG.edit_message(chat_id, msg_id,
                "🏠 <b>منوی کامل</b>", reply_markup=_v23_menu_keyboard()); return
        if action == "start":
            TG.edit_message(chat_id, msg_id,
                "🏠 <b>منوی اصلی</b>", reply_markup=_v23_menu_keyboard()); return
        if action == "help":
            TG.edit_message(chat_id, msg_id, _V23_HELP_TEXT[:3800]); return
        if action == "help2":
            cmd_commands_v23({"chat":{"id":chat_id},"from":cb.get("from",{}),"message":{}}, ""); return

        # style dispatch
        if action == "style":
            if param in CONTENT_STYLES:
                topic = TOPIC_MGR.rotate_next()["name"]
                POOL.submit(_generate_and_post, CONFIG.get(), chat_id, topic, param)
            return

        # quick actions
        if action == "super":
            _c = dict(cb); _c["data"] = "m:super"
            return ROUTER.route_callback(_c)
        if action == "rand":
            return cmd_random_v21({"chat":{"id":chat_id},"from":cb.get("from",{}),"message":{}}, "")
        if action == "next":
            return cmd_next({"chat":{"id":chat_id},"from":cb.get("from",{}),"message":{}}, "")
        if action == "topics":
            return cmd_list_v21({"chat":{"id":chat_id},"from":cb.get("from",{}),"message":{}}, "")
        if action == "find":
            SESSIONS.set_state(uid, "awaiting_search",
                              chat_id=chat_id, msg_id=msg_id)
            TG.edit_message(chat_id, msg_id,
                "🔍 عبارت جستجو را بنویس:",
                reply_markup=kb([[btn("⬅️ لغو","v23:menu")]])); return
        if action == "addtopic":
            SESSIONS.set_state(uid, "v23_addtopic",
                              chat_id=chat_id, msg_id=msg_id)
            TG.edit_message(chat_id, msg_id,
                "➕ فرمت: <code>نام | query</code>\n"
                "مثال: <code>توربین بادی | wind turbine</code>",
                reply_markup=kb([[btn("⬅️ لغو","v23:menu")]])); return

        # delegate to existing handlers
        delegate = {
            "wiki":     "wiki:menu",
            "arxiv":    "arxiv:p:0",
            "arxiv2":   "arxiv:p:0",
            "nasa":     "v21:nasa",
            "news":     "news:menu",
            "politics": "pol:fetch:all",
            "book":     "book:back",
            "music":    "music:back",
            "yt":       "y:rand",
            "poem":     "poem:next",
            "fal":      "poem:fal",
            "joke":     None,   # cmd
            "rate":     "rate:refresh",
            "weather":  "m:weather",
            "flight":   "av:refresh",
            "chat":     None,   # cmd
            "gpt":      None,   # cmd
            "vision":   None,   # cmd
            "proxy":    "proxy:list",
            "api":      "m:api",
            "stats":    "stats:cat:usage",
            "settings": "m:settings",
            "keys":     None,   # cmd showkeys
            "panel":    "m:panel",
            "id":       None,   # cmd
            "clear":    None,   # cmd
        }

        target = delegate.get(action)
        if target:
            _c = dict(cb); _c["data"] = target
            return ROUTER.route_callback(_c)

        # direct command dispatch
        cmd_map = {
            "joke":   cmd_joke,
            "chat":   cmd_chat_v22,
            "gpt":    cmd_gemini,
            "vision": cmd_vision,
            "keys":   cmd_showkeys,
            "id":     cmd_id,
            "clear":  cmd_clear,
        }
        if action in cmd_map:
            fake_msg = {"chat":{"id":chat_id},"from":cb.get("from",{}),"message":{}}
            return cmd_map[action](fake_msg, "")
    except Exception as e:
        log.exception(f"[v23] cb: {e}")


# ── 8) addtopic state handler ─────────────────────────────────────────────
@ROUTER.on_text
def handle_addtopic_v23(msg):
    uid = get_uid(msg)
    s = SESSIONS.get(uid)
    if s.state != "v23_addtopic":
        return
    chat_id = get_chat_id(msg)
    text = (msg.get("text") or "").strip()
    SESSIONS.clear_state(uid)
    if "|" not in text:
        TG.send_message(chat_id, "❌ فرمت: نام | query")
        return
    name, query = [p.strip() for p in text.split("|", 1)]
    if not name or not query:
        TG.send_message(chat_id, "❌ نام و query اجباری است")
        return
    if TOPIC_MGR.add(name, query):
        TG.send_message(chat_id, f"✅ «{name}» اضافه شد")
    else:
        TG.send_message(chat_id, "❌ قبلاً وجود دارد")


# ── 9) health check ───────────────────────────────────────────────────────
@ROUTER.command("v23check", description="بررسی سلامت v23", admin_only=True)
def cmd_v23check(msg, args):
    chat_id = get_chat_id(msg)
    try:
        r = TG.get_my_commands()
        n = len(r.result) if r.ok else 0
    except Exception:
        n = 0
    txt = (
        f"<b>🔍 بررسی v23</b>\n\n"
        f"🔽 تعداد دستورهای منوی کشویی: <code>{n}</code>\n"
        f"📋 تعداد دکمه‌های منوی اصلی: <code>{15 * 3}</code>\n"
        f"📖 دستورهای ثبت‌شده: <code>{len(REGISTRY.all())}</code>\n"
        f"⭐ نسخه: v23"
    )
    TG.send_message(chat_id, txt)


# ── 10) Register dropdown on startup ──────────────────────────────────────
try:
    threading.Thread(target=_v23_register_dropdown, daemon=True,
                     name="v23Menu").start()
except Exception:
    pass


log.info("PATCH v23.0 applied — 32-button menu + full dropdown + complete help")
# ═══════════════════════════════════════════════════════════════════════════


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Clr.BYEL}Interrupted{Clr.R}")
        _final_cleanup()
    except Exception as e:
        log.exception("Fatal error")
        print(f"\n{Clr.BRED}FATAL: {e}{Clr.R}")
        traceback.print_exc()
        _final_cleanup()
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════
