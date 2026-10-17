# Research: Index Momentum Band for Member Stocks

## R1 — Where the weekly ratio comes from

**Decision**: Compute each stock's weekly ratio from the same daily closes that build the index:
SMA-50 and SMA-200 as full-window rolling means of the daily closes, read on the stock's last
bar of each calendar week; ratio = SMA-50 / SMA-200 (`None` when fewer than 200 bars). Pure
function `weekly_momentum(close) -> dict[week_start, float | None]` in `index_anchor.py`.

**Rationale**: FR-003 needs a ratio for every week of the series, including the 250 trading days
before the start date and weeks older than the 365-day retention — those have no stored
`*_metrics` rows. The definition matches the stored stock momentum (`compute_smas`: full 50 /
200 windows on the adjusted daily closes, week's last bar), so stored and computed ratios agree
up to data revisions.

**Alternatives considered**: Read `*_metrics.momentum` — missing for pre-start history and purged
weeks; would need a DB lookup per stock-week. A daily ratio — rejected in clarification (Q2).

## R2 — Excluding a stock's daily returns per week

**Decision**: `index_anchor._returns` (and `fold_close`) take an optional band `(low, high)`; a
daily return on day *d* is dropped when the stock's ratio for *d*'s week is outside
`[low, high]` (inclusive). `None` ratio → kept (FR-007). Drops are recorded per stock and week
(ratio) in an optional collector for logging; the outlier-drop count is unchanged.

**Rationale**: Every index path (one-off initialization, weekly update, new sector start) folds
returns through `fold_close`, so one change covers FR-004. The index level is built from daily
returns, so a stock leaving or rejoining causes no jump (spec edge case).

**Alternatives considered**: Filtering members before download — cannot be per week. Filtering
in `DailyAccumulator` — it does not see closes.

## R3 — Start-date minimum counts in-band members only

**Decision**: In `_scan`, a member's close on a candidate date counts toward
`INDEX_MIN_COMPONENTS` only when its ratio for that week is inside the band (or `None`).

**Rationale**: Spec edge case: the start-date rule applies to the remaining members.

## R4 — Member count and uptrend percentage

**Decision**: `BASE_WEEK_STATS_SQL` gets `AND m.sma_50 / m.sma_200 BETWEEN %s AND %s`
(parameters); `write_index_weeks` takes the band and passes it.

**Rationale**: `ticker_count` / `pct_uptrend` come from the week's stored metrics (unchanged
source); the stored row's ratio is the same definition as R1 for that week. Rare boundary
disagreements (a ratio of 0.1500003 vs 0.1499998 after a data revision) are accepted and
documented; the next initialization re-aligns both.

**Alternatives considered**: Computing counts in Python from the download — larger change to a
working, tested path for a negligible difference.

## R5 — Download windows

**Decision**: Raise the index download lookback before the start date
(`index_anchor.DOWNLOAD_LOOKBACK_DAYS`) from 400 to 700 calendar days, and the weekly job's
download (`fetch_sma.HISTORY_DAYS`) from 400 to 600 calendar days.

**Rationale**: A ratio needs 200 bars before its week. Initialization: 250 history days + 200
bars ≈ 450 trading days ≈ 650 calendar days. Weekly update: the new week's SMA-200 uses the last
200 daily levels, each needing its week's ratio → ≈ 400 trading days ≈ 580 calendar days. Without
this, the oldest part of each window would have no ratio and stay included regardless.
Stock metrics are unaffected (they use the last 200 bars). Cost: ~50 % more rows per yfinance
batch, still free and within rate limits (batching/delays unchanged).

**Alternatives considered**: Keep 400 days and accept "no ratio → included" for the oldest weeks
— silently weakens FR-003. A separate second download — more requests than a longer one.

## R6 — Settings

**Decision**: `INDEX_MOMENTUM_MIN` (default 0.15) and `INDEX_MOMENTUM_MAX` (default 1.5) in
`config.py` (`index_momentum_min` / `index_momentum_max`), passed through `AnchorSettings`;
`get_config` raises `ValueError` when min ≥ max or min ≤ 0 (FR-005).

**Rationale**: Same pattern as `OUTLIER_MAX_GROWTH` / `OUTLIER_MIN_GROWTH`.

## R7 — Logging

**Decision**: Per country per run, one INFO summary
`Indices <c>: momentum band [0.15, 1.5] excluded <n> stock-week(s) from <m> stock(s)` and one
WARNING per excluded stock in the weeks being written:
`Index band: excluded <SYMBOL> week <week_start> ratio <r>` (initialization: only stocks excluded
in the latest stored week are listed individually, to keep the log readable; the summary counts
all weeks).

**Rationale**: FR-006 / SC-003 without thousands of lines on a full rebuild.

## R8 — Documentation and rollout

**Decision**: `README.md` (Equal-weighted indices: members; settings table) and
`.cursor/rules/RULES.mdc` (indices data-model sentence) describe the band — RULES rule 6
(published threshold). `project-docs/` untouched. After deploy, the owner re-runs
`compute_indices.py` per country (`scripts/run_compute_indices.sh`); no migration.
