"""Admin-only updates; preparation runs in a separate, stdlib-only process."""
import ast
from functools import wraps
import html
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

log = logging.getLogger("bot.update")
_busy = threading.Lock()
_condition = threading.Condition()
_active = 0
_paused = False
_deployment_lock = None
_local = threading.local()


def paused():
    with _condition:
        return _paused


def activity(fn):
    """Count existing jobs so an update can wait without interrupting a send."""
    @wraps(fn)
    def wrapped(*args, **kwargs):
        global _active
        with _condition:
            _active += 1
        depth = getattr(_local, "depth", 0)
        _local.depth = depth + 1
        try:
            return fn(*args, **kwargs)
        finally:
            _local.depth = depth
            with _condition:
                _active -= 1
                _condition.notify_all()
    return wrapped


def new_job_paused():
    return paused() and getattr(_local, "depth", 0) <= 1


def _state_path(root):
    return Path(root) / "data" / "update.json"


def _read_state(root):
    try:
        state = json.loads(_state_path(root).read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(root, state):
    path = _state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"update-{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _lock(root):
    path = Path(root) / "data" / "update.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            handle.write(b"0")
            handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except BaseException:
        handle.close()
        raise


class UpdateError(Exception):
    pass


def _run(root, args, stage, timeout=120):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never",
               PIP_NO_INPUT="1")
    try:
        result = subprocess.run(args, cwd=root, env=env, capture_output=True,
                                text=True, encoding="utf-8", errors="replace",
                                timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise UpdateError(stage) from None
    if result.returncode:
        # Git/pip stderr can contain credential-bearing URLs: never forward it.
        raise UpdateError(stage)
    return result.stdout.strip()


def prepare(root):
    root = Path(root).resolve()
    git = lambda *args, stage="بررسی گیت": _run(root, ["git", *args], stage)
    if Path(git("rev-parse", "--show-toplevel")).resolve() != root:
        raise UpdateError("پوشهٔ بات باید ریشهٔ یک checkout مستقل گیت باشد")
    git("symbolic-ref", "--quiet", "HEAD", stage="شاخهٔ فعلی مشخص نیست")
    git("rev-parse", "--verify", "@{upstream}", stage="upstream شاخه تنظیم نشده")
    if git("status", "--porcelain"):
        raise UpdateError("تغییر محلی یا فایل ثبت‌نشده وجود دارد؛ ابتدا تعیین تکلیفش کن")
    old = git("rev-parse", "HEAD")
    deps_changed = False
    try:
        git("pull", "--ff-only", "--no-rebase", stage="دریافت آپدیت از گیت‌هاب")
        new = git("rev-parse", "HEAD")
        if old == new:
            return {"status": "unchanged", "old_head": old, "new_head": new}
        # Check syntax without importing the bot, providers or Hermes.
        for filename in git("ls-files", "*.py").splitlines():
            if "hermes" in filename.lower():
                continue
            try:
                ast.parse((root / filename).read_text(encoding="utf-8-sig"), filename)
            except (OSError, SyntaxError, UnicodeError):
                raise UpdateError("بررسی ساختار کد نسخهٔ جدید") from None
        deps_changed = bool(git("diff", "--name-only", old, new, "--", "requirements.txt"))
        if deps_changed:
            _run(root, [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
                 "نصب وابستگی‌های نسخهٔ جدید", timeout=600)
        # Isolated import smoke check: no main(), DB init or service calls.
        _run(root, [sys.executable, "-c", "import main"], "بررسی راه‌اندازی کد نسخهٔ جدید")
        return {"status": "ready", "old_head": old, "new_head": new}
    except UpdateError as exc:
        # --keep refuses to overwrite edits made during the update.
        try:
            git("reset", "--keep", old, stage="بازگرداندن نسخهٔ قبلی")
            if deps_changed:
                _run(root, [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
                     "بازگرداندن وابستگی‌های قبلی", timeout=600)
        except UpdateError:
            raise UpdateError(f"{exc}؛ بازگردانی کامل نشد، بررسی دستی لازم است") from None
        raise


def request(tg, message, restart, *, dry_run=False, service_mode=True):
    """Fail closed, including when the legacy admin allowlist is empty."""
    global _paused, _deployment_lock
    import config
    chat = message.get("chat", {}).get("id")
    user = message.get("from", {}).get("id")
    if (not config.ADMIN_USER_IDS or user not in config.ADMIN_USER_IDS
            or str(chat) != str(config.ADMIN_CHAT_ID)):
        tg.send_message(chat, "⛔ /update فقط در گروه ادمین و برای ADMIN_USER_IDS مشخص مجاز است.")
        return
    if not config.UPDATE_ENABLED or dry_run or not service_mode:
        tg.send_message(chat, "برای /update باید UPDATE_ENABLED=true باشد و بات در حالت دائمی، بدون dry-run اجرا شود.")
        return
    if len((message.get("text") or "").split()) != 1:
        tg.send_message(chat, "فقط /update را بفرست؛ شاخه و دستور اضافی پذیرفته نمی‌شود.")
        return
    if not _busy.acquire(blocking=False):
        tg.send_message(chat, "⏳ یک آپدیت در حال انجام است.")
        return
    root = config.BASE_DIR
    state = {"request_id": f"{chat}:{message.get('message_id')}", "chat_id": chat,
             "status": "running", "started_at": time.time()}
    try:
        _deployment_lock = _lock(root)
        if _read_state(root).get("request_id") == state["request_id"]:
            raise UpdateError("این درخواست قبلاً بررسی شده؛ برای درخواست تازه دوباره /update بفرست")
        _write_state(root, state)
        with _condition:
            _paused = True
        tg.send_message(chat, "🔄 آپدیت شروع شد؛ منتظر پایان پردازش خبرهای فعلی می‌مانم…")
        threading.Thread(target=_worker, args=(root, tg, state, restart),
                         name="bot-update", daemon=True).start()
    except Exception:
        _release()
        tg.send_message(chat, "آپدیت شروع نشد؛ درخواست تکراری است یا قفل آپدیت در اختیار اجرای دیگری است.")


def _release():
    global _paused, _deployment_lock
    with _condition:
        _paused = False
    if _deployment_lock is not None:
        _deployment_lock.close()
        _deployment_lock = None
    if _busy.locked():
        _busy.release()


def _worker(root, tg, state, restart):
    import config
    ready = False
    try:
        with _condition:
            if not _condition.wait_for(lambda: _active == 0, timeout=config.UPDATE_DRAIN_TIMEOUT):
                raise UpdateError("خبرهای در حال پردازش در زمان مقرر تمام نشدند")
        tg.send_message(state["chat_id"], "⬇️ در حال دریافت و بررسی نسخهٔ جدید…")
        kwargs = {"pass_fds": (_deployment_lock.fileno(),)} if os.name != "nt" else {}
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--prepare", str(root)],
            cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
            **kwargs,
        )
        outcome = json.loads(result.stdout)
        if result.returncode or outcome.get("status") == "failed":
            raise UpdateError(outcome.get("error", "آماده‌سازی آپدیت"))
        if outcome.get("status") not in ("ready", "unchanged"):
            raise UpdateError("پاسخ نامعتبر آماده‌سازی آپدیت")
        state.update(outcome)
        _write_state(root, state)
        if state["status"] == "unchanged":
            tg.send_message(state["chat_id"], "✅ بات همین حالا آخرین نسخه است؛ ری‌استارت لازم نیست.")
            return
        tg.send_message(state["chat_id"], "♻️ بررسی تمام شد؛ بات در حال ری‌استارت است…")
        restart()
        ready = True  # Keep the deployment lock until exec replaces this process.
    except Exception as exc:
        error = str(exc) if isinstance(exc, UpdateError) else "خطای داخلی آپدیت"
        log.error("update failed: %s", error)
        state.update(status="failed", error=error)
        try:
            _write_state(root, state)
        finally:
            tg.send_message(state["chat_id"], f"❌ آپدیت انجام نشد: {html.escape(error)}\nبات ری‌استارت نشد.")
    finally:
        if not ready:
            _release()


def notify_startup(tg):
    import config
    state = _read_state(config.BASE_DIR)
    if state.get("status") != "ready":
        return
    head = str(state.get("new_head", ""))[:12]
    if tg.send_message(state["chat_id"], f"✅ بات با نسخهٔ جدید روشن شد.\nکامیت: <code>{html.escape(head)}</code>"):
        state["status"] = "complete"
        _write_state(config.BASE_DIR, state)


def restart_process():
    """Replace only this bot; preserve interpreter, arguments and watchdog PID."""
    import config
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        os.execv(sys.executable, [sys.executable, str(config.BASE_DIR / "main.py"), *sys.argv[1:]])
    except OSError:
        _release()
        raise


if __name__ == "__main__":
    try:
        if len(sys.argv) != 3 or sys.argv[1] != "--prepare":
            raise UpdateError("آرگومان نامعتبر")
        print(json.dumps(prepare(sys.argv[2]), ensure_ascii=True))
    except Exception as exc:
        error = str(exc) if isinstance(exc, UpdateError) else "خطای داخلی آماده‌سازی"
        print(json.dumps({"status": "failed", "error": error}, ensure_ascii=True))
        sys.exit(1)
