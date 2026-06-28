#!/usr/bin/env bash
# Ephemeral dev VM bootstrap for RFC-011 (no cron — data collection via CI only).
# Run as root via GCE startup-script on a fresh Debian 12 e2-micro.
# Application code and dependencies are deployed by dev-backfill CI from the runner.

set -euo pipefail

APP_DIR="/opt/fansboda-finance"
APP_USER="fansboda"
LOG_DIR="/var/log/fansboda-finance"
BOOTSTRAP_MARKER="/var/run/fansboda-dev-bootstrap.done"

apt-get update
apt-get install -y python3 python3-pip python3-venv git pipenv curl

if ! id "$APP_USER" &>/dev/null; then
  useradd --system --home-dir "$APP_DIR" --create-home --shell /usr/sbin/nologin "$APP_USER"
fi

mkdir -p "$APP_DIR"
chown "$APP_USER:$APP_USER" "$APP_DIR"

timedatectl set-timezone UTC

mkdir -p "$LOG_DIR"
chown "$APP_USER:$APP_USER" "$LOG_DIR"

touch "$BOOTSTRAP_MARKER"
echo "Dev VM bootstrap complete. Code and deps are deployed by dev-backfill CI."
