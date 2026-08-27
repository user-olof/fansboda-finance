# RFC-001: Data Model

| Field | Value |
|-------|-------|
| **Priority** | P0 |
| **Status** | Implemented |
| **Depends on** | — |
| **PRD** | §6 |
| **Feature** | [Core data features](../FEATURES.md#core-data-features) |

## Summary

Postgres schema for the watchlist (`tickers`), SMA history (`metrics`), and cross-sectional market aggregates (`market`). One `metrics` row per `(ticker, trading_date)`; one `market` row per `trading_date`. Cascade delete from watchlist to metrics.

## Requirements (PRD §6)

### `tickers`

| Column | Type | Notes |
|--------|------|-------|
| `symbol` | TEXT | Primary key |
| `company` | TEXT | Company name |
| `sector` | TEXT | Sector from yfinance (`sectorKey`) |
| `industry` | TEXT | Industry from yfinance (`industryKey`) |
| `updated_at` | TIMESTAMPTZ | When the row was written |

### `metrics`

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGSERIAL | Primary key |
| `ticker` | TEXT | FK → `tickers.symbol` `ON DELETE CASCADE` |
| `company` | TEXT | Copied from `tickers` at fetch time |
| `trading_date` | DATE | Market session for this snapshot |
| `updated_at` | TIMESTAMPTZ | When the row was written |
| `currency` | TEXT | Listing currency code from yfinance |
| `sma_50` | NUMERIC(18,6) | 50-day SMA |
| `sma_200` | NUMERIC(18,6) | 200-day SMA |
| `current_price` | NUMERIC(18,6) | Adjusted close on `trading_date` |
| `raw_50` | NUMERIC(18,6) | `sma_50 / current_price` |
| `raw_200` | NUMERIC(18,6) | `sma_200 / current_price` |

- Unique constraint on `(ticker, trading_date)`.
- Index on `metrics.trading_date` for retention purge.
- Deleting a `tickers` row cascades to all `metrics` rows.

### `market`

| Column | Type | Notes |
|--------|------|-------|
| `trading_date` | DATE | Primary key (one row per session) |
| `updated_at` | TIMESTAMPTZ | When the row was written |
| `raw_mean_50` | NUMERIC(18,6) | Mean of watchlist `raw_50` on this date |
| `raw_mean_200` | NUMERIC(18,6) | Mean of watchlist `raw_200` on this date |
| `raw_std_50` | NUMERIC(18,6) | Std dev of watchlist `raw_50` on this date |
| `raw_std_200` | NUMERIC(18,6) | Std dev of watchlist `raw_200` on this date |

Used for cross-sectional normalization (heatmap z-scores / ranks). Populated by RFC-012; purged by RFC-004.

## Implementation

### Current state

| Artifact | Status |
|----------|--------|
| `schema.sql` | `tickers`, `metrics`, `market` with full PRD §6 columns |
| `migrate_*.sql` | Incremental upgrades for legacy databases |
| `migrate_add_raw_ratios_and_market.sql` | Adds `raw_50`, `raw_200`, `market` table |
| `project-docs/MIGRATIONS.md` | Migration order and paths by starting state |
| `scripts/verify_schema.sql` | Post-migration verification |
| `tests/test_schema.py` | CI validation of DDL files |
| `tests/test_market.py` | `db/market.py` unit tests |

**Schema note:** PRD §6 places `sector` and `industry` on `tickers` (RFC-002, RFC-010) and `currency` on `metrics` (RFC-003). Ratio computation and market upsert from the weekly job are RFC-012.

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
| `migrate_move_metadata_to_tickers.sql` | Add `tickers.sector`, `tickers.industry`, `metrics.currency` |
| `migrate_rename_name_to_company.sql` | Rename `name` → `company` on `tickers` and `metrics` |
| `migrate_add_metrics_metadata.sql` | **Superseded** — see `migrate_move_metadata_to_tickers.sql` |
| `migrate_add_raw_ratios_and_market.sql` | Add `raw_50`, `raw_200`, `market` table |
| `models.py` | `TickerEntry`, `MetricRow`, `MarketRow` |
| `db/metrics.py` | `insert_metrics` persists `raw_50`, `raw_200` |
| `db/market.py` | `upsert_market_stats`, `purge_stale_market` |

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

SELECT symbol, company, sector, industry FROM tickers LIMIT 5;

SELECT ticker, trading_date, company, currency,
       sma_50, sma_200, current_price, raw_50, raw_200
FROM metrics ORDER BY trading_date DESC LIMIT 5;

SELECT trading_date, raw_mean_50, raw_mean_200, raw_std_50, raw_std_200
FROM market ORDER BY trading_date DESC LIMIT 5;
```

## Acceptance criteria

- [x] `tickers` and `metrics` tables exist with documented columns
- [x] `UNIQUE (ticker, trading_date)` via `metrics_ticker_trading_date_key`
- [x] FK cascade delete from `tickers` to `metrics`
- [x] `NUMERIC(18, 6)` on price and ratio columns
- [x] `idx_metrics_trading_date` for retention purge
- [x] Migration path in `MIGRATIONS.md`
- [x] `tests/test_schema.py` validates DDL in CI
- [x] `tickers.updated_at` column (PRD §6)
- [x] `tickers.sector`, `tickers.industry` columns (PRD §6)
- [x] `metrics.currency` column (PRD §6)
- [x] `tickers.company`, `metrics.company` columns (PRD §6)
- [x] `MetricRow` / `insert_metrics` include `currency` and `raw_50`, `raw_200`
- [x] `TickerEntry` / `upsert_tickers` include `sector`, `industry` (RFC-002)
- [x] `metrics.raw_50`, `metrics.raw_200` columns
- [x] `market` table with primary key on `trading_date`
- [x] `MarketRow` / `db/market.py` upsert and purge helpers
- [x] `schema.sql` and migrations aligned to full PRD §6 layout

## Open questions

- See RFC-012 for populating `raw_*` and `market` from the weekly job and backfill.
