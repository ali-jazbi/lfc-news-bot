"""عیب‌یاب — python doctor.py

۱) فایل .env
۲) اتصال مستقیم و پراکسی‌های موجود
۳) توکن ربات
۴) تک‌تک سرویس‌های زنجیره ترجمه را به ترتیب اولویت واقعاً صدا می‌زند
"""
# --- path bootstrap: allow running from scripts/ subdir ---
import sys as _sys
import pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[2]))
import socket
import sys
import time

import requests

import config
import translate

OK = "\u2705"
NO = "\u274C"
WARN = "\u26A0\uFE0F"

COMMON_PORTS = [
    (10808, "v2rayN / v2rayNG (SOCKS)"),
    (10809, "v2rayN (HTTP)"),
    (2080, "Nekoray / NekoBox"),
    (2081, "Nekoray (جایگزین)"),
    (7890, "Clash (HTTP)"),
    (7891, "Clash (SOCKS)"),
    (12334, "Hiddify"),
    (1080, "Shadowsocks (SOCKS)"),
    (1081, "Shadowsocks (HTTP)"),
    (8080, "عمومی HTTP"),
    (8888, "عمومی"),
    (8889, "عمومی"),
    (9050, "Tor"),
    (20171, "Lantern"),
]

TEST_URL = "https://www.gstatic.com/generate_204"

SAMPLE = {
    "source_tag": "Fabrizio Romano",
    "title": "Liverpool agree deal for midfielder",
    "body": "Liverpool have reached a full agreement with the player over a five-year contract. "
            "Medical is scheduled for tomorrow at Anfield. Here we go!",
    "url": "https://x.com/FabrizioRomano/status/1",
    "priority": True,
}


def head(t):
    print("\n" + "\u2500" * 62)
    print(t)
    print("\u2500" * 62)


def mask(s):
    if not s:
        return "(خالی)"
    return s[:6] + "..." + s[-4:] if len(s) > 14 else s[:3] + "..."


# ------------------------------------------------------------ ۱
def check_env():
    head("۱) فایل .env")
    if not config.BOT_TOKEN:
        print(f"{NO} BOT_TOKEN خالی است")
    elif ":" not in config.BOT_TOKEN:
        print(f"{NO} BOT_TOKEN فرمت غلط دارد")
    else:
        print(f"{OK} BOT_TOKEN: {mask(config.BOT_TOKEN)}")

    if not config.ADMIN_CHAT_ID:
        print(f"{WARN} ADMIN_CHAT_ID خالی است (با python get_chat_id.py بگیرش)")
    else:
        print(f"{OK} ADMIN_CHAT_ID: {config.ADMIN_CHAT_ID}")

    print(f"   حالت انتشار: {config.PUBLISH_MODE}")
    print(f"   PROXY: {config.PROXY or '(خالی)'}")

    head("زنجیره ترجمه (به ترتیب اولویت)")
    names = translate.chain_names()
    if not names:
        print(f"{NO} هیچ سرویسی فعال نیست. در .env یک اسلات LLM پر کن"
              " یا ENABLE_DEEP_TRANSLATOR=true بگذار.")
        return False
    for i, n in enumerate(names, 1):
        print(f"   {i}. {n}")
    print(f"\n   TRANSLATE_ORDER = {','.join(config.TRANSLATE_ORDER)}")
    skipped = [
        s for s in config.TRANSLATE_ORDER
        if s in config.LLM_SLOTS and not config.LLM_SLOTS[s]["key"]
    ]
    if skipped:
        print(f"   {WARN} این اسلات‌ها کلید ندارند و رد شدند: {', '.join(skipped)}")
    return True


# ------------------------------------------------------------ ۲
def port_open(port, timeout=0.4):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex(("127.0.0.1", port)) == 0


def try_proxy(proxy_url, timeout=8):
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    try:
        r = requests.get(TEST_URL, proxies=proxies, timeout=timeout)
        return (r.status_code in (200, 204)), f"HTTP {r.status_code}"
    except Exception as e:
        return False, type(e).__name__


def scan():
    head("۲) اتصال اینترنت")
    direct_ok, msg = try_proxy(None, timeout=6)
    print(f"{OK if direct_ok else NO} اتصال مستقیم: {msg}")

    open_ports = [(p, n) for p, n in COMMON_PORTS if port_open(p)]
    for p, n in open_ports:
        print(f"{OK} پورت {p} باز است — {n}")
    if not open_ports and not direct_ok:
        print(f"{NO} نه اتصال مستقیم داری نه پراکسی روشنی پیدا شد.")

    working = [""] if direct_ok else []
    for p, _ in open_ports:
        for scheme in ("socks5h", "http"):
            url = f"{scheme}://127.0.0.1:{p}"
            good, msg = try_proxy(url, timeout=8)
            print(f"{OK if good else NO} {url:32} {msg}")
            if good:
                working.append(url)
                break
    return working


# ------------------------------------------------------------ ۳
def test_telegram():
    head("۳) توکن ربات")
    if not config.BOT_TOKEN:
        print(f"{NO} توکن خالی است")
        return
    proxies = {"http": config.PROXY, "https": config.PROXY} if config.PROXY else None
    try:
        r = requests.get(
            "https://api.telegram.org/bot" + config.BOT_TOKEN + "/getMe",
            timeout=30,
            proxies=proxies,
        )
    except Exception as e:
        print(f"{NO} اتصال برقرار نشد: {type(e).__name__}")
        return
    if r.status_code == 200 and r.json().get("ok"):
        print(f"{OK} ربات: @{r.json()['result']['username']}")
    else:
        print(f"{NO} HTTP {r.status_code}: {r.text[:200]}")


# ------------------------------------------------------------ ۴
def test_chain():
    head("۴) تست واقعی زنجیره ترجمه")
    chain = translate._chain()
    if not chain:
        return

    healthy = []
    for name, kind, fn in chain:
        t0 = time.time()
        try:
            if kind == "plain":
                data = fn(SAMPLE)
            else:
                data = translate._extract_json(fn(translate._build_prompt(SAMPLE)))
            dt = time.time() - t0
            if data and data.get("body"):
                preview = data["body"].replace("\n", " ")[:70]
                print(f"{OK} {name}  ({dt:.1f}s)\n     نمونه: {preview}...")
                healthy.append(name)
            else:
                print(f"{NO} {name}  — خروجی نامعتبر (مدل JSON تمیز نداد)")
        except Exception as e:
            print(f"{NO} {name}\n     {e}")

    head("نتیجه")
    if healthy:
        print(f"{OK} {len(healthy)} سرویس سالم است: {', '.join(healthy)}")
        print(f"   اولویت اول سالم: {healthy[0]}")
        print("   ربات آماده است → python main.py --sample")
    else:
        print(f"{NO} هیچ سرویسی جواب نداد.")
        print("   ساده‌ترین راه حل: در .env بگذار ENABLE_DEEP_TRANSLATOR=true")
        print("   و در TRANSLATE_ORDER کلمه translate را داشته باش (بدون کلید کار می‌کند).")


def main():
    print("\U0001F50D عیب‌یابی LFC News Bot")
    has_chain = check_env()
    working = scan()

    if not working:
        head("نتیجه")
        print(f"{NO} هیچ مسیر اینترنتی کار نکرد. کلاینت فیلترشکن را روشن کن.")
        sys.exit(1)

    if config.PROXY and config.PROXY not in working:
        print(f"\n{WARN} PROXY فعلی ({config.PROXY}) کار نمی‌کند.")
        print(f"   بگذار: PROXY={working[0]}" if working[0] else "   بگذار: PROXY=  (خالی)")
        print("   بعد از اصلاح، دوباره doctor را اجرا کن.")

    test_telegram()
    if has_chain:
        test_chain()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
