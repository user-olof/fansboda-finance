# RFC-015: Equal-Weighted Equity Indices

| Field | Value |
|-------|-------|
| **Priority** | P3 |
| **Status** | **Revision proposed** — code implements v1 (single `index_price` per `week_start`); v2 below (price / SMA-50 / SMA-200 levels + momentum per `trading_date`) is not implemented |
| **Depends on** | RFC-001, RFC-003, RFC-004, RFC-014 |
| **PRD** | §5.1 (FR-7, FR-7b), §5.8 (FR-34–FR-45), §6 |
| **Feature** | [Equity indices](../FEATURES.md#equity-indices) |

## Summary

One synthetic, equal-weighted index per country set, stored in a single
`indices` table shaped like the `*_metrics` tables: per index and calendar
week, an index **price** level, **SMA-50** and **SMA-200** levels, and
**momentum** (`sma_50 / sma_200`). Every stock counts once regardless of
size. Computed in SQL from stored `*_metrics`; no yfinance. No `z_score`.

| Country set | Index name | Ticker | Source |
|-------------|------------|--------|--------|
| US | US Equity Index | `US-IDX` | `us_metrics` |
| Swedish | OMX Equity Index | `SWE-IDX` | `swe_metrics` |
| UK | FTSE Equity Index | `UK-IDX` | `uk_metrics` |

## Requirements (PRD §5.8)

| ID | Requirement |
|----|-------------|
| FR-34 | Three indices: `US-IDX`, `SWE-IDX`, `UK-IDX` with the names above |
| FR-35 | One row per ticker per calendar week; `trading_date` = latest contributing `trading_date`; key `(ticker, trading_date)`; a later bar in the same week replaces the row |
| FR-36 | Contributing stocks: positive `current_price`, `sma_50`, `sma_200` in both `w` and the previous stored week `p`; one set drives all three levels |
| FR-37 | Per measure `x`: `g_x(w) = mean(x_i(w) / x_i(p) − 1)` (equal weight, reset weekly) |
| FR-38 | `level_x(w) = level_x(p) × (1 + g_x(w))`, stored as `current_price` / `sma_50` / `sma_200` |
| FR-39 | Base week: `current_price = 100`; `sma_50 = 100 × mean(sma_50_i / price_i)`; `sma_200 = 100 × mean(sma_200_i / price_i)` |
| FR-40 | `momentum = sma_50 / sma_200` (NULL if `sma_200` is zero); no `z_score` |
| FR-41 | No contributing stocks → no row; next week chains from the last stored row |
| FR-42 | Recompute overwrites; weeks computed in ascending order |
| FR-43 | Weekly job (FR-7b) for weeks just written + later weeks; standalone full rebuild `compute_indices.py [--country]` |
| FR-44 | Purge rows with `trading_date` older than `METRICS_RETENTION_DAYS` |
| FR-45 | Log `trading_date`, `ticker_count`, three levels, `momentum` per index + summary; non-zero exit on DB failure |

## Calculation

For index ticker `X` (country set `c`) and calendar week `w` (`week_start`
Monday):

1. **Previous row:** `p` = the latest `indices` row for `X` with
   `trading_date < w`. Its week is `week_start_of(p.trading_date)`.
2. **Base week** (no `p`): over stocks in `{c}_metrics` for week `w` with
   `current_price`, `sma_50`, `sma_200` all > 0:
   - `ticker_count = N`, `trading_date = MAX(trading_date)`
   - `current_price = 100`
   - `sma_50 = 100 × AVG(sma_50 / current_price)`
   - `sma_200 = 100 × AVG(sma_200 / current_price)`
3. **Chained week:** join each stock's week-`w` row to its row in `p`'s week;
   keep stocks where all six values are > 0. Then
   `g_x = AVG(x_w / x_p − 1)` for each measure and
   `level_x = p.level_x × (1 + g_x)`; `trading_date = MAX(cur.trading_date)`.
4. **Momentum:** `sma_50 / sma_200` on the new levels.
5. `N = 0` → write nothing and delete any existing row for `X` in week `w`.

Why the SMA base uses the price ratio: if both SMA levels started at 100,
index momentum would be exactly 1.0 in the base week and would then only
show the change since the base week. Anchoring them at
`100 × mean(sma / price)` places the SMA levels where they sit relative to
price for the average stock, so momentum carries the real trend from week
one. Growth rates and ratios are unit-free, so mixed price units in a set
(UK `GBp` vs `GBP`) do not distort the levels.

Using the previous **stored** week (not strictly `w − 7 days`) keeps the
chain intact across a missed weekly run. `current_price` is the adjusted
close at fetch time; a dividend or split adjustment between two weekly
fetches can introduce a small one-week error for that stock (accepted).

### SQL sketch (chained week, one country)

```sql
SELECT
    COUNT(*)                                        AS ticker_count,
    MAX(cur.trading_date)                           AS trading_date,
    AVG(cur.current_price / prev.current_price - 1) AS g_price,
    AVG(cur.sma_50 / prev.sma_50 - 1)               AS g_sma_50,
    AVG(cur.sma_200 / prev.sma_200 - 1)             AS g_sma_200
FROM {metrics} cur
JOIN {metrics} prev
  ON prev.ticker = cur.ticker
 AND prev.week_start = %s          -- week of the previous index row
WHERE cur.week_start = %s
  AND cur.current_price > 0 AND cur.sma_50 > 0 AND cur.sma_200 > 0
  AND prev.current_price > 0 AND prev.sma_50 > 0 AND prev.sma_200 > 0;
```

Base week:

```sql
SELECT COUNT(*), MAX(trading_date),
       AVG(sma_50 / current_price), AVG(sma_200 / current_price)
FROM {metrics}
WHERE week_start = %s
  AND current_price > 0 AND sma_50 > 0 AND sma_200 > 0;
```

Only week dates and the index ticker are runtime values (parameters); the
table name comes from the `{metrics}` placeholder (`sql_for_countries`).

## Design (v2 changes to the v1 code)

| Path | Change |
|------|--------|
| `migrate_indices_levels.sql` | **Step 19** — if `indices` still has `week_start`, drop it and recreate in the v2 shape (data is derived; rebuild afterwards). No-op once applied |
| `schema.sql` | `indices` in the v2 shape |
| `equity_index.py` | `IndexLevels(current_price, sma_50, sma_200)`; `IndexRow` gains `trading_date`, three levels, `momentum` (drops `week_start`, `avg_return`, `index_price`); `build_base_row` / `build_chained_row` |
| `db/indices.py` | Base / chained stats SQL above; load previous row by `trading_date`; replace the week's row (delete `ticker` rows with `trading_date` in `[w, w + 6]`, then insert); purge by `trading_date` |
| `compute_indices.py` | Same entrypoints; log the three levels + momentum |
| `fetch_sma.py` / `db/retention.py` | Unchanged wiring (FR-7b, 3-way purge) |
| `scripts/apply_migrations.sh` / `scripts/verify_schema.sql` | Step 19; column checks for the v2 shape |
| `tests/` | Base-week anchoring, chained levels, common contributing set, momentum, same-week replacement, purge by `trading_date`, migration guard |

## Schema (v2)

```sql
CREATE TABLE IF NOT EXISTS indices (
    ticker         TEXT            NOT NULL,
    name           TEXT            NOT NULL,
    country        TEXT            NOT NULL,
    trading_date   DATE            NOT NULL,
    updated_at     TIMESTAMPTZ     NOT NULL,
    ticker_count   INTEGER         NOT NULL,
    current_price  NUMERIC(18, 6)  NOT NULL,
    sma_50         NUMERIC(18, 6)  NOT NULL,
    sma_200        NUMERIC(18, 6)  NOT NULL,
    momentum       NUMERIC(18, 6),
    PRIMARY KEY (ticker, trading_date)
);
```

At most one row per ticker per calendar week is enforced by the writer
(FR-35), which replaces the week's row instead of relying on the key.

## Rollout

1. Apply step 19 (`migrate_indices_levels.sql`) — drops v1 index rows.
2. Rebuild: `pipenv run python compute_indices.py`.
3. Deploy v2 code — the weekly job then writes one row per index per week.

## Open questions

- None.
