# Data Model: Fast Per-Stock Lookups in the Metrics Tables

**Feature**: [spec.md](./spec.md) | **Date**: 2026-11-09

No table, column, constraint, or stored value changes. Three secondary indexes are added.

## New indexes

| Index | Table | Key | Unique | Built by |
|---|---|---|---|---|
| `idx_us_metrics_ticker_trading_date` | `us_metrics` | `(ticker, trading_date)` | no | `schema.sql` (fresh) / step 25 (existing) |
| `idx_swe_metrics_ticker_trading_date` | `swe_metrics` | `(ticker, trading_date)` | no | same |
| `idx_uk_metrics_ticker_trading_date` | `uk_metrics` | `(ticker, trading_date)` | no | same |

- Not unique: uniqueness stays with `*_metrics_week_start_ticker_key` `(week_start, ticker)`;
  `(ticker, trading_date)` is unique in practice but must not become a constraint
  (`tests/test_schema.py` asserts `UNIQUE (ticker, trading_date)` is absent from `schema.sql`).
- Valid state: `pg_index.indisvalid = true` for all three after step 25 (`verify_schema.sql`).

## Existing indexes (kept, unchanged)

| Index | Key | Used by |
|---|---|---|
| `*_metrics_pkey` | `(id)` | primary key |
| `*_metrics_week_start_ticker_key` | `(week_start, ticker)` | week upserts (`ON CONFLICT`), week-level queries |
| `idx_*_metrics_trading_date` | `(trading_date)` | retention purge, freshness check |

## Lookups served (consumer app, `fansboda` `src/routes/stocks.py`)

| Lookup | Shape | Before (2026-11-09, warm) | With the index |
|---|---|---|---|
| Chart history (`_metric_history`) | `ticker = ? AND trading_date >= ? ORDER BY trading_date` | parallel seq scan, 34 ms | index range scan, ≤ 53 rows |
| Latest observation (`_latest_observation`) | `ticker = ? ORDER BY trading_date DESC LIMIT 1` | backward scan of `idx_us_metrics_trading_date`; miss for SWE / UK stock ≈ 300 ms | backward index scan, 1 row; miss = empty range |
| Latest row for a page (`_get_latest_metrics_for_symbols`) | `MAX(trading_date) … WHERE ticker IN (25) GROUP BY ticker` + join | 2 seq scans, 107 ms | index scans per symbol |
| Venue symbols with metrics (`_matching_symbols_with_metrics`) | `DISTINCT ticker WHERE ticker IN (~3 300)` | seq scan, 97 ms | planner's choice (index-only scan or seq scan) |
| Venue SMA history (`_batch_sma_history`, full venue) | `ticker IN (~3 300) AND trading_date >= ?` | seq scan, 193 ms | likely still seq scan (reads most rows) — out of target |
| Latest row per ticker, whole table (`/stocks/latest`) | `GROUP BY ticker` over all rows | 312 ms | may improve; out of target |
