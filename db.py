"""ذخیره‌سازی و جلوگیری از خبر تکراری (SQLite)."""
import json
import os
import re
import sqlite3
import hashlib
import threading
import time
from urllib.parse import urlparse, urlunparse

import config

_lock = threading.Lock()
_conn = None

# وضعیت‌های جدید (state machine) — وضعیت‌های قدیمی همچنان معتبرند
STATUS_DISCOVERED = "discovered"
STATUS_ANALYZING = "analyzing"
STATUS_VERIFICATION = "verification"
STATUS_REJECTED = "rejected"
STATUS_APPROVED_BY_AI = "approved_by_ai"
STATUS_TRANSLATION = "translation"
STATUS_TRANSLATION_REVIEW = "translation_review"
STATUS_MEDIA_PROCESSING = "media_processing"
STATUS_PENDING_ADMIN = "pending_admin"
STATUS_APPROVED = "approved"
STATUS_PUBLISHED = "published"
STATUS_FAILED = "failed"
STATUS_RETRY_PENDING = "retry_pending"
# وضعیت‌های قدیمی که برای سازگاری حفظ شده‌اند:
# new | sent_admin | skipped | rejected | approved | published

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    key         TEXT PRIMARY KEY,
    source      TEXT,
    url         TEXT,
    title       TEXT,
    norm_title  TEXT,
    payload     TEXT,
    status      TEXT DEFAULT 'new',   -- new | sent_admin | published | rejected | skipped | ...
    admin_msg   INTEGER,
    created_at  REAL
);
CREATE INDEX IF NOT EXISTS idx_created ON items(created_at);

-- cache della pipeline articoli (article_pipeline.py): URL normalizzato → risultato Telegraph
CREATE TABLE IF NOT EXISTS articles (
    url_norm      TEXT PRIMARY KEY,
    source_url    TEXT,
    archive_url   TEXT,
    telegraph_url TEXT,
    title         TEXT,
    status        TEXT DEFAULT 'done',   -- done | failed
    created_at    REAL
);
CREATE INDEX IF NOT EXISTS idx_admin_msg ON items(admin_msg);

-- گواهی‌های راستی‌آزمایی (مرحله ۵): منبع، ادعا، شواهد، اطمینان
CREATE TABLE IF NOT EXISTS verifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    news_key    TEXT,
    source      TEXT,
    claim       TEXT,
    evidence    TEXT,
    confidence  REAL,
    checked_at  REAL
);

-- حلقه بازخورد انسانی (مرحله ۱۲): تصمیم AI در برابر اقدام ادمین
CREATE TABLE IF NOT EXISTS feedback (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    news_key             TEXT,
    ai_decision          TEXT,
    human_action         TEXT,
    reason               TEXT,
    corrected_translation TEXT,
    created_at           REAL
);

-- سلامت منابع (مرحله ۹): منبع → وضعیت و آمار
CREATE TABLE IF NOT EXISTS source_health (
    source_id            TEXT PRIMARY KEY,
    last_success_at      REAL,
    last_attempt_at      REAL,
    last_item_at         REAL,
    consecutive_failures INTEGER DEFAULT 0,
    total_failures       INTEGER DEFAULT 0,
    total_ok             INTEGER DEFAULT 0,
    latency_ms           REAL DEFAULT 0,
    status               TEXT DEFAULT 'healthy'
);
"""

# ستون‌های جدید روی جدول items — با try/except تا DB قدیمی/جدید هر دو کار کند
_COLUMN_MIGRATIONS = (
    "ALTER TABLE items ADD COLUMN error TEXT",
    "ALTER TABLE items ADD COLUMN retry_count INTEGER DEFAULT 0",
    "ALTER TABLE items ADD COLUMN last_attempt_at REAL",
    "ALTER TABLE items ADD COLUMN analysis TEXT",
    "ALTER TABLE items ADD COLUMN verification TEXT",
    "ALTER TABLE items ADD COLUMN feedback TEXT",
)


def _migrate():
    for stmt in _COLUMN_MIGRATIONS:
        try:
            _conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # ستون از قبل هست
    _conn.commit()


def init():
    global _conn
    os.makedirs(os.path.dirname(os.path.abspath(config.DB_PATH)), exist_ok=True)
    _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    # WAL: چون poller_loop (ترد پس‌زمینه) و bot_loop (ترد اصلی) هم‌زمان به
    # دیتابیس می‌نویسند/می‌خوانند، WAL خواندن و نوشتن هم‌زمان را ممکن می‌کند
    # و ریسک قفل‌شدن دیتابیس ("database is locked") را عملاً از بین می‌برد.
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute("PRAGMA synchronous=NORMAL")
    # اگر با وجود WAL یک لحظه قفل شد، به‌جای خطای فوری تا ۵ ثانیه صبر کند.
    _conn.execute("PRAGMA busy_timeout=5000")
    _conn.executescript(SCHEMA)
    _migrate()
    _conn.commit()
    return _conn


def _c():
    return _conn if _conn is not None else init()


def normalize_url(url: str) -> str:
    try:
        p = urlparse(url)
        return urlunparse((p.scheme, p.netloc.lower().replace("www.", ""), p.path.rstrip("/"), "", "", ""))
    except Exception:
        return url


def normalize_title(title: str) -> str:
    t = (title or "").lower()
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"[^a-z0-9\u0600-\u06FF ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def make_key(item: dict) -> str:
    base = normalize_url(item.get("url", "")) or item.get("title", "")
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:20]


def _similar(a: str, b: str) -> int:
    try:
        from rapidfuzz import fuzz
        return int(fuzz.token_set_ratio(a, b))
    except Exception:
        import difflib
        return int(difflib.SequenceMatcher(None, a, b).ratio() * 100)


def _source_key(item: dict) -> str:
    """هویت منبع — برای توییتر خود دسته، نه کل توییتر."""
    return (item.get("source_tag") or item.get("source") or "").strip().lower()


def is_duplicate(item: dict) -> bool:
    """لایه ۱: کلید یکتا  |  لایه ۲: شباهت عنوان در ۴۸ ساعت اخیر.

    پیش‌فرض DUPLICATE_SCOPE=source یعنی شباهت فقط درون همان منبع چک می‌شود؛
    پس اگر رومانو و اورنستین یک خبر را بدهند، هر دو به گروه می‌روند.
    """
    key = make_key(item)
    norm = normalize_title(item.get("title", ""))
    scope = getattr(config, "DUPLICATE_SCOPE", "source")
    src = _source_key(item)

    with _lock:
        cur = _c().execute("SELECT 1 FROM items WHERE key=?", (key,))
        if cur.fetchone():
            return True
        if not norm:
            return False
        since = time.time() - 48 * 3600
        rows = _c().execute(
            "SELECT norm_title, payload FROM items WHERE created_at > ?", (since,)
        ).fetchall()

    for r in rows:
        if not r["norm_title"]:
            continue
        if scope == "source" and src:
            try:
                old = json.loads(r["payload"] or "{}")
            except Exception:
                old = {}
            if _source_key(old) != src:
                continue  # منبع دیگری است — خبرش جداگانه ارزش دارد
        if _similar(norm, r["norm_title"]) >= config.DUPLICATE_THRESHOLD:
            return True
    return False


def similar_sources(item: dict, hours=48, statuses=None, exclude_self=True):
    """منابعی که همین خبر را داده‌اند (برای نمایش به ادمین).

    statuses    → فقط این وضعیت‌ها (مثلاً ("approved", "published"))
    exclude_self → خود همان منبع حذف شود یا نه
    """
    norm = normalize_title(item.get("title", ""))
    if not norm:
        return []
    src = _source_key(item)
    since = time.time() - hours * 3600
    with _lock:
        rows = _c().execute(
            "SELECT norm_title, payload, status FROM items WHERE created_at > ?", (since,)
        ).fetchall()

    out = []
    for r in rows:
        if not r["norm_title"]:
            continue
        if statuses and r["status"] not in statuses:
            continue
        if _similar(norm, r["norm_title"]) < config.DUPLICATE_THRESHOLD:
            continue
        try:
            old = json.loads(r["payload"] or "{}")
        except Exception:
            continue
        tag = old.get("source_tag") or old.get("source")
        if not tag or tag in out:
            continue
        if exclude_self and _source_key(old) == src:
            continue
        out.append(tag)
    return out


def save(item: dict, status="new", admin_msg=None):
    key = make_key(item)
    with _lock:
        _c().execute(
            "INSERT OR REPLACE INTO items "
            "(key, source, url, title, norm_title, payload, status, admin_msg, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                key,
                item.get("source"),
                item.get("url"),
                item.get("title"),
                normalize_title(item.get("title", "")),
                json.dumps(item, ensure_ascii=False),
                status,
                admin_msg,
                time.time(),
            ),
        )
        _c().commit()
    return key


def set_status(key: str, status: str):
    with _lock:
        _c().execute("UPDATE items SET status=? WHERE key=?", (status, key))
        _c().commit()


def update_payload(key: str, item: dict, status=None):
    """payload/عنوان را آپدیت می‌کند بدون اینکه ستون‌های state (analysis،
    verification، retry_count و...) را بازنشانی کند (برخلاف INSERT OR REPLACE)."""
    with _lock:
        _c().execute(
            "UPDATE items SET source=?, url=?, title=?, norm_title=?, payload=?, "
            "status=COALESCE(?, status) WHERE key=?",
            (
                item.get("source"),
                item.get("url"),
                item.get("title"),
                normalize_title(item.get("title", "")),
                json.dumps(item, ensure_ascii=False),
                status,
                key,
            ),
        )
        _c().commit()


def set_admin_msg(key: str, msg_id, status="sent_admin"):
    with _lock:
        _c().execute(
            "UPDATE items SET admin_msg=?, status=? WHERE key=?",
            (msg_id, status, key),
        )
        _c().commit()


def get(key: str):
    with _lock:
        row = _c().execute("SELECT * FROM items WHERE key=?", (key,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["payload"] = json.loads(d["payload"])
    return d


def count() -> int:
    with _lock:
        return _c().execute("SELECT COUNT(*) FROM items").fetchone()[0]


# ------------------------------------------------------------------ state machine
def mark_attempt(key: str, status: str, error=None, retry=False):
    """هر تغییر وضعیت/شکست را با خطا و شمارنده تلاش ثبت می‌کند تا هیچ خبری
    بی‌صدا گم نشود. retry=True یعنی retry_count بالا می‌رود (تلاش مجدد)."""
    with _lock:
        if retry:
            _c().execute(
                "UPDATE items SET status=?, error=?, last_attempt_at=?,"
                " retry_count = COALESCE(retry_count,0)+1 WHERE key=?",
                (status, (error or "")[:500], time.time(), key),
            )
        else:
            _c().execute(
                "UPDATE items SET status=?, error=?, last_attempt_at=? WHERE key=?",
                (status, (error or "")[:500], time.time(), key),
            )
        _c().commit()


def record_analysis(key: str, analysis: dict):
    with _lock:
        _c().execute(
            "UPDATE items SET analysis=? WHERE key=?",
            (json.dumps(analysis, ensure_ascii=False), key),
        )
        _c().commit()


def record_verification(key: str, verification: dict):
    with _lock:
        _c().execute(
            "UPDATE items SET verification=? WHERE key=?",
            (json.dumps(verification, ensure_ascii=False), key),
        )
        _c().commit()
    with _lock:
        _c().execute(
            "INSERT INTO verifications (news_key, source, claim, evidence, confidence, checked_at)"
            " VALUES (?,?,?,?,?,?)",
            (
                key,
                (verification.get("source") or ""),
                (verification.get("claim") or ""),
                json.dumps(verification.get("evidence") or [], ensure_ascii=False),
                verification.get("confidence"),
                time.time(),
            ),
        )
        _c().commit()


def record_feedback(key: str, ai_decision=None, human_action=None, reason=None,
                    corrected_translation=None):
    """بازخورد حلقه انسانی (مرحله ۱۲) — بعداً برای بهتر کردن پرامپت‌ها."""
    with _lock:
        _c().execute(
            "INSERT INTO feedback (news_key, ai_decision, human_action, reason,"
            " corrected_translation, created_at) VALUES (?,?,?,?,?,?)",
            (
                key, ai_decision, human_action, reason,
                corrected_translation, time.time(),
            ),
        )
        _c().commit()


def get_analysis(key: str):
    row = get(key)
    if not row:
        return None
    try:
        return json.loads(row.get("analysis") or "null")
    except Exception:
        return None


def get_verification(key: str):
    row = get(key)
    if not row:
        return None
    try:
        return json.loads(row.get("verification") or "null")
    except Exception:
        return None


def retryable_items(limit=10, max_retries=None):
    """خبرهایی که ارسال‌شان شکست خورده و باید دوباره تلاش شوند."""
    max_retries = max_retries if max_retries is not None else getattr(config, "MAX_SEND_RETRIES", 3)
    with _lock:
        rows = _c().execute(
            "SELECT * FROM items WHERE status=? AND COALESCE(retry_count,0) < ?"
            " ORDER BY last_attempt_at ASC LIMIT ?",
            (STATUS_RETRY_PENDING, max_retries, limit),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["payload"] = json.loads(d["payload"])
        out.append(d)
    return out


def channel_examples(limit=10):
    """نمونه‌های پست‌های تأییدشده/منتشرشده کانال — فقط برای استایل ترجمه."""
    with _lock:
        rows = _c().execute(
            "SELECT payload FROM items WHERE status IN (?,?) AND payload LIKE '%translated%'"
            " ORDER BY created_at DESC LIMIT ?",
            (STATUS_APPROVED, STATUS_PUBLISHED, limit),
        ).fetchall()
    out = []
    for r in rows:
        try:
            p = json.loads(r["payload"])
        except Exception:
            continue
        tr = p.get("translated")
        if tr and (tr.get("body") or "").strip():
            out.append(p)
    return out


# ------------------------------------------------------------------ source health (مرحله ۹)
def record_source_health(source_id, ok, items=0, latency_ms=0, error=""):
    """هر تلاش خواندن یک منبع را ثبت می‌کند. وضعیت از روی شکست‌های پشت‌سرهم
    محاسبه می‌شود: ۰ → healthy، ۲+ → degraded، ۵+ → failed."""
    now = time.time()
    with _lock:
        row = _c().execute(
            "SELECT * FROM source_health WHERE source_id=?", (source_id,)
        ).fetchone()
        base = dict(row) if row else {}
        consec = (base.get("consecutive_failures") or 0) + 1 if not ok else 0
        if ok:
            status = "healthy"
            total_ok = (base.get("total_ok") or 0) + 1
            total_fail = base.get("total_failures") or 0
        else:
            total_ok = base.get("total_ok") or 0
            total_fail = (base.get("total_failures") or 0) + 1
            if consec >= 5:
                status = "failed"
            elif consec >= 2:
                status = "degraded"
            else:
                status = "degraded" if consec else "healthy"
        _c().execute(
            "INSERT OR REPLACE INTO source_health (source_id, last_success_at,"
            " last_attempt_at, last_item_at, consecutive_failures, total_failures,"
            " total_ok, latency_ms, status) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                source_id,
                now if ok else base.get("last_success_at"),
                now,
                now if items else base.get("last_item_at"),
                consec, total_fail, total_ok,
                latency_ms if ok else base.get("latency_ms") or 0,
                status,
            ),
        )
        _c().commit()
    return status


def source_health_status(source_id):
    with _lock:
        row = _c().execute(
            "SELECT * FROM source_health WHERE source_id=?", (source_id,)
        ).fetchone()
    return dict(row) if row else {"source_id": source_id, "status": "healthy"}


def list_source_health():
    with _lock:
        rows = _c().execute(
            "SELECT * FROM source_health ORDER BY status, source_id"
        ).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------------ article cache (article_pipeline.py)
def article_get(url_norm: str):
    """Ambil hasil pipeline artikel dari cache. None kalau belum ada."""
    with _lock:
        row = _c().execute("SELECT * FROM articles WHERE url_norm=?", (url_norm,)).fetchone()
    return dict(row) if row else None


def article_save(url_norm: str, source_url: str, archive_url: str,
                 telegraph_url: str, title: str, status: str = "done"):
    """Simpan hasil pipeline artikel (INSERT OR REPLACE — cache terakhir menang)."""
    with _lock:
        _c().execute(
            "INSERT OR REPLACE INTO articles "
            "(url_norm, source_url, archive_url, telegraph_url, title, status, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (url_norm, source_url, archive_url, telegraph_url, title, status, time.time()),
        )
        _c().commit()
