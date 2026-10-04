import config
import news_policy


def _item(title, body='', handle='DataAnalyticEPL'):
    return {'title': title, 'body': body, 'source': 'Twitter',
            'ingest_handle': '@' + handle}


def test_united_only_xg_post_is_rejected(monkeypatch):
    monkeypatch.setattr(config, 'TWITTER_LFC_ONLY', [])
    result = news_policy.decision(_item(
        "One of the Reasons Manchester United's xG per shot (0.07) is the LOWEST in the league."))
    assert result[0] == 'reject'
    assert 'manchester united' in result[1].casefold()


def test_generic_league_and_transfer_words_are_not_liverpool_signals(monkeypatch):
    monkeypatch.setattr(config, 'TWITTER_LFC_ONLY', [])
    result = news_policy.decision(_item(
        'Medical completed; here we go', 'Premier League transfer window update'))
    assert result == ('review', 'no explicit Liverpool context; admin review')


def test_liverpool_story_survives_rival_comparison(monkeypatch):
    monkeypatch.setattr(config, 'TWITTER_LFC_ONLY', [])
    result = news_policy.decision(_item(
        'Salah compared with Manchester United forwards', 'Liverpool forward Mohamed Salah'))
    assert result == ('review', 'Liverpool context')


def test_other_rival_only_story_is_rejected(monkeypatch):
    monkeypatch.setattr(config, 'TWITTER_LFC_ONLY', [])
    result = news_policy.decision(_item('Arsenal sign a new midfielder'))
    assert result[0] == 'reject'
