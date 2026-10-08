"""Independent news discovery and conservative story grouping; no agent calls."""
import email.utils
import json
import math
import re
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

import config
import db
import news_policy
import source_policy
from sources.base import SourceBatch, clean_text, parse_rss

_search_lock = threading.Lock()
_audit_lock = threading.Lock()


def published_time(value):
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            stamp = float(value)
        else:
            try:
                date = email.utils.parsedate_to_datetime(value)
            except (TypeError, ValueError):
                date = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            if date.tzinfo is None:
                return None
            stamp = date.timestamp()
        if not math.isfinite(stamp):
            return None
        datetime.fromtimestamp(stamp, timezone.utc)  # Validate dates before captions use them.
        return stamp
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def in_audit_window(item):
    stamp = published_time(item.get('published_at'))
    hours = config.OUTLET_RSS_MAX_AGE_HOURS
    return stamp is None or hours <= 0 or stamp >= time.time() - hours * 3600


def _meta(key, default=None):
    with db._lock:
        row = db._c().execute('SELECT value FROM pipeline_meta WHERE key=?', (key,)).fetchone()
    return row[0] if row else default


def _set_meta(key, value):
    with db._lock, db._c():
        db._c().execute('INSERT INTO pipeline_meta VALUES (?,?) ON CONFLICT(key) '
                        'DO UPDATE SET value=excluded.value', (key, str(value)))


def search_queries():
    queries = ['"Liverpool FC" OR "Liverpool football" when:1d']
    with db._lock:
        rows = db._c().execute("SELECT name,role FROM news_entities WHERE role IN ('current','target') "
                               "AND (expires_at=0 OR expires_at>?) ORDER BY name", (time.time(),)).fetchall()
    if rows:
        cursor = int(_meta('search_cursor', '0')) % len(rows)
        person = rows[cursor]
        # A transfer target's name alone must not import every story about their club.
        suffix = ' Liverpool' if person['role'] == 'target' else ' football'
        queries.append('"' + person['name'].replace('"', '') + '"' + suffix + ' when:1d')
        _set_meta('search_cursor', cursor + 1)
    return queries


def fetch_search(limit=100, refresh=False):
    if not source_policy.source_enabled('news_search') or not _search_lock.acquire(blocking=False):
        return SourceBatch()
    try:
        if not refresh and time.time() - float(_meta('search_checked', '0')) < config.NEWS_SEARCH_INTERVAL:
            return SourceBatch()
        items, errors = [], []
        import source_health
        for query in search_queries():
            url = 'https://news.google.com/rss/search?' + urlencode(
                {'q': query, 'hl': 'en-GB', 'gl': 'GB', 'ceid': 'GB:en'})
            try:
                entries = parse_rss(url, timeout=config.REQUEST_TIMEOUT, strict=True)
                source_health.mark_ok('news_search:' + query, items=len(entries))
                for entry in entries:
                    title, link = clean_text(entry.get('title')), entry.get('link')
                    if title and link:
                        publisher = clean_text(entry.get('publisher'))
                        if publisher and title.endswith(' - ' + publisher):
                            title = title[:-(len(publisher) + 3)].strip()
                        items.append(dict(source='News search', source_tag=publisher or 'News search',
                                          title=title, body=clean_text(entry.get('summary')) or title,
                                          url=link, image=entry.get('image'),
                                          published_at=entry.get('published'), discovery_query=query,
                                          publisher_url=entry.get('publisher_url')))
            except Exception as exc:
                source_health.mark_fail('news_search:' + query, error=str(exc))
                errors.append(str(exc))
        if errors and not items:
            raise ConnectionError('; '.join(errors))
        _set_meta('search_checked', time.time())
        return SourceBatch(items)
    finally:
        _search_lock.release()


def material_signature(item):
    text = ((item.get('title') or '') + ' ' + (item.get('body') or '')).casefold()
    numbers = tuple(sorted(set(re.findall(r'\b\d+(?:[.,]\d+)?\b', text))))
    denied = bool(re.search(r"\b(no|not|never|denies?|denied|false|ruled out|won't|isn't|hasn't)\b", text))
    tentative = bool(re.search(r'\b(may|might|could|rumou?r|reportedly|interested|considering|talks)\b', text))
    units = set()
    for unit, pattern in {
        'gbp': r'£|\b(?:gbp|pounds?)\b', 'eur': r'€|\b(?:eur|euros?)\b',
        'usd': r'\$|\b(?:usd|dollars?)\b', 'million': r'\bmillion\b|\d\s*m\b',
        'billion': r'\bbillion\b|\d\s*bn\b', 'percent': r'%|\bpercent\b',
        'years': r'\byears?\b', 'months': r'\bmonths?\b',
    }.items():
        if re.search(pattern, text):
            units.add(unit)
    import names
    identities = {spelling for name, spelling in names.glossary().items()
                  if news_policy._has_phrase(text, name) and name.casefold() not in news_policy._EXPLICIT_CLUB_TERMS
                  and (len(name.split()) > 1 or len(name) >= 7 or name.casefold() in news_policy._UNIQUE_PLAYER_TERMS)}
    original = (item.get('title') or '') + '\n' + (item.get('body') or '')
    speakers = re.findall(r"\b([A-ZÀ-Ž][a-zà-ž'’-]+(?:\s+[A-ZÀ-Ž][a-zà-ž'’-]+){0,3})\s*(?::|\bsaid\b|\bsays\b)", original)
    speakers = tuple(sorted({s.casefold() for s in speakers if s.casefold() not in ('breaking', 'exclusive', 'update')}))
    return numbers, denied, tentative, tuple(sorted(units)), tuple(sorted(identities)), speakers


def _links(item):
    text = (item.get('title') or '') + ' ' + (item.get('body') or '')
    urls = re.findall(r'https?://[^\s<>"\]]+', text)
    urls += (item.get('external_urls') or []) + (item.get('linked_urls') or [])
    return {db.normalize_url(u.rstrip('.,)')) for u in urls}


def same_story(a, b):
    """A similar headline alone is never sufficient to suppress a received item."""
    date_a, date_b = news_policy.publication_time(a), news_policy.publication_time(b)
    if date_a is not None and date_b is not None and abs(date_a - date_b) > 12 * 3600:
        return False
    if material_signature(a) != material_signature(b):
        return False
    body_a = db.normalize_title(a.get('body') or '')
    body_b = db.normalize_title(b.get('body') or '')
    if min(len(body_a.split()), len(body_b.split())) < 12:
        return False
    if body_a == body_b:
        return True
    linked = (db.normalize_url(a.get('url') or '') in _links(b) or
              db.normalize_url(b.get('url') or '') in _links(a))
    words_a, words_b = set(body_a.split()), set(body_b.split())
    return linked and len(words_a & words_b) / max(1, len(words_a | words_b)) >= .85


def _merge_payload(leader, member, can_enrich):
    sources = leader.setdefault('story_sources', [])
    if not sources:
        sources.append({'url': leader.get('url'), 'source': leader.get('source_tag') or leader.get('source')})
    for source in member.get('story_sources') or [{'url': member.get('url'),
                                                  'source': member.get('source_tag') or member.get('source')}]:
        if source.get('url') and source['url'] not in {s['url'] for s in sources}:
            sources.append(source)
    if can_enrich:
        if len(member.get('body') or '') > len(leader.get('body') or ''):
            leader.setdefault('story_original_text', {'title': leader.get('title'), 'body': leader.get('body')})
            leader['body'] = member['body']
            leader['text_source_url'] = member.get('url')
        for field in ('image', 'images', 'video_url', 'video_urls', 'video_thumb'):
            if not leader.get(field) and member.get(field):
                leader[field] = member[field]
                if field == 'video_url':
                    leader['video_source_url'] = member.get('video_source_url') or member.get('url')
    return leader


def _attach(c, leader_row, member_row):
    leader, member = json.loads(leader_row['payload']), json.loads(member_row['payload'])
    can_enrich = leader_row['status'] in ('new', 'discovered') and not leader.get('translated')
    _merge_payload(leader, member, can_enrich)
    c.execute('UPDATE items SET payload=? WHERE key=?',
              (json.dumps(leader, ensure_ascii=False), leader_row['key']))
    c.execute("UPDATE items SET status='grouped',story_key=? WHERE key=?",
              (leader_row['key'], member_row['key']))


def group_pending_stories(c):
    # ponytail: bounded matching per claim; fuzzy titles stay advisory for the admin.
    rows = c.execute("SELECT * FROM items WHERE created_at>? AND story_key IS NULL "
                     "AND status IN ('discovered','new','sent_admin','pending_admin','approved','published') "
                     "ORDER BY created_at,key LIMIT 1000", (time.time() - 48 * 3600,)).fetchall()
    by_body, by_url = {}, {}
    with c:
        for row in rows:
            item = json.loads(row['payload'])
            if source_policy.disabled_reason(item):
                continue
            if news_policy.decision(item, discovered_at=row['created_at'])[0] != 'review':
                continue
            norm = db.normalize_title(item.get('body') or '')
            candidates = list(by_body.get(norm, {}).values())
            candidates += [by_url[u] for u in _links(item) if u in by_url]
            leader = next((old for old in candidates
                           if db._source_key(json.loads(old['payload'])) != db._source_key(item)
                           and same_story(json.loads(old['payload']), item)), None)
            if leader:
                existing = json.loads(leader['payload'])
                if any(item.get(field) and existing.get(field) and item[field] != existing[field]
                       for field in ('video_url', 'video_urls', 'images')):
                    leader = None
            if leader and leader['status'] not in ('discovered', 'new'):
                existing = json.loads(leader['payload'])
                # A later exclusive video/photo needs its own reviewable card.
                if any(item.get(field) and item[field] != existing.get(field)
                       for field in ('video_url', 'video_urls', 'image', 'images')):
                    leader = None
            if leader and row['status'] in ('discovered', 'new'):
                # Reload after each attachment so earlier sources/media are retained.
                _attach(c, c.execute('SELECT * FROM items WHERE key=?', (leader['key'],)).fetchone(), row)
            else:
                by_body.setdefault(norm, {}).setdefault(db._source_key(item), row)
                by_url[db.normalize_url(item.get('url') or '')] = row


def merge_stories(leader_key, member_key):
    """Explicit admin confirmation allows paraphrases, but never contradictory claims."""
    with db._lock, db._c():
        c = db._c()
        leader = c.execute('SELECT * FROM items WHERE key=?', (leader_key,)).fetchone()
        member = c.execute('SELECT * FROM items WHERE key=?', (member_key,)).fetchone()
        if not leader or not member or leader_key == member_key:
            raise ValueError('دو شناسهٔ متفاوت و معتبر لازم است.')
        if leader['story_key'] or member['story_key']:
            raise ValueError('این خبر قبلاً تجمیع شده؛ شناسهٔ خبر اصلی را استفاده کن.')
        if member['status'] not in ('discovered', 'new', 'sent_admin', 'pending_admin', 'failed', 'rejected'):
            raise ValueError('خبر در حال پردازش یا منتشرشده را نمی‌توان ادغام کرد.')
        if leader['status'] not in ('discovered', 'new', 'sent_admin', 'pending_admin', 'approved', 'published'):
            raise ValueError('ابتدا پردازش خبر اصلی باید تمام شود.')
        if material_signature(json.loads(leader['payload'])) != material_signature(json.loads(member['payload'])):
            raise ValueError('اعداد، نفی یا قطعیت متفاوت است؛ خبرها جدا نگه داشته شدند.')
        _attach(c, leader, member)


def source_handles():
    with db._lock:
        return [r[0] for r in db._c().execute("SELECT handle FROM source_candidates WHERE state='watching' "
                                              'AND expires_at>? ORDER BY handle', (time.time(),))]


def set_source(handle, state='watching', days=7, club_only=False):
    handle = handle.lstrip('@').casefold()
    if not re.fullmatch(r'[a-z0-9_]{1,15}', handle) or not 1 <= days <= 30:
        raise ValueError('نام اکانت معتبر و مدت بین ۱ تا ۳۰ روز لازم است.')
    with db._lock, db._c():
        db._c().execute('INSERT INTO source_candidates VALUES (?,?,?,?) ON CONFLICT(handle) '
                        'DO UPDATE SET state=excluded.state,expires_at=excluded.expires_at,club_only=excluded.club_only',
                        (handle, state, time.time() + days * 86400, int(club_only)))


def discover_sources(items):
    trusted = {h.lstrip('@').casefold() for h in config.TWITTER_TIER1 + config.TWITTER_LFC_ONLY}
    tracked = {h.lstrip('@').casefold() for h in config.TWITTER_ACCOUNTS}
    with db._lock, db._c():
        c = db._c()
        for item in items:
            author = str(item.get('ingest_handle') or item.get('handle') or '').lstrip('@').casefold()
            if author not in trusted or not news_policy._has_liverpool_context(
                    (item.get('title') or '') + ' ' + (item.get('body') or '')):
                continue
            cited = list(item.get('original_sources') or [])
            if item.get('original_source'):
                cited.append(item['original_source'])
            cited += re.findall(r'(?:via|according to|reported by|\[)\s*@([A-Za-z0-9_]{1,15})\b',
                                item.get('body') or '', re.I)
            for handle in cited:
                handle = str(handle).lstrip('@').casefold()
                if handle in tracked or handle == author or not re.fullmatch(r'[a-z0-9_]{1,15}', handle):
                    continue
                c.execute('INSERT OR IGNORE INTO source_candidates(handle) VALUES (?)', (handle,))
                c.execute('INSERT OR IGNORE INTO source_citations VALUES (?,?,?,?,?)',
                          (handle, db.make_key(item), item.get('url'), author, time.time()))


def scan_missed():
    """Keep the reference snapshot separately. Only a human recovery ingests it."""
    if not _audit_lock.acquire(blocking=False):
        return False
    try:
        from sources import outlet_rss, lfc_official
        sources = []
        if source_policy.source_enabled('lfc_official'):
            sources.append(('lfc_official', lfc_official.fetch))
        if source_policy.source_enabled('outlet_rss'):
            sources.append(('outlet_rss', outlet_rss.fetch))
            if outlet_rss.enabled_source_ids():
                sources.append(('rss_extra', outlet_rss.fetch_extra))
        if source_policy.source_enabled('news_search'):
            sources.append(('news_search', lambda limit: fetch_search(limit, refresh=True)))
        errors, received = [], 0
        for source_id, fetch in sources:
            try:
                batch = fetch(limit=config.FETCH_ITEMS_PER_SOURCE)
                for raw in batch:
                    item = dict(raw, source_id=source_id)
                    received += 1
                    with db._lock, db._c():
                        db._c().execute('INSERT INTO discovery_candidates(key,payload,found_at,updated_at) '
                                        'VALUES (?,?,?,?) ON CONFLICT(key) DO UPDATE SET '
                                        'payload=excluded.payload,updated_at=excluded.updated_at',
                                        (db.make_key(item), json.dumps(item, ensure_ascii=False), time.time(), time.time()))
            except Exception as exc:
                errors.append(source_id + ': ' + str(exc)[:150])
        _set_meta('missed_scan', json.dumps({'at': time.time(), 'received': received,
                                            'sources': [s[0] for s in sources], 'errors': errors}))
        return True
    finally:
        _audit_lock.release()


def missed_candidates():
    with db._lock:
        rows = db._c().execute("SELECT * FROM discovery_candidates WHERE state='missing' "
                               'ORDER BY found_at DESC,key').fetchall()
    out = []
    for row in rows:
        item = json.loads(row['payload'])
        if source_policy.disabled_reason(item):
            continue
        if not in_audit_window(item) or news_policy.decision(item)[0] == 'reject':
            continue
        existing = db.get(db.make_key(item))
        if existing and existing['status'] not in ('rejected', 'failed', 'skipped'):
            continue
        out.append(dict(row, payload=item, existing_status=existing['status'] if existing else None))
    return out


def recover(key):
    with db._lock, db._c():
        c = db._c()
        row = db.get(key)
        candidate = c.execute('SELECT * FROM discovery_candidates WHERE key=?', (key,)).fetchone()
        if row and row['status'] not in ('rejected', 'failed', 'retry_pending', 'skipped', 'awaiting_relevance'):
            raise ValueError('این خبر در صف، در انتظار ادمین یا منتشرشده است.')
        if not row and not candidate:
            raise ValueError('خبر پیدا نشد.')
        item = row['payload'] if row else json.loads(candidate['payload'])
        if source_policy.disabled_reason(item):
            raise ValueError('این منبع فعلاً غیرفعال است؛ بازیابی خبر متوقف شد.')
        if not item.get('body') and candidate:
            item = json.loads(candidate['payload'])
        if not item.get('body') and not item.get('title'):
            raise ValueError('متن خبر موجود نیست؛ لینک را دوباره ارسال کن.')
        item['admin_relevance'] = 'related'
        if row:
            c.execute("UPDATE items SET payload=?,status='discovered',retry_count=0,next_retry_at=0,error=NULL "
                      'WHERE key=?', (json.dumps(item, ensure_ascii=False), key))
        else:
            c.execute('INSERT INTO items(key,source,url,title,norm_title,payload,status,created_at,canonical_url) '
                      "VALUES (?,?,?,?,?,?,'discovered',?,?)",
                      (key, item.get('source'), item.get('url'), item.get('title'), db.normalize_title(item.get('title')),
                       json.dumps(item, ensure_ascii=False), time.time(), db.normalize_url(item.get('url') or '')))
        if candidate:
            c.execute("UPDATE discovery_candidates SET state='recovered' WHERE key=?", (key,))
        return key
