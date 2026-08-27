# RFC-012: Normalized SMA Ratios & Market Aggregates

| Field | Value |
|-------|-------|
| **Priority** | P1 |
| **Status** | Implemented |
| **Depends on** | RFC-001, RFC-003, RFC-005 |
| **PRD** | §6 |
| **Feature** | [Market aggregates](../FEATURES.md#market-aggregates) |

## Summary

Extend the weekly pipeline and backfill to store scale-free SMA ratios on each `metrics` row (`raw_50`, `raw_200`) and cross-sectional watchlist statistics in a `market` table (one row per `trading_date`). Supports unbiased heatmap coloring — ranking tickers relative to the watchlist on each date rather than using raw SMA-distance signals.

## Requirements (PRD §6)

### Per-ticker ratios (`metrics`)

| Column | Formula | Notes |
|--------|---------|-------|
| `raw_50` | `sma_50 / current_price` | `NULL` when either operand is `NULL` or `current_price` is zero |
| `raw_200` | `sma_200 / current_price` | Same guard as `raw_50` |

Computed at insert time in `fetch_sma.py` and `backfill_sma.py` alongside existing SMA fields.

### Cross-sectional aggregates (`market`)

One row per `trading_date` present in the weekly run:

| Column | Formula |
|--------|---------|
| `raw_mean_50` | Mean of `raw_50` across all tickers with non-null values on that date |
| `raw_mean_200` | Mean of `raw_200` across all tickers with non-null values on that date |
| `raw_std_50` | Sample or population std dev of `raw_50` on that date |
| `raw_std_200` | Sample or population std dev of `raw_200` on that date |
| `trading_date` | Snapshot date (unique) |
| `updated_at` | When the row was written |

Upsert on `trading_date` conflict (replace stats when the weekly job re-processes a date).

### Downstream use (out of scope for this RFC)

Consumers may derive z-scores, e.g. `(raw_50 - raw_mean_50) / raw_std_50`, or percentile ranks within sector for heatmap cells. No UI or API in this repo.

## Implementation

### Schema

| Artifact | Role |
|----------|------|
| `schema.sql` | Add `raw_50`, `raw_200` to `metrics`; create `market` table — **done (RFC-001)** |
| `migrate_add_raw_ratios_and_market.sql` | Upgrade path for existing databases — **done (RFC-001)** |
| `scripts/verify_schema.sql` | Assert new columns and `market` table — **done (RFC-001)** |
| `tests/test_schema.py` | CI validation — **done (RFC-001)** |

### Domain & DB

| File | Role |
|------|------|
| `models.py` | `MetricRow.raw_50`, `MetricRow.raw_200`; `MarketRow` — **done (RFC-001)** |
| `db/metrics.py` | `insert_metrics`, `load_raw_ratios_for_date`, `load_distinct_trading_dates` |
| `db/market.py` | `upsert_market_stats(database_url, row)` — **done (RFC-001)** |

### Pure logic

| Function | Module | Purpose |
|----------|--------|---------|
| `compute_raw_ratios(sma_50, sma_200, current_price)` | `fetch_sma.py` or shared module | Return `(raw_50, raw_200)` with divide-by-zero guards |
| `aggregate_market_stats(...)` | `fetch_sma.py` | Population mean/std for one `trading_date` |
| `upsert_market_for_trading_dates(...)` | `fetch_sma.py` | Load ratios from DB and upsert `market` |

### Job integration

**`fetch_sma.py` `main()`** — after `insert_metrics` for a batch (or once per run after all inserts for the session date):

1. Collect all `MetricRow` objects inserted or fetched for the active `trading_date`.
2. Compute mean/std → `upsert_market_stats`.

**`backfill_sma.py`** — compute `raw_50` / `raw_200` on each generated row; after all batches, `upsert_market_for_trading_dates` for every `trading_date` in the run.

**`backfill_market.py`** — one-off manual script to recompute `market` rows from all distinct `metrics.trading_date` values (for legacy DBs or after schema upgrade).

### Retention (RFC-004)

Purge `market` rows where `trading_date` is older than `metrics_retention_days`, in the same `fetch_sma.py` run as `purge_stale_metrics`.

## Acceptance criteria

- [x] `metrics.raw_50` and `metrics.raw_200` columns in `schema.sql` and migration (RFC-001)
- [x] `market` table in `schema.sql` with primary key on `trading_date` (RFC-001)
- [x] `MetricRow` includes `raw_50`, `raw_200`; `insert_metrics` persists them (RFC-001)
- [x] `db/market.py` upsert and purge helpers (RFC-001)
- [x] `scripts/verify_schema.sql` and `tests/test_schema.py` updated (RFC-001)
- [x] `fetch_sma.py` computes ratios on every new metrics row
- [x] `fetch_sma.py` upserts one `market` row per processed `trading_date`
- [x] `backfill_sma.py` populates `raw_50` and `raw_200` on backfilled rows
- [x] Retention purge deletes stale `market` rows (RFC-004)
- [x] Unit tests for ratio math, aggregation, market upsert, and backfill integration
- [x] `backfill_sma.py` upserts `market` rows for backfilled trading dates
- [x] `backfill_market.py` recomputes historical `market` rows from stored metrics

## Resolved decisions

- **Backfill `market` history:** `backfill_sma.py` upserts per run; `backfill_market.py` recomputes all dates from `metrics`.
- **Std dev:** population std dev (`statistics.pstdev`) for full watchlist.
- **Per-sector market stats:** defer to consumer queries joining `tickers.sector` — not separate tables in v1.

## Open questions

- None.
