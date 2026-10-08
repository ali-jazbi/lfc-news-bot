"""Updates use disposable local Git repos and fake Telegram; never deploy the bot."""
import json
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

import bot_update
import config


@pytest.fixture(autouse=True)
def update_config(monkeypatch, tmp_path):
    bot_update._release()
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(config, "UPDATE_ENABLED", True)
    monkeypatch.setattr(config, "ADMIN_USER_IDS", [7])
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", "-100")
    yield
    bot_update._release()


def message(**changes):
    return dict({"chat": {"id": -100}, "from": {"id": 7},
                 "message_id": 12, "text": "/update"}, **changes)


@pytest.mark.parametrize("admins,user,chat,enabled,text,dry_run", [
    ([], 7, -100, True, "/update", False),
    ([7], 8, -100, True, "/update", False),
    ([7], None, -100, True, "/update", False),
    ([7], 7, 7, True, "/update", False),
    ([7], 7, -100, False, "/update", False),
    ([7], 7, -100, True, "/update branch;command", False),
    ([7], 7, -100, True, "/update", True),
])
def test_denied_requests_cannot_launch(monkeypatch, fake_tg, admins, user, chat, enabled, text, dry_run):
    monkeypatch.setattr(config, "ADMIN_USER_IDS", admins)
    monkeypatch.setattr(config, "UPDATE_ENABLED", enabled)
    monkeypatch.setattr(bot_update.threading, "Thread", lambda **kw: pytest.fail("unauthorized launch"))
    bot_update.request(fake_tg, message(chat={"id": chat}, **{"from": {"id": user}}, text=text),
                       lambda: pytest.fail("unauthorized restart"), dry_run=dry_run)
    assert fake_tg.sent_messages
    assert not bot_update.paused()


def test_concurrent_and_replayed_requests_do_not_launch_twice(monkeypatch, fake_tg):
    launched = []
    monkeypatch.setattr(bot_update.threading, "Thread",
                        lambda **kw: SimpleNamespace(start=lambda: launched.append(kw)))
    bot_update.request(fake_tg, message(), lambda: None)
    bot_update.request(fake_tg, message(message_id=13), lambda: None)
    assert len(launched) == 1
    assert bot_update.paused()
    bot_update._release()
    bot_update.request(fake_tg, message(), lambda: None)
    assert len(launched) == 1
    assert not bot_update.paused()


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def repositories(tmp_path):
    origin = tmp_path / "origin.git"
    writer = tmp_path / "writer"
    server = tmp_path / "server"
    git(tmp_path, "init", "--bare", str(origin))
    git(tmp_path, "clone", str(origin), str(writer))
    git(writer, "config", "user.email", "test@example.invalid")
    git(writer, "config", "user.name", "Update test")
    git(writer, "switch", "-c", "main")
    (writer / "main.py").write_text("VERSION = 1\n", encoding="utf-8")
    (writer / "requirements.txt").write_text("# old requirements\n", encoding="utf-8")
    (writer / ".gitignore").write_text("data/\n.env\n__pycache__/\n", encoding="utf-8")
    git(writer, "add", ".")
    git(writer, "commit", "-m", "initial")
    git(writer, "push", "-u", "origin", "main")
    git(origin, "symbolic-ref", "HEAD", "refs/heads/main")
    git(tmp_path, "clone", str(origin), str(server))
    return writer, server


def publish(writer, code="VERSION = 2\n", requirements=None):
    (writer / "main.py").write_text(code, encoding="utf-8")
    if requirements is not None:
        (writer / "requirements.txt").write_text(requirements, encoding="utf-8")
    git(writer, "add", ".")
    git(writer, "commit", "-m", "update")
    git(writer, "push")


def test_real_fast_forward_and_unchanged(repositories):
    writer, server = repositories
    old = git(server, "rev-parse", "HEAD")
    publish(writer)
    result = bot_update.prepare(server)
    assert result == {"status": "ready", "old_head": old,
                      "new_head": git(writer, "rev-parse", "HEAD")}
    assert (server / "main.py").read_text() == "VERSION = 2\n"
    assert bot_update.prepare(server)["status"] == "unchanged"


@pytest.mark.parametrize("code", ["broken = (", "import missing_update_test_module\n"])
def test_invalid_new_code_rolls_back_without_touching_env(repositories, code):
    writer, server = repositories
    old = git(server, "rev-parse", "HEAD")
    (server / ".env").write_text("test sentinel", encoding="utf-8")
    publish(writer, code)
    with pytest.raises(bot_update.UpdateError):
        bot_update.prepare(server)
    assert git(server, "rev-parse", "HEAD") == old
    assert (server / "main.py").read_text() == "VERSION = 1\n"
    assert (server / ".env").read_text() == "test sentinel"


@pytest.mark.parametrize("untracked", [False, True])
def test_local_edits_are_backed_up_before_update(repositories, untracked):
    writer, server = repositories
    publish(writer)
    path = server / ("untracked.txt" if untracked else "main.py")
    path.write_text("my local changes", encoding="utf-8")
    (server / ".env").write_text("env sentinel", encoding="utf-8")
    (server / "data").mkdir()
    (server / "data" / "news.db").write_bytes(b"database sentinel")
    # Backup also works when the deployment account has no Git identity.
    git(server, "config", "user.name", "")
    git(server, "config", "user.email", "")
    result = bot_update.prepare(server)
    assert result["status"] == "ready"
    assert git(server, "rev-parse", "HEAD") == git(writer, "rev-parse", "HEAD")
    assert (server / "main.py").read_text() == "VERSION = 2\n"
    assert (server / ".env").read_text() == "env sentinel"
    assert (server / "data" / "news.db").read_bytes() == b"database sentinel"
    ref = result["backup_ref"]
    # Dedicated ref survives removal from the ordinary stash list.
    git(server, "stash", "drop")
    revision = f"{ref}^3:untracked.txt" if untracked else f"{ref}:main.py"
    assert git(server, "show", revision) == "my local changes"


@pytest.mark.parametrize("new_code", [None, "broken = ("])
def test_dirty_checkout_restored_on_noop_or_failure(repositories, new_code):
    writer, server = repositories
    old = git(server, "rev-parse", "HEAD")
    (server / "main.py").write_text("LOCAL = 1\n", encoding="utf-8")
    git(server, "add", "main.py")
    (server / "main.py").write_text("LOCAL = 2\n", encoding="utf-8")
    (server / "untracked.txt").write_text("local", encoding="utf-8")
    before = git(server, "status", "--porcelain")
    if new_code:
        publish(writer, new_code)
        with pytest.raises(bot_update.UpdateError):
            bot_update.prepare(server)
    else:
        assert bot_update.prepare(server)["status"] == "unchanged"
    assert git(server, "rev-parse", "HEAD") == old
    assert git(server, "status", "--porcelain") == before
    assert git(server, "show", ":main.py") == "LOCAL = 1"
    assert (server / "main.py").read_text() == "LOCAL = 2\n"
    assert (server / "untracked.txt").read_text() == "local"


def test_untracked_collision_backed_up(repositories):
    writer, server = repositories
    (writer / "new.txt").write_text("upstream", encoding="utf-8")
    publish(writer)
    (server / "new.txt").write_text("local", encoding="utf-8")
    result = bot_update.prepare(server)
    assert result["status"] == "ready"
    assert (server / "new.txt").read_text() == "upstream"
    assert git(server, "show", f"{result['backup_ref']}^3:new.txt") == "local"


def test_runtime_excluded_even_with_broken_local_gitignore(repositories):
    writer, server = repositories
    publish(writer)
    (server / ".gitignore").write_text("", encoding="utf-8")
    (server / ".env").write_text("private", encoding="utf-8")
    (server / "data").mkdir()
    (server / "data" / "news.db").write_bytes(b"database")
    (server / "account.session").write_bytes(b"session")
    result = bot_update.prepare(server)
    assert result["status"] == "ready"
    assert (server / ".env").read_text() == "private"
    assert (server / "data" / "news.db").read_bytes() == b"database"
    assert (server / "account.session").read_bytes() == b"session"
    assert not git(server, "ls-tree", "-r", "--name-only", f"{result['backup_ref']}^3")


def test_remote_cannot_overwrite_ignored_env(repositories):
    writer, server = repositories
    (server / ".env").write_text("private", encoding="utf-8")
    (writer / ".env").write_text("remote", encoding="utf-8")
    git(writer, "add", "-f", ".env")
    publish(writer)
    with pytest.raises(bot_update.UpdateError, match="runtime"):
        bot_update.prepare(server)
    assert (server / ".env").read_text() == "private"


def test_divergent_branch_is_not_reset_or_merged(repositories):
    writer, server = repositories
    publish(writer)
    git(server, "config", "user.email", "test@example.invalid")
    git(server, "config", "user.name", "Update test")
    (server / "main.py").write_text("LOCAL = 1\n", encoding="utf-8")
    git(server, "add", "main.py")
    git(server, "commit", "-m", "local commit")
    old = git(server, "rev-parse", "HEAD")
    with pytest.raises(bot_update.UpdateError, match="دریافت آپدیت"):
        bot_update.prepare(server)
    assert git(server, "rev-parse", "HEAD") == old
    assert (server / "main.py").read_text() == "LOCAL = 1\n"


@pytest.mark.parametrize("fail", [False, True])
def test_dependencies_install_only_when_changed_and_restore_on_failure(monkeypatch, repositories, fail):
    writer, server = repositories
    old = git(server, "rev-parse", "HEAD")
    publish(writer, requirements="# new requirements\n")
    real_run = bot_update._run
    installs = []

    def run(root, args, stage, timeout=120):
        if args[:3] == [sys.executable, "-m", "pip"]:
            installs.append((server / "requirements.txt").read_text())
            if fail and len(installs) == 1:
                raise bot_update.UpdateError(stage)
            return ""
        return real_run(root, args, stage, timeout)

    monkeypatch.setattr(bot_update, "_run", run)
    if fail:
        with pytest.raises(bot_update.UpdateError):
            bot_update.prepare(server)
        assert git(server, "rev-parse", "HEAD") == old
        assert installs == ["# new requirements\n", "# old requirements\n"]
    else:
        assert bot_update.prepare(server)["status"] == "ready"
        assert installs == ["# new requirements\n"]


def test_process_lock_excludes_second_updater(tmp_path):
    handle = bot_update._lock(tmp_path)
    try:
        with pytest.raises(OSError):
            bot_update._lock(tmp_path)
    finally:
        handle.close()
    bot_update._lock(tmp_path).close()


@pytest.mark.parametrize("status", ["ready", "unchanged", "failed"])
def test_worker_handoff_failure_and_noop(monkeypatch, fake_tg, status):
    state = {"request_id": "-100:12", "chat_id": -100}
    outcome = {"status": status, "new_head": "a" * 40, "error": "مرحلهٔ آزمایشی"}
    monkeypatch.setattr(bot_update.subprocess, "run", lambda *a, **kw:
                        SimpleNamespace(returncode=int(status == "failed"), stdout=json.dumps(outcome)))
    bot_update._busy.acquire()
    bot_update._deployment_lock = bot_update._lock(config.BASE_DIR)
    bot_update._paused = True
    restarts = []
    bot_update._worker(config.BASE_DIR, fake_tg, state, lambda: restarts.append(True))
    assert restarts == ([True] if status == "ready" else [])
    assert bot_update._read_state(config.BASE_DIR)["status"] == status
    assert bot_update.paused() == (status == "ready")


def test_worker_records_and_announces_backup(monkeypatch, fake_tg):
    ref = "refs/bot-update-backups/test"
    outcome = {"status": "ready", "new_head": "a" * 40, "backup_ref": ref}
    monkeypatch.setattr(bot_update.subprocess, "run", lambda *a, **kw:
                        SimpleNamespace(returncode=0, stdout=json.dumps(outcome)))
    bot_update._deployment_lock = bot_update._lock(config.BASE_DIR)
    restarted = []
    bot_update._worker(config.BASE_DIR, fake_tg, {"chat_id": -100}, lambda: restarted.append(True))
    assert restarted == [True]
    assert bot_update._read_state(config.BASE_DIR)["backup_ref"] == ref
    assert any("پشتیبان" in item for item in fake_tg.sent_messages)


def test_drain_timeout_never_runs_git_or_restarts(monkeypatch, fake_tg):
    monkeypatch.setattr(config, "UPDATE_DRAIN_TIMEOUT", 0.01)
    monkeypatch.setattr(bot_update, "_active", 1)
    monkeypatch.setattr(bot_update.subprocess, "run", lambda *a, **kw: pytest.fail("undrained update"))
    bot_update._worker(config.BASE_DIR, fake_tg, {"chat_id": -100}, lambda: pytest.fail("restart"))
    assert bot_update._read_state(config.BASE_DIR)["status"] == "failed"
    assert not bot_update.paused()


def test_existing_nested_work_can_finish_during_pause():
    @bot_update.activity
    def nested():
        return bot_update.new_job_paused()

    @bot_update.activity
    def started_job():
        bot_update._paused = True
        return nested()

    assert started_job() is False
    assert nested() is True
    assert bot_update._active == 0


def test_prepare_waits_for_real_active_job_to_finish(monkeypatch, fake_tg):
    started, finish, prepared = threading.Event(), threading.Event(), threading.Event()

    @bot_update.activity
    def job():
        started.set()
        assert finish.wait(3)

    def prepare(*args, **kwargs):
        prepared.set()
        return SimpleNamespace(returncode=0, stdout='{"status":"unchanged"}')

    monkeypatch.setattr(bot_update.subprocess, "run", prepare)
    job_thread = threading.Thread(target=job)
    job_thread.start()
    assert started.wait(1)
    bot_update._paused = True
    bot_update._deployment_lock = bot_update._lock(config.BASE_DIR)
    worker = threading.Thread(target=bot_update._worker,
                              args=(config.BASE_DIR, fake_tg, {"chat_id": -100}, lambda: None))
    worker.start()
    try:
        assert not prepared.wait(0.05)
    finally:
        finish.set()
        job_thread.join(3)
        worker.join(3)
    assert prepared.is_set()
    assert not worker.is_alive()
    assert bot_update._active == 0


def test_one_shot_execution_cannot_update(fake_tg, monkeypatch):
    monkeypatch.setattr(bot_update.threading, "Thread", lambda **kw: pytest.fail("one-shot update"))
    bot_update.request(fake_tg, message(), lambda: None, service_mode=False)
    assert not bot_update.paused()


def test_command_routes_qualified_update_to_background_worker(patched_main, monkeypatch):
    import main
    launches = []
    monkeypatch.setattr(main, "_service_mode", True)
    monkeypatch.setattr(main, "DRY_RUN", False)
    monkeypatch.setattr(bot_update.threading, "Thread",
                        lambda **kw: SimpleNamespace(start=lambda: launches.append(kw)))
    main.handle_message(message(text="/update@testbot"))
    assert len(launches) == 1
    assert launches[0]["target"] is bot_update._worker
    assert bot_update.paused()


def test_raw_subprocess_errors_are_not_exposed(monkeypatch, repositories, caplog):
    _, server = repositories
    monkeypatch.setattr(bot_update.subprocess, "run", lambda *a, **kw:
                        SimpleNamespace(returncode=1, stdout="", stderr="test-private-sentinel"))
    with pytest.raises(bot_update.UpdateError) as error:
        bot_update.prepare(server)
    assert "test-private-sentinel" not in str(error.value)
    assert "test-private-sentinel" not in caplog.text


def test_startup_reports_completion_once_and_retries_failed_notification(fake_tg):
    bot_update._write_state(config.BASE_DIR, {"status": "ready", "chat_id": -100, "new_head": "a" * 40})
    fake_tg.fail_send = True
    bot_update.notify_startup(fake_tg)
    assert bot_update._read_state(config.BASE_DIR)["status"] == "ready"
    fake_tg.fail_send = False
    bot_update.notify_startup(fake_tg)
    assert bot_update._read_state(config.BASE_DIR)["status"] == "complete"
    before = len(fake_tg.calls)
    bot_update.notify_startup(fake_tg)
    assert len(fake_tg.calls) == before


def test_restart_replaces_only_current_bot_with_same_interpreter(monkeypatch):
    calls = []
    monkeypatch.setattr(sys, "argv", ["main.py", "--dry-run"])
    monkeypatch.setattr(bot_update.os, "execv", lambda *a: calls.append(a))
    bot_update.restart_process()
    assert calls == [(sys.executable, [sys.executable, str(config.BASE_DIR / "main.py"), "--dry-run"])]


def test_command_uses_strict_update_permissions_even_when_legacy_admins_are_open(patched_main, monkeypatch):
    import main
    monkeypatch.setattr(config, "ADMIN_USER_IDS", [])
    main.handle_message(message())
    assert "ADMIN_USER_IDS" in main.tg.sent_messages[-1]
    assert not bot_update.paused()


def test_pause_blocks_polling_and_late_manual_links(patched_main, monkeypatch):
    import main
    bot_update._paused = True
    monkeypatch.setattr(main, "collect", lambda: pytest.fail("collection during update"))
    monkeypatch.setattr(main.twitter, "item_from_url", lambda *a: pytest.fail("late manual extraction"))
    main.run_cycle()
    main._handle_tweet_link("https://x.com/LFC/status/123", -100)
    main.handle_callback({"id": "pause-test"})
    assert any("آپدیت" in t for t in main.tg.sent_messages)
