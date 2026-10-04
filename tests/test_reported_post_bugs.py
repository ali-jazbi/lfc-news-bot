import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import config
import formatter
import translate
from telegram_api import Telegram
from userbot_downloader import _send_video_with_caption


def test_admin_preview_has_one_short_warning_without_technical_dump():
    tr = {'title': 'خبر', 'body': 'متن خبر', 'provider': 'model/private',
          'human_review_required': True, 'machine': True,
          'quality_issues': ['unapproved names: Reasons Manchester United']}
    caption = formatter.build_admin_caption({'url': 'https://example.test'}, tr)
    assert caption.count('⚠️') == 1
    assert 'model/private' not in caption and 'unapproved names' not in caption


def test_untranslated_source_has_an_explicit_single_warning():
    caption = formatter.build_admin_caption({}, {'body': 'Original text', 'provider': 'raw',
                                                 'human_review_required': True})
    assert caption.count('⚠️') == 1
    assert 'ترجمه انجام نشده' in caption


@pytest.mark.parametrize('speaker,source,icon', [
    ('ژرمی ژاکه', 'James Pearce', '🎙'),
    ('جیمز پیرس', 'James Pearce', '🔴'),
    ('فابریتزیو رومانو', 'Fabrizio Romano', '🔴'),
])
def test_interview_and_reporter_quotes_have_distinct_icons(speaker, source, icon):
    tr = {'title': '', 'body': speaker + ': «امروز بازی بسیار خوبی داشتیم و خوشحال هستم.»',
          'importance': 'normal'}
    caption = formatter.build_caption({'source_tag': source}, tr)
    assert caption.startswith(icon)
    assert '<blockquote expandable>' in caption
    assert speaker in caption.splitlines()[0]


def test_original_interview_speaker_is_retained_when_translation_omits_prefix():
    tr = {'title': 'صحبت‌های بعد از بازی', 'body': '«خیلی خوب بود.»'}
    item = {'title': 'Mohamed Salah: “It was very good.”', 'source_tag': 'James Pearce'}
    caption = formatter.build_caption(item, tr)
    assert caption.startswith('🎙️ <b>محمد صلاح:')
    assert '<blockquote expandable>«خیلی خوب بود.»' in caption


def test_exclusive_transfer_report_is_not_an_interview():
    caption = formatter.build_caption({'title': 'Exclusive transfer news'},
                                      {'title': 'خبر اختصاصی انتقال', 'body': 'لیورپول توافق کرد.'})
    assert not caption.startswith('🎙')


@pytest.mark.parametrize('size', [20, 1800])
def test_userbot_sends_caption_with_video_and_preserves_continuations(size):
    client = SimpleNamespace(send_file=AsyncMock(return_value=SimpleNamespace(id=9)),
                             send_message=AsyncMock(return_value=SimpleNamespace(id=10)))
    text = '<b>عنوان</b>\n' + 'خبر فارسی ' * size
    asyncio.run(_send_video_with_caption(client, 'channel', 'video', text))
    first = client.send_file.call_args.kwargs['caption']
    assert first and len(first.encode('utf-16-le')) // 2 <= 1024
    all_text = first + ''.join(c.args[1] for c in client.send_message.call_args_list)
    assert formatter.plain(all_text) == formatter.plain(text)


def test_userbot_does_not_report_success_when_caption_continuation_fails():
    client = SimpleNamespace(send_file=AsyncMock(return_value=SimpleNamespace(id=9)),
                             send_message=AsyncMock(return_value=None))
    with pytest.raises(RuntimeError, match='continuation failed'):
        asyncio.run(_send_video_with_caption(client, 'channel', 'video', 'خبر ' * 1000))


def test_bot_long_video_has_caption_and_complete_text(monkeypatch):
    client = Telegram(token='test')
    calls = []
    def call(method, **params):
        calls.append((method, params))
        return {'message_id': len(calls)}
    monkeypatch.setattr(client, 'call', call)
    text = '<b>عنوان</b>\n' + 'خبر 🔴 ' * 400
    assert client.send_post('channel', text, video='video')
    assert calls[0][0] == 'sendVideo' and calls[0][1]['caption']
    combined = calls[0][1]['caption'] + ''.join(p['text'] for m, p in calls[1:])
    assert formatter.plain(combined) == formatter.plain(text)


def test_local_video_upload_receives_caption(monkeypatch, tmp_path):
    client = Telegram(token='test')
    video = tmp_path / 'video.mp4'
    video.write_bytes(b'video')
    captured = []
    monkeypatch.setattr(client, 'upload_video', lambda *a, **k:
                        captured.append((a, k)) or {'message_id': 1})
    assert client.send_post('channel', 'کپشن فارسی', video=str(video))
    assert captured[0][0][2] == 'کپشن فارسی'


def test_video_album_preserves_long_caption(monkeypatch):
    client = Telegram(token='test')
    calls = []
    def call(method, **params):
        calls.append((method, params))
        return [{'message_id': 1}, {'message_id': 2}] if method == 'sendMediaGroup' else {'message_id': 3}
    monkeypatch.setattr(client, 'call', call)
    text = 'خبر کامل 🔴 ' * 350
    assert client.send_media_group('channel', ['v1', 'v2'], caption=text, media_type='video')
    first = calls[0][1]['media'][0]['caption']
    assert first and len(first.encode('utf-16-le')) // 2 <= 1024
    assert first + ''.join(p['text'] for m, p in calls[1:]) == text


def test_rate_limited_first_llm_falls_back_to_next_model(monkeypatch):
    import json
    calls = []
    class Router:
        def completion(self, **kwargs):
            calls.append(kwargs['model'])
            if kwargs['model'] == 'limited':
                raise RuntimeError('429 Rate limit reached')
            content = json.dumps({'title': '', 'body': 'لیورپول توافق نکرد.'}, ensure_ascii=False)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    monkeypatch.setattr(translate, '_get_router', lambda: (Router(), ['limited', 'good']))
    monkeypatch.setattr(translate, '_deployments', lambda: ([], [], False))
    monkeypatch.setattr(translate, '_review_call', lambda *a: {'ok': True, 'issues': []})
    assert translate.translate({'body': 'Liverpool have not agreed.'})['provider'] == 'good'
    assert calls == ['limited', 'good']


def test_router_initialization_failure_still_tries_machine_fallback(monkeypatch):
    monkeypatch.setattr(translate, '_get_router', lambda: (_ for _ in ()).throw(RuntimeError('router failed')))
    monkeypatch.setattr(translate, '_deployments', lambda: ([], [], True))
    monkeypatch.setattr(translate, '_deep_translate', lambda item:
                        {'title': '', 'body': 'متن فارسی لیورپول', 'machine': True})
    result = translate.translate({'body': 'Liverpool news'})
    assert result['machine'] and result['human_review_required']


def test_config_loads_llm13_when_it_is_in_translation_order(monkeypatch):
    import runpy
    monkeypatch.setenv('TRANSLATE_ORDER', 'llm13,translate')
    monkeypatch.setenv('LLM13_MODEL', 'test13')
    loaded = runpy.run_path(config.__file__)
    assert loaded['LLM_SLOTS']['llm13']['model'] == 'test13'


def test_channel_video_delivery_receives_clean_saved_caption(patched_main, sample_item, monkeypatch):
    import db
    import main
    import userbot_downloader
    calls = []
    downloader = SimpleNamespace(is_configured=lambda: True,
        download_and_forward_sync=lambda **params: calls.append(params) or True)
    monkeypatch.setattr(userbot_downloader, 'get_downloader', lambda: downloader)
    monkeypatch.setattr(config, 'ENABLE_USERBOT_VIDEOS', True)
    monkeypatch.setattr(config, 'CHANNEL_ID', '-100123')
    item = dict(sample_item, video_url='https://example.test/video.mp4',
                translated={'title': 'صحبت‌های ویرتز', 'body': 'متن کامل فارسی خبر',
                            'provider': 'private/model'})
    key = db.save(item, status='sent_admin')
    assert main.send_to_channel(key)[0]
    assert calls[0]['caption'] == formatter.build_caption(item, item['translated'])
    assert 'private/model' not in calls[0]['caption']
    assert db.get(key)['status'] == 'published'
