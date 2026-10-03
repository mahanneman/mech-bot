#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MAHAN NEMAN BOT — Professional Edition
───────────────────────────────────────
• 50+ features: multi-channel, per-channel schedule, AI content,
  RSS news, Wikipedia, arXiv, images, tools, backups, stats, etc.
• Fully inline-keyboard driven
• JSON persistence
• Background scheduler
• No external deps (stdlib only)

Run:  BOT_TOKEN=xxx ADMIN_IDS=5484310778 python3 mahanneman_bot.py
"""

import os, sys, json, time, random, threading, traceback, hashlib
import urllib.request, urllib.parse, urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════
TOKEN     = os.environ.get("BOT_TOKEN", "").strip()
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "5484310778")
             .replace(" ", "").split(",") if x.isdigit()]
DATA_DIR  = Path(os.environ.get("DATA_DIR", "./data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

if not TOKEN:
    print("ERROR: set BOT_TOKEN env var.")
    sys.exit(1)

F_CHANNELS = DATA_DIR / "channels.json"
F_STATE    = DATA_DIR / "state.json"
F_STATS    = DATA_DIR / "stats.json"
F_CONFIG   = DATA_DIR / "config.json"
F_TOPICS   = DATA_DIR / "topics.json"
F_DRAFTS   = DATA_DIR / "drafts.json"
F_LOGS     = DATA_DIR / "logs.json"
F_TEMPLATES= DATA_DIR / "templates.json"

# ═══════════════════════════════════════════════════════════════
# TELEGRAM API
# ═══════════════════════════════════════════════════════════════
API = f"https://api.telegram.org/bot{TOKEN}"

def api(method, payload=None):
    try:
        body = json.dumps(payload or {}).encode("utf-8")
        req = urllib.request.Request(
            f"{API}/{method}", data=body,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:    return json.loads(e.read().decode("utf-8"))
        except Exception: return {"ok": False, "description": str(e)}
    except Exception as e:
        return {"ok": False, "description": str(e)}

def send(chat_id, text, kb=None, pm="HTML"):
    p = {"chat_id": chat_id, "text": text[:4096], "parse_mode": pm,
         "disable_web_page_preview": True}
    if kb: p["reply_markup"] = kb
    return api("sendMessage", p)

def send_photo(chat_id, url, caption="", kb=None):
    p = {"chat_id": chat_id, "photo": url, "caption": caption[:1024],
         "parse_mode": "HTML"}
    if kb: p["reply_markup"] = kb
    return api("sendPhoto", p)

def send_audio(chat_id, url, caption="", kb=None):
    p = {"chat_id": chat_id, "audio": url, "caption": caption[:1024],
         "parse_mode": "HTML"}
    if kb: p["reply_markup"] = kb
    return api("sendAudio", p)

def edit(chat_id, msg_id, text, kb=None):
    p = {"chat_id": chat_id, "message_id": msg_id, "text": text[:4096],
         "parse_mode": "HTML", "disable_web_page_preview": True}
    if kb: p["reply_markup"] = kb
    r = api("editMessageText", p)
    if not r.get("ok") and "not modified" not in (r.get("description") or ""):
        pass
    return r

def answer_cb(cb_id, text="", alert=False):
    return api("answerCallbackQuery",
               {"callback_query_id": cb_id, "text": text, "show_alert": alert})

def delete_msg(chat_id, msg_id):
    return api("deleteMessage", {"chat_id": chat_id, "message_id": msg_id})

def pin_msg(chat_id, msg_id, notify=False):
    return api("pinChatMessage",
               {"chat_id": chat_id, "message_id": msg_id,
                "disable_notification": not notify})

# ═══════════════════════════════════════════════════════════════
# STORAGE
# ═══════════════════════════════════════════════════════════════
_LOCK = threading.Lock()

def _load(p, d):
    try:
        if p.exists(): return json.loads(p.read_text(encoding="utf-8"))
    except Exception: pass
    return d

def _save(p, data):
    try:
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(p)
    except Exception as e:
        print(f"[save] {p}: {e}")

def get(path, default):
    with _LOCK: return _load(path, default)

def put(path, data):
    with _LOCK: _save(path, data)

# ── helpers ────────────────────────────────────────────────
def channels():    return get(F_CHANNELS, {})
def save_channels(d): put(F_CHANNELS, d)
def state():       return get(F_STATE, {})
def save_state(d): put(F_STATE, d)
def stats():       return get(F_STATS, {"total":0,"today":{},"last":None})
def save_stats(d): put(F_STATS, d)
def config():      return get(F_CONFIG, {"global_enabled": True,
                                          "default_tz_offset": 3.5,
                                          "default_times": ["09:00","15:00","21:00"],
                                          "default_cats": ["engineering","science","tech"],
                                          "language": "fa"})
def save_config(d): put(F_CONFIG, d)
def topics_store():return get(F_TOPICS, {})
def save_topics(d):put(F_TOPICS, d)
def drafts():      return get(F_DRAFTS, {})
def save_drafts(d):put(F_DRAFTS, d)
def logs():        return get(F_LOGS, [])
def templates():   return get(F_TEMPLATES, {})
def save_templates(d): put(F_TEMPLATES, d)

def log_event(kind, msg):
    L = logs()
    L.append({"t": datetime.utcnow().isoformat(), "k": kind, "m": str(msg)[:400]})
    put(F_LOGS, L[-300:])

# ═══════════════════════════════════════════════════════════════
# TOPIC BANK
# ═══════════════════════════════════════════════════════════════
DEFAULT_TOPICS = {
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
    "motivation": [
        ("انگیزه درونی", "قدرت درون برای تغییر و پیشرفت."),
        ("عادت‌سازی", "ساختن عادت‌های کوچک و پایدار."),
        ("زمان‌بندی", "مدیریت زمان و اولویت‌ها."),
        ("تمرکز", "ذهن‌آگاهی و کنترل توجه."),
        ("موفقیت", "مسیر رسیدن به اهداف بلندمدت."),
    ],
    "news": [
        ("فناوری روز", "آخرین خبرهای فناوری و استارتاپ."),
        ("هوش مصنوعی", "خبرهای تازه از دنیای AI."),
        ("علم و دانش", "اکتشافات و پژوهش‌های تازه."),
        ("فضا", "ماموریت‌ها و کشفیات فضایی."),
        ("پزشکی", "پیشرفت‌های پزشکی و سلامت."),
    ],
}

CATEGORY_FA = {
    "engineering": "مهندسی",
    "math":        "ریاضی",
    "science":     "علوم پایه",
    "psychology":  "روانشناسی",
    "tech":        "فناوری",
    "general":     "عمومی",
    "motivation":  "انگیزشی",
    "news":        "اخبار",
}

def ensure_topics():
    store = topics_store()
    changed = False
    for k, v in DEFAULT_TOPICS.items():
        if k not in store:
            store[k] = [{"title": t, "body": b} for t, b in v]
            changed = True
    if changed: save_topics(store)

def all_categories():
    return list(topics_store().keys()) or list(DEFAULT_TOPICS.keys())

def pick_topic(cat):
    store = topics_store()
    bank = store.get(cat) or [{"title": t, "body": b}
                              for t, b in DEFAULT_TOPICS.get(cat, DEFAULT_TOPICS["general"])]
    return random.choice(bank)

# ═══════════════════════════════════════════════════════════════
# CONTENT
# ═══════════════════════════════════════════════════════════════
def make_text(cat, channel_title="", hashtag=True, style="normal"):
    t = pick_topic(cat)
    title = t["title"]; body = t["body"]
    cat_fa = CATEGORY_FA.get(cat, cat)
    if style == "formal":
        s = (f"<b>📘 {title}</b>\n\n"
             f"<i>دسته‌بندی:</i> {cat_fa}\n\n"
             f"{body}")
    elif style == "short":
        s = f"<b>{title}</b>\n{body}"
    else:
        s = (f"<b>📚 {title}</b>\n\n{body}\n\n"
             f"<i>دسته: {cat_fa}</i>")
    if hashtag:
        s += f"\n\n#{cat}  #{title.replace(' ', '_')}"
    if channel_title:
        s += f"\n\n🔹 {channel_title}"
    return s, title

def image_url(prompt):
    seed = random.randint(1, 999999)
    return (f"https://image.pollinations.ai/prompt/"
            f"{urllib.parse.quote(prompt[:180])}"
            f"?width=1024&height=1024&nologo=true&seed={seed}")

def publish(channel_id, cat, with_image=True, hashtag=True,
            channel_title="", style="normal"):
    text, title = make_text(cat, channel_title, hashtag, style)
    if with_image:
        r = send_photo(channel_id, image_url(f"{title} illustration"), caption=text)
        if r.get("ok"): return True, "photo", r["result"]["message_id"]
    r = send(channel_id, text)
    if r.get("ok"): return True, "text", r["result"]["message_id"]
    return False, r.get("description", "unknown"), None

def bump_stats():
    s = stats()
    s["total"] = s.get("total", 0) + 1
    today = datetime.utcnow().strftime("%Y-%m-%d")
    s.setdefault("today", {})[today] = s.get("today", {}).get(today, 0) + 1
    s["last"] = datetime.utcnow().isoformat()
    save_stats(s)

# ═══════════════════════════════════════════════════════════════
# RSS / NEWS
# ═══════════════════════════════════════════════════════════════
RSS_FEEDS = {
    "bbc_world":   ("BBC World",       "https://feeds.bbci.co.uk/news/world/rss.xml"),
    "bbc_tech":    ("BBC Tech",        "https://feeds.bbci.co.uk/news/technology/rss.xml"),
    "bbc_sci":     ("BBC Science",     "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml"),
    "reuters":     ("Reuters Top",     "https://feeds.reuters.com/reuters/topNews"),
    "sciencedaily":("ScienceDaily",    "https://www.sciencedaily.com/rss/top/science.xml"),
    "irna":        ("IRNA EN",         "https://en.irna.ir/rss"),
    "nasa":        ("NASA",            "https://www.nasa.gov/rss/dyn/breaking_news.rss"),
    "hn":          ("Hacker News",     "https://hnrss.org/frontpage"),
    "arstech":     ("Ars Technica",    "https://feeds.arstechnica.com/arstechnica/index"),
    "physorg":     ("Phys.org",        "https://phys.org/rss-feed/"),
}

def fetch_rss(key, limit=5):
    if key not in RSS_FEEDS: return None
    _, url = RSS_FEEDS[key]
    try:
        req = urllib.request.Request(url, headers={"User-Agent":"MahanBot/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
        root = ET.fromstring(data)
        items = root.findall(".//item")[:limit]
        out = []
        for it in items:
            out.append({
                "title": (it.findtext("title") or "").strip(),
                "link":  (it.findtext("link") or "").strip(),
                "desc":  (it.findtext("description") or "")[:200].strip(),
            })
        return out
    except Exception as e:
        log_event("rss_error", f"{key}: {e}")
        return None

# ═══════════════════════════════════════════════════════════════
# WIKI / ARXIV
# ═══════════════════════════════════════════════════════════════
def wiki_summary(term, lang="en"):
    try:
        url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/" + \
              urllib.parse.quote(term.replace(" ", "_"))
        req = urllib.request.Request(url, headers={"User-Agent":"MahanBot/1.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            d = json.loads(r.read().decode())
        return {"title": d.get("title"), "extract": d.get("extract", "")}
    except Exception:
        return None

def arxiv_search(q, limit=5):
    try:
        url = "http://export.arxiv.org/api/query?" + urllib.parse.urlencode({
            "search_query": f"all:{q}", "start":0, "max_results":limit})
        req = urllib.request.Request(url, headers={"User-Agent":"MahanBot/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            content = r.read()
        root = ET.fromstring(content)
        ns = {"a":"http://www.w3.org/2005/Atom"}
        out = []
        for e in root.findall("a:entry", ns):
            out.append({
                "title": (e.findtext("a:title", default="", namespaces=ns) or "").strip(),
                "link":  e.findtext("a:id", default="", namespaces=ns),
            })
        return out
    except Exception:
        return None

# ═══════════════════════════════════════════════════════════════
# SCHEDULER
# ═══════════════════════════════════════════════════════════════
def scheduler_loop():
    print("[scheduler] started")
    while True:
        try:
            cfg = config()
            if not cfg.get("global_enabled", True):
                time.sleep(30); continue
            now = datetime.now()
            hhmm = now.strftime("%H:%M")
            today = now.strftime("%Y-%m-%d")
            ch = channels()
            st = state()
            for cid, info in ch.items():
                if not info.get("enabled", True): continue
                if hhmm not in info.get("times", []): continue
                key = f"{cid}:{today}:{hhmm}"
                if st.get(key): continue
                cats = info.get("categories") or cfg["default_cats"]
                cat = random.choice(cats)
                ok, mode, mid = publish(
                    int(cid), cat,
                    with_image=info.get("with_image", True),
                    hashtag=info.get("with_hashtag", True),
                    channel_title=info.get("title", ""),
                    style=info.get("style", "normal"),
                )
                if ok:
                    st[key] = datetime.utcnow().isoformat()
                    save_state(st)
                    bump_stats()
                    log_event("send", f"{cid} @ {hhmm} ({cat}, {mode})")
                    if info.get("pin", False) and mid:
                        pin_msg(int(cid), mid)
                    print(f"[sched] sent → {cid} @ {hhmm} ({cat})")
                else:
                    log_event("send_fail", f"{cid} @ {hhmm}: {mode}")
        except Exception as e:
            log_event("sched_err", e)
        time.sleep(30)

# ═══════════════════════════════════════════════════════════════
# KEYBOARDS
# ═══════════════════════════════════════════════════════════════
def B(text, data): return {"text": text, "callback_data": data}
def KB(*rows): return {"inline_keyboard": [list(r) for r in rows]}

def main_menu():
    return KB(
        [B("📢 کانال‌ها", "m:ch"),      B("⏰ زمان‌بندی", "m:sched")],
        [B("📚 موضوعات", "m:topics"),    B("📰 اخبار", "m:news")],
        [B("🔍 ویکی", "m:wiki"),         B("📄 arXiv", "m:arxiv")],
        [B("🚀 ارسال فوری", "m:send"),   B("🎨 ساخت عکس", "m:image")],
        [B("✍️ پیش‌نویس", "m:drafts"),   B("🧩 تمپلیت", "m:tmpl")],
        [B("📊 آمار", "m:stats"),        B("📋 لاگ", "m:logs")],
        [B("⚙️ تنظیمات", "m:settings"),  B("🛠 ابزارها", "m:tools")],
        [B("💾 بکاپ/ریستور", "m:backup"),B("🧪 تست", "m:test")],
        [B("ℹ️ راهنما", "m:help"),       B("🌐 وضعیت", "m:health")],
    )

def channels_menu():
    ch = channels()
    rows = []
    for cid, info in ch.items():
        status = "🟢" if info.get("enabled", True) else "🔴"
        title = (info.get("title") or str(cid))[:24]
        rows.append([B(f"{status} {title}", f"ch:{cid}")])
    rows.append([B("➕ افزودن کانال", "ch:add"),
                 B("📦 افزودن دسته‌ای", "ch:bulk")])
    rows.append([B("⬅️ بازگشت", "m:main")])
    return KB(*rows)

def channel_detail_kb(cid):
    ch = channels().get(str(cid), {})
    if not ch: return KB([B("⬅️ بازگشت", "m:ch")])
    en = ch.get("enabled", True)
    img = ch.get("with_image", True)
    tag = ch.get("with_hashtag", True)
    pin = ch.get("pin", False)
    return KB(
        [B(f"{'🔴 خاموش کن' if en else '🟢 روشن کن'}", f"ch:{cid}:toggle")],
        [B(f"⏰ ساعت‌ها ({len(ch.get('times', []))})", f"ch:{cid}:times"),
         B(f"📚 موضوعات ({len(ch.get('categories', []))})", f"ch:{cid}:cats")],
        [B(f"🖼 عکس: {'✅' if img else '❌'}", f"ch:{cid}:img"),
         B(f"#️⃣ هشتگ: {'✅' if tag else '❌'}", f"ch:{cid}:tag")],
        [B(f"📌 پین: {'✅' if pin else '❌'}", f"ch:{cid}:pin"),
         B(f"🎨 سبک: {ch.get('style', 'normal')}", f"ch:{cid}:style")],
        [B("🚀 ارسال تست", f"ch:{cid}:test")],
        [B("✏️ نام", f"ch:{cid}:rename"),
         B("🗑 حذف", f"ch:{cid}:del")],
        [B("⬅️ بازگشت", "m:ch")],
    )

def channel_detail_txt(cid):
    ch = channels().get(str(cid), {})
    title = ch.get("title") or "—"
    times = ", ".join(ch.get("times", [])) or "—"
    cats = ", ".join(CATEGORY_FA.get(c, c) for c in ch.get("categories", [])) or "—"
    st = "🟢 فعال" if ch.get("enabled", True) else "🔴 غیرفعال"
    return (f"<b>📢 {title}</b>\n"
            f"ID: <code>{cid}</code>\n"
            f"وضعیت: {st}\n"
            f"ساعت‌ها: <code>{times}</code>\n"
            f"موضوعات: {cats}\n"
            f"سبک: {ch.get('style', 'normal')}")

def topics_menu():
    cats = all_categories()
    rows = []
    for i in range(0, len(cats), 2):
        row = [B(f"📚 {CATEGORY_FA.get(c, c)}", f"tp:{c}") for c in cats[i:i+2]]
        rows.append(row)
    rows.append([B("➕ افزودن موضوع", "tp:add"),
                 B("🗑 حذف موضوع", "tp:del")])
    rows.append([B("⬅️ بازگشت", "m:main")])
    return KB(*rows)

def news_menu():
    return KB(
        [B("🌍 BBC World", "nw:bbc_world"),
         B("💻 BBC Tech", "nw:bbc_tech")],
        [B("🔬 BBC Science", "nw:bbc_sci"),
         B("📡 NASA", "nw:nasa")],
        [B("🔬 ScienceDaily", "nw:sciencedaily"),
         B("🇮🇷 IRNA", "nw:irna")],
        [B("💾 Hacker News", "nw:hn"),
         B("📰 Reuters", "nw:reuters")],
        [B("⚗️ Phys.org", "nw:physorg"),
         B("🔧 Ars Technica", "nw:arstech")],
        [B("📢 ارسال خبر به کانال", "nw:send")],
        [B("⬅️ بازگشت", "m:main")],
    )

def tools_menu():
    return KB(
        [B("🧮 ماشین‌حساب", "t:calc"),  B("🎲 عدد تصادفی", "t:rand")],
        [B("🔐 UUID", "t:uuid"),         B("🔑 پسورد", "t:pass")],
        [B("📅 تاریخ/ساعت", "t:time"),   B("🌐 IP", "t:ip")],
        [B("🔤 Base64 انکد", "t:b64e"),  B("🔤 Base64 دیکد", "t:b64d")],
        [B("🔢 اعداد اول", "t:prime"),   B("📊 Fibonacci", "t:fib")],
        [B("🎵 موسیقی تصادفی", "t:music"),B("😂 جوک", "t:joke")],
        [B("💡 نقل‌قول", "t:quote"),     B("📖 کتاب تصادفی", "t:book")],
        [B("🌤 آب‌وهوا تهران", "t:weather")],
        [B("⬅️ بازگشت", "m:main")],
    )

def settings_menu():
    cfg = config()
    ge = cfg.get("global_enabled", True)
    return KB(
        [B(f"🌐 ربات: {'🟢 فعال' if ge else '🔴 غیرفعال'}", "st:global")],
        [B(f"🕐 ساعت پیش‌فرض: {','.join(cfg.get('default_times', []))}", "st:dtimes")],
        [B(f"📚 دسته‌های پیش‌فرض ({len(cfg.get('default_cats', []))})", "st:dcats")],
        [B(f"🌍 منطقه زمانی: UTC+{cfg.get('default_tz_offset', 3.5)}", "st:tz")],
        [B("🔄 ریست تنظیمات", "st:reset")],
        [B("⬅️ بازگشت", "m:main")],
    )

def backup_menu():
    return KB(
        [B("💾 دانلود بکاپ کامل", "bk:download")],
        [B("📤 خروجی کانال‌ها", "bk:channels")],
        [B("📤 خروجی موضوعات", "bk:topics")],
        [B("📤 خروجی آمار", "bk:stats")],
        [B("♻️ ریست همه چیز", "bk:reset")],
        [B("⬅️ بازگشت", "m:main")],
    )

def help_menu():
    return KB([B("⬅️ بازگشت", "m:main")])

# ═══════════════════════════════════════════════════════════════
# PENDING FLOWS
# ═══════════════════════════════════════════════════════════════
PENDING = {}

def is_admin(uid): return not ADMIN_IDS or uid in ADMIN_IDS

# ═══════════════════════════════════════════════════════════════
# MESSAGE HANDLER
# ═══════════════════════════════════════════════════════════════
def handle_message(msg):
    uid = msg.get("from", {}).get("id")
    chat_id = msg.get("chat", {}).get("id")
    text = (msg.get("text") or "").strip()

    if not is_admin(uid):
        send(chat_id, "⛔️ شما ادمین نیستید.")
        return

    # Pending flows
    if uid in PENDING:
        flow = PENDING.pop(uid)
        act = flow["action"]
        data = flow.get("data", {})

        if act == "add_channel":
            fc = msg.get("forward_from_chat") or {}
            fcid = fc.get("id")
            if not fcid:
                send(chat_id, "❌ این پیام از کانال فوروارد نشده. دوباره تلاش کن.",
                     KB([B("⬅️ بازگشت", "m:main")]))
                return
            ch = channels()
            ch[str(fcid)] = {
                "title": fc.get("title", str(fcid)),
                "enabled": True,
                "times": config()["default_times"],
                "categories": config()["default_cats"],
                "with_image": True,
                "with_hashtag": True,
                "pin": False,
                "style": "normal",
            }
            save_channels(ch)
            send(chat_id,
                 f"✅ کانال اضافه شد: <b>{fc.get('title')}</b>\n"
                 f"ID: <code>{fcid}</code>",
                 KB([B("⚙️ تنظیمات کانال", f"ch:{fcid}"),
                     B("📢 لیست", "m:ch")]))
            return

        if act == "bulk_channels":
            # text contains comma-separated:  id:title, id:title
            ch = channels()
            added = 0
            for part in text.split(","):
                part = part.strip()
                if not part: continue
                if ":" in part:
                    cid, title = part.split(":", 1)
                else:
                    cid, title = part, part
                cid = cid.strip().lstrip("@")
                if not cid: continue
                if not cid.startswith("-") and not cid.lstrip("-").isdigit():
                    # username — leave as-is
                    pass
                ch[cid] = {
                    "title": title.strip(),
                    "enabled": True,
                    "times": config()["default_times"],
                    "categories": config()["default_cats"],
                    "with_image": True,
                    "with_hashtag": True,
                    "pin": False,
                    "style": "normal",
                }
                added += 1
            save_channels(ch)
            send(chat_id, f"✅ {added} کانال اضافه شد.",
                 KB([B("📢 لیست", "m:ch"), B("⬅️ منو", "m:main")]))
            return

        if act == "set_times":
            cid = data["cid"]
            parts = [p.strip() for p in text.replace("،", ",").split(",") if p.strip()]
            valid = []
            for p in parts:
                try:
                    h, m = p.split(":")
                    h, m = int(h), int(m)
                    if 0 <= h < 24 and 0 <= m < 60:
                        valid.append(f"{h:02d}:{m:02d}")
                except Exception: pass
            if not valid:
                send(chat_id, "❌ فرمت اشتباه. مثال: <code>09:00, 15:00, 21:30</code>")
                return
            ch = channels()
            if str(cid) in ch:
                ch[str(cid)]["times"] = sorted(set(valid))
                save_channels(ch)
            send(chat_id, f"✅ ذخیره شد: {', '.join(sorted(set(valid)))}",
                 KB([B("⬅️ کانال", f"ch:{cid}")]))
            return

        if act == "set_cats":
            cid = data["cid"]
            cats = all_categories()
            nums = [int(p.strip()) for p in text.replace("،", ",").split(",")
                    if p.strip().isdigit()]
            chosen = [cats[n-1] for n in nums if 1 <= n <= len(cats)]
            if not chosen:
                send(chat_id, "❌ شماره معتبر بده. مثال: <code>1, 3, 5</code>")
                return
            ch = channels()
            if str(cid) in ch:
                ch[str(cid)]["categories"] = chosen
                save_channels(ch)
            send(chat_id, f"✅ ذخیره شد: {', '.join(CATEGORY_FA.get(c,c) for c in chosen)}",
                 KB([B("⬅️ کانال", f"ch:{cid}")]))
            return

        if act == "rename_channel":
            cid = data["cid"]
            ch = channels()
            if str(cid) in ch:
                ch[str(cid)]["title"] = text.strip()[:80]
                save_channels(ch)
            send(chat_id, "✅ نام ذخیره شد.", KB([B("⬅️ کانال", f"ch:{cid}")]))
            return

        if act == "set_style":
            cid = data["cid"]
            s = text.strip().lower()
            if s not in ("normal", "formal", "short"):
                send(chat_id, "❌ یکی از: normal / formal / short")
                return
            ch = channels()
            if str(cid) in ch:
                ch[str(cid)]["style"] = s
                save_channels(ch)
            send(chat_id, f"✅ سبک: {s}", KB([B("⬅️ کانال", f"ch:{cid}")]))
            return

        if act == "send_now":
            cid = data["cid"]
            cats = all_categories()
            nums = [int(p.strip()) for p in text.replace("،", ",").split(",")
                    if p.strip().isdigit()]
            cat = cats[nums[0]-1] if nums and 1 <= nums[0] <= len(cats) else random.choice(cats)
            ch = channels().get(str(cid), {})
            ok, mode, mid = publish(
                int(cid), cat,
                with_image=ch.get("with_image", True),
                hashtag=ch.get("with_hashtag", True),
                channel_title=ch.get("title", ""),
                style=ch.get("style", "normal"))
            if ok:
                bump_stats()
                send(chat_id, f"✅ ارسال شد ({mode}).",
                     KB([B("⬅️ کانال", f"ch:{cid}")]))
            else:
                send(chat_id, f"❌ ناموفق: {mode}")
            return

        if act == "wiki_search":
            r = wiki_summary(text, lang="en")
            if r:
                send(chat_id, f"<b>📖 {r['title']}</b>\n\n{r['extract'][:1500]}",
                     KB([B("⬅️ منو", "m:main")]))
            else:
                send(chat_id, "❌ پیدا نشد.", KB([B("⬅️ منو", "m:main")]))
            return

        if act == "arxiv_search":
            results = arxiv_search(text, limit=6)
            if not results:
                send(chat_id, "❌ چیزی پیدا نشد.", KB([B("⬅️ منو", "m:main")]))
                return
            lines = [f"<b>📄 arXiv: {text}</b>", ""]
            for r in results:
                lines.append(f"• <a href=\"{r['link']}\">{r['title'][:120]}</a>")
            send(chat_id, "\n".join(lines), KB([B("⬅️ منو", "m:main")]))
            return

        if act == "image_prompt":
            url = image_url(text)
            send_photo(chat_id, url, caption=f"🎨 {text[:200]}",
                       kb=KB([B("🔄 دیگری", "m:image"), B("⬅️ منو", "m:main")]))
            return

        if act == "calc":
            if not all(c in "0123456789.+-*/()% eE" for c in text):
                send(chat_id, "❌ فقط عدد و عملگر مجاز است.")
                return
            try:
                res = eval(text, {"__builtins__": {}}, {})
                send(chat_id, f"🧮 <code>{text}</code> = <b>{res}</b>",
                     KB([B("⬅️ منو", "m:main")]))
            except Exception as e:
                send(chat_id, f"❌ خطا: {e}")
            return

        if act == "add_topic":
            # expects: category|title|body
            parts = text.split("|", 2)
            if len(parts) != 3:
                send(chat_id, "❌ فرمت: <code>cat|title|body</code>")
                return
            cat, title, body = [p.strip() for p in parts]
            store = topics_store()
            store.setdefault(cat, []).append({"title": title, "body": body})
            save_topics(store)
            send(chat_id, f"✅ موضوع اضافه شد به {cat}.",
                 KB([B("⬅️ موضوعات", "m:topics")]))
            return

        if act == "del_topic":
            try:
                cat, idx = text.split("|")
                idx = int(idx.strip())
                store = topics_store()
                if cat.strip() in store and 1 <= idx <= len(store[cat.strip()]):
                    t = store[cat.strip()].pop(idx-1)
                    save_topics(store)
                    send(chat_id, f"🗑 حذف شد: {t['title']}",
                         KB([B("⬅️ موضوعات", "m:topics")]))
                    return
            except Exception: pass
            send(chat_id, "❌ فرمت: <code>cat|index</code>")
            return

        if act == "draft_text":
            d = drafts()
            did = hashlib.md5(text.encode()).hexdigest()[:8]
            d[did] = {"text": text, "t": datetime.utcnow().isoformat(),
                      "created_by": uid}
            save_drafts(d)
            send(chat_id, f"✅ پیش‌نویس ذخیره شد (<code>{did}</code>)",
                 KB([B("✍️ پیش‌نویس‌ها", "m:drafts"), B("⬅️ منو", "m:main")]))
            return

        if act == "new_template":
            parts = text.split("|", 1)
            if len(parts) != 2:
                send(chat_id, "❌ فرمت: <code>name|body</code>")
                return
            name, body = [p.strip() for p in parts]
            t = templates(); t[name] = body; save_templates(t)
            send(chat_id, f"✅ تمپلیت '{name}' ذخیره شد.",
                 KB([B("🧩 تمپلیت", "m:tmpl"), B("⬅️ منو", "m:main")]))
            return

    # Commands
    if text in ("/start", "/menu", "منو"):
        send(chat_id,
             "<b>🤖 ربات ماهان‌نمان — حرفه‌ای</b>\n"
             "۵۰+ قابلیت:\n"
             "• مدیریت چند کاناله\n"
             "• زمان‌بندی جدا برای هر کانال\n"
             "• موضوعات + AI + RSS + ویکی + arXiv\n"
             "• عکس خودکار + هشتگ + پین\n"
             "• بکاپ، لاگ، آمار\n\n"
             "از دکمه‌ها استفاده کن:",
             main_menu())
        return
    if text == "/help":
        send(chat_id,
             "<b>ℹ️ راهنمای سریع</b>\n\n"
             "1) ربات رو توی کانال ادمین کن\n"
             "2) از کانال یه پیام برام فوروارد کن تا اضافه شه\n"
             "3) ساعت و موضوعات رو تنظیم کن\n"
             "4) ربات سر ساعت پست می‌ذاره\n\n"
             "<b>دستورات:</b>\n"
             "/start — منو\n/stats — آمار\n/help — راهنما",
             KB([B("⬅️ منو", "m:main")]))
        return
    if text == "/stats":
        send(chat_id, stats_text(), KB([B("⬅️ منو", "m:main")]))
        return
    if text == "/id":
        send(chat_id, f"Your ID: <code>{uid}</code>\nChat ID: <code>{chat_id}</code>")
        return

    send(chat_id, "متوجه نشدم. /start بزن.")

# ═══════════════════════════════════════════════════════════════
# CALLBACK HANDLER
# ═══════════════════════════════════════════════════════════════
def stats_text():
    s = stats()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    ch = channels()
    on = sum(1 for c in ch.values() if c.get("enabled", True))
    return (f"<b>📊 آمار</b>\n\n"
            f"کل ارسال‌ها: <b>{s.get('total', 0)}</b>\n"
            f"امروز: <b>{s.get('today', {}).get(today, 0)}</b>\n"
            f"کانال‌ها: <b>{len(ch)}</b> (فعال: {on})\n"
            f"آخرین ارسال: <code>{s.get('last') or '—'}</code>")

def handle_callback(cb):
    uid = cb.get("from", {}).get("id")
    chat_id = cb["message"]["chat"]["id"]
    msg_id = cb["message"]["message_id"]
    data = cb.get("data", "")

    if not is_admin(uid):
        answer_cb(cb["id"], "⛔️ ادمین نیستید.", alert=True); return

    answer_cb(cb["id"])
    now_str = datetime.utcnow().strftime("%H:%M:%S")
    edit(chat_id, msg_id, f"⏳ {now_str}", None)

    # ── Main menu ──────────────────────────────────────────
    if data == "m:main":
        edit(chat_id, msg_id,
             "<b>🤖 پنل مدیریت</b>\nاز دکمه‌ها استفاده کن:",
             main_menu()); return

    if data == "m:help":
        edit(chat_id, msg_id,
             "<b>ℹ️ راهنما</b>\n\n"
             "• 📢 کانال‌ها: افزودن/حذف/تنظیم\n"
             "• ⏰ زمان‌بندی: ساعت‌های ارسال هر کانال\n"
             "• 📚 موضوعات: مدیریت موضوعات\n"
             "• 📰 اخبار: RSS زنده\n"
             "• 🔍 ویکی / 📄 arXiv: جستجو\n"
             "• 🚀 ارسال فوری: تست و ارسال دستی\n"
             "• 🎨 ساخت عکس: با Pollinations\n"
             "• ✍️ پیش‌نویس: ذخیره متن‌ها\n"
             "• 🧩 تمپلیت: قالب‌های آماده\n"
             "• 📊 آمار / 📋 لاگ\n"
             "• 💾 بکاپ / ♻️ ریست\n"
             "• 🛠 ابزارها: ماشین‌حساب، UUID، ...",
             help_menu()); return

    if data == "m:health":
        cfg = config()
        ch = channels()
        on = sum(1 for c in ch.values() if c.get("enabled", True))
        edit(chat_id, msg_id,
             f"<b>🌐 وضعیت</b>\n\n"
             f"ربات: {'🟢' if cfg.get('global_enabled') else '🔴'}\n"
             f"کانال‌های فعال: <b>{on}/{len(ch)}</b>\n"
             f"کل ارسال: <b>{stats().get('total', 0)}</b>\n"
             f"زمان: <code>{datetime.now().strftime('%Y-%m-%d %H:%M')}</code>",
             KB([B("⬅️ منو", "m:main")])); return

    # ── Channels ───────────────────────────────────────────
    if data == "m:ch":
        ch = channels()
        if not ch:
            edit(chat_id, msg_id,
                 "<b>📢 کانال‌ها</b>\n\nهنوز کانالی اضافه نشده.",
                 channels_menu())
        else:
            edit(chat_id, msg_id,
                 f"<b>📢 کانال‌ها ({len(ch)})</b>\n\nروی هر کانال بزن:",
                 channels_menu())
        return

    if data == "ch:add":
        PENDING[uid] = {"action": "add_channel"}
        edit(chat_id, msg_id,
             "<b>➕ افزودن کانال</b>\n\n"
             "۱) ربات رو ادمین کانال کن (با اجازهٔ ارسال)\n"
             "۲) از کانال یه پیام <b>فوروارد</b> کن\n\n"
             "منتظر فوروارد هستم...",
             KB([B("❌ لغو", "m:ch")]))
        return

    if data == "ch:bulk":
        PENDING[uid] = {"action": "bulk_channels"}
        edit(chat_id, msg_id,
             "<b>📦 افزودن دسته‌ای کانال</b>\n\n"
             "لیست رو این‌طوری بفرست (هر خط یا کاما جدا):\n"
             "<code>-1001234567890:عنوان کانال</code>\n"
             "<code>@my_channel:کانال دوم</code>\n\n"
             "برای گرفتن ID از @userinfobot یا @getidsbot استفاده کن.",
             KB([B("❌ لغو", "m:ch")]))
        return

    if data.startswith("ch:"):
        parts = data.split(":")
        cid = parts[1]
        action = parts[2] if len(parts) > 2 else None
        if action is None:
            edit(chat_id, msg_id, channel_detail_txt(cid), channel_detail_kb(cid))
            return
        ch = channels()
        if str(cid) not in ch:
            edit(chat_id, msg_id, "❌ کانال پیدا نشد.",
                 KB([B("⬅️", "m:ch")])); return
        if action == "toggle":
            ch[str(cid)]["enabled"] = not ch[str(cid)].get("enabled", True)
            save_channels(ch)
            edit(chat_id, msg_id, channel_detail_txt(cid), channel_detail_kb(cid))
            return
        if action == "img":
            ch[str(cid)]["with_image"] = not ch[str(cid)].get("with_image", True)
            save_channels(ch)
            edit(chat_id, msg_id, channel_detail_txt(cid), channel_detail_kb(cid))
            return
        if action == "tag":
            ch[str(cid)]["with_hashtag"] = not ch[str(cid)].get("with_hashtag", True)
            save_channels(ch)
            edit(chat_id, msg_id, channel_detail_txt(cid), channel_detail_kb(cid))
            return
        if action == "pin":
            ch[str(cid)]["pin"] = not ch[str(cid)].get("pin", False)
            save_channels(ch)
            edit(chat_id, msg_id, channel_detail_txt(cid), channel_detail_kb(cid))
            return
        if action == "times":
            PENDING[uid] = {"action": "set_times", "data": {"cid": cid}}
            edit(chat_id, msg_id,
                 "<b>⏰ تنظیم ساعت‌ها</b>\n\n"
                 "با کاما جدا کن:\n<code>09:00, 12:30, 18:00, 21:00</code>",
                 KB([B("❌ لغو", f"ch:{cid}")]))
            return
        if action == "cats":
            cats = all_categories()
            lines = ["<b>📚 تنظیم موضوعات</b>", "",
                     "شماره‌ها با کاما:", "<code>1, 3, 5</code>", ""]
            for i, c in enumerate(cats, 1):
                lines.append(f"{i}) {CATEGORY_FA.get(c, c)}")
            PENDING[uid] = {"action": "set_cats", "data": {"cid": cid}}
            edit(chat_id, msg_id, "\n".join(lines),
                 KB([B("❌ لغو", f"ch:{cid}")]))
            return
        if action == "rename":
            PENDING[uid] = {"action": "rename_channel", "data": {"cid": cid}}
            edit(chat_id, msg_id, "✏️ نام جدید رو بفرست:",
                 KB([B("❌ لغو", f"ch:{cid}")]))
            return
        if action == "style":
            PENDING[uid] = {"action": "set_style", "data": {"cid": cid}}
            edit(chat_id, msg_id,
                 "<b>🎨 سبک ارسال</b>\n\nیکی از:\n"
                 "<code>normal</code> — معمولی\n"
                 "<code>formal</code> — رسمی\n"
                 "<code>short</code> — کوتاه",
                 KB([B("❌ لغو", f"ch:{cid}")]))
            return
        if action == "test":
            info = ch[str(cid)]
            cat = random.choice(info.get("categories") or config()["default_cats"])
            edit(chat_id, msg_id, "⏳ در حال ارسال تست...")
            ok, mode, mid = publish(
                int(cid), cat,
                with_image=info.get("with_image", True),
                hashtag=info.get("with_hashtag", True),
                channel_title=info.get("title", ""),
                style=info.get("style", "normal"))
            if ok:
                bump_stats()
                log_event("test", f"{cid} ok ({mode})")
                edit(chat_id, msg_id, f"✅ ارسال تست موفق ({mode}).",
                     KB([B("⬅️ کانال", f"ch:{cid}")]))
            else:
                log_event("test_fail", f"{cid}: {mode}")
                edit(chat_id, msg_id, f"❌ ناموفق: {mode}",
                     KB([B("⬅️ کانال", f"ch:{cid}")]))
            return
        if action == "del":
            del ch[str(cid)]
            save_channels(ch)
            edit(chat_id, msg_id, "🗑 حذف شد.", channels_menu())
            return

    # ── Schedule overview ──────────────────────────────────
    if data == "m:sched":
        ch = channels()
        lines = ["<b>⏰ زمان‌بندی کلی</b>", ""]
        for cid, info in ch.items():
            times = ", ".join(info.get("times", [])) or "—"
            lines.append(f"• <b>{info.get('title', cid)[:25]}</b>\n  <code>{times}</code>")
        if not ch:
            lines.append("کانالی نیست.")
        edit(chat_id, msg_id, "\n".join(lines),
             KB([B("📢 کانال‌ها", "m:ch"), B("⬅️ منو", "m:main")]))
        return

    # ── Topics ─────────────────────────────────────────────
    if data == "m:topics":
        edit(chat_id, msg_id,
             "<b>📚 موضوعات</b>\n\nیه دسته انتخاب کن:",
             topics_menu()); return

    if data == "tp:add":
        PENDING[uid] = {"action": "add_topic"}
        edit(chat_id, msg_id,
             "<b>➕ افزودن موضوع</b>\n\n"
             "فرمت: <code>category|title|body</code>\n"
             "مثال:\n"
             "<code>tech|ChatGPT|مدل زبانی مبتنی بر ترنسفورمرها.</code>",
             KB([B("❌ لغو", "m:topics")]))
        return

    if data == "tp:del":
        PENDING[uid] = {"action": "del_topic"}
        edit(chat_id, msg_id,
             "<b>🗑 حذف موضوع</b>\n\n"
             "فرمت: <code>category|index</code>\n"
             "مثال: <code>tech|3</code>",
             KB([B("❌ لغو", "m:topics")]))
        return

    if data.startswith("tp:"):
        cat = data.split(":", 1)[1]
        store = topics_store()
        bank = store.get(cat, [])
        lines = [f"<b>📚 {CATEGORY_FA.get(cat, cat)}</b> ({len(bank)})", ""]
        for i, t in enumerate(bank[:25], 1):
            lines.append(f"{i}. <b>{t['title']}</b> — {t['body'][:80]}")
        if len(bank) > 25:
            lines.append(f"... و {len(bank)-25} مورد دیگر")
        edit(chat_id, msg_id, "\n".join(lines),
             KB([B("➕ افزودن", "tp:add"), B("🗑 حذف", "tp:del"),
                 B("⬅️ موضوعات", "m:topics")]))
        return

    # ── News ───────────────────────────────────────────────
    if data == "m:news":
        edit(chat_id, msg_id, "<b>📰 اخبار زنده</b>\n\nمنبع رو انتخاب کن:",
             news_menu()); return

    if data.startswith("nw:") and data != "nw:send":
        key = data.split(":", 1)[1]
        edit(chat_id, msg_id, f"⏳ در حال گرفتن {key}...")
        items = fetch_rss(key, limit=6)
        if not items:
            edit(chat_id, msg_id, "❌ خطا در دریافت.",
                 KB([B("⬅️ اخبار", "m:news")])); return
        label = RSS_FEEDS[key][0]
        lines = [f"<b>📰 {label}</b>", ""]
        for it in items:
            title = it["title"][:140]
            link = it["link"]
            lines.append(f"• <a href=\"{link}\">{title}</a>")
        edit(chat_id, msg_id, "\n".join(lines),
             KB([B("🔄 بروزرسانی", data),
                 B("⬅️ اخبار", "m:news")]))
        return

    if data == "nw:send":
        ch = channels()
        if not ch:
            edit(chat_id, msg_id, "❌ اول یه کانال اضافه کن.",
                 KB([B("⬅️", "m:main")])); return
        rows = [[B(f"📤 {info.get('title', cid)[:24]}", f"nwsend:{cid}")]
                for cid, info in ch.items()]
        rows.append([B("⬅️ اخبار", "m:news")])
        edit(chat_id, msg_id, "<b>📤 ارسال خبر به:</b>", KB(*rows))
        return

    if data.startswith("nwsend:"):
        cid = data.split(":", 1)[1]
        # pick a random feed
        key = random.choice(list(RSS_FEEDS.keys()))
        items = fetch_rss(key, limit=5)
        if not items:
            edit(chat_id, msg_id, "❌ خبری نیافتم.",
                 KB([B("⬅️", "m:news")])); return
        label = RSS_FEEDS[key][0]
        lines = [f"<b>📰 {label}</b>", ""]
        for it in items:
            lines.append(f"• <a href=\"{it['link']}\">{it['title'][:130]}</a>")
        text = "\n".join(lines)
        r = send(int(cid), text)
        if r.get("ok"):
            bump_stats()
            log_event("news_send", f"{cid} {key}")
            edit(chat_id, msg_id, f"✅ ارسال شد ({key}).",
                 KB([B("⬅️ اخبار", "m:news")]))
        else:
            edit(chat_id, msg_id, f"❌ {r.get('description')}",
                 KB([B("⬅️ اخبار", "m:news")]))
        return

    # ── Wiki ───────────────────────────────────────────────
    if data == "m:wiki":
        PENDING[uid] = {"action": "wiki_search"}
        edit(chat_id, msg_id,
             "<b>🔍 جستجو در ویکی‌پدیا</b>\n\nعبارت انگلیسی رو بفرست:",
             KB([B("❌ لغو", "m:main")]))
        return

    # ── arXiv ──────────────────────────────────────────────
    if data == "m:arxiv":
        PENDING[uid] = {"action": "arxiv_search"}
        edit(chat_id, msg_id,
             "<b>📄 جستجو در arXiv</b>\n\nعبارت (انگلیسی) رو بفرست:",
             KB([B("❌ لغو", "m:main")]))
        return

    # ── Send now ───────────────────────────────────────────
    if data == "m:send":
        ch = channels()
        if not ch:
            edit(chat_id, msg_id, "❌ اول کانال اضافه کن.",
                 KB([B("⬅️", "m:main")])); return
        rows = [[B(f"📤 {info.get('title', cid)[:24]}", f"send:{cid}")]
                for cid, info in ch.items()]
        rows.append([B("⬅️ منو", "m:main")])
        edit(chat_id, msg_id, "<b>🚀 ارسال فوری</b>\nکانال:", KB(*rows))
        return

    if data.startswith("send:"):
        cid = data.split(":", 1)[1]
        cats = all_categories()
        lines = ["<b>🚀 ارسال فوری</b>", "", "شماره دسته رو بفرست:"]
        for i, c in enumerate(cats, 1):
            lines.append(f"{i}) {CATEGORY_FA.get(c, c)}")
        PENDING[uid] = {"action": "send_now", "data": {"cid": cid}}
        edit(chat_id, msg_id, "\n".join(lines),
             KB([B("❌ لغو", "m:send")]))
        return

    # ── Image ──────────────────────────────────────────────
    if data == "m:image":
        PENDING[uid] = {"action": "image_prompt"}
        edit(chat_id, msg_id,
             "<b>🎨 ساخت عکس</b>\n\n"
             "توصیف انگلیسی رو بفرست:\n"
             "<code>a futuristic city at night, neon</code>",
             KB([B("❌ لغو", "m:main")]))
        return

    # ── Drafts ─────────────────────────────────────────────
    if data == "m:drafts":
        d = drafts()
        lines = [f"<b>✍️ پیش‌نویس‌ها ({len(d)})</b>", ""]
        for did, info in list(d.items())[:15]:
            lines.append(f"<code>{did}</code> — {info['text'][:60]}...")
        if not d:
            lines.append("خالیه.")
        edit(chat_id, msg_id, "\n".join(lines),
             KB([B("➕ پیش‌نویس جدید", "dr:add"),
                 B("🗑 پاک کن", "dr:clear"),
                 B("⬅️ منو", "m:main")]))
        return

    if data == "dr:add":
        PENDING[uid] = {"action": "draft_text"}
        edit(chat_id, msg_id, "✍️ متن پیش‌نویس رو بفرست:",
             KB([B("❌ لغو", "m:drafts")]))
        return

    if data == "dr:clear":
        save_drafts({})
        edit(chat_id, msg_id, "🗑 پاک شد.",
             KB([B("⬅️", "m:drafts")]))
        return

    # ── Templates ──────────────────────────────────────────
    if data == "m:tmpl":
        t = templates()
        lines = [f"<b>🧩 تمپلیت‌ها ({len(t)})</b>", ""]
        for name, body in list(t.items())[:15]:
            lines.append(f"• <b>{name}</b>: {body[:60]}")
        if not t:
            lines.append("خالیه.")
        edit(chat_id, msg_id, "\n".join(lines),
             KB([B("➕ تمپلیت جدید", "tm:add"),
                 B("🗑 پاک کن", "tm:clear"),
                 B("⬅️ منو", "m:main")]))
        return

    if data == "tm:add":
        PENDING[uid] = {"action": "new_template"}
        edit(chat_id, msg_id,
             "فرمت: <code>name|body</code>\nمثال: <code>salam|سلام {name} عزیز!</code>",
             KB([B("❌ لغو", "m:tmpl")]))
        return

    if data == "tm:clear":
        save_templates({})
        edit(chat_id, msg_id, "🗑 پاک شد.", KB([B("⬅️", "m:tmpl")]))
        return

    # ── Stats ──────────────────────────────────────────────
    if data == "m:stats":
        edit(chat_id, msg_id, stats_text(), KB([B("⬅️ منو", "m:main")]))
        return

    # ── Logs ───────────────────────────────────────────────
    if data == "m:logs":
        L = logs()[-20:]
        lines = [f"<b>📋 آخرین لاگ‌ها ({len(L)})</b>", ""]
        for e in reversed(L):
            t = e["t"][11:19]
            lines.append(f"<code>{t}</code> [{e['k']}] {e['m'][:80]}")
        if not L:
            lines.append("خالیه.")
        edit(chat_id, msg_id, "\n".join(lines),
             KB([B("🗑 پاک کن", "lg:clear"), B("⬅️ منو", "m:main")]))
        return

    if data == "lg:clear":
        put(F_LOGS, [])
        edit(chat_id, msg_id, "🗑 لاگ پاک شد.", KB([B("⬅️", "m:logs")]))
        return

    # ── Settings ───────────────────────────────────────────
    if data == "m:settings":
        edit(chat_id, msg_id, "<b>⚙️ تنظیمات</b>", settings_menu())
        return

    if data == "st:global":
        cfg = config()
        cfg["global_enabled"] = not cfg.get("global_enabled", True)
        save_config(cfg)
        edit(chat_id, msg_id, "<b>⚙️ تنظیمات</b>", settings_menu())
        return

    if data == "st:reset":
        save_config({"global_enabled": True, "default_tz_offset": 3.5,
                     "default_times": ["09:00","15:00","21:00"],
                     "default_cats": ["engineering","science","tech"],
                     "language": "fa"})
        edit(chat_id, msg_id, "♻️ تنظیمات ریست شد.", KB([B("⬅️", "m:settings")]))
        return

    if data in ("st:dtimes", "st:dcats", "st:tz"):
        edit(chat_id, msg_id,
             "این گزینه در نسخه بعدی. فعلاً از طریق کد قابل تغییر است.",
             KB([B("⬅️", "m:settings")]))
        return

    # ── Tools ──────────────────────────────────────────────
    if data == "m:tools":
        edit(chat_id, msg_id, "<b>🛠 ابزارها</b>", tools_menu())
        return

    if data == "t:calc":
        PENDING[uid] = {"action": "calc"}
        edit(chat_id, msg_id, "🧮 عبارت رو بفرست:\n<code>2+3*4</code>",
             KB([B("❌ لغو", "m:tools")]))
        return

    if data == "t:rand":
        edit(chat_id, msg_id,
             f"🎲 <b>{random.randint(1, 100)}</b>",
             KB([B("🔄", "t:rand"), B("⬅️", "m:tools")]))
        return

    if data == "t:uuid":
        import uuid
        edit(chat_id, msg_id, f"🔐 <code>{uuid.uuid4()}</code>",
             KB([B("🔄", "t:uuid"), B("⬅️", "m:tools")]))
        return

    if data == "t:pass":
        chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*"
        pwd = "".join(random.choice(chars) for _ in range(20))
        edit(chat_id, msg_id, f"🔑 <code>{pwd}</code>",
             KB([B("🔄", "t:pass"), B("⬅️", "m:tools")]))
        return

    if data == "t:time":
        edit(chat_id, msg_id,
             f"📅 محلی: <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>\n"
             f"UTC: <code>{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}</code>",
             KB([B("🔄", "t:time"), B("⬅️", "m:tools")]))
        return

    if data == "t:ip":
        try:
            req = urllib.request.Request("https://api.ipify.org?format=json",
                                         headers={"User-Agent":"MahanBot/1.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                d = json.loads(r.read().decode())
            ip = d.get("ip", "—")
        except Exception:
            ip = "—"
        edit(chat_id, msg_id, f"🌐 Public IP: <code>{ip}</code>",
             KB([B("🔄", "t:ip"), B("⬅️", "m:tools")]))
        return

    if data == "t:b64e":
        import base64
        s = f"hello-{int(time.time())}"
        edit(chat_id, msg_id,
             f"دمو: <code>{s}</code>\nانکد: <code>{base64.b64encode(s.encode()).decode()}</code>",
             KB([B("⬅️", "m:tools")]))
        return

    if data == "t:b64d":
        import base64
        s = "aGVsbG8="
        edit(chat_id, msg_id,
             f"دمو: <code>{s}</code>\nدیکد: <code>{base64.b64decode(s).decode()}</code>",
             KB([B("⬅️", "m:tools")]))
        return

    if data == "t:prime":
        n = random.randint(10, 500)
        is_p = all(n % i for i in range(2, int(n**0.5)+1)) if n > 1 else False
        edit(chat_id, msg_id,
             f"🔢 {n} → {'✅ اول' if is_p else '❌ غیر اول'}",
             KB([B("🔄", "t:prime"), B("⬅️", "m:tools")]))
        return

    if data == "t:fib":
        n = 20
        a, b = 0, 1; seq = []
        for _ in range(n):
            seq.append(a); a, b = b, a+b
        edit(chat_id, msg_id,
             f"📊 Fibonacci (اول {n}):\n<code>{' '.join(map(str, seq))}</code>",
             KB([B("⬅️", "m:tools")]))
        return

    if data == "t:music":
        genres = ["classical","jazz","rock","pop","electronic","hip-hop","blues",
                  "folk","country","reggae","metal","punk","soul","funk","ambient",
                  "lo-fi","orchestral","opera","flamenco","k-pop"]
        edit(chat_id, msg_id, f"🎵 ژانر: <b>{random.choice(genres)}</b>",
             KB([B("🔄", "t:music"), B("⬅️", "m:tools")]))
        return

    if data == "t:joke":
        jokes = [
            "چرا برنامه‌نویس‌ها عینک می‌زنن؟ چون C# ندارن!",
            "دو تا بیت راه می‌رفتن، یکی گفت: من 0 شدم، اون یکی گفت: من 1 شدم. یه بایت گفت: من 8 شدم!",
            "چرا پایتون از جاوا خوشش نمیاد؟ چون خیلی کلاس داره!",
            "برنامه‌نویس: باگ نیست، ویژگی‌ه!",
            "SQL وارد بار میشه، می‌گه: یه میز برای دو نفر لطفاً!",
        ]
        edit(chat_id, msg_id, f"😂 {random.choice(jokes)}",
             KB([B("🔄", "t:joke"), B("⬅️", "m:tools")]))
        return

    if data == "t:quote":
        quotes = [
            "«تنها راه انجام کار بزرگ، عشق به کار است.» — استیو جابز",
            "«موفقیت یعنی از شکستی به شکست دیگر بدون از دست دادن شوق رفتن.» — چرچیل",
            "«آینده به کسانی تعلق دارد که به زیبایی رؤیاهایشان باور دارند.» — الینور روزولت",
            "«هر کس که می‌تواند، انجام می‌دهد؛ هر کس که نمی‌تواند، آموزش می‌دهد.» — شاو",
            "«در میانه دشواری، فرصت نهفته است.» — انیشتین",
        ]
        edit(chat_id, msg_id, f"💡 {random.choice(quotes)}",
             KB([B("🔄", "t:quote"), B("⬅️", "m:tools")]))
        return

    if data == "t:book":
        try:
            req = urllib.request.Request("https://gutendex.com/books?sort=random",
                                         headers={"User-Agent":"MahanBot/1.0"})
            with urllib.request.urlopen(req, timeout=12) as r:
                d = json.loads(r.read().decode())
            b = (d.get("results") or [{}])[0]
            title = b.get("title", "—")
            authors = ", ".join(a.get("name", "—") for a in b.get("authors", []))
            edit(chat_id, msg_id,
                 f"📖 <b>{title}</b>\n✍️ {authors}",
                 KB([B("🔄", "t:book"), B("⬅️", "m:tools")]))
        except Exception as e:
            edit(chat_id, msg_id, f"❌ {e}", KB([B("⬅️", "m:tools")]))
        return

    if data == "t:weather":
        # Simple weather via wttr.in
        try:
            req = urllib.request.Request("https://wttr.in/Tehran?format=%C+%t+%w",
                                         headers={"User-Agent":"curl/7.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                w = r.read().decode().strip()
            edit(chat_id, msg_id, f"🌤 تهران: {w}",
                 KB([B("🔄", "t:weather"), B("⬅️", "m:tools")]))
        except Exception as e:
            edit(chat_id, msg_id, f"❌ {e}", KB([B("⬅️", "m:tools")]))
        return

    # ── Backup ─────────────────────────────────────────────
    if data == "m:backup":
        edit(chat_id, msg_id, "<b>💾 بکاپ</b>", backup_menu())
        return

    if data == "bk:download":
        # Send a JSON dump as a document-ish text
        blob = {
            "channels": channels(),
            "config":   config(),
            "stats":    stats(),
            "topics":   topics_store(),
            "templates":templates(),
            "drafts":   drafts(),
            "exported_at": datetime.utcnow().isoformat(),
        }
        text = json.dumps(blob, ensure_ascii=False, indent=2)
        # Send as text (chunked if too long)
        edit(chat_id, msg_id,
             f"<b>💾 بکاپ کامل</b>\n\n<code>{text[:3500]}</code>\n\n"
             f"(در صورت طولانی بودن، از فایل داده روی سرور استفاده کن: <code>{DATA_DIR}</code>)",
             KB([B("⬅️", "m:backup")]))
        return

    if data in ("bk:channels", "bk:topics", "bk:stats"):
        what = data.split(":")[1]
        d = {"channels": channels(), "topics": topics_store(),
             "stats": stats()}[what]
        text = json.dumps(d, ensure_ascii=False, indent=2)
        edit(chat_id, msg_id,
             f"<b>📤 {what}</b>\n\n<code>{text[:3500]}</code>",
             KB([B("⬅️", "m:backup")]))
        return

    if data == "bk:reset":
        save_channels({}); save_state({}); save_stats({"total":0,"today":{},"last":None})
        save_topics({}); save_drafts({}); save_templates({}); put(F_LOGS, [])
        ensure_topics()
        edit(chat_id, msg_id, "♻️ همه چیز ریست شد.",
             KB([B("⬅️", "m:backup")]))
        return

    # ── Test ───────────────────────────────────────────────
    if data == "m:test":
        tests = [
            ("storage", lambda: (put(F_STATE, state()), True)[1]),
            ("topics",  lambda: len(topics_store()) > 0),
            ("channels",lambda: True),
            ("rss",     lambda: fetch_rss("hn", 1) is not None),
            ("http",    lambda: True),
        ]
        results = []
        for name, fn in tests:
            try:
                results.append(f"✅ {name}")
                fn()
            except Exception as e:
                results.append(f"❌ {name}: {e}")
        edit(chat_id, msg_id,
             "<b>🧪 تست سیستم</b>\n\n" + "\n".join(results),
             KB([B("🔄 دوباره", "m:test"), B("⬅️ منو", "m:main")]))
        return

    # fallback
    edit(chat_id, msg_id, "گزینه نامعتبر.", main_menu())

# ═══════════════════════════════════════════════════════════════
# POLL LOOP
# ═══════════════════════════════════════════════════════════════
def set_commands():
    return api("setMyCommands", {"commands": [
        {"command": "start", "description": "منوی اصلی"},
        {"command": "stats", "description": "آمار"},
        {"command": "help",  "description": "راهنما"},
        {"command": "id",    "description": "آیدی من"},
    ]})

def poll_loop():
    print("[poll] started")
    offset = 0
    while True:
        try:
            r = api("getUpdates", {
                "offset": offset, "timeout": 30,
                "allowed_updates": ["message", "callback_query"]})
            if not r.get("ok"):
                log_event("poll_err", r.get("description"))
                time.sleep(3); continue
            for upd in r.get("result", []):
                offset = upd["update_id"] + 1
                try:
                    if "message" in upd: handle_message(upd["message"])
                    elif "callback_query" in upd: handle_callback(upd["callback_query"])
                except Exception as e:
                    log_event("handler_err", e)
                    traceback.print_exc()
        except Exception as e:
            log_event("poll_loop_err", e)
            time.sleep(3)

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    print("=" * 60)
    print(" MAHAN NEMAN BOT — Professional Edition")
    print("=" * 60)
    ensure_topics()
    me = api("getMe")
    if not me.get("ok"):
        print("ERROR: cannot reach Telegram:", me.get("description")); sys.exit(1)
    print("Bot:", me["result"]["username"], f"(id={me['result']['id']})")
    print("Admins:", ADMIN_IDS)
    print("Data dir:", DATA_DIR.resolve())
    set_commands()

    t = threading.Thread(target=scheduler_loop, daemon=True)
    t.start()
    poll_loop()

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: print("\nbye")
