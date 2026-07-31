#!/usr/bin/env bash
# watchdog.sh — جایگزین ساده‌ی systemd روی هاست اشتراکی (که بهت دسترسی root/systemd نمی‌ده).
# با Cron Job هر ۵ دقیقه اجرا می‌شه: اگه بات خاموشه (کرش، ریبوت سرور، کشته
# شدن دستی)، دوباره روشنش می‌کنه. اگه روشن باشه، هیچ کاری نمی‌کنه.
#
# قبل از استفاده:
#   1) دو خط پایین رو با مقادیر واقعی خودت پر کن.
#   2) مسیر VENV_ACTIVATE رو از صفحه‌ی cPanel → Setup Python App کپی کن (بعد از ساخت اپ).
#   3) قابل اجرا کن: chmod +x deploy/watchdog.sh
#   4) توی cPanel → Cron Jobs این خط رو هر ۵ دقیقه اضافه کن:
#      */5 * * * * /bin/bash /home/lfcnewss/lfc-bot/deploy/watchdog.sh

set -u

APP_DIR="/home/lfcnewss/lfc-bot"                                        # اگه مسیر فرق بود تغییرش بده
VENV_ACTIVATE="/home/lfcnewss/virtualenv/lfc-bot/3.11/bin/activate"     # این رو از Setup Python App کپی کن

LOG_FILE="$APP_DIR/data/watchdog.log"
LOCK_FILE="$APP_DIR/data/watchdog.lock"
mkdir -p "$APP_DIR/data"

cd "$APP_DIR" || exit 1

# قفل فایلی: اگه یه اجرای قبلی این اسکریپت هنوز باز باشه (مثلاً کرون قبلی گیر
# کرده)، این اجرای جدید بی‌سروصدا خارج می‌شه. بدون این، دو تا کرون هم‌زمان
# می‌تونن هر دو main.py رو استارت کنن و با هم قاپ getUpdates بندازن (409).
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
	exit 0   # یه اجرای دیگه از watchdog همین الان در حال کاره
fi

if pgrep -f "python3 .*main\.py" > /dev/null 2>&1; then
	exit 0   # بات روشنه، کاری لازم نیست
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') — بات خاموش بود، دوباره روشن شد" >> "$LOG_FILE"

# shellcheck disable=SC1090
source "$VENV_ACTIVATE"
nohup python3 main.py >> "$APP_DIR/data/bot.log" 2>&1 &
disown
