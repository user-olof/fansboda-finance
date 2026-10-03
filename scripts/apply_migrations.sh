#!/usr/bin/env bash
# Apply schema for Neon (dev-backfill CI and manual upgrades).
#
# Country-partitioned DBs before step 14: schema.sql + steps 11–19 (idempotent).
# DBs past step 14 (us_metrics has no raw_50; includes fresh schema.sql DBs):
#   schema.sql + steps 15–19 only — steps 11–13 copy raw_* columns step 14 dropped.
# Legacy single-set DBs: run pre-split migrations, then steps 11–19.
#
# Skips destructive one-time migrations unsafe to re-run:
#   - migrate_one_row_per_ticker.sql
#   - migrate_add_tickers_table.sql
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

run_sql() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    echo "Missing SQL file: $path" >&2
    exit 1
  fi
  echo "Applying $(basename "$path")..."
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$path"
}

# Country baseline (CREATE IF NOT EXISTS) — safe on every run.
run_sql "$REPO_DIR/schema.sql"

has_legacy="$(
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -tAc \
    "SELECT CASE WHEN to_regclass('public.metrics') IS NOT NULL
                  OR to_regclass('public.tickers') IS NOT NULL
             THEN 'yes' ELSE 'no' END"
)"

LEGACY_MIGRATIONS=(
  migrate_add_current_price.sql
  migrate_metrics_history.sql
  migrate_add_trading_date_index.sql
  migrate_add_tickers_updated_at.sql
  migrate_move_metadata_to_tickers.sql
  migrate_rename_name_to_company.sql
  migrate_add_raw_ratios_and_market.sql
  migrate_tickers_market_and_market_metrics.sql
)

has_raw_ratios="$(
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -tAc \
    "SELECT CASE WHEN EXISTS (
               SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public'
                 AND table_name = 'us_metrics'
                 AND column_name = 'raw_50'
             )
             THEN 'yes' ELSE 'no' END"
)"

if [[ "$has_legacy" == "no" && "$has_raw_ratios" == "no" ]]; then
  echo "Schema already past step 14 — skipping steps 11–14."
  run_sql "$REPO_DIR/migrate_week_buckets.sql"
  run_sql "$REPO_DIR/migrate_add_business_summary.sql"
  run_sql "$REPO_DIR/migrate_add_by_sector_tables.sql"
  run_sql "$REPO_DIR/migrate_add_indices_table.sql"
  run_sql "$REPO_DIR/migrate_indices_levels.sql"
  echo "All migrations applied (us_* / swe_* / uk_*)."
  exit 0
fi

if [[ "$has_legacy" == "yes" ]]; then
  echo "Legacy tickers/metrics detected — applying pre-split migrations..."
  for migration in "${LEGACY_MIGRATIONS[@]}"; do
    run_sql "$REPO_DIR/$migration"
  done
else
  echo "No legacy tickers/metrics — skipping pre-split migrations."
fi

# Step 11: ensure us_*/swe_* exist; copy from legacy when present; drop legacy.
run_sql "$REPO_DIR/migrate_split_us_swe_tables.sql"

# Step 12: exchange_name on us_*/swe_* (and uk_* if already present; step 13 creates UK).
run_sql "$REPO_DIR/migrate_add_exchange_name.sql"

# Step 13: UK table set (uk_tickers / uk_metrics / uk_market_metrics); move .L / uk_market from us_*.
run_sql "$REPO_DIR/migrate_add_uk_tables.sql"

# Step 14: momentum / z_score (drop raw_* columns).
run_sql "$REPO_DIR/migrate_momentum_zscore.sql"

# Step 15: one metrics row per ticker per calendar week (week_start); re-key market_metrics.
run_sql "$REPO_DIR/migrate_week_buckets.sql"

# Step 16: business_summary on *_tickers.
run_sql "$REPO_DIR/migrate_add_business_summary.sql"

# Step 17: *_by_sector weekly sector trend tables.
run_sql "$REPO_DIR/migrate_add_by_sector_tables.sql"

# Step 18: indices (US-IDX / SWE-IDX / UK-IDX).
run_sql "$REPO_DIR/migrate_add_indices_table.sql"

# Step 19: indices v2 (price / SMA levels + momentum by trading_date).
run_sql "$REPO_DIR/migrate_indices_levels.sql"

echo "All migrations applied (us_* / swe_* / uk_*)."
