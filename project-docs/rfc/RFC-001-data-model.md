# RFC-001: Data Model

| Field | Value |
|-------|-------|
| **Priority** | P0 |
| **Status** | Implemented |
| **Depends on** | — |
| **PRD** | §6 |
| **Feature** | [Core data features](../FEATURES.md#core-data-features) |

## Summary

Postgres schema for the watchlist (`tickers`) and SMA history (`metrics`). One row per `(ticker, trading_date)` with cascade delete from watchlist to metrics.

## Requirements (PRD §6)

### `tickers`

| Column | Type | Notes |
|--------|------|-------|
| `symbol` | TEXT | Primary key |
| `name` | TEXT | Company name |
| `sector` | TEXT | Sector from yfinance (`sectorKey`) |
| `industry` | TEXT | Industry from yfinance (`industryKey`) |
| `updated_at` | TIMESTAMPTZ | When the row was written |

### `metrics`

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGSERIAL | Primary key |
| `ticker` | TEXT | FK → `tickers.symbol` `ON DELETE CASCADE` |
| `name` | TEXT | Copied from `tickers` at fetch time |
| `trading_date` | DATE | Market session for this snapshot |
| `updated_at` | TIMESTAMPTZ | When the row was written |
| `currency` | TEXT | Listing currency code from yfinance |
| `sma_50` | NUMERIC(18,6) | 50-day SMA |
| `sma_200` | NUMERIC(18,6) | 200-day SMA |
| `current_price` | NUMERIC(18,6) | Adjusted close on `trading_date` |

- Unique constraint on `(ticker, trading_date)`.
- Index on `metrics.trading_date` for retention purge.
- Deleting a `tickers` row cascades to all `metrics` rows.

## Implementation

### Current state

| Artifact | Status |
|----------|--------|
| `schema.sql` | Defines `tickers` and `metrics` with FK, unique constraint, index |
| `migrate_*.sql` | Incremental upgrades for legacy databases |
| `project-docs/MIGRATIONS.md` | Migration order and paths by starting state |
| `scripts/verify_schema.sql` | Post-migration verification |
| `tests/test_schema.py` | CI validation of DDL files |

**Schema note:** PRD §6 places `sector` and `industry` on `tickers` (RFC-002, RFC-010) and `currency` on `metrics` (RFC-003). Legacy DBs apply `migrate_move_metadata_to_tickers.sql`.

### Files

| File | Purpose |
|------|---------|
| `schema.sql` | Initial schema for new Neon databases |
| `migrate_add_current_price.sql` | Add `current_price` column |
| `migrate_one_row_per_ticker.sql` | Legacy collapse (superseded) |
| `migrate_add_tickers_table.sql` | Add `tickers` table and FK |
| `migrate_metrics_history.sql` | Restore `(ticker, trading_date)` uniqueness |
| `migrate_add_trading_date_index.sql` | Add retention index |
| `migrate_add_tickers_updated_at.sql` | Add `tickers.updated_at` for existing DBs |
| `migrate_move_metadata_to_tickers.sql` | Add `tickers.sector`, `tickers.industry`, `metrics.currency`; drop misplaced `metrics.sector` / `metrics.industry` |
| `migrate_add_metrics_metadata.sql` | **Superseded** — see `migrate_move_metadata_to_tickers.sql` |
| `models.py` | `TickerEntry` (`sector`, `industry`), `MetricRow` (`currency`) |

### New database setup

```bash
psql "$DATABASE_URL" -f schema.sql
psql "$DATABASE_URL" -f scripts/verify_schema.sql
pipenv run python seed_tickers.py
```

Legacy upgrades: see [MIGRATIONS.md](../MIGRATIONS.md).

### Verification

```sql
SELECT conname FROM pg_constraint
WHERE conrelid = 'metrics'::regclass AND contype = 'u';

SELECT symbol, name, sector, industry FROM tickers LIMIT 5;

SELECT ticker, trading_date, name, currency, sma_50, sma_200, current_price
FROM metrics ORDER BY trading_date DESC LIMIT 5;
```

## Acceptance criteria

- [x] `tickers` and `metrics` tables exist with documented columns
- [x] `UNIQUE (ticker, trading_date)` via `metrics_ticker_trading_date_key`
- [x] FK cascade delete from `tickers` to `metrics`
- [x] `NUMERIC(18, 6)` on price columns
- [x] `idx_metrics_trading_date` for retention purge
- [x] Migration path in `MIGRATIONS.md`
- [x] `tests/test_schema.py` validates DDL in CI
- [x] `tickers.updated_at` column (PRD §6)
- [x] `tickers.sector`, `tickers.industry` columns (PRD §6)
- [x] `metrics.currency` column (PRD §6)
- [x] `schema.sql` and migrations aligned to PRD §6 column layout
- [x] `TickerEntry` / `upsert_tickers` include `sector`, `industry` (RFC-002)
- [x] `MetricRow` / `insert_metrics` include `currency` only on metrics (RFC-003)

## Open questions

- Should `backfill_sma.py` populate `metrics.currency`, or leave it `NULL` until the weekly fetch runs?
