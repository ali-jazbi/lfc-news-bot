"""Synthetic, independently labelled stories; seeded transport variations, no network."""
import json
import random
import time

import pytest

import config
import db
import news_policy


# Labels describe editorial intent, not the implementation's current answer.
BLOCKED = [
    'Bayern Munich agree a deal for a new striker.',
    'Ajax announce their starting eleven for tonight.',
    'Benfica sign a new winger on a five-year contract.',
    'Celtic win the Scottish Cup final.',
    'Galatasaray are in talks with a goalkeeper.',
    'Inter Milan confirm a contract extension.',
    'AC Milan sack their head coach.',
    'Portugal beat Norway 3-1 in the qualifier.',
    'Chelsea midfielder returns from injury.',
    'Manchester City have agreed personal terms with a defender.',
    'West Ham announce the signing of a striker.',
    'Brighton beat Fulham with two late goals.',
    'The Champions League draw takes place tomorrow.',
    'Premier League club owners meet to discuss broadcast rights.',
    'The best goal I have ever seen. Incredible technique.',
    'Here we go! Medical completed and documents signed.',
    'Nine matches in my career. What a journey.',
    'Good morning everyone. Coffee and a long drive today.',
    'New episode tonight: subscribe to our podcast.',
    'The Los Angeles Lakers win an NBA game.',
    'The Reds beat the Cubs in baseball last night.',
    'Liverpool City Council approves a new housing project.',
    'Liverpool airport announces new flights to Spain.',
    'Liverpool museum opens an exhibition of modern paintings.',
    'The University of Liverpool publishes a chemistry study.',
    'Heavy rain is forecast in Liverpool tomorrow.',
    'A new cafe opens in Kirkby town centre.',
    'Anfield residents complain about road repairs.',
    'Nintendo announces a new Kirby game.',
    'Alisson Santos signs for Sporting CP.',
    'Alisson Ramalho wins a volleyball tournament.',
    'Salah Abdeslam appears in court in France.',
    'Salah Brahimi has been elected mayor.',
    'A Wirtz family bakery opens in Berlin.',
    'Frimpong launches her new fashion collection.',
    'Jordan Henderson scores for Ajax.',
    'Trent Alexander-Arnold starts for Real Madrid.',
    'Liverpool Women beat Chelsea Women in the WSL.',
    'Liverpool U18s defeat Everton U18s in the academy league.',
    'Liverpool under-21 side face Arsenal under-21s tonight.',
    'فردا در شهر لیورپول باران شدید می‌بارد.',
    'تیم زنان لیورپول مقابل چلسی پیروز شد.',
    'بسکتبال: لیکرز با اختلاف ده امتیاز پیروز شد.',
    'شهرداری لیورپول ساخت یک مجموعه مسکونی را تصویب کرد.',
    'RT @LFC: Liverpool won 2-0 tonight.',
    'RT @fan: Salah scored again for Liverpool.',
    'Benfica, known as the Reds, win the Portuguese league.',
    'Alisson Martins joins Porto on a four-year deal.',
    'Salah Hassan signs a contract with a Turkish club.',
    'Ahmed Salah signs a contract with Porto.',
    'Patrick Wirtz moves to Bayern Munich.',
]
ALLOWED = [
    'Liverpool are preparing a bid for a Real Madrid midfielder.',
    'Liverpool have not agreed a fee for the defender yet.',
    'Liverpool deny the rumour about their next manager.',
    'Liverpool are interested in a Barcelona forward, according to reports.',
    'Liverpool lost 1-0 to Manchester City.',
    'Liverpool recorded more shots than Arsenal this weekend.',
    'Liverpool could sign the player if negotiations progress.',
    'Liverpool first-team players train with the U21 goalkeeper today.',
    'Liverpool support the local foodbank at Anfield.',
    'Mohamed Salah scored twice for Egypt.',
    'Salah: We have to improve our finishing.',
    'Alisson Becker made three saves for Brazil.',
    'Alisson kept another clean sheet.',
    'Florian Wirtz created four chances for Germany.',
    'Wirtz: I feel better after the injury.',
    'Cody Gakpo is doubtful after picking up an injury.',
    'Dominik Szoboszlai captains Hungary tonight.',
    'Jeremie Frimpong impressed in training today.',
    'Hugo Ekitike could return next week.',
    'Klopp recalls his first match as Liverpool manager in 2015.',
    'Watch: Liverpool score twice in stoppage time.',
    'The Reds are preparing for their next match at Anfield.',
    'Morning session at the AXA training centre.',
    'محمد صلاح برای تیم ملی مصر دو گل زد.',
    'فلوریان ویرتز در تمرین امروز حضور داشت.',
    'لیورپول هنوز برای خرید مدافع به توافق نرسیده است.',
    'Salah nets a hat-trick for Egypt.',
    'Alisson saves a penalty in the final minute.',
    'Gakpo shines in training ahead of the derby.',
    'Szoboszlai leads Hungary to victory.',
    'Wirtz celebrates his first international goal.',
    'Salah explains his role in the new formation.',
    'Frimpong faces a fitness test tomorrow.',
]


@pytest.fixture
def roster(tmp_db, monkeypatch):
    monkeypatch.setattr(config, 'INCLUDE_WOMEN', False)
    people = [
        ('Mohamed Salah', 'محمد صلاح', ['Salah']),
        ('Alisson Becker', 'آلیسون بکر', ['Alisson']),
        ('Florian Wirtz', 'فلوریان ویرتز', ['Wirtz']),
        ('Cody Gakpo', 'کودی خاکپو', ['Gakpo']),
        ('Dominik Szoboszlai', 'دومینیک سوبوسلای', ['Szoboszlai']),
        ('Jeremie Frimpong', 'جرمی فریمپونگ', ['Frimpong']),
        ('Hugo Ekitike', 'هوگو اکیتیکه', ['Ekitike']),
    ]
    with db._c():
        for english, persian, aliases in people:
            db._c().execute('INSERT INTO news_entities VALUES (?,?,?,?,?)',
                            (english.casefold(), 'current', 0, 'test roster', time.time()))
            db._c().execute('INSERT OR REPLACE INTO person_names(english,persian,aliases) VALUES (?,?,?)',
                            (english, persian, json.dumps(aliases)))
        for english in ('Jordan Henderson', 'Trent Alexander-Arnold'):
            db._c().execute('INSERT INTO news_entities VALUES (?,?,?,?,?)',
                            (english.casefold(), 'former', 0, 'test roster', time.time()))


def variants():
    rng = random.Random(20261006)
    stories = [(text, False) for text in BLOCKED] + [(text, True) for text in ALLOWED]
    rng.shuffle(stories)
    for index, (text, allowed) in enumerate(stories):
        for variant in range(6):
            body = text
            if variant == 2:
                body = rng.choice((text.upper(), text.lower()))
            elif variant == 3:
                body += '\nhttps://example.test/liverpool/lfc/salah'
            elif variant == 4:
                body += '\n#Liverpool #LFC #Salah'
            elif variant == 5:
                body += '\nVia @LFC'
            item = {'title': text if variant == 1 else '', 'body': body, 'source': 'Twitter',
                    'url': f'https://example.test/story/{index}/{variant}',
                    'ingest_handle': rng.choice(('LFC', 'FabrizioRomano', 'Asim_LFC', 'PartedBeard', 'random')),
                    'source_tag': rng.choice(('Liverpool news', 'Reporter', 'LFC')),
                    'club_specific': rng.choice((True, False))}
            yield item, allowed


def test_fresh_stories_with_randomized_accounts_and_transport_metadata(roster):
    profiles = news_policy.entity_profiles()
    mistakes = []
    for item, allowed in variants():
        action, reason = news_policy.decision(item, profiles)
        if (action == 'review') != allowed:
            mistakes.append({'text': item['body'], 'expected': 'allow' if allowed else 'block',
                             'actual': action, 'reason': reason})
    summary = {m['text'].split('\n')[0].casefold(): m['expected'] + ' -> ' + m['actual'] for m in mistakes}
    assert not mistakes, json.dumps({'mistakes': len(mistakes), 'stories': summary}, ensure_ascii=False, indent=2)


def test_unrelated_cases_never_reach_translation_or_admin_group(roster, patched_main, monkeypatch):
    import main
    called = []
    monkeypatch.setattr(main.translate, 'translate', lambda item: called.append(item['body']))
    items = [item for item, allowed in variants() if not allowed]
    for item in items:
        assert main.process_item(item) is False
    assert called == []
    assert main.tg.calls == []
    assert db.count() == len(items)
    assert set(db.pipeline_stats()).issubset({'rejected', 'awaiting_relevance'})


def test_mixed_batch_only_claims_relevant_stories(roster):
    from sources.base import SourceBatch
    labelled = list(variants())
    db.ingest_batch('challenge', SourceBatch([item for item, _ in labelled]))
    expected = {db.make_key(item) for item, allowed in labelled if allowed}
    news_policy.classify_queued()
    claimed = set()
    while rows := db.queue_items(5):
        claimed.update(row['key'] for row in rows)
        assert len(rows) <= 5
        for row in rows:
            db.set_status(row['key'], db.STATUS_PENDING_ADMIN)
    assert claimed == expected
    assert db.count() == len(labelled)
