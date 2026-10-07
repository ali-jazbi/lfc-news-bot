"""ذخیره‌سازی و جلوگیری از خبر تکراری (SQLite)."""
import json
import os
import re
import sqlite3
import hashlib
import threading
import time
from collections import defaultdict, deque
from contextlib import closing
from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import config

_lock = threading.RLock()
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
STATUS_AWAITING_RELEVANCE = "awaiting_relevance"
QUEUE_STATUSES = (STATUS_DISCOVERED, "new", "processing", STATUS_ANALYZING,
                  STATUS_VERIFICATION, STATUS_APPROVED_BY_AI, STATUS_TRANSLATION,
                  STATUS_TRANSLATION_REVIEW, STATUS_MEDIA_PROCESSING,
                  STATUS_RETRY_PENDING, STATUS_FAILED, STATUS_PENDING_ADMIN,
                  "sent_admin", STATUS_APPROVED, "grouped", STATUS_AWAITING_RELEVANCE)
# وضعیت‌های قدیمی که برای سازگاری حفظ شده‌اند:
# new | sent_admin | skipped | rejected | approved | published

SCHEMA = """
CREATE TABLE IF NOT EXISTS discovery_candidates (
    key TEXT PRIMARY KEY, payload TEXT NOT NULL, found_at REAL, updated_at REAL,
    state TEXT DEFAULT 'missing'
);
CREATE TABLE IF NOT EXISTS account_polls (
    handle TEXT PRIMARY KEY, attempted_at REAL, last_item_at REAL,
    received INTEGER DEFAULT 0, polls INTEGER DEFAULT 0, empty_streak INTEGER DEFAULT 0,
    outcome TEXT, error TEXT, latency_ms REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS source_candidates (
    handle TEXT PRIMARY KEY, state TEXT DEFAULT 'suggested', expires_at REAL DEFAULT 0,
    club_only INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS source_citations (
    handle TEXT, news_key TEXT, url TEXT, cited_by TEXT, created_at REAL,
    PRIMARY KEY(handle,news_key)
);
CREATE TABLE IF NOT EXISTS news_entities (
    name TEXT PRIMARY KEY, role TEXT, expires_at REAL DEFAULT 0, evidence TEXT,
    updated_at REAL
);
CREATE TABLE IF NOT EXISTS pipeline_meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS checkpoints (
    source_id TEXT, account TEXT, watermark REAL,
    PRIMARY KEY(source_id, account)
);
CREATE TABLE IF NOT EXISTS person_names (
    id INTEGER PRIMARY KEY, english TEXT UNIQUE, persian TEXT,
    aliases TEXT DEFAULT '[]', official_url TEXT, wikidata_id TEXT,
    candidate TEXT, evidence TEXT DEFAULT '[]', checked_at REAL DEFAULT 0,
    approved_at REAL, identity_verified INTEGER DEFAULT 0
);
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
    "ALTER TABLE items ADD COLUMN retry_stage TEXT",
    "ALTER TABLE items ADD COLUMN next_retry_at REAL DEFAULT 0",
    "ALTER TABLE items ADD COLUMN canonical_url TEXT",
    "ALTER TABLE items ADD COLUMN story_key TEXT",
    "ALTER TABLE person_names ADD COLUMN roster_seen_at REAL DEFAULT 0",
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
    # Back up an existing DB before the first queue migration, including WAL data.
    has_items = _conn.execute("SELECT 1 FROM sqlite_master WHERE name='items'").fetchone()
    has_meta = _conn.execute("SELECT 1 FROM sqlite_master WHERE name='pipeline_meta'").fetchone()
    has_discovery = _conn.execute("SELECT 1 FROM sqlite_master WHERE name='discovery_candidates'").fetchone()
    if has_items and (not has_meta or not has_discovery):
        folder = Path(config.DB_PATH).resolve().parent / "backups"
        folder.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(folder / f"pre-pipeline-{time.time_ns()}.db")) as backup:
            _conn.backup(backup)
    # WAL: چون poller_loop (ترد پس‌زمینه) و bot_loop (ترد اصلی) هم‌زمان به
    # دیتابیس می‌نویسند/می‌خوانند، WAL خواندن و نوشتن هم‌زمان را ممکن می‌کند
    # و ریسک قفل‌شدن دیتابیس ("database is locked") را عملاً از بین می‌برد.
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute("PRAGMA synchronous=NORMAL")
    # اگر با وجود WAL یک لحظه قفل شد، به‌جای خطای فوری تا ۵ ثانیه صبر کند.
    _conn.execute("PRAGMA busy_timeout=5000")
    _conn.executescript(SCHEMA)
    _migrate()
    # Preserve old news keys/buttons while adopting stronger URL canonicalization.
    for row in _conn.execute("SELECT key,url FROM items WHERE canonical_url IS NULL").fetchall():
        _conn.execute("UPDATE items SET canonical_url=? WHERE key=?", (normalize_url(row['url'] or ''), row['key']))
    _conn.execute('CREATE INDEX IF NOT EXISTS idx_canonical_url ON items(canonical_url)')
    if not _conn.execute("SELECT 1 FROM pipeline_meta WHERE key='queue_v1'").fetchone():
        _conn.execute("UPDATE items SET status=?, retry_stage='translation', retry_count=0 "
                      "WHERE status='skipped' AND error='translation chain failed'",
                      (STATUS_DISCOVERED,))
        _conn.execute("INSERT INTO pipeline_meta VALUES ('queue_v1','1')")
    for row in _conn.execute("SELECT key,payload,retry_count FROM items WHERE status='retry_pending' AND retry_stage IS NULL").fetchall():
        payload = json.loads(row['payload'] or '{}')
        stage = 'send' if payload.get('translated') else 'translation'
        status = STATUS_FAILED if (row['retry_count'] or 0) >= config.MAX_SEND_RETRIES else STATUS_RETRY_PENDING
        _conn.execute('UPDATE items SET retry_stage=?,status=? WHERE key=?', (stage, status, row['key']))
    # A process restart makes interrupted stages eligible again, retaining payload.
    _conn.execute("UPDATE items SET status=? WHERE status IN "
                  "('processing','analyzing','verification','approved_by_ai',"
                  "'translation','translation_review','media_processing')",
                  (STATUS_DISCOVERED,))
    _conn.commit()
    if not _conn.execute("SELECT 1 FROM pipeline_meta WHERE key='translation_wait_v2'").fetchone():
        folder = Path(config.DB_PATH).parent / 'backups'
        folder.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(folder / f'pre-provider-queue-{time.time_ns()}.db')) as backup:
            _conn.backup(backup)
        with _conn:
            _conn.execute("UPDATE items SET status='retry_pending',retry_stage='translation',retry_count=0,"
                          "next_retry_at=0 WHERE status='failed' AND error='translation chain failed'")
            _conn.execute("INSERT INTO pipeline_meta VALUES ('translation_wait_v2','1')")
    return _conn


def _c():
    return _conn if _conn is not None else init()


def normalize_url(url: str) -> str:
    try:
        p = urlparse(url)
        host = p.netloc.lower().removeprefix('www.')
        scheme = 'https' if p.scheme in ('http', 'https') else p.scheme
        # Canonical Twitter identity is independent of handle spelling/domain.
        tweet = re.search(r'/status(?:es)?/(\d+)', p.path)
        if host in ('x.com', 'twitter.com', 'mobile.twitter.com') and tweet:
            return 'https://x.com/i/status/' + tweet.group(1)
        query = urlencode(sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                                 if not k.lower().startswith("utm_") and k.lower() not in ("fbclid", "gclid")))
        return urlunparse((scheme, host, p.path.rstrip("/"), "", query, ""))
    except Exception:
        return url


def normalize_title(title: str) -> str:
    t = (title or "").lower()
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"[^a-z0-9\u0600-\u06FF ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def make_key(item: dict) -> str:
    base = normalize_url(item.get("url", "")) or item.get("title", "")
    if _conn is not None and item.get('url'):
        with _lock:
            row = _conn.execute('SELECT key FROM items WHERE canonical_url=? ORDER BY created_at LIMIT 1', (base,)).fetchone()
        if row:
            return row['key']
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
    """Only exact identities in terminal/review states block processing."""
    key = make_key(item)
    with _lock:
        cur = _c().execute("SELECT status FROM items WHERE key=?", (key,))
        row = cur.fetchone()
        if row:
            return row['status'] in ('sent_admin', STATUS_PENDING_ADMIN,
                                     STATUS_APPROVED, STATUS_PUBLISHED, STATUS_REJECTED,
                                     'skipped', 'grouped')
        return False  # Similar titles are advisory; a different URL is not a duplicate.

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
    from discovery import same_story
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
        if not same_story(item, old):
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
            "INSERT INTO items "
            "(key, source, url, title, norm_title, payload, status, admin_msg, created_at, canonical_url) "
            "VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
            "payload=excluded.payload, title=excluded.title, norm_title=excluded.norm_title, "
            "status=excluded.status, admin_msg=COALESCE(excluded.admin_msg,items.admin_msg)",
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
                normalize_url(item.get('url') or ''),
            ),
        )
        _c().commit()
    return key


def checkpoint_map(source_id):
    with _lock:
        return {r['account']: r['watermark'] for r in _c().execute(
            "SELECT account,watermark FROM checkpoints WHERE source_id=?", (source_id,))}


def import_checkpoints(source_id, values):
    """One-time legacy import. Collection subsequently owns all watermark writes."""
    marker = 'checkpoint_import:' + source_id
    with _lock:
        c = _c()
        if c.execute("SELECT 1 FROM pipeline_meta WHERE key=?", (marker,)).fetchone():
            return
        with c:
            for account, watermark in values.items():
                c.execute("INSERT OR IGNORE INTO checkpoints VALUES (?,?,?)",
                          (source_id, account.lower(), float(watermark)))
            c.execute("INSERT INTO pipeline_meta VALUES (?, '1')", (marker,))


def ingest_batch(source_id, batch):
    """Either received payloads AND watermarks commit, or neither does."""
    inserted = 0
    with _lock:
        c = _c()
        with c:
            for original in batch.items:
                item = dict(original, source_id=source_id)
                cur = c.execute(
                    "INSERT OR IGNORE INTO items "
                    "(key,source,url,title,norm_title,payload,status,created_at,canonical_url) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (make_key(item), item.get('source'), item.get('url'), item.get('title'),
                     normalize_title(item.get('title')), json.dumps(item, ensure_ascii=False),
                     STATUS_DISCOVERED, time.time(), normalize_url(item.get('url') or '')))
                inserted += cur.rowcount
            for diag in batch.diagnostics:
                handle = diag['handle'].lstrip('@').casefold()
                count = int(diag.get('received', 0))
                now = time.time()
                c.execute('INSERT INTO account_polls '
                          '(handle,attempted_at,last_item_at,received,polls,empty_streak,outcome,error,latency_ms) '
                          'VALUES (?,?,?,?,1,?,?,?,?) ON CONFLICT(handle) DO UPDATE SET '
                          'attempted_at=excluded.attempted_at, '
                          'last_item_at=CASE WHEN excluded.last_item_at>COALESCE(account_polls.last_item_at,0) '
                          'THEN excluded.last_item_at ELSE account_polls.last_item_at END, '
                          'received=account_polls.received+excluded.received,polls=account_polls.polls+1, '
                          'empty_streak=CASE WHEN excluded.received>0 THEN 0 ELSE account_polls.empty_streak+1 END, '
                          'outcome=excluded.outcome,error=excluded.error,latency_ms=excluded.latency_ms',
                          (handle, now, diag.get('latest_at') or None, count, 0 if count else 1,
                           diag.get('outcome', 'returned' if count else 'empty'),
                           str(diag.get('error') or '')[:300], diag.get('latency_ms', 0)))
            for account, watermark in batch.checkpoints.items():
                c.execute("INSERT INTO checkpoints VALUES (?,?,?) ON CONFLICT(source_id,account) "
                          "DO UPDATE SET watermark=MAX(checkpoints.watermark,excluded.watermark)",
                          (source_id, account.lower(), float(watermark)))
    return inserted


def queue_items(limit=5):
    """Claim FIFO per source/account, rotating across groups between cycles."""
    with _lock:
        c = _c()
        from discovery import group_pending_stories
        group_pending_stories(c)
        rows = c.execute("SELECT * FROM items WHERE status IN ('discovered','new') "
                         "OR (status='retry_pending' AND retry_stage!='send' AND "
                         "COALESCE(next_retry_at,0)<=?) ORDER BY created_at,key",
                         (time.time(),)).fetchall()
        groups = defaultdict(deque)
        for r in rows:
            item = json.loads(r['payload'])
            group = str(item.get('source_id') or item.get('source') or '') + ':' + str(
                item.get('ingest_handle') or item.get('handle') or '')
            groups[group].append((dict(r), item))
        keys = sorted(groups)
        cursor = c.execute("SELECT value FROM pipeline_meta WHERE key='queue_cursor'").fetchone()
        if cursor and keys:
            cut = next((i for i, k in enumerate(keys) if k > cursor['value']), len(keys))
            keys = keys[cut:] + keys[:cut]
        chosen = []
        with c:
            while keys and len(chosen) < limit:
                for group in list(keys):
                    row, item = groups[group].popleft()
                    row['payload'] = item
                    chosen.append(row)
                    c.execute("UPDATE items SET status='processing', last_attempt_at=? WHERE key=?",
                              (time.time(), row['key']))
                    c.execute("INSERT INTO pipeline_meta VALUES ('queue_cursor',?) "
                              "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (group,))
                    if not groups[group]:
                        keys.remove(group)
                    if len(chosen) >= limit:
                        break
        return chosen


def stage_failed(key, stage, error):
    with _lock:
        c = _c()
        row = c.execute("SELECT retry_stage,retry_count FROM items WHERE key=?", (key,)).fetchone()
        attempts = (row['retry_count'] or 0) + 1 if row and row['retry_stage'] == stage else 1
        status = STATUS_FAILED if attempts >= getattr(config, 'MAX_SEND_RETRIES', 3) else STATUS_RETRY_PENDING
        c.execute("UPDATE items SET status=?,retry_stage=?,retry_count=?,error=?,"
                  "last_attempt_at=?,next_retry_at=? WHERE key=?",
                  (status, stage, attempts, str(error)[:500], time.time(),
                   time.time() + min(30 * 2 ** (attempts - 1), 1800), key))
        c.commit()


def defer_translation(key, until):
    with _lock, _c():
        _c().execute("UPDATE items SET status='retry_pending',retry_stage='translation',"
                     "next_retry_at=?,last_attempt_at=?,error='waiting for translation provider' WHERE key=?",
                     (until, time.time(), key))


def reset_retry(key):
    with _lock:
        c = _c()
        c.execute("UPDATE items SET status='discovered',retry_count=0,next_retry_at=0,error=NULL "
                  "WHERE key=? AND status IN ('failed','retry_pending')", (key,))
        c.commit()


def pipeline_stats():
    with _lock:
        return dict(_c().execute("SELECT status,COUNT(*) FROM items GROUP BY status").fetchall())


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


def get_by_admin_msg(msg_id) -> "dict | None":
    """خبر بر اساس message_id پیش‌نمایش گروه — برای ویرایش با ریپلای + /edit.
    اگر چند ردیف همان msg_id را داشتند، آخرین (تازه‌ترین) برمی‌گردد."""
    if msg_id is None:
        return None
    with _lock:
        row = _c().execute(
            "SELECT * FROM items WHERE admin_msg=? ORDER BY created_at DESC LIMIT 1",
            (msg_id,),
        ).fetchone()
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
            "SELECT * FROM items WHERE status=? AND (retry_stage='send' OR retry_stage IS NULL) AND COALESCE(retry_count,0) < ? AND COALESCE(next_retry_at,0)<=?"
            " ORDER BY last_attempt_at ASC LIMIT ?",
            (STATUS_RETRY_PENDING, max_retries, time.time(), limit),
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
