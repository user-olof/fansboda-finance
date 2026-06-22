#!/usr/bin/env bash
# Ephemeral dev VM bootstrap for RFC-011 (no cron — data collection via CI only).
# Run as root via GCE startup-script on a fresh Debian 12 e2-micro.

set -euo pipefail

APP_DIR="/opt/fansboda-finance"
APP_USER="fansboda"
LOG_DIR="/var/log/fansboda-finance"

metadata_attr() {
  curl -sf -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1" || true
}

REPO_URL="$(metadata_attr repo-url)"
BRANCH="$(metadata_attr branch)"
REPO_URL="${REPO_URL:-https://github.com/user-olof/fansboda-finance.git}"
BRANCH="${BRANCH:-dev}"

apt-get update
apt-get install -y python3 python3-pip python3-venv git pipenv curl

if ! id "$APP_USER" &>/dev/null; then
  useradd --system --home-dir "$APP_DIR" --create-home --shell /usr/sbin/nologin "$APP_USER"
fi

mkdir -p "$APP_DIR"
if [ ! -d "$APP_DIR/.git" ]; then
  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi

chown -R "$APP_USER:$APP_USER" "$APP_DIR"

su -s /bin/bash "$APP_USER" -c "cd '$APP_DIR' && PIPENV_VENV_IN_PROJECT=1 pipenv install --deploy"

timedatectl set-timezone UTC

mkdir -p "$LOG_DIR"
chown "$APP_USER:$APP_USER" "$LOG_DIR"

echo "Dev VM bootstrap complete (branch=$BRANCH). .env is written by dev-backfill CI."
