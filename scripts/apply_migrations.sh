#!/usr/bin/env bash
# Apply idempotent schema migrations before dev-backfill CI (MIGRATIONS.md).
#
# Skips legacy one-time migrations that are unsafe to re-run on a live dev branch:
#   - migrate_one_row_per_ticker.sql (destructive row collapse)
#   - migrate_add_tickers_table.sql (bootstrap for DBs without tickers/FK)
#
# Safe to re-run on every workflow: each file uses IF NOT EXISTS / conditional DDL.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATABASE_URL="${DATABASE_URL:-}"

if [[ -z "$DATABASE_URL" ]]; then
  echo "DATABASE_URL is not set" >&2
  exit 1
fi

if ! command -v psql >/dev/null 2>&1; then
  echo "psql is required but not installed" >&2
  exit 1
fi

MIGRATIONS=(
  migrate_add_current_price.sql
  migrate_metrics_history.sql
  migrate_add_trading_date_index.sql
  migrate_add_tickers_updated_at.sql
  migrate_move_metadata_to_tickers.sql
  migrate_rename_name_to_company.sql
  migrate_add_raw_ratios_and_market.sql
)

for migration in "${MIGRATIONS[@]}"; do
  path="$REPO_DIR/$migration"
  if [[ ! -f "$path" ]]; then
    echo "Missing migration file: $migration" >&2
    exit 1
  fi
  echo "Applying $migration..."
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$path"
done

echo "All migrations applied."
