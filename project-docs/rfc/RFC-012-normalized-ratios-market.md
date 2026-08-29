# RFC-012: Normalized SMA Ratios & Market Aggregates

| Field | Value |
|-------|-------|
| **Priority** | P1 |
| **Status** | Implemented |
| **Depends on** | RFC-001, RFC-003, RFC-005 |
| **PRD** | §6 |
| **Feature** | [Market aggregates](../FEATURES.md#market-aggregates) |

## Summary

Extend the weekly pipeline and backfill to store scale-free SMA ratios on each `metrics` row (`raw_50`, `raw_200`) and cross-sectional statistics in **`market_metrics`** — one row per (`trading_date`, listing `market`). Listing `market` comes from `tickers.market` (yfinance bucket, e.g. `us_market`, `se_market`; RFC-002, RFC-010).

Supports unbiased heatmap coloring — ranking tickers relative to peers in the same listing market on each date rather than using raw SMA-distance signals.

## Requirements (PRD §6)

### Per-ticker ratios (`metrics`)

| Column | Formula | Notes |
|--------|---------|-------|
| `raw_50` | `sma_50 / current_price` | `NULL` when either operand is `NULL` or `current_price` is zero |
| `raw_200` | `sma_200 / current_price` | Same guard as `raw_50` |

Computed at insert time in `fetch_sma.py` and `backfill_sma.py` alongside existing SMA fields.

### Cross-sectional aggregates (`market_metrics`)

One row per (`trading_date`, listing `market`) present in the run:

| Column | Formula |
|--------|---------|
| `market` | Listing market bucket; matches `tickers.market` |
| `trading_date` | Snapshot date |
| `updated_at` | When the row was written |
| `raw_mean_50` | Mean of `raw_50` across tickers with the same `tickers.market` and non-null values on that date |
| `raw_mean_200` | Mean of `raw_200` across tickers with the same `tickers.market` and non-null values on that date |
| `raw_std_50` | Population std dev of `raw_50` in that `market` on that date |
| `raw_std_200` | Population std dev of `raw_200` in that `market` on that date |

Primary key on `(market, trading_date)`. Upsert on conflict (replace stats when the weekly job re-processes a date for that market).

### Downstream use (out of scope for this RFC)

Consumers may derive z-scores, e.g. `(raw_50 - raw_mean_50) / raw_std_50`, or percentile ranks within sector for heatmap cells. No UI or API in this repo.

## Implementation

### Schema

| Artifact | Role |
|----------|------|
| `schema.sql` | `raw_50`, `raw_200` on `metrics`; `market_metrics` table |
| `migrate_add_raw_ratios_and_market.sql` | Step 9 — ratios + legacy watchlist-wide `market` |
| `migrate_tickers_market_and_market_metrics.sql` | Step 10 — `tickers.market`, `market_metrics` ([MIGRATIONS.md](../MIGRATIONS.md)) |
| `scripts/verify_schema.sql` | Assert columns, `market_metrics`, retention indexes |
| `tests/test_schema.py` | CI validation |

### Domain & DB

| File | Role |
|------|------|
| `models.py` | `MetricRow.raw_50`, `MetricRow.raw_200`; `MarketRow.market` |
| `db/metrics.py` | `insert_metrics`, `load_raw_ratios_by_market_for_date`, `load_distinct_trading_dates` |
| `db/market.py` | `upsert_market_stats`, `purge_stale_market` → `market_metrics` table |

### Pure logic

| Function | Module | Purpose |
|----------|--------|---------|
| `compute_raw_ratios(sma_50, sma_200, current_price)` | `fetch_sma.py` | Return `(raw_50, raw_200)` with divide-by-zero guards |
| `aggregate_market_stats(...)` | `fetch_sma.py` | Population mean/std for one (`market`, `trading_date`) group |
| `upsert_market_for_trading_dates(...)` | `fetch_sma.py` | Load ratios from DB grouped by `tickers.market`; upsert `market_metrics` |

### Job integration

**`fetch_sma.py` `main()`** — after `insert_metrics`:

1. For each processed `trading_date`, load `raw_50` / `raw_200` from `metrics` joined to `tickers`.
2. Group by `tickers.market`; compute mean/std per group → `upsert_market_stats`.

**`backfill_sma.py`** — compute `raw_50` / `raw_200` on each generated row; after all batches, upsert `market_metrics` for every (`trading_date`, `market`) in the run.

**`backfill_market.py`** — one-off manual script to recompute all `market_metrics` rows from distinct `metrics.trading_date` values (for legacy DBs or after schema upgrade).

### Retention (RFC-004)

Purge `market_metrics` rows where `trading_date` is older than `metrics_retention_days`, in the same `fetch_sma.py` run as `purge_stale_metrics`.

## Acceptance criteria

- [x] `metrics.raw_50` and `metrics.raw_200` columns in `schema.sql` and migrations (RFC-001)
- [x] `market_metrics` table with PK on `(market, trading_date)`; step 10 migration
- [x] `MetricRow` includes `raw_50`, `raw_200`; `insert_metrics` persists them
- [x] `MarketRow.market`; `db/market.py` upsert and purge helpers target `market_metrics`
- [x] `fetch_sma.py` computes ratios on every new metrics row
- [x] `fetch_sma.py` upserts `market_metrics` grouped by listing `market`
- [x] `backfill_sma.py` populates `raw_50` and `raw_200` on backfilled rows
- [x] `backfill_sma.py` upserts `market_metrics` for backfilled trading dates
- [x] `backfill_market.py` recomputes historical `market_metrics` from stored metrics
- [x] Retention purge deletes stale `market_metrics` rows (RFC-004)
- [x] `tickers.market` populated by seed/refresh (RFC-002, RFC-010)
- [x] Unit tests for ratio math, per-market aggregation, market upsert, and backfill integration

## Resolved decisions

- **Backfill aggregate history:** `backfill_sma.py` upserts per run; `backfill_market.py` recomputes all dates from `metrics`.
- **Std dev:** population std dev (`statistics.pstdev`) within each listing `market` group.
- **Per-sector market stats:** defer to consumer queries joining `tickers.sector` — not separate tables in v1.

## Open questions

- None.
