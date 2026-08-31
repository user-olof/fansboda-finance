# RFC-001: Data Model

| Field | Value |
|-------|-------|
| **Priority** | P0 |
| **Status** | Implemented |
| **Depends on** | — |
| **PRD** | §6 |
| **Feature** | [Core data features](../FEATURES.md#core-data-features) |

## Summary

Postgres schema for the watchlist (`tickers`), SMA history (`metrics`), and cross-sectional aggregates (`market_metrics`). One `metrics` row per `(ticker, trading_date)`; one `market_metrics` row per (`trading_date`, listing `market`). Cascade delete from watchlist to metrics.

Listing **`market`** (yfinance bucket on `tickers`, e.g. `us_market`, `se_market`) groups rows in **`market_metrics`** — distinct from the aggregate table name.

## Requirements (PRD §6)

### `tickers`

| Column | Type | Notes |
|--------|------|-------|
| `symbol` | TEXT | Primary key |
| `company` | TEXT | Company name |
| `sector` | TEXT | Sector from yfinance (`sectorKey`) |
| `industry` | TEXT | Industry from yfinance (`industryKey`) |
| `market` | TEXT | Listing market from yfinance (e.g. `us_market`, `se_market`) |
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

### `market_metrics`

| Column | Type | Notes |
|--------|------|-------|
| `market` | TEXT | Listing market bucket; matches `tickers.market` |
| `trading_date` | DATE | Market session for this snapshot |
| `updated_at` | TIMESTAMPTZ | When the row was written |
| `raw_mean_50` | NUMERIC(18,6) | Mean of `raw_50` for tickers in this `market` on this date |
| `raw_mean_200` | NUMERIC(18,6) | Mean of `raw_200` for tickers in this `market` on this date |
| `raw_std_50` | NUMERIC(18,6) | Std dev of `raw_50` in this `market` on this date |
| `raw_std_200` | NUMERIC(18,6) | Std dev of `raw_200` in this `market` on this date |

- Primary key on `(market, trading_date)`.
- Aggregates `metrics` rows whose tickers share the same `tickers.market` on that date.
- Used for cross-sectional normalization within a listing market (heatmap z-scores / ranks). Populated by RFC-012; purged by RFC-004.

## Implementation

### Current state

| Artifact | Status |
|----------|--------|
| `schema.sql` | `tickers`, `metrics`, legacy `market` table — **PRD §6 layout pending** |
| `migrate_*.sql` | Incremental upgrades; step 10 planned for `tickers.market` + `market_metrics` |
| `migrate_add_raw_ratios_and_market.sql` | Adds `raw_50`, `raw_200`, legacy watchlist-wide `market` table — **done** |
| `migrate_tickers_market_and_market_metrics.sql` | **Planned** — see [MIGRATIONS.md](../MIGRATIONS.md) step 10 |
| `project-docs/MIGRATIONS.md` | Migration order and paths by starting state |
| `scripts/verify_schema.sql` | Post-migration verification |
| `tests/test_schema.py` | CI validation of DDL files |
| `tests/test_market.py` | `db/market.py` unit tests (legacy `market` table name) |

**Schema note:** PRD §6 places `sector`, `industry`, and listing `market` on `tickers` (RFC-002, RFC-010), `currency` on `metrics` (RFC-003), and per-listing-`market` aggregates in `market_metrics` (RFC-012).

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
| `migrate_add_raw_ratios_and_market.sql` | Add `raw_50`, `raw_200`, legacy `market` table |
| `migrate_tickers_market_and_market_metrics.sql` | Add `tickers.market`; rename to `market_metrics` — **planned** |
| `models.py` | `TickerEntry`, `MetricRow`, `MarketRow` |
| `db/metrics.py` | `insert_metrics` persists `raw_50`, `raw_200` |
| `db/market.py` | `upsert_market_stats`, `purge_stale_market` (legacy `market` table) |

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

SELECT symbol, company, sector, industry, market FROM tickers LIMIT 5;

SELECT ticker, trading_date, company, currency,
       sma_50, sma_200, current_price, raw_50, raw_200
FROM metrics ORDER BY trading_date DESC LIMIT 5;

SELECT market, trading_date, raw_mean_50, raw_mean_200, raw_std_50, raw_std_200
FROM market_metrics ORDER BY trading_date DESC, market LIMIT 5;
```

## Acceptance criteria

### Shipped

- [x] `tickers` and `metrics` tables exist with documented columns (except `tickers.market`)
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
- [x] Legacy `market` table with PK on `trading_date` only (step 9 migration)
- [x] `MarketRow` / `db/market.py` upsert and purge helpers (legacy table name)

### Pending (PRD §6)

- [ ] `tickers.market` column; seed/refresh resolve listing `market` from yfinance (RFC-002, RFC-010)
- [ ] Rename `market` → `market_metrics`; add `market` column; PK on `(market, trading_date)`
- [ ] `schema.sql`, `scripts/verify_schema.sql`, and step 10 migration aligned to PRD §6
- [ ] Pipeline upserts grouped by listing `market` (RFC-012)

## Open questions

- None.
