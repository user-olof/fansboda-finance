# RFC-001: Data Model

| Field | Value |
|-------|-------|
| **Priority** | P0 |
| **Status** | Implemented |
| **Depends on** | — |
| **Enables** | RFC-002, RFC-006, RFC-007, RFC-008 |
| **PRD** | §6 |
| **Feature** | [Core data features](../FEATURES.md#core-data-features) |

## Summary

Postgres schema for US, Swedish, and UK watchlists, SMA history, and cross-sectional aggregates. Data is partitioned by listing country into three parallel table sets (PRD §6):

| Set | Watchlist | SMA history | Cross-sectional aggregates |
|-----|-----------|-------------|----------------------------|
| US stocks | `us_tickers` | `us_metrics` | `us_market_metrics` |
| Swedish stocks | `swe_tickers` | `swe_metrics` | `swe_market_metrics` |
| UK stocks | `uk_tickers` | `uk_metrics` | `uk_market_metrics` |

**Country routing (seed / refresh / insert):**

| Country | Symbol cue | Listing `market` |
|---------|------------|------------------|
| Swedish | `.ST` | `se_market` |
| UK | `.L` | `uk_market` |
| US | default / other | `us_market` (and other non-SE/UK buckets) |

Listing **`market`** (yfinance bucket on `*_tickers`, e.g. `us_market`, `se_market`, `uk_market`) is also stored on `*_market_metrics`. Watchlist tables also store **`exchange_name`** from yfinance `fullExchangeName`.

**Legacy note:** Steps 1–10 in [MIGRATIONS.md](../MIGRATIONS.md) build the single-set tables `tickers` / `metrics` / `market_metrics`. Step 11 (`migrate_split_us_swe_tables.sql`) splits those into the `us_*` / `swe_*` sets. Steps 12–13 add `exchange_name` and the UK table set.

## Schema

### Watchlist tables (`us_tickers` / `swe_tickers` / `uk_tickers`)

| Column | Type | Notes |
|--------|------|-------|
| `symbol` | TEXT PK | Yahoo Finance symbol |
| `company` | TEXT | Display name |
| `sector` | TEXT | From yfinance `sectorKey` |
| `industry` | TEXT | From yfinance `industryKey` |
| `market` | TEXT | Listing market from yfinance (e.g. `us_market`, `se_market`, `uk_market`) |
| `exchange_name` | TEXT | Exchange display name from yfinance `fullExchangeName` |
| `updated_at` | TIMESTAMPTZ | Seed / refresh timestamp |

### Metrics tables (`us_metrics` / `swe_metrics` / `uk_metrics`)

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGSERIAL PK | |
| `ticker` | TEXT FK | → matching `*_tickers.symbol` ON DELETE CASCADE |
| `company` | TEXT | Copied from tickers at insert time |
| `trading_date` | DATE | Session date for the snapshot |
| `updated_at` | TIMESTAMPTZ | Insert time |
| `currency` | TEXT | From yfinance |
| `sma_50` / `sma_200` / `current_price` | NUMERIC(18,6) | |
| `raw_50` / `raw_200` | NUMERIC(18,6) | SMA / price ratios |

- One row per `(ticker, trading_date)` within each set (`*_metrics_ticker_trading_date_key`)
- Append-only: `ON CONFLICT (ticker, trading_date) DO NOTHING`
- Deleting a row from `us_tickers`, `swe_tickers`, or `uk_tickers` cascades to all of its rows in the matching metrics table.

### Market metrics tables (`us_market_metrics` / `swe_market_metrics` / `uk_market_metrics`)

| Column | Type | Notes |
|--------|------|-------|
| `market` | TEXT | Listing market bucket |
| `trading_date` | DATE | |
| `updated_at` | TIMESTAMPTZ | |
| `raw_mean_50` / `raw_mean_200` / `raw_std_50` / `raw_std_200` | NUMERIC(18,6) | Cross-sectional stats |
| PK | `(market, trading_date)` | |

## Implementation

### Current state

| Artifact | Status |
|----------|--------|
| `schema.sql` | `us_*` / `swe_*` / `uk_*` country sets including `exchange_name` |
| `migrate_*.sql` | Steps 1–10: legacy single-set upgrades; step 11 splits to US/SWE |
| `migrate_split_us_swe_tables.sql` | Step 11 — US/SWE country partition — **done** |
| `migrate_add_exchange_name.sql` | Step 12 — add `exchange_name` to `*_tickers` — **done** |
| `migrate_add_uk_tables.sql` | Step 13 — create `uk_*` table set — **done** |
| `project-docs/MIGRATIONS.md` | Migration order and paths by starting state |
| `scripts/verify_schema.sql` | Asserts US/SWE/UK sets and `exchange_name` |
| `tests/test_schema.py` | CI validation of DDL files |
| `db/country.py` | Routes rows to US / SWE / UK by `market` / `.ST` / `.L` |
| `db/tickers.py`, `db/metrics.py`, `db/market.py` | Target all three country-set tables |

**Schema note:** PRD §6 places `sector`, `industry`, listing `market`, and `exchange_name` on `*_tickers` (RFC-002, RFC-010), `currency` on `*_metrics` (RFC-003), and per-country-set aggregates in `*_market_metrics` (RFC-012).

### Files

| File | Purpose |
|------|---------|
| `schema.sql` | Initial schema for new Neon databases (must create `us_*` / `swe_*` / `uk_*` sets, including `exchange_name`) |
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
| `migrate_split_us_swe_tables.sql` | Split into `us_*` / `swe_*` sets (step 11 — **done**) |
| `migrate_add_exchange_name.sql` | Step 12 — add `exchange_name` to `*_tickers` |
| `migrate_add_uk_tables.sql` | Step 13 — create `uk_*` sets |
| `models.py` | `TickerEntry` (incl. `exchange_name`), `MetricRow`, `MarketRow` |
| `db/metrics.py` | `insert_metrics` persists `raw_50`, `raw_200` into country metrics |
| `db/market.py` | `upsert_market_stats`, `purge_stale_market` for all country sets |

### New database setup

```bash
psql "$DATABASE_URL" -f schema.sql
psql "$DATABASE_URL" -f scripts/verify_schema.sql
pipenv run python seed_tickers.py
```

Legacy upgrades: see [MIGRATIONS.md](../MIGRATIONS.md).

### Verification

```sql
SELECT symbol, company, sector, industry, market, exchange_name FROM us_tickers LIMIT 5;
SELECT symbol, company, sector, industry, market, exchange_name FROM swe_tickers LIMIT 5;
SELECT symbol, company, sector, industry, market, exchange_name FROM uk_tickers LIMIT 5;

SELECT ticker, trading_date, company, currency,
       sma_50, sma_200, current_price, raw_50, raw_200
FROM us_metrics ORDER BY trading_date DESC LIMIT 5;

SELECT ticker, trading_date, company, currency,
       sma_50, sma_200, current_price, raw_50, raw_200
FROM swe_metrics ORDER BY trading_date DESC LIMIT 5;

SELECT ticker, trading_date, company, currency,
       sma_50, sma_200, current_price, raw_50, raw_200
FROM uk_metrics ORDER BY trading_date DESC LIMIT 5;

SELECT market, trading_date, raw_mean_50, raw_mean_200, raw_std_50, raw_std_200
FROM us_market_metrics ORDER BY trading_date DESC, market LIMIT 5;

SELECT market, trading_date, raw_mean_50, raw_mean_200, raw_std_50, raw_std_200
FROM swe_market_metrics ORDER BY trading_date DESC, market LIMIT 5;

SELECT market, trading_date, raw_mean_50, raw_mean_200, raw_std_50, raw_std_200
FROM uk_market_metrics ORDER BY trading_date DESC, market LIMIT 5;
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

### Shipped (PRD §6 US / Swedish / UK sets)

- [x] `schema.sql` creates `us_*`, `swe_*`, and `uk_*` table sets
- [x] Step 11 migration (`migrate_split_us_swe_tables.sql`) moves legacy rows and drops legacy tables
- [x] Step 12 migration (`migrate_add_exchange_name.sql`) adds `exchange_name` on `*_tickers`
- [x] Step 13 migration (`migrate_add_uk_tables.sql`) creates UK set and moves `.L` / `uk_market` rows from `us_*`
- [x] `scripts/verify_schema.sql` asserts all three country sets and `exchange_name`
- [x] DB access layer targets `us_*`, `swe_*`, and `uk_*` tables (`db/country.py`, `db/tickers.py`, `db/metrics.py`, `db/market.py`)
- [x] `TickerEntry.exchange_name` and upsert rows include `exchange_name`

## Open questions

- None.
