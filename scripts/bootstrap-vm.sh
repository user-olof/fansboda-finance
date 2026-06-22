#!/usr/bin/env bash
# One-time bootstrap for the GCP e2-micro production VM (RFC-008).
# Run as root or with sudo on a fresh Debian 12 instance.

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root or with sudo." >&2
  exit 1
fi

APP_DIR="/opt/fansboda-finance"
APP_USER="fansboda"
LOG_DIR="/var/log/fansboda-finance"
CRON_SCHEDULE="0 11 * * 4"  # Thursdays 11:00 UTC (PRD §10)
REPO_URL="${REPO_URL:-https://github.com/user-olof/fansboda-finance.git}"

apt-get update
apt-get install -y python3 python3-pip python3-venv git pipenv

if ! id "$APP_USER" &>/dev/null; then
  useradd --system --home-dir "$APP_DIR" --create-home --shell /usr/sbin/nologin "$APP_USER"
fi

mkdir -p "$APP_DIR"
if [ ! -d "$APP_DIR/.git" ]; then
  git clone "$REPO_URL" "$APP_DIR"
fi

chown -R "$APP_USER:$APP_USER" "$APP_DIR"

su -s /bin/bash "$APP_USER" -c "cd '$APP_DIR' && PIPENV_VENV_IN_PROJECT=1 pipenv install --deploy"

timedatectl set-timezone UTC

mkdir -p "$LOG_DIR"
chown "$APP_USER:$APP_USER" "$LOG_DIR"
touch "$LOG_DIR/fetch_sma.log"
chown "$APP_USER:$APP_USER" "$LOG_DIR/fetch_sma.log"

CRON_LINE="${CRON_SCHEDULE} cd ${APP_DIR} && set -a && [ -f .env ] && . ./.env && set +a && PIPENV_VENV_IN_PROJECT=1 pipenv run python fetch_sma.py >> ${LOG_DIR}/fetch_sma.log 2>&1"
(crontab -u "$APP_USER" -l 2>/dev/null | grep -v 'fetch_sma.py' || true; echo "$CRON_LINE") | crontab -u "$APP_USER" -

echo "Bootstrap complete."
echo "Add DATABASE_URL via GitHub deploy (push to main) or manually:"
echo "  $APP_DIR/.env  (owner $APP_USER, mode 600, include APP_ENV=production)"
