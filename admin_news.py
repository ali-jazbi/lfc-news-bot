"""Admin views/actions. Called only after main's existing authorization check."""
import json
import threading
import time

import config
import db
import discovery
import formatter
import news_policy

PAGE_SIZE = 6
FILTERS = {
    'pending': ('discovered', 'new', 'retry_pending'),
    'review': ('sent_admin', 'pending_admin', 'approved'),
    'failed': ('failed',), 'rejected': ('rejected', 'skipped'), 'grouped': ('grouped',),
}
LABELS = {'pending': 'منتظر پردازش', 'review': 'منتظر ادمین', 'failed': 'ناموفق',
          'rejected': 'ردشده', 'grouped': 'تجمیع‌شده', 'all': 'همه'}


def _page(value):
    return min(10000, max(0, int(value)))


def _button(label, data):
    return {'text': label, 'callback_data': data}


def _navigation(prefix, page, total):
    buttons = []
    if page:
        buttons.append(_button('⬅️ قبلی', f'{prefix}:{page-1}'))
    if (page + 1) * PAGE_SIZE < total:
        buttons.append(_button('بعدی ➡️', f'{prefix}:{page+1}'))
    return [buttons] if buttons else []


def queue(tg, chat_id, kind='pending', page=0):
    if kind not in LABELS:
        raise ValueError('فیلترها: pending, review, failed, rejected, grouped, all')
    where, args = '', []
    if kind != 'all':
        statuses = FILTERS[kind]
        where = ' WHERE status IN (' + ','.join('?' for _ in statuses) + ')'
        args = list(statuses)
    with db._lock:
        total = db._c().execute('SELECT COUNT(*) FROM items' + where, args).fetchone()[0]
        page = min(page, max(0, (total - 1) // PAGE_SIZE))
        rows = db._c().execute('SELECT * FROM items' + where + ' ORDER BY created_at,key LIMIT ? OFFSET ?',
                               args + [PAGE_SIZE, page * PAGE_SIZE]).fetchall()
    lines = [f'📋 <b>صف خبرها: {LABELS[kind]}</b> — {total} خبر | صفحهٔ {page+1}']
    buttons = [[_button(label, f'qpg:{key}:0') for key, label in list(LABELS.items())[:3]],
               [_button(LABELS[k], f'qpg:{k}:0') for k in ('rejected', 'grouped', 'all')]]
    for n, row in enumerate(rows, 1):
        item = json.loads(row['payload'])
        title = (item.get('translated') or {}).get('title') or item.get('title') or 'بدون عنوان'
        lines.append(f"\n{n}. {formatter.esc(title[:180])}\n<code>{row['key']}</code> · {formatter.esc(row['status'])}")
        if row['error']:
            lines.append(formatter.esc(row['error'][:180]))
        actions = [_button(f'{n}. مشاهده', 'qview:' + row['key'])]
        if row['status'] in ('failed', 'retry_pending', 'rejected', 'skipped'):
            actions.append(_button('بازیابی در صف', 'recover:' + row['key']))
        elif row['status'] in ('discovered', 'new', 'sent_admin', 'pending_admin'):
            actions.append(_button('رد خبر', 'irr:' + row['key']))
        buttons.append(actions)
    buttons += _navigation('qpg:' + kind, page, total)
    tg.send_message(chat_id, '\n'.join(lines), reply_markup={'inline_keyboard': buttons}, silent=True)


def show_item(tg, chat_id, key):
    row = db.get(key)
    if not row:
        raise ValueError('خبر پیدا نشد.')
    item = row['payload']
    text = (formatter.build_admin_caption(item, item['translated']) if item.get('translated')
            else formatter.build_original_message(item, expandable=False) or 'متن ندارد')
    text += '\n\nشناسه: <code>' + key + '</code> · ' + formatter.esc(row['status'])
    text += '\nتصمیم: ' + formatter.esc(item.get('editorial_reason') or news_policy.decision(item)[1])
    if row['story_key']:
        text += '\nخبر اصلی: <code>' + row['story_key'] + '</code>'
    buttons = [[_button('📚 منابع خبر', 'story:' + (row['story_key'] or key)),
                _button('🔗 مسیر ترجمه', 'chain:' + key)]]
    if row['status'] in ('sent_admin', 'pending_admin', 'approved') and item.get('translated'):
        buttons = formatter.keyboard(key)['inline_keyboard']
    elif row['status'] in ('failed', 'retry_pending', 'rejected', 'skipped'):
        buttons.append([_button('بازیابی در صف', 'recover:' + key)])
    tg.send_message(chat_id, text, reply_markup={'inline_keyboard': buttons}, silent=True)


def missed(tg, chat_id, page=0):
    candidates = discovery.missed_candidates()
    summary = json.loads(discovery._meta('missed_scan', '{}'))
    lines = [f'🔎 <b>خبرهای جاافتاده در منابع مرجع</b>: {len(candidates)}']
    if summary:
        lines.append(f"آخرین بررسی: {_ago(summary['at'])} | دریافتی: {summary['received']}")
        lines.append('دامنهٔ بررسی: ' + formatter.esc(', '.join(summary['sources'])))
    else:
        lines.append('هنوز بررسی نشده؛ /missed refresh را بزن.')
    lines.append('وجود در صف هم پوشش محسوب می‌شود؛ این گزارش تمام اینترنت را بررسی نمی‌کند.')
    errors = summary.get('errors') or []
    if errors:
        lines.append('⚠️ بررسی ناقص: ' + formatter.esc('; '.join(errors)))
    # Per-feed failures may be swallowed by the legacy collector; surface them too.
    failed = [r['source_id'] for r in db.list_source_health()
              if r['source_id'].startswith(('feed:', 'news_search:')) and r['consecutive_failures']]
    if failed:
        lines.append('⚠️ ورودی‌های ناموفق: ' + formatter.esc(', '.join(failed)))
    page = min(page, max(0, (len(candidates) - 1) // PAGE_SIZE))
    buttons = [[_button('🔄 بررسی دوباره', 'mscan:0')]]
    for n, row in enumerate(candidates[page * PAGE_SIZE:(page + 1) * PAGE_SIZE], 1):
        item = row['payload']
        lines.append(f"\n{n}. <a href=\"{formatter.esc(item['url'])}\">{formatter.esc(item.get('title', '')[:180])}</a>")
        if row['existing_status']:
            lines.append('وضعیت قبلی: ' + formatter.esc(row['existing_status']))
        buttons.append([_button(f'{n}. واردکردن به صف', 'recover:' + row['key']),
                        _button('نادیده بگیر', 'dismiss:' + row['key'])])
    buttons += _navigation('mpg', page, len(candidates))
    tg.send_message(chat_id, '\n'.join(lines), reply_markup={'inline_keyboard': buttons}, silent=True)


def scan_async(tg, chat_id):
    def work():
        try:
            if not discovery.scan_missed():
                tg.send_message(chat_id, 'بررسی دیگری در حال اجراست.', silent=True)
                return
            missed(tg, chat_id)
        except Exception as exc:
            tg.send_message(chat_id, 'بررسی خبرها ناموفق: ' + formatter.esc(str(exc)), silent=True)
    threading.Thread(target=work, daemon=True).start()


def _ago(stamp):
    if not stamp:
        return 'ثبت نشده'
    minutes = max(0, int((time.time() - stamp) / 60))
    return f'{minutes} دقیقه قبل' if minutes < 60 else f'{minutes // 60} ساعت قبل'


def accounts(tg, chat_id):
    with db._lock:
        polls = {r['handle']: dict(r) for r in db._c().execute('SELECT * FROM account_polls')}
        rows = db._c().execute('SELECT status,payload FROM items WHERE created_at>?',
                               (time.time() - 7 * 86400,)).fetchall()
    stats = {}
    for row in rows:
        item = json.loads(row['payload'])
        handle = (item.get('ingest_handle') or item.get('handle') or '').lstrip('@').casefold()
        counts = stats.setdefault(handle, {})
        counts[row['status']] = counts.get(row['status'], 0) + 1
    handles = sorted({h.lstrip('@').casefold() for h in config.TWITTER_ACCOUNTS + config.TWITTER_TIER1}
                     | set(discovery.source_handles()))
    lines = ['📡 <b>سلامت اکانت‌ها</b>',
             'آمار دریافت خام شامل هم‌پوشانی است؛ آمار صف مربوط به ۷ روز اخیر است.',
             'پاسخ خالی علت مشخصی ندارد و اکانت را تعلیق نمی‌کند. جزئیات پایش فعلاً برای fxembed ثبت می‌شود.']
    for handle in handles:
        poll, counts = polls.get(handle, {}), stats.get(handle, {})
        lines.append(f"\n@{formatter.esc(handle)} — بررسی {_ago(poll.get('attempted_at'))} "
                     f"| آخرین خبر {_ago(poll.get('last_item_at'))}\n"
                     f"دریافتی خام {poll.get('received', 0)} | خالی پیاپی {poll.get('empty_streak', 0)} "
                     f"| ناموفق {counts.get('failed', 0)} | رد {counts.get('rejected', 0)} "
                     f"| ادمین {counts.get('sent_admin', 0) + counts.get('pending_admin', 0)}")
        if poll.get('error'):
            lines.append(formatter.esc(poll['error']))
    tg.send_message(chat_id, '\n'.join(lines), silent=True)


def sources(tg, chat_id):
    with db._lock:
        rows = db._c().execute('SELECT s.*,COUNT(c.news_key) AS sightings FROM source_candidates s '
                               'LEFT JOIN source_citations c ON s.handle=c.handle GROUP BY s.handle '
                               "HAVING s.state='watching' OR (s.state='suggested' AND COUNT(c.news_key)>=2) "
                               'ORDER BY sightings DESC, s.handle LIMIT 30').fetchall()
    lines = ['👥 <b>اکانت‌های پیشنهادی و پایش موقت</b>',
             '/sources watch handle 7 — پایش ۷ روزهٔ اکانت عمومی',
             '/sources lfc handle 7 — تأیید اکانت اختصاصی لیورپول',
             '/sources dismiss handle — توقف پایش پیشنهادی (اکانت‌های env باقی می‌مانند)']
    buttons = []
    for row in rows:
        state = 'پیشنهادی' if row['state'] == 'suggested' else ('در حال پایش' if row['expires_at'] > time.time() else 'پایان پایش')
        lines.append(f"\n@{formatter.esc(row['handle'])}: {state} | {row['sightings']} خبر ارجاع‌دهنده")
        with db._lock:
            evidence = db._c().execute('SELECT url,cited_by FROM source_citations WHERE handle=? '
                                       'ORDER BY created_at DESC LIMIT 2', (row['handle'],)).fetchall()
        for cited in evidence:
            lines.append(f'<a href="{formatter.esc(cited["url"] or "")}">ارجاع از @{formatter.esc(cited["cited_by"])}</a>')
        if row['state'] == 'suggested' or row['expires_at'] <= time.time():
            buttons.append([_button('@' + row['handle'] + ' — پایش ۷ روزه', 'swatch:' + row['handle'])])
    tg.send_message(chat_id, '\n'.join(lines), reply_markup={'inline_keyboard': buttons}, silent=True)


def feedback(key, related):
    with db._lock:
        row = db.get(key)
        if not row:
            raise ValueError('خبر پیدا نشد.')
        if row['status'] in ('processing', 'analyzing', 'translation', 'media_processing'):
            raise ValueError('خبر در حال پردازش است؛ پس از اتمام دوباره بزن.')
        item = row['payload']
        previous_decision = item.get('editorial_decision')
        item['admin_relevance'] = 'related' if related else 'unrelated'
        item['editorial_decision'] = 'review' if related else 'reject'
        item['editorial_reason'] = 'admin marked related' if related else 'admin marked unrelated'
        db.update_payload(key, item, status=('rejected' if not related and row['status'] != 'published' else None))
        db.record_feedback(key, ai_decision=previous_decision,
                           human_action='related' if related else 'unrelated', reason='admin relevance feedback')
        if related and row['status'] in ('rejected', 'failed', 'skipped'):
            discovery.recover(key)


def callback(tg, cq, action, value):
    if action not in ('qpg', 'qview', 'mpg', 'mscan', 'recover', 'dismiss', 'rel', 'irr', 'story', 'chain', 'swatch'):
        return False
    tg.answer_callback(cq['id'])
    chat_id = cq['message']['chat']['id']
    try:
        if action == 'qpg':
            kind, page = value.split(':')
            queue(tg, chat_id, kind, _page(page))
        elif action == 'qview':
            show_item(tg, chat_id, value)
        elif action == 'mpg':
            missed(tg, chat_id, _page(value))
        elif action == 'mscan':
            scan_async(tg, chat_id)
        elif action == 'recover':
            discovery.recover(value)
            tg.send_message(chat_id, '✅ خبر در صف قرار گرفت؛ انتشار همچنان با تأیید ادمین است.', silent=True)
        elif action == 'dismiss':
            with db._lock, db._c():
                db._c().execute("UPDATE discovery_candidates SET state='dismissed' WHERE key=?", (value,))
            tg.send_message(chat_id, 'این پیشنهاد نادیده گرفته شد.', silent=True)
        elif action in ('rel', 'irr'):
            feedback(value, action == 'rel')
            tg.send_message(chat_id, 'بازخورد مرتبط ثبت شد.' if action == 'rel' else
                            'بازخورد نامرتبط ثبت شد؛ خبر منتشرشده از کانال حذف نمی‌شود.', silent=True)
        elif action == 'swatch':
            discovery.set_source(value)
            tg.send_message(chat_id, 'اکانت برای ۷ روز به نوبت عادی دریافت اضافه شد.', silent=True)
        else:
            row = db.get(value)
            if not row:
                raise ValueError('خبر پیدا نشد.')
            item = row['payload']
            if action == 'story':
                if row['story_key']:
                    parent = db.get(row['story_key'])
                    if parent:
                        item = parent['payload']
                sources_list = item.get('story_sources') or [{'url': item.get('url'), 'source': item.get('source_tag') or item.get('source')}]
                text = '📚 <b>منابع این خبر</b>\n' + '\n'.join(
                    f'<a href="{formatter.esc(s["url"] or "")}">{formatter.esc(s.get("source") or "منبع")}</a>' for s in sources_list)
                if item.get('text_source_url'):
                    text += f'\nمتن کامل‌تر: <a href="{formatter.esc(item["text_source_url"])}">منبع متن</a>'
            else:
                attempts = (item.get('translated') or {}).get('translation_attempts') or item.get('translation_attempts') or []
                text = '🔗 <b>مسیر ترجمهٔ این خبر</b>\n'
                for attempt in attempts:
                    text += formatter.esc(attempt.get('provider', '')) + ' — ' + formatter.esc(attempt['outcome'])
                    if attempt.get('chunk'):
                        text += ' · قطعهٔ ' + str(attempt['chunk'])
                    if attempt.get('error'):
                        text += '\n' + formatter.esc(attempt['error'])
                    text += '\n'
                if not attempts:
                    text += 'تاریخچهٔ تلاش برای این خبر قدیمی ثبت نشده است.'
            tg.send_message(chat_id, text, silent=True)
    except (ValueError, KeyError, TypeError) as exc:
        tg.send_message(chat_id, formatter.esc(str(exc)), silent=True)
    return True


def command(tg, chat_id, text):
    parts = text.split()
    cmd = parts[0].split('@')[0]
    if cmd not in ('/queue', '/missed', '/accounts', '/sources', '/watch', '/merge'):
        return False
    try:
        if cmd == '/queue':
            queue(tg, chat_id, parts[1] if len(parts) > 1 else 'pending', max(0, _page(parts[2]) - 1) if len(parts) > 2 else 0)
        elif cmd == '/missed':
            if len(parts) == 1 or parts[1] == 'refresh':
                tg.send_message(chat_id, '🔎 در حال بررسی منابع مرجع…', silent=True)
                scan_async(tg, chat_id)
            else:
                missed(tg, chat_id, max(0, _page(parts[1]) - 1))
        elif cmd == '/accounts':
            accounts(tg, chat_id)
        elif cmd == '/sources':
            if len(parts) >= 3 and parts[1] in ('watch', 'lfc', 'dismiss'):
                discovery.set_source(parts[2], state='dismissed' if parts[1] == 'dismiss' else 'watching',
                                     days=int(parts[3]) if len(parts) > 3 else 7, club_only=parts[1] == 'lfc')
            sources(tg, chat_id)
        elif cmd == '/merge':
            if len(parts) != 3:
                raise ValueError('استفاده: /merge شناسه‌خبر‌اصلی شناسه‌خبر‌دیگر؛ این دستور تأیید ادغام است.')
            discovery.merge_stories(parts[1], parts[2])
            tg.send_message(chat_id, 'منابع در خبر اصلی تجمیع شدند؛ دکمهٔ منابع خبر را بزن.', silent=True)
        else:
            if len(parts) >= 3 and parts[1] in ('target', 'current', 'former', 'remove'):
                # Quoted names aren't necessary: everything after the role is one full name.
                name = ' '.join(parts[2:]).strip().casefold()
                if len(name) < 4 or len(name) > 100 or '\n' in name:
                    raise ValueError('نام کامل بین ۴ تا ۱۰۰ کاراکتر لازم است.')
                with db._lock, db._c():
                    if parts[1] == 'remove':
                        db._c().execute('DELETE FROM news_entities WHERE name=?', (name,))
                    else:
                        db._c().execute('INSERT INTO news_entities VALUES (?,?,?,?,?) ON CONFLICT(name) '
                                        'DO UPDATE SET role=excluded.role,expires_at=excluded.expires_at, '
                                        'evidence=excluded.evidence,updated_at=excluded.updated_at',
                                        (name, parts[1], time.time() + 7 * 86400 if parts[1] == 'target' else 0,
                                         'admin-confirmed', time.time()))
            with db._lock:
                rows = db._c().execute('SELECT * FROM news_entities ORDER BY role,name').fetchall()
            lines = ['👤 <b>ارتباط افراد با تیم</b>', '/watch target Full Name — هدف نقل‌وانتقال برای ۷ روز',
                     '/watch current Full Name — بازیکن یا کادر فعلی', '/watch former Full Name — عضو سابق',
                     '/watch remove Full Name — حذف رابطهٔ دستی']
            for row in rows:
                state = row['role'] + (' (منقضی)' if row['expires_at'] and row['expires_at'] < time.time() else '')
                lines.append(formatter.esc(row['name']) + ': ' + formatter.esc(state))
            tg.send_message(chat_id, '\n'.join(lines), silent=True)
    except (ValueError, KeyError) as exc:
        tg.send_message(chat_id, formatter.esc(str(exc)), silent=True)
    return True


def maybe_audit(tg):
    summary = json.loads(discovery._meta('missed_scan', '{}'))
    if time.time() - summary.get('at', 0) >= 86400 and not discovery._audit_lock.locked():
        scan_async(tg, config.ADMIN_CHAT_ID)
