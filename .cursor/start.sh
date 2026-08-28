#!/usr/bin/env bash
# Per-boot startup for the fansboda-finance Cloud Agent environment.
# Starts a local PostgreSQL server and provisions a dev database so the
# pipeline (seed_tickers.py / fetch_sma.py / backfill_sma.py) can run
# end-to-end. Idempotent: safe to run on every boot.
set -euo pipefail

DB_NAME="fansboda"
DB_USER="fansboda"
DB_PASS="fansboda"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[start] Ensuring PostgreSQL is running..."
sudo service postgresql start || sudo pg_ctlcluster 16 main start || true

# Wait for the server to accept connections.
for _ in $(seq 1 30); do
  if sudo -u postgres pg_isready -q; then break; fi
  sleep 1
done

echo "[start] Provisioning dev role and database (idempotent)..."
sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" \
  | grep -q 1 \
  || sudo -u postgres psql -c "CREATE ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASS}';"
sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" \
  | grep -q 1 \
  || sudo -u postgres psql -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"

echo "[start] Applying schema.sql (CREATE TABLE IF NOT EXISTS)..."
PGPASSWORD="${DB_PASS}" psql -h localhost -U "${DB_USER}" -d "${DB_NAME}" \
  -v ON_ERROR_STOP=1 -f "${REPO_DIR}/schema.sql" >/dev/null

# Provide a local dev .env only if the developer has not supplied their own.
# DevConfig loads .env without overriding real environment variables, so a
# DATABASE_URL secret (e.g. a Neon URL) still takes precedence when present.
if [ ! -f "${REPO_DIR}/.env" ]; then
  echo "[start] Writing local dev .env pointing at the local database..."
  cat > "${REPO_DIR}/.env" <<EOF
APP_ENV=dev
DATABASE_URL=postgresql://${DB_USER}:${DB_PASS}@localhost:5432/${DB_NAME}
EOF
fi

echo "[start] Ready. Local DATABASE_URL: postgresql://${DB_USER}:***@localhost:5432/${DB_NAME}"
