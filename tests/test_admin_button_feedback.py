"""Buttons notify once, keep feedback visible, and avoid new permanent replies."""
import copy

import pytest

import admin_news
import db
import formatter


def query(key, action, markup=None, **media):
    return {'id': 'callback', 'data': action + ':' + key, 'from': {'id': 1},
            'message': {'message_id': 12, 'chat': {'id': -1}, 'reply_markup': markup, **media}}


def save_news(item, **payload):
    return db.save(dict(item, translated={'title': '', 'body': 'لیورپول پیروز شد.'}, **payload), status='sent_admin')


@pytest.mark.parametrize('action,choice', [('rel', 'related'), ('irr', 'unrelated')])
def test_feedback_is_a_toast_and_only_selected_choice_survives_restart(patched_main, sample_item, action, choice):
    key = save_news(sample_item)
    markup = formatter.keyboard(key)
    original = copy.deepcopy(markup)
    patched_main.handle_callback(query(key, action, markup))
    assert not patched_main.tg.sent_messages
    answers = [c for c in patched_main.tg.calls if c[0] == 'answer_callback']
    assert len(answers) == 1 and 'ثبت شد' in answers[0][2]
    edited = patched_main.tg.edits[-1]['markup']['inline_keyboard']
    selected = [b for row in edited for b in row if b['callback_data'] == 'relstate:' + key]
    assert len(selected) == 1
    assert ('✅ مرتبط' if choice == 'related' else '❌ نامرتبط') in selected[0]['text']
    assert not any(b['callback_data'] in ('rel:' + key, 'irr:' + key) for row in edited for b in row)
    assert markup == original
    assert any(b['callback_data'] == 's2c:' + key for row in edited for b in row)
    db._conn.close()
    db._conn = None
    db.init()
    assert formatter.keyboard(key)['inline_keyboard'][3] == selected
    count = db._c().execute('SELECT COUNT(*) FROM feedback').fetchone()[0]
    patched_main.handle_callback(query(key, 'relstate'))
    assert db._c().execute('SELECT COUNT(*) FROM feedback').fetchone()[0] == count


def test_selection_in_a_queue_row_preserves_other_news_buttons():
    markup = {'inline_keyboard': [[{'text': 'مشاهده', 'callback_data': 'qview:one'},
                                  *formatter.relevance_buttons('one')],
                                 formatter.relevance_buttons('two')]}
    result = formatter.selected_relevance(markup, 'one', 'unrelated')
    assert result['inline_keyboard'][0][0] == markup['inline_keyboard'][0][0]
    assert len(result['inline_keyboard'][0]) == 2
    assert result['inline_keyboard'][1] == markup['inline_keyboard'][1]


@pytest.mark.parametrize('action', ['chain', 'story', 'recover', 'dismiss', 'swatch'])
def test_short_button_replies_never_add_group_messages(patched_main, sample_item, action):
    key = save_news(sample_item, translation_attempts=[{'provider': 'example', 'outcome': 'error', 'error': 'rate limit'}])
    if action == 'recover':
        db.set_status(key, 'failed')
    value = 'NewReporter' if action == 'swatch' else key
    patched_main.handle_callback(query(value, action))
    assert not patched_main.tg.sent_messages
    answers = [c for c in patched_main.tg.calls if c[0] == 'answer_callback']
    assert len(answers) == 1 and answers[0][2]


def test_long_trace_is_bounded_in_popup_and_complete_in_command(patched_main, sample_item):
    error = 'rate limit ' + 'خطای موقت 😅 ' * 80
    key = save_news(sample_item, translation_attempts=[{'provider': 'example', 'outcome': 'error', 'error': error}])
    patched_main.handle_callback(query(key, 'chain'))
    notice = patched_main.tg.calls[-1][2]
    assert len(notice.encode('utf-16-le')) // 2 <= 200
    assert '/chain ' + key in notice
    assert not patched_main.tg.sent_messages
    patched_main.handle_message({'text': '/chain ' + key, 'from': {'id': 1}, 'chat': {'id': -1}})
    assert error.strip() in formatter.plain(patched_main.tg.sent_messages[-1])


def test_queue_navigation_edits_existing_report_and_command_keeps_report(patched_main, sample_item):
    db.save(sample_item)
    patched_main.handle_message({'text': '/queue', 'from': {'id': 1}, 'chat': {'id': -1}})
    existing = list(patched_main.tg.sent_messages)
    patched_main.handle_callback(query('pending:0', 'qpg'))
    assert patched_main.tg.sent_messages == existing
    assert 'صف خبرها' in patched_main.tg.edits[-1]['text']


def test_missing_news_button_only_shows_toast(patched_main):
    patched_main.handle_callback(query('missing', 'chain'))
    assert not patched_main.tg.sent_messages
    assert 'پیدا نشد' in patched_main.tg.calls[-1][2]


@pytest.mark.parametrize('action', ['pub', 's2c', 'rtr'])
def test_slow_action_failure_is_visible_on_post_without_second_callback_or_message(patched_main, sample_item, monkeypatch, action):
    key = save_news(sample_item, admin_relevance='related')
    monkeypatch.setattr(patched_main, 'approve', lambda *a, **k: (False, 'ارسال ناموفق'))
    monkeypatch.setattr(patched_main, 'send_to_channel', lambda *a, **k: (False, 'ارسال ناموفق'))
    monkeypatch.setattr(patched_main.translate, 'translate', lambda item: None)
    patched_main.handle_callback(query(key, action, formatter.keyboard(key)))
    assert not patched_main.tg.sent_messages
    assert len([c for c in patched_main.tg.calls if c[0] == 'answer_callback']) == 1
    markup = patched_main.tg.edits[-1]['markup']
    assert any(b['callback_data'] == 'notice:' + key for row in markup['inline_keyboard'] for b in row)
    assert markup['inline_keyboard'][3] == formatter.relevance_buttons(key, 'related')
    patched_main.handle_callback(query(key, 'notice'))
    assert 'ناموفق' in patched_main.tg.calls[-1][2]


def test_retranslation_edits_video_caption_and_keeps_feedback_choice(patched_main, sample_item):
    key = save_news(sample_item, admin_relevance='related')
    patched_main.handle_callback(query(key, 'rtr', formatter.keyboard(key), video={'file_id': 'video'}))
    assert patched_main.tg.edits[-1]['kind'] == 'caption'
    assert patched_main.tg.edits[-1]['markup']['inline_keyboard'][3] == formatter.relevance_buttons(key, 'related')
    assert not patched_main.tg.sent_messages


def test_full_original_button_view_expires_all_parts(patched_main, sample_item, monkeypatch):
    timers = []
    class Timer:
        def __init__(self, seconds, function, args=()):
            self.seconds, self.function, self.args = seconds, function, args
        def start(self):
            timers.append(self)
    monkeypatch.setattr(admin_news.threading, 'Timer', Timer)
    item = dict(sample_item, body='Liverpool have not agreed. ' * 400)
    key = save_news(item)
    patched_main.handle_callback(query(key, 'orig'))
    assert len(patched_main.tg.sent_messages) > 1
    assert len(timers) == len(patched_main.tg.sent_messages)
    assert all(t.seconds == 120 for t in timers)
    for timer in timers:
        timer.function(*timer.args)
    assert len([c for c in patched_main.tg.calls if c[0] == 'delete_message']) == len(timers)
