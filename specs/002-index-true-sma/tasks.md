---

description: "Task list for 002-index-true-sma"
---

# Tasks: Index SMA-50 / SMA-200 as True Moving Averages of the Index Price

**Input**: Design documents from `/specs/002-index-true-sma/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included — constitution Principle VII requires unit tests for every pure-logic change
and mocked DB / yfinance for I/O. Run with `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q`; never
against the `.env` or production database, and never by running `fetch_sma.py`.

**Organization**: Tasks are grouped by user story (spec.md). US1 and US2 share the daily series
(research R1); US3 depends on US1 and US2.

**Note on intermediate state**: Phase 2 changes the `write_index_weeks` signature, which breaks
its callers in `fetch_sma.py` (fixed in US2) and `compute_indices.py` (fixed in US3). Between
checkpoints run only the test files named in the phase; the full suite is green again at the US3
checkpoint.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US3)
- Paths are repository-root relative (single project, see plan.md)

---

## Phase 1: Setup

**Purpose**: Download window (research R3)

- [X] T001 In `fetch_sma.py` change `HISTORY_DAYS = 300` to `400` with a one-line comment that
  the window covers SMA-200 plus the index's 250-trading-day series (≈275 trading days); confirm
  `tests/test_fetch_sma.py` still passes (stock SMAs and growth use only the tail of the download)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The daily level series and the new write path that every story uses

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T002 Add `daily_levels(averages: dict[date, float], pin_date: date, pin_level: float) ->
  dict[date, float]` to `index_anchor.py` (research R1, data-model.md): sorted series dates; pin
  snaps to the latest date ≤ `pin_date` (raise `ValueError` when no such date exists); forward
  `level(d) = level(prev) × (1 + avg(d))`, backward `level(prev) = level(d) / (1 + avg(d))`
- [X] T003 [P] Add `fold_close(accumulator, index_tickers, close, *, max_growth, min_growth,
  until: date | None = None, after: date | None = None) -> int` to `index_anchor.py`: folds one
  stock's `daily_returns` into the `DailyAccumulator`, keeping only returns `≤ until` / `> after`
  when given, and returns the number of daily returns dropped as outliers (make `daily_returns`
  able to report drops, e.g. a private helper returning `(returns, dropped)`)
- [X] T004 [P] Unit tests in `tests/test_index_anchor.py`: `daily_levels` pinned in the middle
  (forward and backward values), pinned on the first and last date, pin on a non-series date
  snaps back, pin before all dates raises; `fold_close` with `until` / `after` windows and the
  dropped count
- [X] T005 [P] In `equity_index.py` rename `build_base_row` to `build_index_row(definition, *,
  trading_date, ticker_count, levels: IndexLevels, pct_uptrend=None)` without the price-100 check;
  remove `build_chained_row`; update `tests/test_compute_indices.py` (or the equity-index tests)
  that reference either function
- [X] T006 In `db/indices.py` (research R6): define `WeekLevels(trading_date, levels:
  IndexLevels, days_used: int)` (frozen dataclass; import it in `index_anchor.py` or define it
  there and import here under `TYPE_CHECKING`); change `write_index_weeks(database_url,
  week_levels: dict[date, dict[str, WeekLevels]], *, country, rebuild=False, only_tickers=None)
  -> IndexWriteResult`: per week (ascending) run `BASE_WEEK_STATS_SQL` for `ticker_count` /
  `pct_uptrend`, build a row with `build_index_row` for every index ticker in that week's levels
  whose sector group has stats (sector key derived from the ticker as in `_stored_row`), apply
  `with_sector_z_scores`, and replace the week as today (`only_tickers` keeps the other stored
  rows); remove `CHAINED_WEEK_STATS_SQL`, `GAP_WEEK_STATS_SQL`, the `start_week` / `anchors` /
  growth-bound parameters and `skipped` from the result
- [X] T007 In `db/indices.py` add `load_previous_indices(database_url, country, before: date) ->
  dict[str, tuple[date, Decimal]]` (ticker → latest `trading_date`, `current_price` before
  `before`) using the existing `LOAD_PREVIOUS_INDICES_SQL`
- [X] T008 Mocked-connection tests in `tests/test_compute_indices.py` for T006–T007: rows built
  from `week_levels` with stats from `BASE_WEEK_STATS_SQL` (one `%s`); an index without stats that
  week gets no row; z-scores across sectors; `only_tickers` keeps other stored rows; `rebuild`
  deletes the country first; `load_previous_indices` maps rows; remove tests for the dropped SQL
  and parameters

**Checkpoint**: `pytest tests/test_index_anchor.py tests/test_compute_indices.py -k "levels or
fold or write_index_weeks or previous or build_index_row"` passes

---

## Phase 3: User Story 1 - Weekly index SMAs are true moving averages (Priority: P1) 🎯 MVP

**Goal**: SMA-50 / SMA-200 of a written week are the means of the last 50 / 200 daily levels
(FR-001, FR-002)

**Independent Test**: From a known daily series, `week_levels` returns SMAs equal to the means of
the last 50 / 200 levels up to the week's last date

### Tests for User Story 1

- [X] T009 [P] [US1] Tests in `tests/test_index_anchor.py` for `week_levels`: row date is the last
  series date in the week; `row_date` override (start week) uses that date; price = level on the
  row date; SMA-50 / SMA-200 = means of the last 50 / 200 levels up to it, as `Decimal` with six
  decimals; fewer than 200 levels → mean of those and `days_used` < 200; no date in the week →
  `None`; flat series → SMA-50 = SMA-200 = price (spec US1 scenario 2)
- [X] T010 [P] [US1] Test in `tests/test_index_anchor.py`: for one synthetic stock, a one-member
  index's momentum from `fold_close` + `daily_levels` + `week_levels` equals
  `compute_smas`-based momentum of the stock on the same date (spec US1 scenario 3; compare
  `sma_50 / sma_200` ratios to six decimals)

### Implementation for User Story 1

- [X] T011 [US1] Implement `week_levels(levels: dict[date, float], week_start: date, *, row_date:
  date | None = None) -> WeekLevels | None` in `index_anchor.py` (data-model.md); replace
  `initial_smas` and `reconstruct_levels` with it and `daily_levels`, and update their remaining
  callers in `index_anchor.py` (`build_anchor` until US3 removes it)

**Checkpoint**: `pytest tests/test_index_anchor.py` passes

---

## Phase 4: User Story 2 - Weekly index price follows the daily index (Priority: P1)

**Goal**: The weekly run chains each index's price over every trading day since its latest stored
row and writes price and true SMAs from that series, reusing its stock download (FR-003, FR-005,
FR-009, FR-010, FR-011; research R2, R4, R7)

**Independent Test**: With a stored previous row at 105 and members up 1% on one day, the weekly
update writes 105 × 1.01 and SMAs from the series pinned at that row, with no extra download on a
full run

### Tests for User Story 2

- [X] T012 [P] [US2] Tests in `tests/test_fetch_sma.py` for folding in `main`: every downloaded
  batch is folded into one `DailyAccumulator` with the index tickers of each symbol (market +
  sector via `index_tickers_for` and `country_set_for`); a failed batch folds nothing
- [X] T013 [P] [US2] Tests in `tests/test_fetch_sma.py` for the supplemental download: members
  not folded (skipped as fresh, failed batch) are downloaded once in batches and folded; nothing
  is downloaded when every member was folded or when no index update runs
- [X] T014 [P] [US2] Tests in `tests/test_fetch_sma.py` for `_run_index_update`: pins from
  `load_previous_indices(…, before=min(week_starts))`; price 105 × 1.01 case (spec US2 scenario
  1); a missed week is chained over all days since the pin (scenario 2); rewriting the same week
  pins at the previous week's row (scenario 3); pin older than the series → no row and an error
  naming `compute_indices.py --country` (R4); index without a series date in the week → no row
  and a warning; a country without index rows → existing warning
- [X] T015 [P] [US2] Update the index-update stub in `tests/test_retention.py` to the new
  `_run_index_update` signature

### Implementation for User Story 2

- [X] T016 [US2] In `fetch_sma.py` `main`: create one `DailyAccumulator`; after
  `metric_rows_from_batch`, fold each symbol's close (`_closes` + `fold_close`, outlier bounds
  from config) into it with `index_tickers_for(entry, country_set_for(market=…, symbol=…))`;
  track folded symbols; keep the per-country dropped counts
- [X] T017 [US2] In `fetch_sma.py` add `_fold_missing_members(config, watchlist, folded,
  accumulator) -> dict[CountrySet, int]`: downloads members not in `folded` with `download_batch`
  (same window, batches, delay, retries; failed batches logged, run continues) and folds them;
  log `Index history: downloading N member(s) not in this run`; called only when `week_starts` is
  non-empty
- [X] T018 [US2] Rewrite `_run_index_update(config, week_starts, accumulator, dropped)` in
  `fetch_sma.py`: per country with index rows, `load_previous_indices(…, before=min(week_starts))`;
  per index pinned there, `daily_levels(accumulator.averages(ticker), pin_date, pin_price)` (R4
  error when the pin is older than the first series date) and `week_levels` for each week in
  `week_starts`; `write_index_weeks(database_url, week_levels, country=country)`; log market rows,
  the dropped daily returns per country, and the weekly outliers (reword `log_excluded_outliers`
  to "weekly outlier(s)", R7); keep the try/except around `_start_new_sectors`
- [X] T019 [US2] Interim step in `fetch_sma.py` `_start_new_sectors` (replaced in T024): build
  `week_levels` from each anchor's start-date series (`daily_levels` pinned at 100 on its start
  date from the anchor scan's averages) so it calls the T006 `write_index_weeks` signature; if
  that is not practical before US3, make it log a warning naming the missing sectors and return
  without writing

**Checkpoint**: `pytest tests/test_fetch_sma.py tests/test_retention.py` passes

---

## Phase 5: User Story 3 - Initialization writes true SMAs for every stored week (Priority: P2)

**Depends on User Stories 1 and 2.**

**Goal**: The one-off initialization and new sectors write every week from a series pinned at 100
on the start date (FR-007, FR-008; research R5)

**Independent Test**: Initialize a country with mocked downloads; every row's price equals the
series level on its date (100 on the start date) and its SMAs the means of the last 50 / 200
levels

### Tests for User Story 3

- [X] T020 [P] [US3] Replace the bridge tests in `tests/test_index_anchor.py`
  (`WeeklyAccumulator`, `build_anchor`, bridge equality) with `compute_index_series` tests:
  returns up to the start date only from members with a close on it, all members after it; the
  series is pinned at 100 on the start date; later start date via the second pass; never reaching
  the minimum → `below_minimum`; failed batch / missing symbols logged
- [X] T021 [P] [US3] Tests in `tests/test_compute_indices.py` for `initialize_indices`: weeks from
  each index's start week are written from its series (start week row on the start date at 100);
  a sector with a later start date gets no rows before its start week; all-or-nothing per country
  unchanged; no metrics → nothing written; per-index log line (contracts/compute-indices-cli.md)
- [X] T022 [P] [US3] Test in `tests/test_fetch_sma.py`: `_start_new_sectors` writes the new
  sector's stored weeks from its series with `only_tickers`, other indices unchanged

### Implementation for User Story 3

- [X] T023 [US3] In `index_anchor.py` replace `compute_anchors` / `Anchor` / `AnchorResult` with
  `compute_index_series(entries, country, *, settings, index_tickers=None) -> SeriesResult(series:
  dict[str, IndexSeries], below_minimum, missing_symbols)` (data-model.md): `_scan` folds returns
  `≤ start_date` only for members with a close on it and returns `> start_date` for all members
  (`fold_close`), drops the weekly bridge; remove `WeeklyAccumulator`, `_eligible_growth`,
  `_bridge_weeks`, `build_anchor`, and the lazy `metric_rows_from_weekly_samples` import; update
  the module docstring
- [X] T024 [US3] In `fetch_sma.py` `_start_new_sectors`: use `compute_index_series` for the
  missing sectors and write stored weeks from each series' start week with `week_levels`
  (`row_date` = start date on the start week) via `write_index_weeks(…, only_tickers=…)`
- [X] T025 [US3] In `compute_indices.py` `_initialize_country`: use `compute_index_series`; build
  `week_levels` for every stored week ≥ each index's start week; all-or-nothing check against
  `load_index_tickers` (stored − series − below_minimum); `write_index_weeks(…, rebuild=True)`;
  per-index log (`start_date`, first / last row date, start-date SMAs, momentum, `days_used`);
  update the module docstring and parser description

**Checkpoint**: `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q` passes (full suite)

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T026 [P] Update `.cursor/rules/RULES.mdc`: the `indices` data-model sentence (price and SMAs
  from the index's daily series; SMAs = 50 / 200-day means; weekly run pins at the latest stored
  row, initialization at 100 on the start date; outliers dropped per day; `ticker_count` rule);
  the Weekly growth bullet (growth columns drive the outlier email, not the indices); the
  `fetch_sma.py` row (≈400d download, index daily series from the same download, supplemental
  download of skipped members); the `index_anchor.py` row. Do not edit `project-docs/`
- [X] T027 [P] Update the `fetch_sma.py` module docstring (index update from the daily series)
- [X] T028 Grep for leftovers of removed names (`CHAINED_WEEK_STATS_SQL`, `GAP_WEEK_STATS_SQL`,
  `build_chained_row`, `build_base_row`, `compute_anchors`, `WeeklyAccumulator`, `Anchor`) across
  `*.py` and `tests/`; `tests/test_sql_security.py` still passes
- [X] T029 Run `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q`; all tests pass
- [ ] T030 Run quickstart.md §2–§4 against a local Docker Postgres 16 (never the `.env`
  database); compare one `US-IDX` row with a notebook-computed 50 / 200-day mean (SC-001)
- [ ] T031 Production rollout (owner, manual): after deploy, run `pipenv run python
  compute_indices.py --country us`, then `swe`, `uk`; check exit 0 and the summary lines
  (quickstart.md §5)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none
- **Foundational (Phase 2)**: after Setup; blocks all stories
- **US1 (Phase 3)**: after Foundational
- **US2 (Phase 4)**: after Foundational and US1 (`week_levels`)
- **US3 (Phase 5)**: after US1 and US2
- **Polish (Phase 6)**: after US3

### Within Each Story

- Tests first (they fail), then implementation
- `index_anchor.py` before `fetch_sma.py` / `compute_indices.py`

### Parallel Opportunities

- Phase 2: T003, T004, T005 in parallel (T002 first for T004's `daily_levels` cases)
- US1: T009 and T010 in parallel
- US2: T012–T015 in parallel (different test cases / files)
- US3: T020, T021, T022 in parallel (three test files)
- Polish: T026, T027 in parallel

---

## Parallel Example: User Story 2

```bash
Task: "Folding tests in tests/test_fetch_sma.py (T012)"
Task: "Supplemental download tests in tests/test_fetch_sma.py (T013)"
Task: "Retention stub in tests/test_retention.py (T015)"
```

---

## Implementation Strategy

### MVP First (User Story 1)

1. Setup + Foundational
2. US1: `week_levels` — the definition of a true index SMA, verified in isolation
3. Stop and validate the US1 tests

### Incremental Delivery

1. US2 makes the weekly run write true SMAs from the stored row onward (deployable on its own;
   stored history keeps 001 values until initialization)
2. US3 rewrites stored history and new sectors with the same definition
3. Polish, local end-to-end, owner rollout

---

## Notes

- [P] tasks = different files, no dependencies
- Commit after each phase; do not commit `.env`
- `project-docs/` is frozen; documentation changes go to `specs/002-index-true-sma/` and
  `.cursor/rules/RULES.mdc`
