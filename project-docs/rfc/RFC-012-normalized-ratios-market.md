# RFC-012: Normalized SMA Ratios & Market Aggregates

| Field | Value |
|-------|-------|
| **Priority** | P1 |
| **Status** | Implemented |
| **Depends on** | RFC-001, RFC-003, RFC-005 |
| **PRD** | §6 |
| **Feature** | [Market aggregates](../FEATURES.md#market-aggregates) |

## Summary

Extend the weekly pipeline and backfill to store scale-free SMA ratios on each metrics row (`raw_50`, `raw_200`) and cross-sectional statistics in **`us_market_metrics` / `swe_market_metrics`** — one row per `(market, trading_date)` within each country set. Listing `market` comes from `us_tickers.market` / `swe_tickers.market` (yfinance bucket, e.g. `us_market`, `se_market`; RFC-002, RFC-010).

Supports unbiased heatmap coloring — ranking tickers relative to peers in the same country set on each date rather than using raw SMA-distance signals.

## Requirements (PRD §6)

### Per-ticker ratios (`us_metrics` / `swe_metrics`)

| Column | Formula | Notes |
|--------|---------|-------|
| `raw_50` | `sma_50 / current_price` | `NULL` when either operand is `NULL` or `current_price` is zero |
| `raw_200` | `sma_200 / current_price` | Same guard as `raw_50` |

Computed at insert time in `fetch_sma.py` and `backfill_sma.py` alongside existing SMA fields.

### Cross-sectional aggregates (`us_market_metrics` / `swe_market_metrics`)

One row per listing-`market` bucket and `trading_date` present in the run (routed to the matching country aggregate table):

| Column | Formula |
|--------|---------|
| `market` | Listing market bucket from the matching `*_tickers.market` |
| `trading_date` | Snapshot date |
| `updated_at` | When the row was written |
| `raw_mean_50` | Mean of `raw_50` across tickers in that market bucket with non-null values on that date |
| `raw_mean_200` | Mean of `raw_200` across tickers in that market bucket with non-null values on that date |
| `raw_std_50` | Population std dev of `raw_50` in the bucket on that date |
| `raw_std_200` | Population std dev of `raw_200` in the bucket on that date |

Primary key on `(market, trading_date)`. Upsert on conflict (replace stats when the weekly job re-processes a date for that market).

`us_market` → `us_market_metrics`; `se_market` → `swe_market_metrics` (`db.country.country_set_for`).

### Downstream use (out of scope for this RFC)

Consumers may derive z-scores, e.g. `(raw_50 - raw_mean_50) / raw_std_50`, or percentile ranks within sector for heatmap cells. No UI or API in this repo.

## Implementation

### Schema

| Artifact | Role |
|----------|------|
| `schema.sql` | `raw_50`, `raw_200` on `us_metrics` / `swe_metrics`; `us_market_metrics` / `swe_market_metrics` |
| `migrate_add_raw_ratios_and_market.sql` | Step 9 — ratios + legacy watchlist-wide `market` |
| `migrate_tickers_market_and_market_metrics.sql` | Step 10 — `tickers.market`, `market_metrics` ([MIGRATIONS.md](../MIGRATIONS.md)) |
| `migrate_split_us_swe_tables.sql` | Step 11 — country partition — **done** |
| `scripts/verify_schema.sql` | Assert columns, country market metrics tables, retention indexes |
| `tests/test_schema.py` | CI validation |

### Domain & DB

| File | Role |
|------|------|
| `models.py` | `MetricRow.raw_50`, `MetricRow.raw_200`; `MarketRow.market` |
| `db/country.py` | Route upserts to US vs SWE aggregate tables |
| `db/metrics.py` | `insert_metrics`, `load_raw_ratios_by_market_for_date`, `load_distinct_trading_dates` |
| `db/market.py` | `upsert_market_stats`, `purge_stale_market` → `us_market_metrics` / `swe_market_metrics` |

### Pure logic

| Function | Module | Purpose |
|----------|--------|---------|
| `compute_raw_ratios(sma_50, sma_200, current_price)` | `fetch_sma.py` | Return `(raw_50, raw_200)` with divide-by-zero guards |
| `aggregate_market_stats(...)` | `fetch_sma.py` | Population mean/std for one `(market, trading_date)` group |
| `upsert_market_for_trading_dates(...)` | `fetch_sma.py` | Load ratios from DB per listing market; upsert country `*_market_metrics` |

### Job integration

**`fetch_sma.py` `main()`** — after `insert_metrics`:

1. For each processed `trading_date`, load `raw_50` / `raw_200` from `us_metrics` / `swe_metrics` joined to the matching tickers table, grouped by listing `market`.
2. Compute mean/std per market bucket → `upsert_market_stats` into `us_market_metrics` / `swe_market_metrics`.

**`backfill_sma.py`** — compute `raw_50` / `raw_200` on each generated row; after all batches, upsert `*_market_metrics` for every `trading_date` in the run.

**`backfill_market.py`** — one-off manual script to recompute all `us_market_metrics` / `swe_market_metrics` rows from distinct `*_metrics.trading_date` values.

### Retention (RFC-004)

Purge `us_market_metrics` / `swe_market_metrics` rows where `trading_date` is older than `metrics_retention_days`, in the same `fetch_sma.py` run as `purge_stale_metrics`.

## Acceptance criteria

- [x] `raw_50` and `raw_200` columns in schema and migrations (RFC-001)
- [x] Aggregate tables with PK on `(market, trading_date)` — `us_market_metrics` / `swe_market_metrics`
- [x] `MetricRow` includes `raw_50`, `raw_200`; `insert_metrics` persists them into country metrics tables
- [x] `MarketRow.market`; `db/market.py` upsert and purge helpers target country aggregate tables
- [x] `fetch_sma.py` computes ratios on every new metrics row
- [x] `fetch_sma.py` upserts market aggregates per processed date and listing market
- [x] `backfill_sma.py` populates `raw_50` and `raw_200` on backfilled rows
- [x] `backfill_sma.py` / `backfill_market.py` upsert country market aggregate history
- [x] Retention purge deletes stale aggregate rows (RFC-004)
- [x] Listing `market` populated by seed/refresh (RFC-002, RFC-010)
- [x] Unit tests for ratio math, aggregation, market upsert (US + SWE), and backfill integration

## Resolved decisions

- **Backfill aggregate history:** `backfill_sma.py` upserts per run; `backfill_market.py` recomputes all dates from metrics.
- **Std dev:** population std dev (`statistics.pstdev`) within each listing-`market` bucket.
- **Per-sector market stats:** defer to consumer queries joining `*_tickers.sector` — not separate tables in v1.

## Open questions

- None.
