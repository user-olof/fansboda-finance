# Research: Index Initial SMA from Daily History

All Technical Context items were known from the codebase; no NEEDS CLARIFICATION remained. The
decisions below fix the design choices the spec leaves open.

## R1. Where the start levels come from

- **Decision**: A new pure module `index_anchor.py` computes, per index, the "anchor": the levels
  (price, SMA-50, SMA-200) on the start week, or — when the start week is no longer stored — on
  the calendar week just before the oldest stored metrics week. `write_index_weeks` uses the
  anchor as the "previous row" for an index with no stored row, instead of building a base row
  from SMA-to-price ratios.
- **Rationale**: Keeps the weekly chaining code path unchanged (FR-007); only the seed differs.
- **Alternatives**: Store anchors in a new table (rejected: schema change and FR-011 says only
  weekly rows are stored); compute SMAs from stored weekly prices (rejected: weekly data cannot
  give a 50-/200-trading-day average).

## R2. Daily reconstruction

- **Decision**: For each member stock, daily return `r = close_d / close_prev - 1` on its own
  consecutive bars, for the 250 trading days before the start date plus the start date
  (`index_history_trading_days`). A return is dropped if above `outlier_max_growth` or below
  `outlier_min_growth`. Per index and date, accumulate `sum(r)` and `count`; average = sum/count.
  The trading calendar per country is the union of dates with at least one return. Level on
  the start date = 100; walking backwards, `L(prev) = L(d) / (1 + avg(d))`. Initial SMA-50 =
  mean of the last 50 levels ending on the start date, SMA-200 = mean of the last 200 (fewer
  if fewer are available, logged).
- **Rationale**: Matches the spec (FR-003 to FR-005); sums/counts keep memory small across
  batches.
- **Alternatives**: Average of price levels (rejected: price-weighted, not equal-weighted).

## R3. Members

- **Decision**: Members are the country's `*_tickers` rows (sector from the same table, normalized
  with a Python `sector_key()` that mirrors `SECTOR_KEY_SQL`) that have a close on the index's start
  date (R7) in the download. Market index: all of them; sector index: those with that sector key; blank
  sector counts toward the market only.
- **Rationale**: Same membership source the weekly SQL uses (join on `*_tickers`).
- **Alternatives**: Members from stored `*_metrics` of the start week (rejected: gone once
  retention purges it).

## R4. Bridge after retention (FR-014)

- **Decision**: If the oldest stored metrics week `M0` is later than the start week `S`, compute
  weekly stock rows for weeks `S+1 … M0-1` from the same download with
  `metric_rows_from_weekly_samples` (identical rules to the backfill and weekly job: one SMA
  snapshot from the week's last bar, growth vs the previous calendar week, ≥ 200 closes), then
  aggregate per index exactly like `CHAINED_WEEK_STATS_SQL` (positive price/SMAs, all three
  growths within bounds, equal-weighted mean). Chain from the anchor at `S`. A week with no
  eligible stock carries the previous levels forward. The resulting levels are assigned to week
  `M0-1` so the stored chain starts with a normal previous-week link. Bridged weeks are not stored.
- **Rationale**: Reproduces what the stored chain would have been (SC-004) using the project's
  own growth rules.
- **Alternatives**: Re-anchor at the oldest stored week (rejected by FR-012); keep the old index
  rows and only recompute later weeks (rejected: old rows carry the wrong start SMAs).

## R5. Download scope and cost

- **Decision**: One download per country for all its tickers, `start = start_date − 400 days`
  (covers 250 trading days plus holidays), to today, using `download_batch` with the weekly-job
  settings (`yf_batch_size` 40, `yf_batch_delay_seconds` 2.0, backoff). Process and discard each
  batch.
- **Rationale**: ≈145 batches for US + SWE + UK at ≈7–10 s each ≈ 20–25 minutes; within the
  one-hour target (SC-006).
- **Alternatives**: Backfill settings (25 / 5 s, ≈40 minutes) — kept as a fallback via env vars.

## R6. Weekly job and new indices

- **Decision**: The weekly job only updates (FR-015), and that update lives in `fetch_sma.py`
  (R10). It chains each index that has a stored previous row, exactly as today, with no download.
  A new sector index is started by the weekly job itself (R12). A country with no index rows at
  all gets no rows; `fetch_sma.py` logs "country <c> has no indices; run compute_indices.py
  --country <c>".
- **Rationale**: Constitution Principle I (rebuilds stay manual, never cron-scheduled); owner
  decisions 2026-10-07 ("no full rebuild, only an update"; new sectors start automatically) and
  2026-10-08 (start-date rule, R7).
- **Alternatives**: Automatic country rebuild from the weekly job (rejected: violates Principle I);
  leave new sectors to the manual initialization (rejected by the owner).

## R7. Index start date: at least 5 listed members (FR-016)

- **Decision**: Candidate dates are the common start date and then each later week's last
  trading date (from the downloaded trading calendar). An index's start date is the first
  candidate on which at least `index_min_components` (default 5) of its members have a close.
  `compute_anchors` counts, per index and candidate date, the members with a close (small: about
  52 dates × 36 indices) while it accumulates the daily returns of members with a close on the
  common start date. Indices with ≥ 5 on the common start date get their anchor from that pass.
  For the others, a pure `find_start_date(counts, candidates, min_components)` picks the date and
  a second `compute_anchors` call for just those indices' members computes the anchor on it
  (download start = that date − 400 days). An index that never reaches 5 gets no anchor and is
  logged. The same function serves the initialization and the weekly new-sector path (R12).
- **Rationale**: Owner rule 2026-10-08. A minimum of 5 keeps a one- to four-stock index from
  being started on the noise of a single listing. Week-end candidates make the 100 base fall on
  the trading date of a weekly row. Two passes keep memory at per-index sums (no price matrix);
  the second pass is rare and small.
- **Alternatives**: Any trading day with ≥ 5 members (rejected: the base would fall mid-week, not
  on a stored row's date); start on the sector's first stored week (superseded by the owner rule);
  keep every member's closes in memory for one pass (rejected: 1 GB VM).

## R8. Old ratio rule and rows before the start date

- **Decision**: Remove the FR-39a SMA-to-price ratio bounds and ratio columns from
  `BASE_WEEK_STATS_SQL`; the base-week query now only supplies `ticker_count`, `trading_date`,
  and `pct_uptrend` for the start week. `write_index_weeks` writes only weeks `>= S`; the rebuild
  already deletes all of a country's rows first, which removes the UK rows before 2025-10-03.
- **Rationale**: Spec assumptions; FR-013.

## R9. Documentation

- **Decision**: Nothing under `project-docs/` changes (PRD, FEATURES, MIGRATIONS, RFCs are frozen,
  constitution v1.1.0). This feature's documentation lives only in `specs/001-index-initial-sma/`.
  `.cursor/rules/RULES.mdc` (agent guidance, not product documentation) gets its `indices`
  base-week sentence and the `compute_indices.py` "no yfinance" note updated so agents do not
  follow the old rule.
- **Rationale**: Owner decision 2026-10-07: all new documentation in Spec Kit docs.
- **Alternatives**: One-line pointers in the PRD at FR-39 / FR-39a (rejected: owner wants
  `project-docs/` untouched).

## R10. Script responsibilities

- **Decision**: `compute_indices.py` becomes a one-off initialization script (like
  `backfill_sma.py`): per country (`--country`, or all), it downloads daily data, computes the
  anchors, deletes the country's `indices` rows, and writes the full weekly time series from the
  start week. It is never cron-scheduled and has no incremental mode (`refresh_indices` with
  `week_starts` is removed). `fetch_sma.py` owns the weekly update: a `_run_index_update` step,
  after the metrics upsert and retention purge, calls `write_index_weeks` (SQL in `db/indices.py`,
  chaining in `equity_index.py`) for the weeks it wrote, logs outliers and indices without
  history, and no longer imports `compute_indices`.
- **Rationale**: Owner decision 2026-10-07; matches Principle I (one-off scripts stay manual) and
  keeps the weekly path download-free for indices.
- **Alternatives**: Keep one `refresh_indices` serving both (rejected: mixes the one-off
  initialization and the weekly update in one entrypoint).

## R11. All-or-nothing initialization per country

- **Decision**: The initialization computes all anchors for a country before touching the
  database, then loads the country's stored index tickers (`load_index_tickers`, new parameterized
  query in `db/indices.py`). If any stored index has no anchor, the country is skipped: no delete,
  no write, an error naming the missing indices, and exit code 1 after the other countries have
  run. An index anchored on a later start date (R7) is not missing; an
  index that never reaches 5 listed members is not counted as missing either (its old rows go with
  the delete) and is logged. Otherwise the
  country is deleted and rewritten in one transaction as before.
- **Rationale**: `write_index_weeks(rebuild=True)` deletes and writes in one transaction, which
  protects against database errors but not against an empty or incomplete download; without this
  check a failed download would commit the delete and leave the indices empty, and the weekly
  update cannot recover them.
- **Alternatives**: Replace only the indices that got an anchor (rejected: mixes old and new bases
  within a country, which makes the per-week sector z-scores meaningless, and `write_index_weeks`
  replaces a country's rows per week together); a minimum download-coverage threshold (not
  adopted: equal weighting keeps a subset anchor reasonable, missing members are logged, and a
  rerun is cheap).

## R12. New sector in the weekly run (FR-016)

- **Decision**: In `_run_index_update`, per country with stored index rows: expected sector
  index tickers = sector keys (`sector_key`) of the country's `*_tickers` rows; missing = expected
  minus `load_index_tickers`. For the missing sectors, call `compute_anchors` with their members
  only, the common start date, and the oldest stored metrics week (for the bridge, R4); it picks
  each sector's start date by the R7 rule. Then call `write_index_weeks(..., only_tickers=<new
  sector tickers>, anchors=...)` for all stored weeks from each anchor's week through the latest:
  for each week it computes only those tickers' rows (base row at the anchor week, chained after),
  keeps the other indices' stored rows as they are, and recomputes the week's sector z-scores over
  the stored rows plus the new ones. A failed download or a sector that never reaches 5 listed
  members → no anchor → no rows and a warning; the next weekly run tries again because the sector
  is still missing.
- **Rationale**: Owner decisions 2026-10-07 / 2026-10-08: new sectors start automatically with
  the same start-date rule and initial SMA calculation as `compute_indices.py`. Reusing
  `compute_anchors` keeps one implementation. Writing only the new tickers protects the other
  indices' rows: a full per-week rewrite would drop every base row it has no anchor for. A new
  sector is rare and has tens to a few hundred stocks (a few batches), so the weekly run stays
  well inside its window and rate limits (Principles I, II).
- **Alternatives**: Reuse the daily bars `fetch_sma.py` already downloads (rejected: 300 calendar
  days ≈ 205 trading days instead of 250, only stale tickers, frames are discarded per batch);
  manual `compute_indices.py --sector` (rejected by the owner); start on the sector's first week
  (superseded by the 5-member rule).

## R13. Configurable start date

- **Decision**: The common start date is `BaseConfig.index_start_date`, read from
  `INDEX_START_DATE` (ISO date, default `2025-10-03`; an invalid value raises `ValueError` at
  config load). `compute_indices.py` and `fetch_sma.py` read it through `AnchorSettings` and
  `start_week`; nothing hardcodes the date. Moving it (for example to `2025-10-10` once retention
  has removed the 2025-10-03 week) only needs the env var in `.env` / the GitHub `production`
  environment and a rerun of the initialization for all countries.
- **Rationale**: Owner request 2026-10-08; retention removes one week every Saturday, so the
  owner may prefer to move the start date instead of relying on the bridge.
- **Alternatives**: A CLI flag on `compute_indices.py` only (rejected: the weekly run also needs
  the date for new sectors and `start_week`, so it must come from the shared config).
