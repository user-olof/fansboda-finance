#!/usr/bin/env bash
# Idempotent bootstrap for the fansboda-finance Cloud Agent environment.
#
# The default Ubuntu 24.04 base image ships Python 3.12, but the project pins
# Python 3.11 (Pipfile), so we add it from the deadsnakes PPA. We also install
# Pipenv (system-wide, so it is on PATH for every shell) and a local PostgreSQL
# server used to exercise the pipeline end-to-end without a remote Neon DB.
#
# Safe to re-run: every step is guarded and apt installs are idempotent.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v python3.11 >/dev/null 2>&1; then
  echo "[install] Installing Python 3.11 from deadsnakes..."
  sudo apt-get update
  sudo apt-get install -y --no-install-recommends software-properties-common
  sudo add-apt-repository -y ppa:deadsnakes/ppa
  sudo apt-get update
  sudo apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv python3.11-dev build-essential
fi

if ! command -v psql >/dev/null 2>&1; then
  echo "[install] Installing PostgreSQL..."
  sudo apt-get update
  sudo apt-get install -y --no-install-recommends postgresql postgresql-contrib
fi

if ! command -v pipenv >/dev/null 2>&1; then
  echo "[install] Installing Pipenv (system-wide)..."
  sudo pip install --break-system-packages --no-cache-dir pipenv
fi

echo "[install] Installing Python dependencies with Pipenv (Python 3.11)..."
cd "$REPO_DIR"
export PIPENV_VENV_IN_PROJECT=1
pipenv --python 3.11 install --dev

echo "[install] Done."
