#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MAHAN NEMAN BOT
────────────────
• Multi-channel manager (add / remove / toggle)
• Per-channel schedule (list of HH:MM times)
• Topic bank (categorized, Persian + English)
• Auto images (Pollinations, free, no key)
• Full inline-button admin panel
• JSON persistence (state survives restart)
• Background scheduler thread

Run:  BOT_TOKEN=... ADMIN_IDS=123,456 python3 mahanneman_bot.py
"""

import os, sys, json, time, random, threading, traceback
import urllib.request, urllib.parse, urllib.error
from datetime import datetime
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════
TOKEN     = os.environ.get("BOT_TOKEN", "").strip()
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()]
DATA_DIR  = Path(os.environ.get("DATA_DIR", "./data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

if not TOKEN:
    print("ERROR: set BOT_TOKEN env var.")
    sys.exit(1)

CHANNELS_FILE = DATA_DIR / "channels.json"
STATE_FILE    = DATA_DIR / "state.json"
STATS_FILE    = DATA_DIR / "stats.json"
USERS_FILE    = DATA_DIR / "users.json"

# ═══════════════════════════════════════════════════════════════
#  TELEGRAM API
# ═══════════════════════════════════════════════════════════════
API = f"https://api.telegram.org/bot{TOKEN}"

def api(method, payload=None, files=None):
    url = f"{API}/{method}"
    try:
        if files:
            boundary = "----MN" + str(random.randint(1, 10**12))
            parts = []
            for k, v in (payload or {}).items():
                parts.append(
                    f"--{boundary}\r\nContent-Disposition: form-data; "
                    f"name=\"{k}\"\r\n\r\n{v}\r\n".encode()
                )
            for k, (fname, content) in files.items():
                parts.append(
                    f"--{boundary}\r\nContent-Disposition: form-data; "
                    f"name=\"{k}\"; filename=\"{fname}\"\r\n"
                    f"Content-Type: application/octet-stream\r\n\r\n".encode()
                    + content + b"\r\n"
                )
            parts.append(f"--{boundary}--\r\n".encode())
            body = b"".join(parts)
            req = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
            )
        else:
            body = json.dumps(payload or {}).encode("utf-8")
            req = urllib.request.Request(
                url, data=body, headers={"Content-Type": "application/json"}
            )
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:    return json.loads(e.read().decode("utf-8"))
        except Exception: return {"ok": False, "description": str(e)}
    except Exception as e:
        return {"ok": False, "description": str(e)}


def send(chat_id, text, kb=None, parse_mode="HTML"):
    p = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode,
         "disable_web_page_preview": True}
    if kb: p["reply_markup"] = json.dumps(kb)
    return api("sendMessage", p)


def send_photo(chat_id, photo_url, caption="", kb=None):
    p = {"chat_id": chat_id, "photo": photo_url, "caption": caption,
         "parse_mode": "HTML"}
    if kb: p["reply_markup"] = json.dumps(kb)
    return api("sendPhoto", p)


def edit(chat_id, msg_id, text, kb=None):
    p = {"chat_id": chat_id, "message_id": msg_id, "text": text,
         "parse_mode": "HTML", "disable_web_page_preview": True}
    if kb: p["reply_markup"] = json.dumps(kb)
    return api("editMessageText", p)


def answer_cb(cb_id, text="", alert=False):
    return api("answerCallbackQuery",
               {"callback_query_id": cb_id, "text": text, "show_alert": alert})


def delete_msg(chat_id, msg_id):
    return api("deleteMessage", {"chat_id": chat_id, "message_id": msg_id})


# ═══════════════════════════════════════════════════════════════
#  STORAGE
# ═══════════════════════════════════════════════════════════════
def _load(path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _save(path, data):
    try:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(path)
    except Exception as e:
        print(f"[storage] save failed {path}: {e}")


LOCK = threading.Lock()

def load_channels():
    with LOCK:
        return _load(CHANNELS_FILE, {})

def save_channels(d):
    with LOCK:
        _save(CHANNELS_FILE, d)

def load_state():
    with LOCK:
        return _load(STATE_FILE, {})

def save_state(d):
    with LOCK:
        _save(STATE_FILE, d)

def load_stats():
    with LOCK:
        return _load(STATS_FILE, {"sent_total": 0, "sent_today": {},
                                  "last_send": None})

def save_stats(d):
    with LOCK:
        _save(STATS_FILE, d)


# ═══════════════════════════════════════════════════════════════
#  TOPIC BANK
# ═══════════════════════════════════════════════════════════════
TOPICS = {
    "engineering": [
        ("مهندسی مکانیک", "طراحی سیستم‌های مکانیکی، انتقال حرارت، ترمودینامیک و ارتعاشات."),
        ("مهندسی برق", "مدارها، سیگنال، قدرت، کنترل و مخابرات."),
        ("مهندسی عمران", "سازه، بتن، فولاد، ژئوتکنیک و مدیریت پروژه."),
        ("مهندسی شیمی", "فرآیندها، راکتورها، جداسازی و پالایش."),
        ("مهندسی مواد", "آلیاژها، سرامیک‌ها، پلیمرها و کامپوزیت‌ها."),
        ("مهندسی کامپیوتر", "الگوریتم، معماری، شبکه و سیستم‌عامل."),
        ("مهندسی هوافضا", "آیرودینامیک، پیشرانه، مدار و مکانیک پرواز."),
        ("مهندسی پزشکی", "بیومکانیک، سیگنال زیستی و تصویربرداری."),
        ("مهندسی صنایع", "بهینه‌سازی، تحقیق در عملیات و زنجیره تأمین."),
        ("مهندسی نفت", "حفاری، مخازن، بهره‌برداری و پالایش."),
    ],
    "math": [
        ("حساب دیفرانسیل", "حد، مشتق، انتگرال و سری‌های تیلور."),
        ("جبر خطی", "ماتریس، فضای برداری، مقادیر ویژه و SVD."),
        ("معادلات دیفرانسیل", "ODE، PDE و روش‌های عددی."),
        ("آمار و احتمال", "توزیع‌ها، استنباط و آزمون فرض."),
        ("نظریه اعداد", "اعداد اول، همنهشتی و رمزنگاری."),
        ("توپولوژی", "فضاهای متریک، پیوستگی و هم‌شکلی."),
        ("آنالیز عددی", "درون‌یابی، ریشه‌یابی و انتگرال‌گیری عددی."),
        ("بهینه‌سازی", "برنامه‌ریزی خطی، غیرخطی و محدب."),
        ("نظریه گراف", "گراف، مسیر، رنگ‌آمیزی و جریان."),
        ("منطق ریاضی", "گزاره، محمول و اثبات."),
    ],
    "science": [
        ("فیزیک کوانتوم", "اصل عدم قطعیت، درهم‌تنیدگی و دوگانگی موج-ذره."),
        ("نسبیت خاص", "اتساع زمان، انقباض طول و E=mc²."),
        ("نسبیت عام", "گرانش، انحنای فضا-زمان و سیاه‌چاله."),
        ("شیمی آلی", "هیدروکربن‌ها، گروه‌های عاملی و واکنش‌ها."),
        ("زیست‌شناسی سلولی", "غشا، میتوکندری، هسته و تقسیم سلولی."),
        ("ژنتیک", "DNA، RNA، وراثت و جهش."),
        ("زمین‌شناسی", "زمین‌ساخت ورقه‌ای، سنگ‌ها و فسیل."),
        ("اقلیم‌شناسی", "گرمایش جهانی، چرخه کربن و مدل‌های اقلیمی."),
        ("اخترفیزیک", "ستاره‌ها، کهکشان‌ها و کیهان‌شناسی."),
        ("علوم اعصاب", "نورون، سیناپس و مغز."),
    ],
    "psychology": [
        ("روانشناسی شناختی", "حافظه، توجه، ادراک و حل مسئله."),
        ("روانشناسی اجتماعی", "تأثیر گروه، نگرش و تعصب."),
        ("روانشناسی رشد", "مراحل رشد، دلبستگی و بلوغ."),
        ("روانشناسی بالینی", "اختلالات، درمان و ارزیابی."),
        ("روانشناسی مثبت", "شادکامی، فضیلت و معناداری."),
        ("عصب‌روانشناسی", "مغز و رفتار، آسیب‌شناسی."),
        ("روانشناسی یادگیری", "شرطی‌سازی، تقویت و خاموشی."),
        ("روانشناسی سلامت", "استرس، مقابله و بیماری."),
        ("روانشناسی سازمانی", "انگیزش، رهبری و فرهنگ سازمانی."),
        ("تفاوت‌های فردی", "شخصیت، هوش و استعداد."),
    ],
    "tech": [
        ("هوش مصنوعی", "یادگیری ماشین، شبکه عصبی و مدل‌های زبانی."),
        ("یادگیری عمیق", "CNN، RNN، Transformer و GAN."),
        ("علم داده", "پاکسازی، تحلیل و مصورسازی داده."),
        ("امنیت سایبری", "رمزنگاری، نفوذ و دفاع."),
        ("رایانش ابری", "AWS، Azure، GCP و معماری ابری."),
        ("بلاک‌چین", "بیت‌کوین، اتریوم و قرارداد هوشمند."),
        ("اینترنت اشیا", "سنسور، پروتکل و لبه."),
        ("واقعیت مجازی", "VR، AR و متاورس."),
        ("کوانتوم کامپیوتینگ", "کیوبیت، درهم‌تنیدگی و الگوریتم شور."),
        ("رباتیک", "سینماتیک، کنترل و مسیریابی."),
    ],
    "general": [
        ("تاریخ علم", "از یونان باستان تا انقلاب علمی."),
        ("فلسفه علم", "استقرا، ابطال‌پذیری و پارادایم."),
        ("اقتصاد", "عرضه، تقاضا، تورم و رشد."),
        ("مدیریت", "برنامه‌ریزی، سازماندهی و کنترل."),
        ("کارآفرینی", "ایده، MVP و مقیاس‌پذیری."),
        ("زبان‌شناسی", "آوا، نحو، معنا و کاربرد."),
        ("هنر", "نقاشی، موسیقی و معماری."),
        ("ادبیات", "شعر، داستان و نقد."),
        ("تاریخ ایران", "هخامنشیان تا معاصر."),
        ("جغرافیا", "قاره‌ها، اقلیم و جمعیت."),
    ],
}

CATEGORY_FA = {
    "engineering": "مهندسی",
    "math":        "ریاضی",
    "science":     "علوم پایه",
    "psychology":  "روانشناسی",
    "tech":        "فناوری",
    "general":     "عمومی",
}


# ═══════════════════════════════════════════════════════════════
#  CONTENT GENERATOR
# ═══════════════════════════════════════════════════════════════
def make_post(category, channel_title="", with_hashtag=True):
    """Generate one Persian post from a topic."""
    bank = TOPICS.get(category) or TOPICS["general"]
    title, body = random.choice(bank)
    cat_fa = CATEGORY_FA.get(category, category)

    text = (
        f"<b>📚 {title}</b>\n\n"
        f"{body}\n\n"
        f"<i>دسته: {cat_fa}</i>"
    )
    if with_hashtag:
        text += f"\n\n#{category}  #{title.replace(' ', '_')}"
    if channel_title:
        text += f"\n\n🔹 {channel_title}"
    return text, title


def make_image_url(prompt):
    """Free Pollinations image (no key)."""
    safe = urllib.parse.quote(prompt)
    seed = random.randint(1, 999999)
    return f"https://image.pollinations.ai/prompt/{safe}?width=1024&height=1024&nologo=true&seed={seed}"


# ═══════════════════════════════════════════════════════════════
#  SEND TO CHANNEL
# ═══════════════════════════════════════════════════════════════
def publish(channel_id, category, with_image=True, with_hashtag=True, channel_title=""):
    text, title = make_post(category, channel_title=channel_title,
                            with_hashtag=with_hashtag)
    if with_image:
        img = make_image_url(f"{title} {category} illustration minimal")
        r = send_photo(channel_id, img, caption=text)
        if r.get("ok"):
            return True, "photo"
    r = send(channel_id, text)
    if r.get("ok"):
        return True, "text"
    return False, r.get("description", "unknown error")


def record_send():
    s = load_stats()
    s["sent_total"] = s.get("sent_total", 0) + 1
    today = datetime.utcnow().strftime("%Y-%m-%d")
    s.setdefault("sent_today", {})[today] = s["sent_today"].get(today, 0) + 1
    s["last_send"] = datetime.utcnow().isoformat()
    save_stats(s)


# ═══════════════════════════════════════════════════════════════
#  SCHEDULER
# ═══════════════════════════════════════════════════════════════
def scheduler_loop():
    print("[scheduler] started")
    while True:
        try:
            now = datetime.now()
            hhmm = now.strftime("%H:%M")
            today = now.strftime("%Y-%m-%d")
            channels = load_channels()
            state = load_state()

            for cid, ch in channels.items():
                if not ch.get("enabled", True):
                    continue
                times = ch.get("times", [])
                if hhmm not in times:
                    continue
                key = f"{cid}:{today}:{hhmm}"
                if state.get(key):
                    continue

                cats = ch.get("categories") or ["engineering"]
                cat = random.choice(cats)
                title_short = ch.get("title", "")[:40]
                ok, info = publish(
                    int(cid), cat,
                    with_image=ch.get("with_image", True),
                    with_hashtag=ch.get("with_hashtag", True),
                    channel_title=title_short,
                )
                if ok:
                    state[key] = datetime.utcnow().isoformat()
                    save_state(state)
                    record_send()
                    print(f"[scheduler] sent to {cid} @ {hhmm} ({cat}, {info})")
                else:
                    print(f"[scheduler] FAILED {cid} @ {hhmm}: {info}")
        except Exception as e:
            print("[scheduler] error:", e)

        time.sleep(30)


# ═══════════════════════════════════════════════════════════════
#  MENUS
# ═══════════════════════════════════════════════════════════════
def kb(*rows):
    return {"inline_keyboard": [list(r) for r in rows]}

def btn(text, data):
    return {"text": text, "callback_data": data}


def main_menu():
    return kb(
        [btn("📢 کانال‌ها", "menu:channels"), btn("⏰ زمان‌بندی", "menu:sched")],
        [btn("📚 موضوعات", "menu:topics"),   btn("🚀 ارسال فوری", "menu:send")],
        [btn("📊 آمار", "menu:stats"),       btn("⚙️ تنظیمات", "menu:settings")],
        [btn("ℹ️ راهنما", "menu:help")],
    )


def channels_menu():
    ch = load_channels()
    rows = []
    for cid, info in ch.items():
        status = "🟢" if info.get("enabled", True) else "🔴"
        title = (info.get("title") or str(cid))[:25]
        rows.append([btn(f"{status} {title}", f"ch:{cid}")])
    rows.append([btn("➕ افزودن کانال", "ch:add")])
    rows.append([btn("⬅️ بازگشت", "menu:main")])
    return kb(*rows)


def channel_detail(cid):
    ch = load_channels().get(str(cid), {})
    if not ch:
        return kb([btn("⬅️ بازگشت", "menu:channels")])
    enabled = ch.get("enabled", True)
    times = ch.get("times", [])
    cats = ch.get("categories", [])
    rows = [
        [btn(f"{'🔴 خاموش کن' if enabled else '🟢 روشن کن'}", f"ch:{cid}:toggle")],
        [btn(f"⏰ ساعت‌ها ({len(times)})", f"ch:{cid}:times"),
         btn(f"📚 موضوعات ({len(cats)})", f"ch:{cid}:cats")],
        [btn(f"🖼 عکس: {'روشن' if ch.get('with_image', True) else 'خاموش'}", f"ch:{cid}:img"),
         btn(f"#️⃣ هشتگ: {'روشن' if ch.get('with_hashtag', True) else 'خاموش'}", f"ch:{cid}:tag")],
        [btn("🚀 ارسال تست", f"ch:{cid}:test")],
        [btn("🗑 حذف کانال", f"ch:{cid}:del")],
        [btn("⬅️ بازگشت", "menu:channels")],
    ]
    return kb(*rows)


def channel_detail_text(cid):
    ch = load_channels().get(str(cid), {})
    title = ch.get("title") or "—"
    times = ", ".join(ch.get("times", [])) or "—"
    cats = ", ".join(CATEGORY_FA.get(c, c) for c in ch.get("categories", [])) or "—"
    status = "🟢 فعال" if ch.get("enabled", True) else "🔴 غیرفعال"
    return (
        f"<b>📢 {title}</b>\n"
        f"ID: <code>{cid}</code>\n"
        f"وضعیت: {status}\n"
        f"ساعت‌ها: {times}\n"
        f"موضوعات: {cats}\n"
    )


def topics_menu():
    rows = []
    keys = list(TOPICS.keys())
    for i in range(0, len(keys), 2):
        row = [btn(f"📚 {CATEGORY_FA[k]}", f"tp:{k}") for k in keys[i:i+2]]
        rows.append(row)
    rows.append([btn("⬅️ بازگشت", "menu:main")])
    return kb(*rows)


def topic_detail(cat):
    bank = TOPICS.get(cat, [])
    lines = [f"<b>📚 {CATEGORY_FA.get(cat, cat)}</b>", ""]
    for i, (t, b) in enumerate(bank, 1):
        lines.append(f"{i}. <b>{t}</b> — {b}")
    return "\n".join(lines)


def stats_text():
    s = load_stats()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    today_n = s.get("sent_today", {}).get(today, 0)
    ch = load_channels()
    on = sum(1 for c in ch.values() if c.get("enabled", True))
    return (
        "<b>📊 آمار</b>\n\n"
        f"کل ارسال‌ها: <b>{s.get('sent_total', 0)}</b>\n"
        f"امروز: <b>{today_n}</b>\n"
        f"کانال‌ها: <b>{len(ch)}</b> (فعال: {on})\n"
        f"آخرین ارسال: <code>{s.get('last_send') or '—'}</code>"
    )


# ═══════════════════════════════════════════════════════════════
#  ADMIN STATE (multi-step flows)
# ═══════════════════════════════════════════════════════════════
PENDING = {}  # user_id -> {"action": ..., "data": ...}


def is_admin(uid):
    return not ADMIN_IDS or uid in ADMIN_IDS


# ═══════════════════════════════════════════════════════════════
#  HANDLERS
# ═══════════════════════════════════════════════════════════════
def handle_message(msg):
    uid = msg.get("from", {}).get("id")
    chat_id = msg.get("chat", {}).get("id")
    text = (msg.get("text") or "").strip()

    if not is_admin(uid):
        send(chat_id, "⛔️ شما ادمین نیستید.")
        return

    # multi-step flows
    if uid in PENDING:
        flow = PENDING.pop(uid)
        act = flow["action"]

        if act == "add_channel":
            # expect a forwarded message from a channel
            fc = msg.get("forward_from_chat") or {}
            fcid = fc.get("id")
            if not fcid:
                send(chat_id, "❌ این پیام از کانال فوروارد نشده. دوباره امتحان کن.",
                     kb([btn("⬅️ بازگشت", "menu:main")]))
                return
            ch = load_channels()
            ch[str(fcid)] = {
                "title": fc.get("title", str(fcid)),
                "enabled": True,
                "times": ["09:00", "15:00", "21:00"],
                "categories": ["engineering", "science", "tech"],
                "with_image": True,
                "with_hashtag": True,
            }
            save_channels(ch)
            send(chat_id,
                 f"✅ کانال اضافه شد:\n<b>{fc.get('title')}</b>\n"
                 f"ID: <code>{fcid}</code>\n\n"
                 f"ساعت‌های پیش‌فرض: 09:00، 15:00، 21:00\n"
                 f"موضوعات پیش‌فرض: مهندسی، علوم، فناوری",
                 kb([btn("⚙️ تنظیمات کانال", f"ch:{fcid}"),
                     btn("📢 لیست کانال‌ها", "menu:channels")]))
            return

        if act == "set_times":
            cid = flow["data"]["cid"]
            # expected: "09:00, 15:00, 21:30"
            parts = [p.strip() for p in text.replace("،", ",").split(",") if p.strip()]
            valid = []
            for p in parts:
                try:
                    h, m = p.split(":")
                    h, m = int(h), int(m)
                    if 0 <= h < 24 and 0 <= m < 60:
                        valid.append(f"{h:02d}:{m:02d}")
                except Exception:
                    pass
            if not valid:
                send(chat_id, "❌ فرمت اشتباه. مثال: <code>09:00, 15:00, 21:30</code>")
                return
            ch = load_channels()
            if str(cid) in ch:
                ch[str(cid)]["times"] = valid
                save_channels(ch)
            send(chat_id, f"✅ ساعت‌ها ذخیره شد: {', '.join(valid)}",
                 kb([btn("⬅️ بازگشت به کانال", f"ch:{cid}")]))
            return

        if act == "set_cats":
            cid = flow["data"]["cid"]
            keys = list(TOPICS.keys())
            nums = []
            for p in text.replace("،", ",").split(","):
                p = p.strip()
                if p.isdigit():
                    n = int(p)
                    if 1 <= n <= len(keys):
                        nums.append(keys[n-1])
            if not nums:
                send(chat_id, "❌ شماره‌های معتبر بده. مثال: <code>1, 3, 5</code>")
                return
            ch = load_channels()
            if str(cid) in ch:
                ch[str(cid)]["categories"] = nums
                save_channels(ch)
            send(chat_id,
                 f"✅ موضوعات ذخیره شد: {', '.join(CATEGORY_FA[n] for n in nums)}",
                 kb([btn("⬅️ بازگشت به کانال", f"ch:{cid}")]))
            return

        if act == "send_now":
            cid = flow["data"]["cid"]
            nums = [int(p) for p in text.replace("،", ",").split(",") if p.strip().isdigit()]
            keys = list(TOPICS.keys())
            cat = keys[nums[0]-1] if nums and 1 <= nums[0] <= len(keys) else "engineering"
            ch = load_channels().get(str(cid), {})
            ok, info = publish(int(cid), cat,
                              with_image=ch.get("with_image", True),
                              with_hashtag=ch.get("with_hashtag", True),
                              channel_title=ch.get("title", ""))
            if ok:
                record_send()
                send(chat_id, f"✅ ارسال شد به کانال ({info}).")
            else:
                send(chat_id, f"❌ ناموفق: {info}")
            return

    # normal commands
    if text.startswith("/start") or text == "/menu" or text == "منو":
        send(chat_id,
             "<b>🤖 ربات ماهان‌نمان</b>\n\n"
             "از دکمه‌های زیر استفاده کن:",
             main_menu())
        return

    if text == "/help":
        send(chat_id,
             "<b>ℹ️ راهنما</b>\n\n"
             "1) کانال اضافه کن (ربات رو ادمین کانال کن، بعد یه پیام از کانال برام فوروارد کن)\n"
             "2) ساعت‌ها و موضوعات هر کانال رو تنظیم کن\n"
             "3) ربات خودش سر ساعت پست می‌فرسته\n\n"
             "دستورات:\n"
             "/start — منو\n"
             "/stats — آمار\n"
             "/help — این پیام",
             kb([btn("⬅️ منو", "menu:main")]))
        return

    if text == "/stats":
        send(chat_id, stats_text(), kb([btn("⬅️ منو", "menu:main")]))
        return

    send(chat_id, "متوجه نشدم. از /start استفاده کن.")


def handle_callback(cb):
    uid = cb.get("from", {}).get("id")
    chat_id = cb["message"]["chat"]["id"]
    msg_id = cb["message"]["message_id"]
    data = cb.get("data", "")

    if not is_admin(uid):
        answer_cb(cb["id"], "⛔️ ادمین نیستید.", alert=True)
        return

    answer_cb(cb["id"])

    if data == "menu:main":
        edit(chat_id, msg_id,
             "<b>🤖 ربات ماهان‌نمان</b>\n\nاز دکمه‌ها استفاده کن:",
             main_menu())
        return

    if data == "menu:channels":
        edit(chat_id, msg_id, "<b>📢 کانال‌ها</b>\n\nروی هر کانال بزن:",
             channels_menu())
        return

    if data == "menu:sched":
        ch = load_channels()
        lines = ["<b>⏰ زمان‌بندی</b>", ""]
        for cid, info in ch.items():
            times = ", ".join(info.get("times", [])) or "—"
            lines.append(f"• <b>{info.get('title', cid)}</b> → {times}")
        if not ch:
            lines.append("هنوز کانالی اضافه نشده.")
        edit(chat_id, msg_id, "\n".join(lines),
             kb([btn("⬅️ منو", "menu:main")]))
        return

    if data == "menu:topics":
        edit(chat_id, msg_id, "<b>📚 موضوعات</b>\n\nیه دسته انتخاب کن:",
             topics_menu())
        return

    if data.startswith("tp:"):
        cat = data.split(":", 1)[1]
        edit(chat_id, msg_id, topic_detail(cat),
             kb([btn("⬅️ موضوعات", "menu:topics"),
                 btn("⬅️ منو", "menu:main")]))
        return

    if data == "menu:stats":
        edit(chat_id, msg_id, stats_text(), kb([btn("⬅️ منو", "menu:main")]))
        return

    if data == "menu:settings":
        edit(chat_id, msg_id,
             "<b>⚙️ تنظیمات</b>\n\n"
             "برای هر کانال، تنظیمات جدا از صفحهٔ همون کانال قابل تغییره.",
             kb([btn("📢 کانال‌ها", "menu:channels"), btn("⬅️ منو", "menu:main")]))
        return

    if data == "menu:help":
        edit(chat_id, msg_id,
             "<b>ℹ️ راهنما</b>\n\n"
             "۱) کانال اضافه کن\n"
             "۲) ساعت و موضوع تنظیم کن\n"
             "۳) ربات خودش پست می‌فرسته",
             kb([btn("⬅️ منو", "menu:main")]))
        return

    if data == "ch:add":
        PENDING[uid] = {"action": "add_channel"}
        edit(chat_id, msg_id,
             "<b>➕ افزودن کانال</b>\n\n"
             "۱) ربات رو توی کانالت <b>ادمین</b> کن\n"
             "۲) یه پیام از کانال رو برای من <b>فوروارد</b> کن\n\n"
             "منتظر فوروارد هستم...",
             kb([btn("❌ لغو", "menu:channels")]))
        return

    if data == "menu:send":
        ch = load_channels()
        rows = []
        for cid, info in ch.items():
            rows.append([btn(f"📤 {info.get('title', cid)[:25]}", f"send:{cid}")])
        rows.append([btn("⬅️ منو", "menu:main")])
        edit(chat_id, msg_id, "<b>🚀 ارسال فوری</b>\n\nیه کانال انتخاب کن:",
             kb(*rows))
        return

    if data.startswith("send:"):
        cid = data.split(":", 1)[1]
        keys = list(TOPICS.keys())
        lines = ["<b>🚀 ارسال فوری</b>", "", "شمارهٔ دسته رو بفرست:"]
        for i, k in enumerate(keys, 1):
            lines.append(f"{i}) {CATEGORY_FA[k]}")
        PENDING[uid] = {"action": "send_now", "data": {"cid": cid}}
        edit(chat_id, msg_id, "\n".join(lines),
             kb([btn("⬅️ لغو", "menu:main")]))
        return

    # channel detail
    if data.startswith("ch:"):
        parts = data.split(":")
        cid = parts[1]
        action = parts[2] if len(parts) > 2 else None

        if action is None:
            edit(chat_id, msg_id, channel_detail_text(cid), channel_detail(cid))
            return

        ch = load_channels()
        if str(cid) not in ch:
            edit(chat_id, msg_id, "❌ کانال پیدا نشد.", kb([btn("⬅️", "menu:channels")]))
            return

        if action == "toggle":
            ch[str(cid)]["enabled"] = not ch[str(cid)].get("enabled", True)
            save_channels(ch)
            edit(chat_id, msg_id, channel_detail_text(cid), channel_detail(cid))
            return

        if action == "img":
            ch[str(cid)]["with_image"] = not ch[str(cid)].get("with_image", True)
            save_channels(ch)
            edit(chat_id, msg_id, channel_detail_text(cid), channel_detail(cid))
            return

        if action == "tag":
            ch[str(cid)]["with_hashtag"] = not ch[str(cid)].get("with_hashtag", True)
            save_channels(ch)
            edit(chat_id, msg_id, channel_detail_text(cid), channel_detail(cid))
            return

        if action == "times":
            PENDING[uid] = {"action": "set_times", "data": {"cid": cid}}
            edit(chat_id, msg_id,
                 "<b>⏰ تنظیم ساعت‌ها</b>\n\n"
                 "ساعت‌ها رو با کاما جدا کن.\n"
                 "مثال: <code>09:00, 15:00, 21:30</code>",
                 kb([btn("⬅️ لغو", f"ch:{cid}")]))
            return

        if action == "cats":
            keys = list(TOPICS.keys())
            lines = ["<b>📚 تنظیم موضوعات</b>", "",
                     "شماره‌ها رو با کاما بفرست. مثال: <code>1, 3, 5</code>", ""]
            for i, k in enumerate(keys, 1):
                lines.append(f"{i}) {CATEGORY_FA[k]}")
            PENDING[uid] = {"action": "set_cats", "data": {"cid": cid}}
            edit(chat_id, msg_id, "\n".join(lines),
                 kb([btn("⬅️ لغو", f"ch:{cid}")]))
            return

        if action == "test":
            info_ch = ch[str(cid)]
            cat = random.choice(info_ch.get("categories") or ["engineering"])
            edit(chat_id, msg_id, f"⏳ در حال ارسال تست به کانال...")
            ok, info = publish(int(cid), cat,
                              with_image=info_ch.get("with_image", True),
                              with_hashtag=info_ch.get("with_hashtag", True),
                              channel_title=info_ch.get("title", ""))
            if ok:
                record_send()
                edit(chat_id, msg_id, f"✅ ارسال تست موفق ({info}).",
                     kb([btn("⬅️ کانال", f"ch:{cid}")]))
            else:
                edit(chat_id, msg_id, f"❌ ناموفق: {info}",
                     kb([btn("⬅️ کانال", f"ch:{cid}")]))
            return

        if action == "del":
            del ch[str(cid)]
            save_channels(ch)
            edit(chat_id, msg_id, "🗑 کانال حذف شد.", channels_menu())
            return

    edit(chat_id, msg_id, "گزینهٔ نامعتبر.", main_menu())


# ═══════════════════════════════════════════════════════════════
#  POLLING LOOP
# ═══════════════════════════════════════════════════════════════
def set_commands():
    commands = [
        {"command": "start", "description": "منوی اصلی"},
        {"command": "stats", "description": "آمار"},
        {"command": "help",  "description": "راهنما"},
    ]
    return api("setMyCommands", {"commands": commands})


def poll_loop():
    print("[poll] started")
    offset = 0
    while True:
        try:
            r = api("getUpdates", {"offset": offset, "timeout": 30,
                                   "allowed_updates": ["message", "callback_query"]})
            if not r.get("ok"):
                print("[poll] api error:", r.get("description"))
                time.sleep(3)
                continue
            for upd in r.get("result", []):
                offset = upd["update_id"] + 1
                try:
                    if "message" in upd:
                        handle_message(upd["message"])
                    elif "callback_query" in upd:
                        handle_callback(upd["callback_query"])
                except Exception as e:
                    print("[poll] handler error:", e)
                    traceback.print_exc()
        except Exception as e:
            print("[poll] loop error:", e)
            time.sleep(3)


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    print("=" * 60)
    print(" MAHAN NEMAN BOT")
    print("=" * 60)
    me = api("getMe")
    if not me.get("ok"):
        print("ERROR: cannot reach Telegram:", me.get("description"))
        sys.exit(1)
    print("Bot:", me["result"]["username"], f"(id={me['result']['id']})")
    print("Admins:", ADMIN_IDS or "(anyone)")
    print("Data dir:", DATA_DIR.resolve())

    set_commands()

    # scheduler in background
    t = threading.Thread(target=scheduler_loop, daemon=True)
    t.start()

    # polling in main thread
    poll_loop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nbye")