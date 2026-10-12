# Data Model: Index Initial SMA from Daily History

No schema change. Stored data stays in `indices` (one row per index ticker per week); the new
entities below are in-memory only.

## Configuration

| Setting | Env var | Default | Rule |
|---|---|---|---|
| `index_start_date` | `INDEX_START_DATE` | `2025-10-03` | ISO date; start week `S = week_start_of(index_start_date)` |
| `index_history_trading_days` | `INDEX_HISTORY_TRADING_DAYS` | `250` | Trading days before the start date used for the initial SMAs; must be ≥ 200 |
| `index_min_components` | `INDEX_MIN_COMPONENTS` | `5` | Members with a close needed on an index's start date; must be ≥ 1 |

## Member (in memory)

| Field | Description |
|---|---|
| `symbol` | Ticker from the country's `*_tickers` |
| `sector_key` | Normalized sector (`lower`, spaces → `-`, trimmed; blank → none), same as `SECTOR_KEY_SQL` |
| `close` | Adjusted daily closes from the download |

Rule: a member counts for an index only if it has a close on the index's start date (R3).

## Index start date (per index, R7)

`index_start_date` if at least `index_min_components` members have a close on it; otherwise the
first later week's last trading date on which at least that many members have a close; none if
never reached (no rows, logged).

## DailyAverages (in memory, per index)

| Field | Description |
|---|---|
| `sum_by_date` | date → sum of the members' daily returns within the outlier bounds |
| `count_by_date` | date → number of returns summed |

Average return on a date = `sum / count`; dates with `count = 0` are not trading days for the index.

## Anchor (in memory, per index ticker)

| Field | Description |
|---|---|
| `ticker` | Index ticker (`US-IDX`, `US-IDX-TECHNOLOGY`, …) |
| `week_start` | `S` if the start week is stored, else the week before the oldest stored metrics week; for an index with a later start date (R7) the week of that date (or the bridged week before the oldest stored week) |
| `trading_date` | Start date, or the last bridged trading date |
| `current_price`, `sma_50`, `sma_200` | Levels at `week_start` |
| `days_used` | Number of reconstructed levels behind SMA-200 (logged when < 200) |

Validation: price on the start date = 100 exactly; `sma_50 = mean(L[-50:])`,
`sma_200 = mean(L[-200:])` of the reconstructed levels ending on the start date.

## WeeklyBridgeStats (in memory, per index and bridged week)

Same quantities as `CHAINED_WEEK_STATS_SQL`: count of eligible stocks and mean of `price_growth`,
`sma_50_growth`, `sma_200_growth` over stocks with positive price/SMAs and all three growths within
`[outlier_min_growth, outlier_max_growth]`. A week with count 0 leaves levels unchanged.

## Stored `indices` rows (unchanged columns)

- Start week `S` (when stored metrics exist for it): `current_price = 100`, `sma_50` / `sma_200`
  from the anchor, `momentum = sma_50 / sma_200`, `ticker_count` / `pct_uptrend` from stored
  stats of week `S`, `z_score` across the country's sectors as today.
- Weeks after `S`: chained from the previous week's levels × (1 + mean stored growth), unchanged.
- No rows with `trading_date` before the start date.

## State transitions per country

```text
no index rows ──weekly run──▶ no rows written, warning "run compute_indices.py" (no download)
no index rows ──rebuild──▶ rows S..latest (anchor at S)            [start week stored]
no index rows ──rebuild──▶ rows M0..latest (anchor bridged to M0-1) [start week purged]
rows exist ──rebuild, a stored index has no anchor──▶ unchanged, error, exit 1 (R11)
rows exist ──weekly run, all indices present──▶ append/replace week (no download)
rows exist ──weekly run, new sector──▶ download that sector's stocks, start date by R7, sector
                                      rows from its start week to latest; other indices' levels
                                      kept, z-scores recomputed (fetch_sma.py, R12)
rows exist ──weekly run, new sector fails or < 5 listed──▶ no sector rows, warning; retried next week
rows exist ──retention purge──▶ oldest rows deleted, remaining levels unchanged
```
