---

description: "Task list for 001-index-initial-sma"
---

# Tasks: Index Initial SMA from Daily History

**Input**: Design documents from `/specs/001-index-initial-sma/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included — constitution Principle VII requires unit tests for every pure-logic change
and mocked DB / yfinance for I/O. Run with `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q`; never
against the `.env` or production database, and never by running `fetch_sma.py`.

**Organization**: Tasks are grouped by user story (spec.md) so each story can be implemented and
tested independently.

**Script roles (research R10)**: `compute_indices.py` = one-off manual initialization (download,
anchors, full weekly series). `fetch_sma.py` = weekly update (chains the new week onto existing
indices without downloading; creates a new sector index with the same start-date rule and a download of that sector's stocks
only, research R7, R12).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US4)
- Paths are repository-root relative (single project, see plan.md)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: New module and test file skeletons

- [X] T001 Create `index_anchor.py` with a module docstring (pure anchor logic + one download
  wrapper, specs/001-index-initial-sma), a frozen dataclass `Anchor(ticker, week_start,
  trading_date, levels: IndexLevels, days_used: int)` per data-model.md, and an
  `AnchorSettings` dataclass (start_date, trading_days, max/min growth, yf batch size / delay /
  max retries / retry base seconds)
- [X] T002 [P] Create `tests/test_index_anchor.py` with a helper that builds synthetic daily close
  series (`pd.Series` indexed by business days) for unit tests

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Config, sector-key parity, and the anchor hook in the shared index writer

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T003 Add `DEFAULT_INDEX_START_DATE = date(2025, 10, 3)`,
  `DEFAULT_INDEX_HISTORY_TRADING_DAYS = 250`, and `DEFAULT_INDEX_MIN_COMPONENTS = 5` plus
  `BaseConfig` fields `index_start_date`, `index_history_trading_days`, and
  `index_min_components` in `config.py`; parse `INDEX_START_DATE` (ISO date, new `_env_date`
  helper, `ValueError` on bad input), `INDEX_HISTORY_TRADING_DAYS` (`ValueError` if < 200), and
  `INDEX_MIN_COMPONENTS` (`ValueError` if < 1) in `_from_env`
- [X] T004 [P] Add tests for the new defaults, env overrides, and invalid values in
  `tests/test_config.py`
- [X] T005 Add `sector_key(raw: str | None) -> str | None` to `index_anchor.py` mirroring
  `SECTOR_KEY_SQL` in `db/indices.py` (trim, lower, spaces → `-`, blank → None)
- [X] T006 [P] Add parity tests for `sector_key` ("Consumer Cyclical", " Technology ", "", None,
  "consumer-cyclical") in `tests/test_index_anchor.py`
- [X] T007 Change `build_base_row` in `equity_index.py` to take `levels: IndexLevels` (price must
  equal `BASE_INDEX_PRICE`) instead of `avg_sma_50_ratio` / `avg_sma_200_ratio`; update its
  docstring and its tests in `tests/test_compute_indices.py`
- [X] T008 Simplify `BASE_WEEK_STATS_SQL` in `db/indices.py` to return only `GROUPING(sector)`,
  `sector`, `COUNT(*)`, `MAX(trading_date)`, `pct_uptrend` with one `%s` (drop the ratio averages,
  the FR-39a ratio bounds, and `ratio_bounds`); update the SQL-shape assertions in
  `tests/test_compute_indices.py`
- [X] T009 Extend `write_index_weeks` in `db/indices.py` with keyword args
  `start_week: date | None = None` and `anchors: dict[str, Anchor] | None = None`: skip weeks
  `< start_week`; for an index with no stored previous row use its anchor — base row from
  `anchor.levels` and the week's base stats when `anchor.week_start == week`, or treat the anchor
  as the previous row when `anchor.week_start == week - 7 days`; with no usable anchor, write no
  row for that index. Return the written rows and the skipped index tickers (e.g. a small
  `IndexWriteResult` dataclass). Add `only_tickers: set[str] | None = None`: when given, compute
  and replace only those index rows per week, keep the country's other stored rows for the week
  unchanged, and recompute the week's sector z-scores over stored + new rows (research R12)
- [X] T010 Add mocked-connection tests for T009 (anchor as base row, anchor as previous week,
  weeks before `start_week` skipped, index without row and anchor reported as skipped,
  `only_tickers` leaves other rows' levels untouched and updates their z-scores) in
  `tests/test_compute_indices.py`

- [X] T011 Add `LOAD_COUNTRY_INDEX_TICKERS_SQL` (`SELECT DISTINCT ticker FROM indices WHERE
  country = %s`) and `load_index_tickers(database_url, country) -> set[str]` to `db/indices.py`,
  with a mocked-connection test in `tests/test_compute_indices.py` (research R11)

**Checkpoint**: Config, sector keys, and anchor wiring ready — user stories can start

---

## Phase 3: User Story 1 - Initial SMA levels are true moving averages (Priority: P1) 🎯 MVP

**Goal**: The one-off initialization writes, for every index, a start row with price 100 and
SMA-50 / SMA-200 equal to the averages of the reconstructed daily index levels (FR-002 to FR-006,
FR-008, FR-010, FR-011).

**Independent Test**: With mocked downloads of known daily closes, `compute_indices.py` writes a
start row with price 100 and SMA-50 / SMA-200 equal to the means of the last 50 / 200
reconstructed levels (spec US1 acceptance 1–3).

### Tests for User Story 1

- [X] T012 [P] [US1] Unit tests in `tests/test_index_anchor.py`: daily returns per stock
  (consecutive bars only, outlier days dropped), equal-weighted accumulation across stocks with
  missing days, backward reconstruction (two stocks +1% on the last day → previous level
  100 / 1.01), SMA-50 / SMA-200 as means of the last 50 / 200 levels, fewer than 200 levels
  (mean of available, `days_used` reported), members without a close on the start date excluded,
  sector vs market accumulation, `find_start_date` (≥ 5 members on the common start date → that
  date; fewer → first later week-end with ≥ 5; never → None; custom minimum), and SC-003: in a 50-stock index where one stock falls 99% over
  the window, the initial SMA-200 moves by no more than that stock's 1/50 share
- [X] T013 [P] [US1] Tests for `compute_anchors` with `download_batch` mocked (MultiIndex and
  single-ticker frames, one failed batch logged and skipped, tickers missing from the download
  logged, an index with 4 members on the common start date anchored on the first week-end with
  5 via the second pass, an index that never reaches 5 gets no anchor) in
  `tests/test_index_anchor.py`

### Implementation for User Story 1

- [X] T014 [US1] Implement `daily_returns(close, *, start_date, trading_days, max_growth,
  min_growth) -> dict[date, float]` and a `DailyAccumulator` (per index ticker: date → sum,
  count) in `index_anchor.py` (research R2)
- [X] T015 [US1] Implement `reconstruct_levels(accumulator_for_index, start_date) -> list[Decimal]`
  (oldest → start date, start = 100), `initial_smas(levels) -> tuple[sma_50, sma_200,
  days_used]`, and `find_start_date(counts_by_date, candidates, min_components) -> date | None`
  in `index_anchor.py` (research R7)
- [X] T016 [US1] Implement `compute_anchors(tickers: list[TickerEntry], country, *, settings:
  AnchorSettings)` in `index_anchor.py`: `chunked` + `download_batch(start=start_date − 400 days)`
  with the yf batch size / delay / retries, extract `Close` per ticker like
  `metric_rows_from_batch`, membership = close on the start date, feed market + sector
  accumulators batch by batch (discard each batch's frame) and count members with a close per
  index and candidate date (common start date + each later week's last trading date); indices
  below `index_min_components` on the common start date get their start date from
  `find_start_date` and a second pass over just their members; return `{index_ticker: Anchor}`
  and log indices that never reach the minimum (research R7)
- [X] T017 [US1] Rewrite `compute_indices.py` as the one-off initialization (research R10): replace
  `refresh_indices` with `initialize_indices(database_url, *, country=None, settings)` that, per
  country, loads tickers (`load_tickers_from_db(..., country=...)`) and stored weeks
  (`load_distinct_week_starts`), calls `compute_anchors` before touching the database, then applies the all-or-nothing rule
  (research R11): if any ticker from `load_index_tickers` has no anchor, skip the country (no
  delete, no write), log an error naming the missing indices, continue with the other countries,
  and make `main` exit 1; otherwise call `write_index_weeks(..., rebuild=True,
  start_week=week_start_of(start_date), anchors=...)`; log per index the anchor week,
  initial SMA-50 / SMA-200, momentum, and `days_used`; remove the incremental `week_starts` mode
- [X] T018 [US1] Update `compute_indices.py` `main`: build `AnchorSettings` from config; module
  docstring and CLI description say "one-off manual initialization (never cron): downloads daily
  data, sets the start levels on INDEX_START_DATE, and writes the full weekly series" per
  contracts/compute-indices-cli.md
- [X] T019 [US1] Rewrite the `refresh_indices` tests in `tests/test_compute_indices.py` for
  `initialize_indices`: calls `compute_anchors` with the country's tickers, writes the start row
  with the anchor levels and momentum = SMA-50 / SMA-200 (FR-008), skips a country without stored
  metrics (anchors mocked); all-or-nothing (R11): a stored index without an anchor → no
  `write_index_weeks` call for that country, other countries still written, exit code 1; an index
  with a later start date (R7) or that never reaches 5 listed members is not counted as missing

**Checkpoint**: The initialization produces correct initial SMA levels — MVP

---

## Phase 4: User Story 2 - All indices share one start date, 2025-10-03 (Priority: P1)

**Goal**: Every index is anchored at 100 on 2025-10-03 with no rows before it; the initialization
after retention stays on the same anchor; a sector without stocks on the start date starts on
a later start date (FR-012 to FR-014, FR-016, research R4, R7).

**Independent Test**: Initialize with stored weeks starting before 2025-10-03 (UK) → no rows before
it; initialize with the start week purged → oldest row's levels equal those of an initialization
made while it was stored; an index with fewer than 5 stocks priced on the start date starts at
100 on the first later week-end with 5 (spec US2 acceptance 1–3).

### Tests for User Story 2

- [X] T020 [P] [US2] Unit tests for the weekly bridge in `tests/test_index_anchor.py`: weekly
  aggregation matches `CHAINED_WEEK_STATS_SQL` rules (positive values, all three growths in bounds,
  equal-weighted mean), empty week carries levels forward, result assigned to the week before
  the oldest stored week, bridged chain equals the stored chain on the same data
- [X] T021 [P] [US2] Tests in `tests/test_compute_indices.py`: initialization passes the oldest
  stored week to `compute_anchors` and writes only weeks ≥ start week (UK weeks before 2025-10-03
  dropped)

### Implementation for User Story 2

- [X] T022 [US2] Implement the bridge in `index_anchor.py`: when the oldest stored metrics week
  `M0` is after the start week `S`, build weekly stock rows from the same download with
  `metric_rows_from_weekly_samples` (from `backfill_sma.py`) for weeks `S+1 … M0−1`, fold them into
  per-index weekly sums batch by batch (never keep all rows), chain from the start-date levels, and
  return anchors at week `M0 − 7 days` (`compute_anchors` gets a `first_stored_week` argument)
- [X] T023 [US2] In `compute_indices.py` `initialize_indices`: restrict weeks to stored weeks
  `>= week_start_of(start_date)` and pass the oldest stored week to `compute_anchors`
- [X] T024 [US2] Test in `tests/test_compute_indices.py` that `initialize_indices` writes an
  index with a later start date (anchor from `compute_anchors`, research R7) from its own start
  week at 100, writes the other indices from 2025-10-03, and does not skip the country

**Checkpoint**: All indices share 2025-10-03; initialization after retention stays anchored

---

## Phase 5: User Story 3 - Weekly update in fetch_sma.py, later weeks unchanged (Priority: P1)

**Goal**: The weekly job `fetch_sma.py` updates the indices itself after storing the stocks'
growth: it chains the new week onto existing indices exactly as today without downloading,
creates a new sector index with the same start-date rule and initial SMAs from `compute_anchors`
(download of that sector's stocks only), and warns about a country without indices (FR-007,
FR-015, FR-016, research R6, R10, R12).

**Independent Test**: The weekly index update step chains existing indices from stored growth with
no download, starts a missing sector with `compute_anchors` called for that sector's stocks only,
and `fetch_sma.py` no longer imports `compute_indices` (spec US3 acceptance 1–3).

### Tests for User Story 3

- [X] T025 [P] [US3] Tests in `tests/test_fetch_sma.py` for `_run_index_update`: for each country,
  calls `write_index_weeks` with the stored weeks from the earliest written week onward,
  `start_week` from config, and the outlier bounds; with all indices present it never calls
  `compute_anchors`; with one sector missing it calls `compute_anchors` once with that sector's
  members, the common start date, and the oldest stored week, then `write_index_weeks` with
  `only_tickers={that sector}`, the anchor, and the stored weeks from the anchor's week onward; a failed sector download → no anchor, warning, other indices still
  written; a country without index rows → no write and "country <c> has no indices; run
  compute_indices.py --country <c>"; logs excluded outliers
- [X] T026 [P] [US3] Unit tests for `missing_sector_indices` in `tests/test_index_anchor.py`:
  expected sector tickers from `sector_key` of the tickers, minus stored index tickers, blank
  sectors ignored, members grouped per missing ticker
- [X] T027 [P] [US3] Update the index stub in `tests/test_retention.py` (`fetch_sma.refresh_indices`
  → the new weekly step) and keep the existing chained / gap-week tests in
  `tests/test_compute_indices.py` passing unchanged

### Implementation for User Story 3

- [X] T028 [US3] Implement `missing_sector_indices(tickers, stored_index_tickers, country) ->
  dict[str, list[TickerEntry]]` in `index_anchor.py` (research R12)
- [X] T029 [US3] In `fetch_sma.py`: remove `from compute_indices import refresh_indices`; replace
  `_run_indices` with `_run_index_update(config, week_starts)` that, per country, loads stored weeks
  (`load_distinct_week_starts`) from the earliest written week, calls `write_index_weeks(...,
  start_week=week_start_of(config.index_start_date), max_growth=..., min_growth=...)`, logs the
  market rows and outliers (`load_outliers`); then find missing sectors with
  `load_index_tickers` + `missing_sector_indices`, compute their anchors with `compute_anchors`
  (their members only, `AnchorSettings` from config, oldest stored week for the bridge; start date
  by research R7), and call `write_index_weeks(..., only_tickers=..., anchors=...)` for the stored
  weeks from the earliest anchor week; log each new sector's start date, initial levels, and
  `days_used`, and warn for a sector without anchor; skip a country without
  index rows with the warning; keep its position after the retention purge and before the
  outlier email
- [X] T030 [US3] Confirm `CHAINED_WEEK_STATS_SQL`, `GAP_WEEK_STATS_SQL`, and `build_chained_row`
  are unchanged and that `write_index_weeks` ignores anchors for indices with a stored previous
  row (verified by T025 / T027)

**Checkpoint**: Weekly index update runs inside `fetch_sma.py`; existing indices behave as before

---

## Phase 6: User Story 4 - Initialize existing indices with the corrected start (Priority: P2)

**Goal**: The owner can run the one-off initialization for one country or all countries and verify
the result (FR-009, SC-006).

**Independent Test**: `compute_indices.py --country swe` on a local database initializes every
`SWE-IDX*` index from 2025-10-03 with the corrected start (quickstart.md §2).

### Tests for User Story 4

- [X] T031 [P] [US4] Tests for `compute_indices.py` `main` in `tests/test_compute_indices.py`:
  `--country` limits the run to one country, no flag runs all three, `AnchorSettings` is built
  from config, exit code 1 on an unexpected error

### Implementation for User Story 4

- [X] T032 [US4] Add a per-country summary log in `compute_indices.py`: anchors computed, indices
  skipped without anchor, members missing from the download, rows written, and elapsed time
  (SC-006)

**Checkpoint**: Initialization ready for production use

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T033 [P] Update `.cursor/rules/RULES.mdc`: the `indices` base-week sentence (start date
  2025-10-03 from `INDEX_START_DATE`, initial SMAs from the reconstructed daily index price, no
  ratio limits); the Scripts table rows — `compute_indices.py` as a one-off manual initialization
  (downloads daily data, never cron) and `fetch_sma.py` doing the weekly index update; and the
  scope rule listing one-off scripts. Do not edit anything under `project-docs/`
  (constitution v1.1.0)
- [X] T034 [P] Update the parameterization check for the simplified `BASE_WEEK_STATS_SQL` (one
  `%s`) in `tests/test_sql_security.py`
- [X] T035 Run `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q`; all tests pass
- [ ] T036 Run quickstart.md §1–§4 against a local Docker Postgres 16 (never the `.env` database),
  including the initialization's elapsed time, and record the results in
  `specs/001-index-initial-sma/quickstart.md`
- [ ] T037 Production rollout (owner, manual): after deploy, run `pipenv run python
  compute_indices.py` once and the read-only checks in quickstart.md §5

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none
- **Foundational (Phase 2)**: after Setup — blocks all user stories
- **US1 (Phase 3)**: after Foundational — MVP
- **US2 (Phase 4)**: after US1 (extends `compute_anchors` and `initialize_indices`)
- **US3 (Phase 5)**: after US1 and US2 — `_run_index_update` (T029) calls `compute_anchors`
  (T016, US1) and the bridge (T022, US2) to create new sector indices; T029 also replaces the
  `refresh_indices` import that T017 removes, so implement T029 together with T017
- **US4 (Phase 6)**: after US1 and US2
- **Polish (Phase 7)**: after the stories to ship

### Within Each Story

- Tests first (they fail), then implementation, then the story checkpoint
- `index_anchor.py` pure functions before `compute_anchors`, before `compute_indices.py` wiring

### Parallel Opportunities

- T002 with T001; T004 and T006 alongside T005 / T007
- T012 and T013 together; T020 and T021 together; T025 and T027 together
- T033 and T034 together in Polish

---

## Parallel Example: User Story 1

```bash
Task: "Unit tests for daily returns, reconstruction, and initial SMAs in tests/test_index_anchor.py"
Task: "Tests for compute_anchors with download_batch mocked in tests/test_index_anchor.py"
```

---

## Implementation Strategy

### MVP First (User Story 1)

1. Phase 1 + Phase 2
2. Phase 3 (US1) → initialize locally (quickstart §2 without the retention step) and check the
   start row's SMAs
3. Stop and validate before US2

### Incremental Delivery

1. US1 → correct initial SMAs from the one-off initialization
2. US2 → common start date, bridge after retention
3. US3 (after US1 and US2) → weekly index update moved into `fetch_sma.py`, new sectors started
   automatically (ship together with US1 and US2: `fetch_sma.py` must stop importing
   `refresh_indices` once `compute_indices.py` is rewritten)
4. US4 → CLI summary and timing, then production initialization (T037)

### Timing note

Retention removes the 2025-10-03 week on 2026-10-10. Before US2's bridge (T022) exists, an
initialization after that date cannot anchor on 2025-10-03; ship US1 + US2 + US3 together if the
production initialization happens after 2026-10-10.

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks
- Commit after each task or logical group, only when the owner asks
- Never run `fetch_sma.py` or write tests against the `.env` / production database
