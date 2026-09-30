# RFC-014: Sector Trend Averages

| Field | Value |
|-------|-------|
| **Priority** | P3 |
| **Status** | **Implemented** |
| **Depends on** | RFC-001, RFC-003, RFC-004, RFC-012 |
| **PRD** | §5.1 (FR-7a), §5.7 (FR-27–FR-33), §6 |
| **Feature** | [Sector trend averages](../FEATURES.md#sector-trend-averages) |

## Summary

Weekly, equal-weighted trend summary per sector for each country set, stored
in `us_by_sector` / `swe_by_sector` / `uk_by_sector`. Every company counts
once regardless of size — the view of an investor choosing between companies,
not a cap-weighted index. Computed in SQL from stored `*_metrics` +
`*_tickers.sector`; no yfinance.

## Requirements (PRD §5.7)

| ID | Requirement |
|----|-------------|
| FR-27 | Group `*_metrics` ⋈ `*_tickers` by `sector`, `week_start`; skip NULL momentum / blank sector |
| FR-28 | Normalize sector to `sectorKey` form: `lower(replace(btrim(sector), ' ', '-'))` |
| FR-29 | Store `ticker_count`, `momentum_mean`, `momentum_median`, `z_score_mean`, `pct_uptrend` |
| FR-30 | Replace each `(country, week)` atomically (DELETE + INSERT … SELECT in one transaction) |
| FR-31 | Prune `*_by_sector` weeks absent from the matching `*_metrics` table |
| FR-32 | Weekly job refreshes weeks it wrote; standalone CLI with `--country` / `--week` |
| FR-33 | Summary log line; non-zero exit on DB failure |

## Measures

| Column | SQL | Reading |
|--------|-----|---------|
| `momentum_mean` | `AVG(momentum)` | Average trend strength (`> 1` = SMA-50 above SMA-200) |
| `momentum_median` | `percentile_cont(0.5)` | Robust to single-stock outliers |
| `z_score_mean` | `AVG(z_score)` | Sector strength relative to its whole market that week (`> 0` = stronger than market) |
| `pct_uptrend` | `100 * AVG(sma_50 > sma_200)` | Breadth: share of companies in an uptrend |

All sectors are stored with `ticker_count`; small sectors are noisy, so
consumers should filter (e.g. `ticker_count >= 5`).

## Design

- **`db/sector.py`:** `INSERT_SECTOR_WEEK_SQL`, `DELETE_SECTOR_WEEK_SQL`,
  `PRUNE_ORPHAN_SECTOR_WEEKS_SQL` built with `sql_for_countries` (new
  `{by_sector}` placeholder / `BY_SECTOR_TABLE` in `db/country.py`).
  `refresh_sector_weeks(url, weeks, country=…)` and
  `prune_orphan_sector_weeks(url, country=…)`. The only runtime value is
  `week_start`, passed as a parameter.
- **`compute_sector_trends.py`:** `refresh_sector_trends(url, week_starts=None,
  country=None) -> (written, pruned)`. `None` recomputes every week from
  `load_distinct_week_starts`; an explicit list (weekly job) is applied to
  every selected country. CLI: `--country us|swe|uk`, `--week YYYY-MM-DD`
  (normalized to Monday).
- **`fetch_sma.py`:** `_run_sector_trends` runs after `_run_retention_purge`
  in both the normal path (weeks just written) and the all-fresh path (prune
  only). It must run after `upsert_market_for_weeks`, which sets `z_score`.
- **Retention:** no separate cutoff — pruning orphan weeks after the metrics
  purge keeps sector history aligned with RFC-004.
- **Backfills:** `backfill_sma.py` / `backfill_market.py` do not refresh
  sectors; run `compute_sector_trends.py` afterwards.

## Schema

Migration step 17 (`migrate_add_by_sector_tables.sql`), mirrored in
`schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS us_by_sector (
    sector           TEXT            NOT NULL,
    week_start       DATE            NOT NULL,
    updated_at       TIMESTAMPTZ     NOT NULL,
    ticker_count     INTEGER         NOT NULL,
    momentum_mean    NUMERIC(18, 6),
    momentum_median  NUMERIC(18, 6),
    z_score_mean     NUMERIC(18, 6),
    pct_uptrend      NUMERIC(18, 6),
    PRIMARY KEY (sector, week_start)
);
```

## Rollout

1. Apply step 17 (safe to repeat).
2. Fill history once: `pipenv run python compute_sector_trends.py`.
3. Deploy — the weekly job then keeps the tables current.

## Tests

`tests/test_compute_sector_trends.py` (SQL shape, transaction, orchestration,
CLI), `tests/test_retention.py` (weekly job ordering / failure),
`tests/test_schema.py` (DDL + migration order).
