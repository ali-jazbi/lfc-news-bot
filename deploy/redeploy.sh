#!/usr/bin/env bash
# redeploy.sh — بعد از هر آپدیت کد (git pull یا دیپلوی خودکار cPanel) این رو اجرا کن
# تا وابستگی‌ها آپدیت بشن و بات با نسخه‌ی جدید ریستارت بشه.
#
# اجرای دستی (بعد از کپی کردن مسیرها پایین):
#   bash deploy/redeploy.sh

set -e

APP_DIR="/home/lfcnewss/lfc-bot"                                        # مسیر فرق پروژه رو تغییر بده
VENV_ACTIVATE="/home/lfcnewss/virtualenv/lfc-bot/3.11/bin/activate"     # این رو از Setup Python App کپی کن

cd "$APP_DIR"

echo "نصب/آپدیت وابستگی‌ها..."
# shellcheck disable=SC1090
source "$VENV_ACTIVATE"
pip install -r requirements.txt --quiet

echo "متوقف کردن نسخه‌ی قبلی بات (اگه روشن بود)..."
pkill -f "python3 .*main\.py" || true
sleep 2

echo "روشن کردن نسخه‌ی جدید..."
mkdir -p "$APP_DIR/data"
nohup python3 main.py >> "$APP_DIR/data/bot.log" 2>&1 &
disown

echo "انجام شد. لاگ زنده: tail -f $APP_DIR/data/bot.log"
