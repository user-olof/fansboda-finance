# RFC-012: Momentum, Z-Score & Market Aggregates

| Field | Value |
|-------|-------|
| **Priority** | P1 |
| **Status** | Implemented |
| **Depends on** | RFC-001, RFC-003, RFC-005 |
| **PRD** | §6, FR-5 |
| **Feature** | [Market aggregates](../FEATURES.md#market-aggregates) |

## Summary

Weekly pipeline and backfill store **momentum** (`sma_50 / sma_200`) and a
cross-sectional **`z_score`** on each metrics row, plus
**`momentum_mean` / `momentum_std`** in
**`us_market_metrics` / `swe_market_metrics` / `uk_market_metrics`** — one row
per `(market, week_start)` within each country set. Listing `market` comes
from `*_tickers.market` (yfinance bucket; RFC-002, RFC-010).

Supports unbiased heatmap coloring — ranking tickers relative to peers in the
same country set on each date.

Legacy `raw_50` / `raw_200` and `raw_mean_*` / `raw_std_*` columns are removed
by `migrate_momentum_zscore.sql` (step 14); fresh installs use `schema.sql`.

## Requirements (PRD §6)

### Per-ticker fields (`us_metrics` / `swe_metrics` / `uk_metrics`)

| Column | Formula | Notes |
|--------|---------|-------|
| `momentum` | `sma_50 / sma_200` | `NULL` when either SMA is `NULL` or `sma_200` is zero |
| `z_score` | `(momentum - momentum_mean) / momentum_std` | Uses that date's matching `*_market_metrics` row; `NULL` when `momentum` or aggregates missing, or `momentum_std` is zero |

Computed in `fetch_sma.py` and `backfill_sma.py`. Typical order: compute
`momentum` per ticker → upsert market aggregates for the week (`week_start`) → set
`z_score` (two-pass or in-memory after aggregates).

### Cross-sectional aggregates (`us_market_metrics` / `swe_market_metrics` / `uk_market_metrics`)

| Column | Definition |
|--------|------------|
| `momentum_mean` | Mean of `momentum` across tickers in that market bucket with non-null values on that date |
| `momentum_std` | Population std dev of `momentum` in the bucket on that date |

**Routing:** `us_market` → `us_market_metrics`; `se_market` → `swe_market_metrics`; `uk_market` → `uk_market_metrics` (`db.country.country_set_for`).

## Implementation

### Files

| File | Role |
|------|------|
| `schema.sql` | `momentum`, `z_score` on `*_metrics`; `momentum_mean`, `momentum_std` on `*_market_metrics` |
| `migrate_momentum_zscore.sql` (step 14) | Drop `raw_*` columns; add `momentum` / `z_score` / `momentum_mean` / `momentum_std` |
| `models.py` | `MetricRow.momentum`, `MetricRow.z_score`; `MarketRow.momentum_mean`, `MarketRow.momentum_std` |
| `fetch_sma.py` | Compute momentum; aggregate market stats; update z_score after market upsert |
| `backfill_sma.py` / `backfill_market.py` | Same formulas for history / recompute |
| `db/metrics.py` / `db/market.py` | Persist new columns; `update_z_scores_for_week` |
| `tests/` | Momentum / z-score / market aggregation unit tests |

### Key functions

| Function | Module | Purpose |
|----------|--------|---------|
| `compute_momentum(sma_50, sma_200)` | `fetch_sma.py` | Return `momentum` with divide-by-zero guards |
| `compute_z_score(momentum, mean, std)` | `fetch_sma.py` | Return z-score with zero-std guards |
| `aggregate_market_stats(...)` | `fetch_sma.py` | Mean/std of momentum → `MarketRow` |
| `upsert_market_for_weeks(...)` | `fetch_sma.py` | Upsert country market rows; then set z_scores |
| `load_momentum_by_market_for_week(...)` | `db/metrics.py` | Load persisted momentum grouped by listing market |
| `update_z_scores_for_week(...)` | `db/metrics.py` | SQL UPDATE joining metrics → tickers → market_metrics |

## Acceptance criteria

- [x] Schema and migration: drop `raw_50`, `raw_200`, `raw_mean_*`, `raw_std_*`; add `momentum`, `z_score`, `momentum_mean`, `momentum_std`
- [x] `MetricRow` / `MarketRow` and DB layer persist the new columns
- [x] Weekly fetch computes `momentum`, upserts market aggregates, sets `z_score`
- [x] Backfill and `backfill_market.py` use the same formulas
- [x] Tests cover momentum, z-score, and market aggregation
- [x] Docs (FEATURES, RFC-001 verification SQL) match PRD §6
- [x] Country `*_market_metrics` tables with PK on `(market, week_start)` (step 15; originally `trading_date`)
- [x] Retention purge deletes stale aggregate rows (RFC-004)
- [x] Listing `market` populated by seed/refresh (RFC-002, RFC-010)
- [x] UK routing `uk_market` → `uk_market_metrics`

## Resolved decisions

- **Z-score storage:** Persist `z_score` on each metrics row (not compute-only at query time).
- **Std definition:** Population standard deviation (same convention as prior `raw_std_*`).
- **Backfill:** With FR-18 (`--country`), market upserts stay scoped to the selected set.

## Open questions

- Whether historical rows with only `raw_*` should be backfilled for `momentum`/`z_score` via `backfill_market.py` + metrics recompute, or truncated/re-backfilled per country — prefer recompute after migration when feasible.
