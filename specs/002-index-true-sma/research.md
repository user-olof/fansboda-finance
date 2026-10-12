# Research: Index SMA-50 / SMA-200 as True Moving Averages

Decisions for [spec.md](./spec.md). 001's decisions ([../001-index-initial-sma/research.md](../001-index-initial-sma/research.md))
stay in force unless replaced here: start date and the 5-component rule (R7), members with a close
on the start date for the reconstruction before it (R6), all-or-nothing per country (R11), new
sector start in the weekly run (R12), configurable start date (R13).

## R1. One daily level series per index, pinned at one known point

**Decision**: Each index's daily level series is computed from its daily average returns
(`DailyAccumulator.averages`, 001) and one pin `(pin_date, pin_level)`: levels after the pin are
multiplied forward by `1 + average`, levels before it divided backward. New pure function
`daily_levels(averages, pin_date, pin_level) -> dict[date, float]` in `index_anchor.py`;
`reconstruct_levels` (001, backward only from 100) becomes the special case and is replaced.
Weekly values come from `week_levels(levels, week_start, *, row_date=None)`: the row date is the
last series date in the week (or `row_date` for the start week), price = level on that date,
SMA-50 / SMA-200 = mean of the last 50 / 200 levels up to and including it (fewer when not
available, with the count returned for logging).

- Initialization and new sectors pin at `(start_date, 100)`.
- The weekly run pins at the index's latest stored row before the week: `(trading_date,
  current_price)`. If that date is not a series date (no member traded it), the pin snaps to the
  latest series date on or before it.

**Rationale**: FR-001 to FR-003 are then one rule everywhere; forward chaining from the stored row
gives the price (FR-003) and the backward levels give the SMA window (FR-002) from the same
numbers, so price and SMAs can never disagree.

**Alternatives considered**: Rebuilding from the start date every week — the needed history grows
without bound and is cut by retention. SMAs of stored weekly prices — only one point per week, not
a 50- / 200-day average.

## R2. Weekly run reuses the stock download

**Decision**: `fetch_sma.py` folds every downloaded batch into one `DailyAccumulator` (index
tickers are unique across countries) right after `metric_rows_from_batch`, using `_closes` and
`daily_returns` from `index_anchor.py` with the outlier bounds from config. Members (from the
already loaded watchlist; country from `country_set_for(market, symbol)`, sector via
`sector_key`) that were not folded — skipped as fresh, or in a failed batch — are downloaded once
more in batches before the index update, only when an index update runs (`week_starts`
non-empty). Returns are not gated by the start date in the weekly run (all current members).

**Rationale**: A normal Saturday run downloads every member exactly once (SC-003); a re-run in the
same week still gets complete index days. Memory stays small: per index per date one sum and one
count (≈40 indices × ≈275 days), the price frames are dropped batch by batch as today.

**Alternatives considered**: A separate index download of all members every week — doubles
yfinance load. Skipping the supplemental download — a re-run would write an index from a
fraction of its members.

## R3. Download window 300 → 400 calendar days

**Decision**: `fetch_sma.HISTORY_DAYS` becomes 400 (≈275 trading days), the same lookback as
`index_anchor.DOWNLOAD_LOOKBACK_DAYS`.

**Rationale**: FR-005 needs ≥ 200 levels ending on the week's last trading day plus every day since
the previous stored row; 300 days is only ≈205 trading days (less after holidays). Stock metrics
are unchanged: `compute_smas` takes the last 50 / 200 closes and the weekly growth uses the last
two weeks of the same download. Request count is unchanged; payload grows ≈33%.

## R4. Pin older than the download

**Decision**: If an index's latest stored row is older than the first series date (the job did not
run for ≈9 months), the weekly run writes no row for it and logs an error naming
`compute_indices.py --country …`.

**Rationale**: The chain cannot be bridged without data; the one-off initialization rebuilds it.

## R5. Initialization: one series from the start date to today

**Decision**: `compute_anchors` becomes `compute_index_series`: the same scan (download from
`start_date − 400` days; the download runs to today), but the accumulator also takes each
member's returns **after** the start date (all members with data), while returns up to the start
date still come only from members with a close on it (001 R6). Result per index: `IndexSeries
(ticker, start_date, levels)` with `levels = daily_levels(averages, start_date, 100)`. Every stored
week from the index's start week is written from `week_levels`. The 001 weekly bridge
(`WeeklyAccumulator`, `_bridge_weeks`, `build_anchor`, the `metric_rows_from_weekly_samples`
import) is removed: the daily series already covers the weeks retention removed.

**Rationale**: FR-007 / FR-008; one definition for stored history and the weekly run. Retention no
longer needs a special path.

The two-pass rule for indices below the minimum on the start date (001 R7) is unchanged; the second
pass builds those indices' series pinned at their own start date.

## R6. Writing rows: levels computed in Python, stats from SQL

**Decision**: `write_index_weeks(database_url, week_levels, *, country, rebuild=False,
only_tickers=None)` takes `week_levels: dict[date, dict[str, WeekLevels]]` (week → index ticker
→ row date + `IndexLevels`). Per week it still runs `BASE_WEEK_STATS_SQL` for `ticker_count` and
`pct_uptrend`, builds rows with `build_index_row` (renamed from `build_base_row`, without the
price-100 check), computes sector z-scores, and replaces the week (with `only_tickers`, the other
stored rows are kept, as in 001). `CHAINED_WEEK_STATS_SQL`, `GAP_WEEK_STATS_SQL`,
`build_chained_row`, the `anchors` / `start_week` / growth-bound parameters are removed. A new
`load_previous_indices(database_url, country, before) -> dict[ticker, (trading_date,
current_price)]` reads the weekly run's pins (existing `LOAD_PREVIOUS_INDICES_SQL`).

**Rationale**: SQL stays in `db/` and parameterized (constitution IV); the chaining is pure Python
and unit-testable (VII). Gap weeks need no rule (spec assumption).

`ticker_count` becomes the number of stocks with a stored metric row that week (outlier
stock-weeks are no longer subtracted, because exclusion is now per day); `pct_uptrend` is
unchanged.

## R7. Outliers

**Decision**: The weekly outlier detection and email are unchanged (FR-010). Index exclusion is
per daily return (`daily_returns` bounds). `log_excluded_outliers` is reworded from "excluded from
the country's indices" to the weekly outlier list; the index update logs per country the number
of daily returns dropped.

**Rationale**: The weekly stock-weeks no longer drive the index; the log must not claim they do.

## R8. Numeric precision

**Decision**: Daily chaining in `float`, conversion to `Decimal` with six decimals at the
`IndexLevels` boundary (as 001).

**Rationale**: ≈275 multiplications per series; float error is far below the stored precision.

## R9. Stored daily index table (rejected)

**Decision**: Not built (owner, 2026-10-08).

**Rationale**: Would need migration step 23, gap handling, and a second retention rule; the
rebuild from the weekly download costs nothing extra (R2, R3).
