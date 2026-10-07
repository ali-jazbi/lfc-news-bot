"""Account rotation preserves model priority and the shared cooldown gate."""
import json
from types import SimpleNamespace

import config
import health
import translate


def test_fallback_mode_keeps_existing_order():
    names = ['first', 'other', 'first#2']
    assert translate._model_candidates(names) == names
    assert translate._key_cursors == {}


def test_round_robin_rotates_accounts_within_each_model(monkeypatch):
    monkeypatch.setattr(config, 'LLM_KEY_ROTATION', 'round_robin')
    names = ['first', 'other', 'first#2', 'other#2']
    assert translate._model_candidates(names) == ['first', 'first#2', 'other', 'other#2']
    assert translate._model_candidates(names) == ['first#2', 'first', 'other#2', 'other']
    assert translate._model_candidates(names) == ['first', 'first#2', 'other', 'other#2']


def fake_router(monkeypatch, limited=False):
    calls = []
    class Router:
        def completion(self, **kwargs):
            calls.append(kwargs['model'])
            if limited and kwargs['model'] == 'example':
                raise RuntimeError('429 rate limit')
            content = json.dumps({'title': '', 'body': 'لیورپول پیروز شد.'}, ensure_ascii=False)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    monkeypatch.setattr(translate, '_get_router', lambda: (Router(), ['example', 'example#2']))
    monkeypatch.setattr(translate, '_deployments', lambda: ([], ['example', 'example#2'], False))
    return calls


def test_translation_requests_use_alternating_accounts(monkeypatch):
    monkeypatch.setattr(config, 'LLM_KEY_ROTATION', 'round_robin')
    calls = fake_router(monkeypatch)
    results = [translate._translate_short({'body': 'Liverpool won.'}, review=False) for _ in range(4)]
    assert calls == ['example', 'example#2', 'example', 'example#2']
    assert [r['provider'] for r in results] == calls
    assert health._state['counters'].get('fallback_used', 0) == 0


def test_rate_limited_account_is_not_probed_again_during_rotation(monkeypatch):
    monkeypatch.setattr(config, 'LLM_KEY_ROTATION', 'round_robin')
    calls = fake_router(monkeypatch, limited=True)
    for _ in range(4):
        assert translate._translate_short({'body': 'Liverpool won.'}, review=False)['provider'] == 'example#2'
    assert calls == ['example', 'example#2', 'example#2', 'example#2', 'example#2']
    assert health.stats('example')['fail'] == 1


def test_busy_account_can_use_second_account_without_duplicate_call(monkeypatch):
    monkeypatch.setattr(config, 'LLM_KEY_ROTATION', 'round_robin')
    calls = fake_router(monkeypatch)
    with health.provider_slot('example') as allowed:
        assert allowed
        assert translate._translate_short({'body': 'Liverpool won.'}, review=False)['provider'] == 'example#2'
    assert calls == ['example#2']


def test_backup_key_is_configured_and_reported_without_exposing_keys(monkeypatch):
    monkeypatch.setattr(config, 'TRANSLATE_ORDER', ['llm1'])
    monkeypatch.setattr(config, 'LLM_SLOTS', {'llm1': {'name': 'example', 'model': 'test',
        'base_url': 'https://api.example.test/v1', 'key': 'primary-secret', 'key_backup': 'second-secret'}})
    deployments, names, _ = translate._deployments()
    assert names == ['example', 'example#2']
    assert [d['litellm_params']['api_key'] for d in deployments] == ['primary-secret', 'second-secret']
    report = translate.chain_report()
    assert 'کلید دوم' in report and 'example#2' in report
    assert 'primary-secret' not in report and 'second-secret' not in report
