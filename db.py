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

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    key         TEXT PRIMARY KEY,
    source      TEXT,
    url         TEXT,
    title       TEXT,
    norm_title  TEXT,
    payload     TEXT,
    status      TEXT DEFAULT 'new',   -- new | sent_admin | published | rejected | skipped
    admin_msg   INTEGER,
    created_at  REAL
);
CREATE INDEX IF NOT EXISTS idx_created ON items(created_at);
CREATE INDEX IF NOT EXISTS idx_admin_msg ON items(admin_msg);
"""


def init():
    global _conn
    os.makedirs(os.path.dirname(os.path.abspath(config.DB_PATH)), exist_ok=True)
    _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.executescript(SCHEMA)
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
