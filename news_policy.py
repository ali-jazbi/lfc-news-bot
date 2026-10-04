"""Conservative channel policy, independent of agent/editor integrations."""
import re
import config


def decision(item):
    title = (item.get('title') or '').lower()
    body = (item.get('body') or '').lower()
    blob = title + ' ' + body
    if not config.INCLUDE_WOMEN and re.search(r"\b(women(?:'s)?|wsl|u18|u21|under-18|under-21)\b", title):
        return 'reject', 'outside men’s first-team coverage'
    # Promotion needs an explicit call to action, not an isolated word like watch.
    if re.search(r'\b(subscribe now|buy (?:your )?tickets|shop now|bet now|enter (?:our|the) competition)\b', blob):
        return 'reject', 'explicit promotion'
    if body.startswith('rt @') or title.startswith('rt @'):
        return 'reject', 'plain retweet'
    if item.get('source') == 'LFC Official' or 'liverpool' in str(item.get('source_tag', '')).lower():
        return 'review', 'club source'
    handle = str(item.get('ingest_handle') or item.get('handle') or '').lstrip('@').lower()
    if handle in {x.lstrip('@').lower() for x in config.TWITTER_LFC_ONLY}:
        return 'review', 'Liverpool-specific account'
    import names
    if any(k.lower() in blob for k in list(config.ROMANO_KEYWORDS) + list(names.glossary())):
        return 'review', 'Liverpool context'
    # An explicit rival-only result is unrelated; unknown entities remain reviewable.
    if re.fullmatch(r'(?:arsenal|chelsea|tottenham|spurs|manchester united|manchester city) '
                    r'(?:beat|defeat|sign|signed).+', title) and 'liverpool' not in body:
        return 'reject', 'explicitly unrelated team news'
    return 'review', 'uncertain relevance; admin decides'
