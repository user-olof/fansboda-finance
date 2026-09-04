# RFC-001: Data Model

| Field | Value |
|-------|-------|
| **Priority** | P0 |
| **Status** | Implemented |
| **Depends on** | — |
| **PRD** | §6 |
| **Feature** | [Core data features](../FEATURES.md#core-data-features) |

## Summary

Postgres schema for US and Swedish watchlists, SMA history, and cross-sectional aggregates. Data is partitioned by listing country into two parallel table sets (PRD §6):

| Set | Watchlist | SMA history | Cross-sectional aggregates |
|-----|-----------|-------------|----------------------------|
| US stocks | `us_tickers` | `us_metrics` | `us_market_metrics` |
| Swedish stocks | `swe_tickers` | `swe_metrics` | `swe_market_metrics` |

One metrics row per `(ticker, trading_date)` within each set; one market-metrics row per (`trading_date`, listing `market`) within each set. Cascade delete from each watchlist table to its matching metrics table.

Listing **`market`** (yfinance bucket on `*_tickers`, e.g. `us_market`, `se_market`) is also stored on `*_market_metrics`.

**Legacy note:** Steps 1–10 in [MIGRATIONS.md](../MIGRATIONS.md) build the single-set tables `tickers` / `metrics` / `market_metrics`. Step 11 (`migrate_split_us_swe_tables.sql`) splits those into the `us_*` / `swe_*` sets below.

## Requirements (PRD §6)

### Watchlist tables (`us_tickers` / `swe_tickers`)

| Column | Type | Notes |
|--------|------|-------|
| `symbol` | TEXT | Primary key |
| `company` | TEXT | Company name |
| `sector` | TEXT | Sector from yfinance (`sectorKey`) |
| `industry` | TEXT | Industry from yfinance (`industryKey`) |
| `market` | TEXT | Listing market from yfinance (e.g. `us_market`, `se_market`) |
| `updated_at` | TIMESTAMPTZ | When the row was written |

### Metrics tables (`us_metrics` / `swe_metrics`)

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGSERIAL | Primary key |
| `ticker` | TEXT | FK → matching `*_tickers.symbol` `ON DELETE CASCADE` |
| `company` | TEXT | Copied from the matching tickers table at fetch time |
| `trading_date` | DATE | Market session for this snapshot |
| `updated_at` | TIMESTAMPTZ | When the row was written |
| `currency` | TEXT | Listing currency code from yfinance |
| `sma_50` | NUMERIC(18,6) | 50-day SMA |
| `sma_200` | NUMERIC(18,6) | 200-day SMA |
| `current_price` | NUMERIC(18,6) | Adjusted close on `trading_date` |
| `raw_50` | NUMERIC(18,6) | `sma_50 / current_price` |
| `raw_200` | NUMERIC(18,6) | `sma_200 / current_price` |

- Unique constraint on `(ticker, trading_date)`.
- Index on `*_metrics.trading_date` for retention purge.
- Deleting a row from `us_tickers` or `swe_tickers` cascades to all of its rows in the matching metrics table.

### Market metrics tables (`us_market_metrics` / `swe_market_metrics`)

| Column | Type | Notes |
|--------|------|-------|
| `market` | TEXT | Listing market bucket; matches the set's tickers `market` values |
| `trading_date` | DATE | Market session for this snapshot |
| `updated_at` | TIMESTAMPTZ | When the row was written |
| `raw_mean_50` | NUMERIC(18,6) | Mean of `raw_50` for tickers in this set on this date |
| `raw_mean_200` | NUMERIC(18,6) | Mean of `raw_200` for tickers in this set on this date |
| `raw_std_50` | NUMERIC(18,6) | Std dev of `raw_50` in this set on this date |
| `raw_std_200` | NUMERIC(18,6) | Std dev of `raw_200` in this set on this date |

- Primary key on `(market, trading_date)`.
- Aggregates matching `*_metrics` rows for that country set on that date.
- Used for cross-sectional normalization within a country set (heatmap z-scores / ranks). Populated by RFC-012; purged by RFC-004.

## Implementation

### Current state

| Artifact | Status |
|----------|--------|
| `schema.sql` | `us_*` / `swe_*` country sets (PRD §6) |
| `migrate_*.sql` | Steps 1–10: legacy single-set upgrades; step 11 splits to country sets |
| `migrate_split_us_swe_tables.sql` | Step 11 — country partition — **done** |
| `project-docs/MIGRATIONS.md` | Migration order and paths by starting state |
| `scripts/verify_schema.sql` | Asserts both country sets; legacy tables absent |
| `tests/test_schema.py` | CI validation of DDL files |
| `db/country.py` | Routes rows to US vs SWE by `market` / `.ST` suffix |
| `db/tickers.py`, `db/metrics.py`, `db/market.py` | Target country-set tables |

**Schema note:** PRD §6 places `sector`, `industry`, and listing `market` on `*_tickers` (RFC-002, RFC-010), `currency` on `*_metrics` (RFC-003), and per-country-set aggregates in `*_market_metrics` (RFC-012).

### Files

| File | Purpose |
|------|---------|
| `schema.sql` | Initial schema for new Neon databases (must create `us_*` / `swe_*` sets) |
| `migrate_add_current_price.sql` | Add `current_price` column (legacy `metrics`) |
| `migrate_one_row_per_ticker.sql` | Legacy collapse (superseded) |
| `migrate_add_tickers_table.sql` | Add legacy `tickers` table and FK |
| `migrate_metrics_history.sql` | Restore `(ticker, trading_date)` uniqueness on legacy `metrics` |
| `migrate_add_trading_date_index.sql` | Add retention index |
| `migrate_add_tickers_updated_at.sql` | Add `tickers.updated_at` for existing DBs |
| `migrate_move_metadata_to_tickers.sql` | Add `tickers.sector`, `tickers.industry`, `metrics.currency` |
| `migrate_rename_name_to_company.sql` | Rename `name` → `company` on legacy `tickers` and `metrics` |
| `migrate_add_metrics_metadata.sql` | **Superseded** — see `migrate_move_metadata_to_tickers.sql` |
| `migrate_add_raw_ratios_and_market.sql` | Add `raw_50`, `raw_200`, legacy `market` table |
| `migrate_tickers_market_and_market_metrics.sql` | Add `tickers.market`; rename to `market_metrics` |
| `migrate_split_us_swe_tables.sql` | Split into `us_*` / `swe_*` sets |
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
SELECT symbol, company, sector, industry, market FROM us_tickers LIMIT 5;
SELECT symbol, company, sector, industry, market FROM swe_tickers LIMIT 5;

SELECT ticker, trading_date, company, currency,
       sma_50, sma_200, current_price, raw_50, raw_200
FROM us_metrics ORDER BY trading_date DESC LIMIT 5;

SELECT ticker, trading_date, company, currency,
       sma_50, sma_200, current_price, raw_50, raw_200
FROM swe_metrics ORDER BY trading_date DESC LIMIT 5;

SELECT market, trading_date, raw_mean_50, raw_mean_200, raw_std_50, raw_std_200
FROM us_market_metrics ORDER BY trading_date DESC, market LIMIT 5;

SELECT market, trading_date, raw_mean_50, raw_mean_200, raw_std_50, raw_std_200
FROM swe_market_metrics ORDER BY trading_date DESC, market LIMIT 5;
```

## Acceptance criteria

### Shipped (legacy single-set)

- [x] Legacy `tickers` and `metrics` tables with documented columns
- [x] `UNIQUE (ticker, trading_date)` via `metrics_ticker_trading_date_key`
- [x] FK cascade delete from `tickers` to `metrics`
- [x] `NUMERIC(18, 6)` on price and ratio columns
- [x] `idx_metrics_trading_date` for retention purge
- [x] Migration path in `MIGRATIONS.md` (steps 1–10)
- [x] `tests/test_schema.py` validates DDL in CI
- [x] `tickers.updated_at`, `sector`, `industry`, `market`; `metrics.currency`, `company`
- [x] `MetricRow` / `insert_metrics` include `currency` and `raw_50`, `raw_200`
- [x] `TickerEntry` / `upsert_tickers` include `sector`, `industry`, `market`
- [x] Legacy `market` → `market_metrics` with PK on `(market, trading_date)` (step 10)
- [x] `MarketRow` / `db/market.py` upsert and purge helpers

### Pending (PRD §6 country sets)

- [x] `schema.sql` creates `us_tickers`, `us_metrics`, `us_market_metrics`, `swe_tickers`, `swe_metrics`, `swe_market_metrics`
- [x] Step 11 migration (`migrate_split_us_swe_tables.sql`) moves legacy rows and drops legacy tables
- [x] `scripts/verify_schema.sql` asserts both country sets
- [x] DB access layer targets `us_*` and `swe_*` tables (`db/country.py`, `db/tickers.py`, `db/metrics.py`, `db/market.py`)

## Open questions

- None.
