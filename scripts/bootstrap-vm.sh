#!/usr/bin/env bash
# One-time bootstrap for the GCP e2-micro VM.
# Run as root or with sudo on a fresh Debian/Ubuntu instance.

set -euo pipefail

APP_DIR="/opt/fansboda-finance"
REPO_URL="${REPO_URL:-https://github.com/user-olof/fansboda-finance.git}"

apt-get update
apt-get install -y python3 python3-pip python3-venv git pipenv

mkdir -p "$APP_DIR"
if [ ! -d "$APP_DIR/.git" ]; then
  git clone "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"
export PIPENV_VENV_IN_PROJECT=1
pipenv install --deploy

timedatectl set-timezone UTC

CRON_LINE='0 11 * * * cd /opt/fansboda-finance && pipenv run python fetch_sma.py >> /var/log/fetch_sma.log 2>&1'
(crontab -l 2>/dev/null | grep -v 'fetch_sma.py' || true; echo "$CRON_LINE") | crontab -

touch /var/log/fetch_sma.log
chmod 644 /var/log/fetch_sma.log

echo "Bootstrap complete. Add DATABASE_URL via GitHub deploy workflow or manually to $APP_DIR/.env"
