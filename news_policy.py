"""Conservative channel policy, independent of agent/editor integrations."""
import re
import time

import config


# Generic football and transfer vocabulary must never establish Liverpool relevance.
_GENERIC_TERMS = {
    'premier league', 'champions league', 'europa league', 'conference league',
    'carabao cup', 'fa cup', 'transfer window', 'here we go', 'medical',
    'personal terms', 'release clause', 'buy-out clause', 'loan deal', 'add-ons',
    'hamstring injury', 'clean sheet', 'matchday squad', 'academy',
    'contract extension', 'pre-season', 'watch', 'kop end', 'kop',
    'everton', 'brighton', 'iraola', 'amu', 'arsenal', 'chelsea',
    'tottenham', 'spurs', 'manchester united', 'manchester city', 'man utd',
    'man city', 'newcastle', 'west ham', 'aston villa', 'nottingham forest',
    'bournemouth', 'wolves', 'fulham', 'brentford', 'crystal palace',
    'sunderland', 'leeds', 'burnley', 'am ex', 'goodison park', 'etihad',
    'old trafford', 'emirates',
}
_EXPLICIT_CLUB_TERMS = {
    'liverpool', 'liverpool fc', 'lfc', 'anfield', 'merseyside derby',
    'axa training centre', 'لیورپول',
}
_UNIQUE_PLAYER_TERMS = {
    'salah': 'mohamed salah', 'alisson': 'alisson becker', 'wirtz': 'florian wirtz',
    'szoboszlai': 'dominik szoboszlai', 'gakpo': 'cody gakpo', 'gravenberch': 'ryan gravenberch',
    'mamardashvili': 'giorgi mamardashvili', 'konate': 'ibrahima konate',
    'frimpong': 'jeremie frimpong', 'ekitike': 'hugo ekitike', 'ngumoha': 'rio ngumoha',
}
_RIVAL_RE = re.compile(
    r"\b(arsenal|chelsea|tottenham|spurs|manchester united|man utd|"
    r"manchester city|man city|everton|newcastle|west ham|aston villa|"
    r"nottingham forest|bournemouth|wolves|fulham|brentford|crystal palace|"
    r"sunderland|leeds|burnley|brighton)\b", re.I)
_FOREIGN_RE = re.compile(
    r'\b(barcelona|real madrid|raphinha|arda g[uü]ler|roma|calafiori|juventus|'
    r'psg|paris saint.germain|inter miami|messi|belgium|turkey|italy|ireland|israel)\b'
    r'|بارسلونا|رافینیا|رئال مادرید|آردا گولر|بلژیک|ترکیه|اسرائیل|ایرلند|تیم ملی ایتالیا', re.I)
_SELF_PROMO_RE = re.compile(
    r'\b(podcast|new episode|subscribe|listen (?:now|here)|we.?re back tonight|'
    r'we are back tonight|i.?m back tonight)\b|پادکست|قسمت جدید', re.I)
_NON_FOOTBALL_RE = re.compile(
    r'\b(city council|airport|museum|university|cathedral|mayor|housing|'
    r'residents|road repairs|cafe|bakery|chemistry|weather|rain|forecast|'
    r'nintendo|baseball|basketball|volleyball|fashion collection|appears in court)\b'
    r'|شهرداری|فرودگاه|موزه|دانشگاه|بسکتبال|والیبال|باران', re.I)
_FOOTBALL_EVENT_RE = re.compile(
    r'\b(football|soccer|goal|goals|striker|midfielder|defender|goalkeeper|'
    r'first.team|squad|fixture|match|training|anfield stadium)\b'
    r'|فوتبال|گل|بازیکن|مهاجم|مدافع|دروازه.بان|تمرین|مسابقه', re.I)
# A short alias followed by another name must not identify the approved player.
_NAME_CONTEXT_WORDS = set(('is are was were has have had will would could should '
                          'can may might not the a an and or for with without to in on at '
                          'from as by of compared scores scored score kept keeps made makes '
                          'says said confirms confirmed returns returned starts started '
                          'joins joined signs signed agrees agreed injured ruled ready '
                          'out doubtful impresses impressed creates created captains '
                          'nets saves shines leads celebrates explains discusses praises '
                          'faces suffers recovers trains breaks dominates vs injury goal goals update magic '
                          'captain winger forward playmaker star breaking exclusive watch s').split())


def _content_text(text):
    # Attribution links/handles and hashtag stuffing are not affiliation evidence.
    return re.sub(r'https?://\S+|www\.\S+|(?<!\w)[@#][\w\u200c]+', '', text or '', flags=re.I)


def _person_match(text, phrase, profile=None):
    if not _has_phrase(text, phrase):
        return False
    if len(phrase.split()) > 1 or (profile and len(profile['name'].split()) > 1 and _has_phrase(text, profile['name'])):
        return True
    for match in re.finditer(r'(?<!\w)' + re.escape(phrase) + r'(?!\w)', text, re.I):
        preceding = re.search(r'([a-z]+)\s+$', text[:match.start()], re.I)
        if (preceding and preceding[1].casefold() not in _NAME_CONTEXT_WORDS
                and not _FOOTBALL_EVENT_RE.fullmatch(preceding[1])):
            continue
        following = re.match(r'\s+([a-z]+)\b', text[match.end():], re.I)
        if not following or following[1].casefold() in _NAME_CONTEXT_WORDS:
            return True
    return False


def _has_phrase(text, phrase):
    phrase = (phrase or '').strip().casefold()
    if not phrase or phrase in _GENERIC_TERMS:
        return False
    # Names can include punctuation (e.g. Alexander-Arnold); boundaries avoid
    # matching short names as substrings of unrelated words.
    return re.search(r'(?<!\w)' + re.escape(phrase) + r'(?!\w)', text, re.I) is not None


def entity_profiles():
    import db
    if db._conn is None:
        return {}
    with db._lock:
        profiles = {r['name'].casefold(): dict(r) for r in db._c().execute('SELECT * FROM news_entities')}
        people = db._c().execute('SELECT english,persian,aliases FROM person_names').fetchall()
    import json
    for person in people:
        profile = profiles.get(person['english'].casefold())
        if profile:
            aliases = json.loads(person['aliases'] or '[]') + [person['persian'] or '']
            for alias in aliases:
                if alias:
                    profiles[alias.casefold()] = profile
    # Shared Persian spelling connects curated aliases to a manually classified identity.
    for english, persian in config.GLOSSARY.items():
        profile = profiles.get(english.casefold())
        if profile:
            for alias, spelling in config.GLOSSARY.items():
                if spelling == persian:
                    profiles.setdefault(alias.casefold(), profile)
    surname_ids = {}
    for profile in profiles.values():
        identity = profile['name'].casefold()
        surname_ids.setdefault(identity.split()[-1], set()).add(identity)
    for name, profile in list(profiles.items()):
        surname = name.split()[-1]
        if len(name.split()) > 1 and len(surname) >= 5 and len(surname_ids.get(surname, ())) == 1 and surname not in {
                'jones', 'williams', 'davies', 'gomez', 'james', 'lewis', 'walker'}:
            profiles.setdefault(surname, profile)
    return profiles


def _has_liverpool_context(text, profiles=None):
    text = _content_text(text).casefold()
    if any(_has_phrase(text, term) for term in _EXPLICIT_CLUB_TERMS):
        return True

    profiles = entity_profiles() if profiles is None else profiles
    for phrase, profile in profiles.items():
        if profile['role'] == 'current' and _person_match(text, phrase, profile):
            return True
        if (profile['role'] == 'target' and profile['expires_at'] > time.time()
                and _has_phrase(text, phrase) and not (_RIVAL_RE.search(text) or _FOREIGN_RE.search(text))
                and re.search(r'\b(transfer|deal|bid|interest|target|sign|talks|agreement)\b', text)):
            return True

    # A spelling dictionary includes reporters and former players: it is not a roster.
    for candidate, identity in _UNIQUE_PLAYER_TERMS.items():
        if candidate not in profiles and _person_match(text, candidate, {'name': identity}):
            return True
    return False


def decision(item, profiles=None):
    title = _content_text(item.get('title')).casefold()
    body = _content_text(item.get('body')).casefold()
    blob = title + ' ' + body
    if item.get('admin_relevance') == 'unrelated':
        return 'reject', 'admin marked unrelated'
    if item.get('admin_relevance') == 'related':
        return 'review', 'admin marked related'
    if any(re.match(r'^\s*rt\s+@', item.get(field) or '', re.I) for field in ('title', 'body')):
        return 'reject', 'plain retweet'
    women = re.search(r"\b(women(?:'s)?|wsl)\b|تیم زنان|بانوان", blob)
    youth = re.search(r'\b(u18s?|u21s?|under-18|under-21)\b', blob)
    senior = re.search(r'\b(first.team|senior)\b|تیم بزرگسالان|تیم اصلی', blob)
    if not config.INCLUDE_WOMEN and (women or (youth and not senior)):
        return 'reject', 'outside men’s first-team coverage'
    if re.search(r'\b(subscribe now|buy (?:your )?tickets|shop now|bet now|enter (?:our|the) competition)\b', blob):
        return 'reject', 'explicit promotion'

    if _SELF_PROMO_RE.search(blob) and not re.search(
            r'\b(injured|injury|scored|won|lost|signed|agreed|bid|goals?|line.?up)\b', blob):
        return 'reject', 'podcast or personal account announcement'

    if _NON_FOOTBALL_RE.search(blob) and not _FOOTBALL_EVENT_RE.search(blob):
        return 'hold', 'non-football topic or ambiguous person/place identity'

    if _has_liverpool_context(blob, profiles):
        return 'review', 'Liverpool context'

    rival = _RIVAL_RE.search(blob) or _FOREIGN_RE.search(blob)
    if rival:
        return 'reject', 'unrelated club or national-team news: ' + rival.group(0)

    source = str(item.get('source') or '').casefold()
    if source == 'lfc official':
        return 'review', 'club source'

    # Source identity alone cannot turn a personal post into Liverpool news.
    return 'hold', 'Liverpool relevance needs confirmation'


def classify_queued():
    """Classify the backlog before the five-item translation budget is consumed."""
    import db
    import json
    import health
    if config.HERMES_ENABLED:
        return
    profiles = entity_profiles()
    rejected = 0
    with db._lock, db._c():
        c = db._c()
        rows = c.execute("SELECT key,payload,status FROM items WHERE status IN ('discovered','new') "
                         "OR (status='retry_pending' AND retry_stage='translation')").fetchall()
        for row in rows:
            item = json.loads(row['payload'])
            action, reason = decision(item, profiles)
            item.update(editorial_decision=action, editorial_reason=reason)
            status = 'rejected' if action == 'reject' else 'awaiting_relevance' if action == 'hold' else row['status']
            c.execute('UPDATE items SET payload=?,status=?,error=CASE WHEN ? IN '
                      "('rejected','awaiting_relevance') THEN ? ELSE error END WHERE key=?",
                      (json.dumps(item, ensure_ascii=False), status, status, reason, row['key']))
            if action == 'reject':
                rejected += 1
    if rejected:
        health.record_counter('policy_rejected', rejected)
