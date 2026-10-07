import json
from types import SimpleNamespace

import translate
from scripts.maintenance import evaluate_translation


def configure(monkeypatch):
    monkeypatch.setattr(translate.config, 'LLM_SLOTS', {'llm7': {'key': 'private-test-key'}})
    monkeypatch.setattr(translate, '_deployments', lambda: ([{
        'model_name': 'gapgpt-luna',
        'litellm_params': {'model': 'openai/gpt-6-luna', 'timeout': 60},
    }], ['gapgpt-luna'], False))


def test_evaluation_keeps_timeout_and_usage(monkeypatch):
    configure(monkeypatch)

    def completion(**kwargs):
        assert kwargs['timeout'] == 60
        assert kwargs['max_retries'] == 0
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
                'title': '', 'body': 'لیورپول هنوز بر سر مبلغ انتقال توافق نکرده است.',
            }, ensure_ascii=False)))],
            usage={'prompt_tokens': 100, 'completion_tokens': 20},
        )

    monkeypatch.setattr(translate.litellm, 'completion', completion)
    result = evaluate_translation.evaluate(limit=1, live=True)
    assert result['records'][0]['valid']
    assert result['records'][0]['usage'] == {'prompt_tokens': 100, 'completion_tokens': 20}


def test_evaluation_explains_server_error_without_leaking_key(monkeypatch):
    configure(monkeypatch)

    class ServerError(Exception):
        status_code = 500

    def completion(**kwargs):
        # Redact before truncating, including a credential crossing the 300-char boundary.
        raise ServerError('x' * 290 + 'private-test-key' + ' upstream unavailable')

    monkeypatch.setattr(translate.litellm, 'completion', completion)
    result = evaluate_translation.evaluate(limit=5, live=True)
    assert result['ranking'][0]['samples'] == 3
    for row in result['records']:
        assert row['status_code'] == 500
        assert row['error_type'] == 'ServerError'
        assert '[redacted]' in row['error']
        assert 'private' not in row['error']
