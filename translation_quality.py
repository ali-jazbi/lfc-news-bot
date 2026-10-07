"""Source-fidelity checks with no Hermes dependency or arbitrary minimum length."""
import re

_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


def numbers(text):
    text = (text or '').translate(_DIGITS).replace('٬', ',').replace('٫', '.')
    return set(re.findall(r'\d+(?:[.,]\d+)*', text))


def model_refusal(data):
    title = (data.get('title') or '').strip()
    body = (data.get('body') or '').replace('\u200c', ' ')
    if re.fullmatch(r'(?:خطای ورودی|ورودی نامعتبر|عدم امکان ترجمه|خطا در ترجمه)[.!: ]*', title):
        return True
    return bool(re.search(r'(?:متن|ورودی)\s+(?:ارسال شده\s+|دریافتی\s+|این\s+)?[^\n]{0,80}'
                          r'(?:قابل ترجمه (?:نیست|نمی باشد)|فاقد محتوای خبری)|'
                          r'لطفاً متن معتبر برای ترجمه ارسال', body))


def _liverpool_scores(text):
    text = (text or '').translate(_DIGITS)
    club = r'(?<!\w)(?:Liverpool(?: FC)?|LFC|لیورپول)(?!\w)'
    score = r'(?<!\d)(\d{1,2})\s*[-–:]\s*(\d{1,2})(?!\d)'
    left = {(int(m[1]), int(m[2])) for m in re.finditer(club + r'\s*[:：]?\s*' + score, text, re.I)}
    right = {(int(m[2]), int(m[1])) for m in re.finditer(score + r'\s*' + club, text, re.I)}
    return left | right


def check(item, tr, glossary):
    src = (item.get('title') or '') + '\n' + (item.get('body') or '')
    out = (tr.get('title') or '') + '\n' + (tr.get('body') or '')
    issues = []
    missing = numbers(src) - numbers(out)
    extra = numbers(out) - numbers(src)
    if missing:
        issues.append('missing numbers: ' + ', '.join(sorted(missing)))
    if extra:
        issues.append('added numbers: ' + ', '.join(sorted(extra)))
    source_scores, translated_scores = _liverpool_scores(src), _liverpool_scores(out)
    if source_scores and translated_scores and not translated_scores.issubset(source_scores):
        issues.append('match score/team order requires review')
    low = src.lower()
    for en, fa in glossary.items():
        if re.search(r'(?<!\w)' + re.escape(en.lower()) + r'(?!\w)', low) and fa not in out:
            # A surname-only rendering is sufficient when the identity is unchanged.
            if fa.split()[-1] not in out:
                issues.append('missing name/term: ' + en)
    for pattern, fa in ((r'\b(?:pounds?|gbp)\b|£', 'پوند'),
                        (r'\b(?:euros?|eur)\b|€', 'یورو'),
                        (r'\b(?:dollars?|usd)\b|\$', 'دلار')):
        if re.search(pattern, low) and fa not in out:
            issues.append('missing currency: ' + fa)
    if not out.strip() or not re.search(r'[\u0600-\u06ff]', out):
        issues.append('no Persian translation')
    if re.search(r'\b(?:not|never|no agreement|no deal|denies|denied)\b', low) and not re.search(
            r'نیست|نبود|نشده|نمی|ندارد|نخواهد|نکرد|هرگز|تکذیب|عدم|نه\b', out):
        issues.append('negation requires review')
    return issues
