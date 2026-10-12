# RFC-016: Weekly Growth Columns (Split-Robust Index Chaining)

| Field | Value |
|-------|-------|
| **Priority** | P3 |
| **Status** | **Implemented** |
| **Depends on** | RFC-001, RFC-003, RFC-005, RFC-015 |
| **Enables** | RFC-017 |
| **PRD** | §5.1 (FR-5a, FR-6), §5.4 (FR-15a, FR-16), §5.8 (FR-36, FR-37, FR-37a), §6 |
| **Feature** | [SMA metrics history](../FEATURES.md#sma-metrics-history), [Equity indices](../FEATURES.md#equity-indices) |

## Summary

Store each stock's weekly growth in price, SMA-50, and SMA-200 on its
`*_metrics` row, computed from **one** adjusted yfinance download, and chain
the equity indices (RFC-015) from those stored growth values instead of
dividing this week's stored row by last week's.

**Why:** yfinance returns split- and dividend-adjusted history as of the
fetch day. Two stored rows written on different Saturdays can sit on
different adjustment bases, so `x(w) / x(p)` across stored rows can show a
fake jump when a split or dividend lands between the fetches. Both ends of
the FR-5a growth come from the same download, so they share one basis.

This is corporate-action handling layer 1. It does **not** fix series Yahoo
never adjusted (e.g. `WYLD.ST` 1:500 on 2025-12-05); RFC-017 guards the index
against those, and correcting the series is PRD §11 future work.

## Requirements

| ID | Requirement |
|----|-------------|
| FR-5a | From the downloaded series, find the ticker's last bar of the previous calendar week (`week_start − 7 days`); `price_growth = close / prev_close − 1`, `sma_50_growth = sma_50 / prev_sma_50 − 1`, `sma_200_growth = sma_200 / prev_sma_200 − 1`, each SMA using only closes up to its bar. NULL when there is no previous-week bar, the earlier value is missing or zero, or there are too few closes for that SMA at the previous-week bar. No extra yfinance calls |
| FR-6 | The week upsert also writes (and on a newer bar, replaces) the three growth columns |
| FR-15a | Backfill computes the same three columns for every weekly snapshot |
| FR-16 | Backfill still skips stored `(ticker, trading_date)` rows, except rows with NULL growth columns get only those three columns filled — re-running `backfill_sma.py --country …` populates history || FR-36 | A stock contributes to index week `w` only with positive price / SMAs and non-NULL growth columns |
| FR-37 | `g_x(w) = mean(x_growth_i(w))` per measure (equal weight) |
| FR-37a | Gap week (previous stored index week ≠ previous calendar week): fall back to `mean(x_i(w) / x_i(p) − 1)` over stocks positive in both weeks |

## Design

### Pure logic

| Path | Change |
|------|--------|
| `fetch_sma.py` | `compute_weekly_growth(close, this_pos, prev_pos) -> (price_growth, sma_50_growth, sma_200_growth)` — positions into one close series; SMAs via the existing `compute_smas` on `close[: pos + 1]`; returns `None` per value on the FR-5a NULL cases. `previous_week_bar_position(index, week_start)` finds the last bar with date in `[week_start − 7, week_start)` |
| `fetch_sma.py` | `metric_row_from_history` fills the growth fields for the latest bar |
| `backfill_sma.py` | `metric_rows_from_weekly_samples` reuses `last_bar_positions_per_week`: each week's growth is computed against the previous week's last-bar position in the same series |
| `models.py` | `MetricRow` gains `price_growth`, `sma_50_growth`, `sma_200_growth` (`Decimal | None`) |

The weekly job downloads ~300 calendar days (~205 sessions); SMA-200 at the
previous-week bar needs 200 closes up to that bar, so `sma_200_growth` is
NULL for stocks with barely 200 sessions of history. Such stocks do not
contribute to the index that week (FR-36) — the same rule as new listings.

### DB

| Path | Change |
|------|--------|
| `migrate_add_growth_columns.sql` | **Step 20** — `ALTER TABLE {us,swe,uk}_metrics ADD COLUMN IF NOT EXISTS price_growth / sma_50_growth / sma_200_growth NUMERIC(18, 6)`; idempotent |
| `schema.sql` | Same three columns on each `*_metrics` table |
| `db/metrics.py` | `insert_metrics` writes the three columns (insert + `DO UPDATE SET`); new `fill_missing_growth(database_url, rows, *, country)` — parameterized `UPDATE {metrics} SET … WHERE ticker = %s AND trading_date = %s AND price_growth IS NULL AND sma_50_growth IS NULL AND sma_200_growth IS NULL` |
| `db/indices.py` | `CHAINED_WEEK_STATS_SQL` averages the stored growth columns over week `w` (no join); new `GAP_WEEK_STATS_SQL` keeps today's two-week ratio query for FR-37a; `write_index_weeks` picks the query by comparing `week_start_of(prev.trading_date)` with `w − 7 days` |
| `scripts/verify_schema.sql` / `scripts/apply_migrations.sh` | Column checks; run step 20 in both paths |

### Backfill (FR-16)

`backfill_sma.py` splits generated rows into **new** (not stored → insert as
today) and **existing** (stored `(ticker, trading_date)`) — existing rows go
to `fill_missing_growth`, which only touches rows whose growth columns are
all NULL, so re-runs and already-filled rows are no-ops. Log counts for
inserted, growth-filled, and skipped rows (FR-17).
### Chained-week SQL sketch

```sql
SELECT COUNT(*), MAX(trading_date),
       AVG(price_growth), AVG(sma_50_growth), AVG(sma_200_growth)
FROM {metrics}
WHERE week_start = %s
  AND current_price > 0 AND sma_50 > 0 AND sma_200 > 0
  AND price_growth IS NOT NULL
  AND sma_50_growth IS NOT NULL
  AND sma_200_growth IS NOT NULL;
```

Only the week date is a runtime parameter; `{metrics}` comes from
`sql_for_countries`.

## Rollout

1. Apply step 20 (`migrate_add_growth_columns.sql`) — additive, safe to
   repeat, no snapshot needed.
2. Deploy code (the new code writes the columns; old code ignores them).
3. Fill history per country set:
   `pipenv run python backfill_sma.py --country us` (then `swe`, `uk`).
   Until filled, historical weeks have NULL growth and would contribute no
   stocks — so run step 4 only after the backfills.
4. Rebuild indices: `pipenv run python compute_indices.py`.

## Tests

- `compute_weekly_growth`: normal week, missing previous week (holiday
  week / new listing), zero previous close, too few closes for SMA-200 at the
  previous bar.
- Split inside the window of one adjusted series yields ~0 growth (no fake
  jump).
- Backfill: new vs existing rows; `fill_missing_growth` SQL only updates
  all-NULL rows and is parameterized.
- Indices: chained week averages stored growth; gap week uses the ratio
  query; stocks with NULL growth excluded.
- Schema: step 20 adds the columns to all three sets and is idempotent.

## Open questions

- None.
