# Database migrations

Schema specification: [RFC-001](./rfc/RFC-001-data-model.md).

## New database

Run `schema.sql` once in the Neon SQL editor or via `psql`:

```bash
psql "$DATABASE_URL" -f schema.sql
```

Then seed the watchlist (`pipenv run python seed_tickers.py`) before running fetch or backfill jobs.

## Existing database

Apply only the migrations you have not yet run, **in order**. Each file is idempotent where possible but intended as a one-time step.

| Order | File | When to run |
|------:|------|-------------|
| 1 | `migrate_add_current_price.sql` | `metrics` lacks `current_price` column |
| 2 | `migrate_one_row_per_ticker.sql` | Legacy only — collapsed history to one row per ticker (superseded by step 4) |
| 3 | `migrate_add_tickers_table.sql` | `tickers` table or FK from `metrics` → `tickers` missing |
| 4 | `migrate_metrics_history.sql` | Restore one row per `(ticker, trading_date)`; drops `metrics_ticker_key` if present |
| 5 | `migrate_add_trading_date_index.sql` | Add `idx_metrics_trading_date` if missing (also included in step 4) |
| 6 | `migrate_add_tickers_updated_at.sql` | Add `tickers.updated_at` if missing |
| 7 | `migrate_move_metadata_to_tickers.sql` | Add `tickers.sector`, `tickers.industry`, `metrics.currency`; drop misplaced `metrics.sector` / `metrics.industry` if present |
| 8 | `migrate_rename_name_to_company.sql` | Rename `name` → `company` on `tickers` and `metrics` (PRD §6) |

### Path by starting state

**Fresh install (no tables):** `schema.sql` only.

**Has `metrics` with `(ticker, trading_date)` unique (never ran step 2):**

1. `migrate_add_current_price.sql` (if needed)
2. `migrate_add_tickers_table.sql` (if needed)

**Has `metrics` with one row per ticker (`metrics_ticker_key`):**

1. `migrate_add_tickers_table.sql` (if `tickers` / FK missing)
2. `migrate_metrics_history.sql`

**After history migration, before backfill:**

Run `migrate_metrics_history.sql`, then `pipenv run python backfill_sma.py`.

## Verify schema

```bash
psql "$DATABASE_URL" -f scripts/verify_schema.sql
```

Or run the queries in the Neon SQL editor.

## Rollback

Migrations are forward-only. Take a Neon branch snapshot before applying destructive steps (especially `migrate_one_row_per_ticker.sql`, which deletes duplicate rows).
