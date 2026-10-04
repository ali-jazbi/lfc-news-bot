"""Conservative channel policy, independent of agent/editor integrations."""
import re

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
    'axa training centre', 'kirby', 'kirkby', 'the reds',
}
_UNIQUE_PLAYER_TERMS = {
    'salah', 'alisson', 'wirtz', 'szoboszlai', 'gakpo', 'gravenberch',
    'mamardashvili', 'konate', 'frimpong', 'ekitike', 'ngumoha',
}
_RIVAL_RE = re.compile(
    r"\b(arsenal|chelsea|tottenham|spurs|manchester united|man utd|"
    r"manchester city|man city|everton|newcastle|west ham|aston villa|"
    r"nottingham forest|bournemouth|wolves|fulham|brentford|crystal palace|"
    r"sunderland|leeds|burnley|brighton)\b", re.I)


def _has_phrase(text, phrase):
    phrase = (phrase or '').strip().casefold()
    if not phrase or phrase in _GENERIC_TERMS:
        return False
    # Names can include punctuation (e.g. Alexander-Arnold); boundaries avoid
    # matching short names as substrings of unrelated words.
    return re.search(r'(?<!\w)' + re.escape(phrase) + r'(?!\w)', text, re.I) is not None


def _has_liverpool_context(text):
    if any(_has_phrase(text, term) for term in _EXPLICIT_CLUB_TERMS):
        return True

    # Use named people only as a signal; ignore generic phrases and short,
    # collision-prone surnames. Approved roster names from the shared glossary
    # are authoritative; ROMANO_KEYWORDS contains a few account-specific aliases.
    import names
    for candidate in (*names.glossary().keys(), *config.ROMANO_KEYWORDS):
        candidate = candidate.strip().casefold()
        if candidate in _GENERIC_TERMS or candidate in _EXPLICIT_CLUB_TERMS:
            continue
        if len(candidate.split()) == 1 and len(candidate) < 7 and candidate not in _UNIQUE_PLAYER_TERMS:
            continue
        if _has_phrase(text, candidate):
            return True
    return False


def decision(item):
    title = (item.get('title') or '').casefold()
    body = (item.get('body') or '').casefold()
    blob = title + ' ' + body
    if not config.INCLUDE_WOMEN and re.search(r"\b(women(?:'s)?|wsl|u18|u21|under-18|under-21)\b", title):
        return 'reject', 'outside men’s first-team coverage'
    if re.search(r'\b(subscribe now|buy (?:your )?tickets|shop now|bet now|enter (?:our|the) competition)\b', blob):
        return 'reject', 'explicit promotion'
    if body.startswith('rt @') or title.startswith('rt @'):
        return 'reject', 'plain retweet'

    source = str(item.get('source') or '').casefold()
    source_tag = str(item.get('source_tag') or '').casefold()
    if source == 'lfc official' or 'liverpool' in source_tag:
        return 'review', 'club source'

    handle = str(item.get('ingest_handle') or item.get('handle') or '').lstrip('@').casefold()
    if handle in {x.lstrip('@').casefold() for x in config.TWITTER_LFC_ONLY}:
        return 'review', 'Liverpool-specific account'

    if _has_liverpool_context(blob):
        return 'review', 'Liverpool context'

    rival = _RIVAL_RE.search(blob)
    if rival:
        return 'reject', 'rival-only news: ' + rival.group(0)

    # No textual Liverpool signal: preserve plausible football news for human
    # review, but make the reason explicit so admins can spot this edge case.
    return 'review', 'no explicit Liverpool context; admin review'
