"""Online name suggestions; an admin owns the approved Persian spelling."""
import json
import logging
import re
import threading
import time
from urllib.parse import urljoin

import requests
import config
import db

log = logging.getLogger('names')
ROSTER = 'https://www.liverpoolfc.com/team/mens'
API = 'https://www.wikidata.org/w/api.php'
_refresh_lock = threading.Lock()


def glossary():
    result = dict(config.GLOSSARY)
    if db._conn is None:
        return result
    with db._lock:
        rows = db._c().execute('SELECT english,persian,aliases FROM person_names WHERE persian IS NOT NULL').fetchall()
    for row in rows:
        result[row['english']] = row['persian']
        for alias in json.loads(row['aliases'] or '[]'):
            if len(alias) >= 4:
                result.setdefault(alias, row['persian'])
    return result


def unknown_in(text):
    if db._conn is None:
        return []
    with db._lock:
        rows = db._c().execute('SELECT english FROM person_names WHERE persian IS NULL').fetchall()
    low = (text or '').casefold()
    return [r['english'] for r in rows if r['english'].casefold() in low]


def _api(params):
    response = requests.get(API, params=dict(params, format='json'), timeout=12,
                            headers={'User-Agent': 'LFCNewsBot/1.0 (name suggestions; read-only)'})
    response.raise_for_status()
    return response.json()


def lookup(english, club_id=None):
    hits = _api({'action': 'wbsearchentities', 'search': english, 'language': 'en', 'limit': 5}).get('search', [])
    ids = [h['id'] for h in hits if h.get('label', '').casefold() == english.casefold()
           and (club_id or re.search(r'football|soccer|physiotherapist', h.get('description', ''), re.I))]
    if not ids:
        return None
    entities = _api({'action': 'wbgetentities', 'ids': '|'.join(ids), 'props': 'labels|aliases|claims',
                     'languages': 'en|fa'}).get('entities', {})
    matches = []
    for qid, entity in entities.items():
        claims = entity.get('claims') or {}
        def values(prop):
            return {c.get('mainsnak', {}).get('datavalue', {}).get('value', {}).get('id')
                    for c in claims.get(prop, []) if c.get('rank') != 'deprecated'
                    and isinstance(c.get('mainsnak', {}).get('datavalue', {}).get('value'), dict)}
        # Exact English label + human + independently recorded Liverpool affiliation.
        if 'Q5' not in values('P31') or (club_id and club_id not in (values('P54') | values('P108'))):
            continue
        fa = (entity.get('labels', {}).get('fa') or {}).get('value')
        if fa and re.fullmatch(r'[\u0600-\u06ff\s\u200c\-]+', fa):
            aliases = [a['value'] for a in entity.get('aliases', {}).get('en', [])]
            matches.append((qid, fa, aliases))
    return matches[0] if len(matches) == 1 else None


def refresh():
    """Daily roster inventory, with 24-hour positive/negative entity lookup cache."""
    from bs4 import BeautifulSoup
    if not _refresh_lock.acquire(blocking=False):
        return
    try:
        response = requests.get(ROSTER, timeout=20, headers={'User-Agent': config.USER_AGENT})
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        roster = {}
        for anchor in soup.select('a[href]'):
            href = anchor.get('href', '')
            if '/teams/mens-team/' not in href:
                continue
            slug = href.rstrip('/').rsplit('/', 1)[-1]
            # Official profile slugs are stable identity anchors, not free-text search hits.
            name = slug.replace('-', ' ').title()
            if re.fullmatch(r'[A-Za-zÀ-ž ]{4,80}', name):
                roster[name] = urljoin(ROSTER, href)
        if not roster:
            raise ValueError('official roster returned no person profiles; retaining existing names')
        with db._lock:
            c = db._c()
            for english, url in roster.items():
                existing = next((fa for en, fa in config.GLOSSARY.items() if en.casefold() == english.casefold()), None)
                c.execute('INSERT INTO person_names (english,persian,official_url,approved_at,roster_seen_at) VALUES (?,?,?,?,?) '
                          'ON CONFLICT(english) DO UPDATE SET official_url=excluded.official_url,roster_seen_at=excluded.roster_seen_at',
                          (english, existing, url, time.time() if existing else None, time.time()))
                c.execute("INSERT INTO news_entities VALUES (?,'current',0,?,?) ON CONFLICT(name) DO UPDATE SET "
                          "role='current',expires_at=0,evidence=excluded.evidence,updated_at=excluded.updated_at",
                          (english.casefold(), url, time.time()))
            # Only a successful, nonempty roster snapshot can retire an affiliation.
            for entity in c.execute("SELECT name FROM news_entities WHERE role='current' "
                                    "AND evidence LIKE 'https://www.liverpoolfc.com/%'").fetchall():
                if entity['name'] not in {en.casefold() for en in roster}:
                    c.execute("UPDATE news_entities SET role='former',updated_at=? WHERE name=?",
                              (time.time(), entity['name']))
            c.commit()
            rows = c.execute('SELECT * FROM person_names WHERE checked_at<?', (time.time() - 86400,)).fetchall()
        club = _api({'action': 'wbgetentities', 'sites': 'enwiki', 'titles': 'Liverpool F.C.', 'props': 'labels'})
        club_ids = [k for k in club.get('entities', {}) if re.fullmatch(r'Q\d+', k)]
        if len(club_ids) != 1:
            raise ValueError('could not resolve club identity')
        for row in rows:
            try:
                candidate = lookup(row['english'], club_ids[0])
                qid, fa, aliases = candidate if candidate else (None, None, [])
                evidence = [row['official_url']] + (['https://www.wikidata.org/wiki/' + qid] if qid else [])
                with db._lock:
                    c.execute('UPDATE person_names SET wikidata_id=?,candidate=?,aliases=?,evidence=?,checked_at=?, '
                              'identity_verified=? WHERE id=?',
                              (qid, fa, json.dumps(aliases), json.dumps(evidence), time.time(), bool(qid), row['id']))
                    c.commit()
            except Exception as exc:
                log.warning('name lookup failed for %s: %s', row['english'], exc)
    except Exception as exc:
        log.warning('roster refresh failed; cached names retained: %s', exc)
    finally:
        _refresh_lock.release()


def start_refresh(stop=None):
    stop = stop or threading.Event()
    def loop():
        with db._lock:
            row = db._c().execute("SELECT value FROM pipeline_meta WHERE key='names_roster_checked'").fetchone()
            last_roster = float(row[0]) if row else 0
        while not stop.is_set():
            if time.time() - last_roster >= 86400:
                refresh()
                last_roster = time.time()
                with db._lock:
                    c = db._c()
                    c.execute("INSERT INTO pipeline_meta VALUES ('names_roster_checked',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(last_roster),))
                    c.commit()
            refresh_unknowns()
            stop.wait(60)
    threading.Thread(target=loop, name='name-refresh', daemon=True).start()


def remember_unknowns(item):
    """Queue possible new football names for background lookup; never block translation."""
    text = (item.get('body') or item.get('title') or '')
    candidates = set(re.findall(r'\b[A-Z][a-zÀ-ž]+(?:\s+(?:van|de|di))?(?:\s+[A-Z][a-zÀ-ž]+){1,2}\b', text))
    blocked = {'Liverpool', 'Premier', 'Champions', 'Football', 'Club', 'The', 'This', 'Breaking',
               'Personal', 'Training', 'Centre', 'Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'}
    approved = {en.casefold() for en in glossary()}
    with db._lock:
        c = db._c()
        for name in candidates:
            if name.casefold() in approved or blocked.intersection(name.split()):
                continue
            c.execute('INSERT OR IGNORE INTO person_names (english,evidence) VALUES (?,?)',
                      (name, json.dumps([item.get('url') or ''])))
        c.commit()


def refresh_unknowns():
    with db._lock:
        c = db._c()
        rows = c.execute('SELECT * FROM person_names WHERE official_url IS NULL AND checked_at<?',
                         (time.time() - 86400,)).fetchall()
    for row in rows:
        try:
            candidate = lookup(row['english'])
            qid, fa, aliases = candidate if candidate else (None, None, [])
            evidence = json.loads(row['evidence'] or '[]')
            if qid:
                evidence.append('https://www.wikidata.org/wiki/' + qid)
            with db._lock:
                c.execute('UPDATE person_names SET candidate=?,wikidata_id=?,aliases=?,evidence=?, '
                          'checked_at=?,identity_verified=? WHERE id=?',
                          (fa, qid, json.dumps(aliases), json.dumps(list(dict.fromkeys(evidence))),
                           time.time(), bool(qid), row['id']))
                c.commit()
        except Exception as exc:
            log.warning('unknown-name lookup unavailable for %s: %s', row['english'], exc)
            with db._lock:
                c.execute('UPDATE person_names SET checked_at=? WHERE id=?', (time.time(), row['id']))
                c.commit()


def approve(person_id, persian):
    if not persian.strip() or not re.fullmatch(r'[\u0600-\u06ff\s\u200c\-]+', persian.strip()):
        raise ValueError('نام باید فارسی باشد')
    with db._lock:
        c = db._c()
        row = c.execute('SELECT * FROM person_names WHERE id=?', (person_id,)).fetchone()
        if row is None:
            raise KeyError('شناسه نام پیدا نشد')
        # Manual spelling is tied to a profile from the official roster.
        if not row['official_url'] and not row['identity_verified']:
            raise ValueError('هویت رسمی برای این نام ثبت نشده')
        c.execute('UPDATE person_names SET persian=?,approved_at=? WHERE id=?',
                  (persian.strip(), time.time(), person_id))
        c.commit()


def report():
    from html import escape
    with db._lock:
        rows = db._c().execute('SELECT * FROM person_names WHERE persian IS NULL OR '
                               '(candidate IS NOT NULL AND candidate!=persian) ORDER BY english').fetchall()
    parts = ['نام‌های پیشنهادی؛ تأیید/اصلاح: /names set شناسه نام‌فارسی']
    for row in rows:
        parts.append(f"\n{row['id']} — {escape(row['english'])}: {escape(row['candidate'] or 'نام فارسی پیدا نشد')}"
                     + '\n' + '\n'.join(escape(u) for u in (json.loads(row['evidence'] or '[]') or [row['official_url'] or ''])))
    return '\n'.join(parts) if rows else 'نام تازه‌ای برای تأیید وجود ندارد'
