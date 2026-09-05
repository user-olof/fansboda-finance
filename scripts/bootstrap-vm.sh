#!/usr/bin/env bash
# One-time bootstrap for the GCP e2-micro production VM (RFC-008).
# Run as root or with sudo on a fresh Debian 12 instance.
# Application code and locked deps are deployed by deploy.yml (tarball + pipenv).

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root or with sudo." >&2
  exit 1
fi

APP_DIR="/opt/fansboda-finance"
APP_USER="fansboda"
LOG_DIR="/var/log/fansboda-finance"
CRON_SCHEDULE="0 11 * * 4"  # Thursdays 11:00 UTC (PRD §10)


if ! id "$APP_USER" &>/dev/null; then
  useradd --system --home-dir "$APP_DIR" --create-home --shell /usr/sbin/nologin "$APP_USER"
fi

mkdir -p "$APP_DIR"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

timedatectl set-timezone UTC

mkdir -p "$LOG_DIR"
chown "$APP_USER:$APP_USER" "$LOG_DIR"
touch "$LOG_DIR/fetch_sma.log"
chown "$APP_USER:$APP_USER" "$LOG_DIR/fetch_sma.log"

if ! crontab -u "$APP_USER" -l 2>/dev/null | grep -q 'fetch_sma.py'; then
  CRON_LINE="${CRON_SCHEDULE} cd ${APP_DIR} && set -a && [ -f .env ] && . ./.env && set +a && PIPENV_VENV_IN_PROJECT=1 pipenv run python fetch_sma.py >> ${LOG_DIR}/fetch_sma.log 2>&1"
  (crontab -u "$APP_USER" -l 2>/dev/null || true; echo "$CRON_LINE") | crontab -u "$APP_USER" -
fi

echo "Bootstrap complete."
echo "Application code and Pipenv deps come from deploy.yml (tarball + pipenv install --deploy)."
echo "Add DATABASE_URL / APP_ENV via GitHub deploy (push to main) or manually:"
echo "  $APP_DIR/.env  (owner $APP_USER, mode 600)"
echo "After seed/fetch, verify Neon: us_metrics / swe_metrics / uk_metrics"
echo "  and us_market_metrics / swe_market_metrics / uk_market_metrics"
echo "  (tickers tables include exchange_name; see RFC-008 runbook)."
