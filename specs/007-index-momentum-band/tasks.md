---

description: "Task list for 007 — index momentum band for member stocks"
---

# Tasks: Index Momentum Band for Member Stocks

**Input**: Design documents from `/specs/007-index-momentum-band/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/settings-and-log.md, quickstart.md

**Tests**: Included — constitution VII requires unit tests for pure logic and mocked I/O tests.

**Organization**: Tasks are grouped by user story so each story can be implemented and tested independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1 = stocks outside the band leave the indices (P1); US2 = band limits are settings (P2)
- Single project at repository root; tests in `tests/`; run with `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest`

---

## Phase 1: Setup

**Purpose**: Confirm a green baseline before changing the index computation.

- [X] T001 Run `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q` from the repo root and confirm all tests pass on the current `tests/` suite (baseline for SC-002)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Band settings with defaults exist and reach the index code; both stories build on them.

- [X] T002 Add `DEFAULT_INDEX_MOMENTUM_MIN = 0.15` / `DEFAULT_INDEX_MOMENTUM_MAX = 1.5` and `BaseConfig` fields `index_momentum_min` / `index_momentum_max` (defaults only, next to `index_min_components`) in `config.py`
- [X] T003 Add `momentum_min: float` and `momentum_max: float` to `AnchorSettings` and fill them in `AnchorSettings.from_config` from `config.index_momentum_min` / `config.index_momentum_max` in `index_anchor.py` (update every `AnchorSettings(...)` construction in `tests/test_index_anchor.py`, `tests/test_compute_indices.py`, `tests/test_fetch_sma.py` so the suite stays green)

**Checkpoint**: Settings carry the band; no behaviour change yet.

---

## Phase 3: User Story 1 - Stocks with an extreme SMA ratio do not move the indices (Priority: P1) 🎯 MVP

**Goal**: In every calendar week where a stock's SMA-50 / SMA-200 (last bar of the week, full 50 / 200 windows) is outside the inclusive band, it contributes nothing to its market and sector index's daily returns, start-date count, `ticker_count`, or `pct_uptrend` — in the one-off initialization, the weekly update, and new sector starts (FR-001–FR-004, FR-006, FR-007).

**Independent Test**: Initialize indices from mocked closes where one stock sits at ~0.009, one at ~1.62, and the rest inside the band; the out-of-band stocks' returns are absent in their weeks, the stats SQL receives the band parameters, the log lists them, and an all-in-band set gives the same levels as before.

### Tests for User Story 1

- [X] T004 [P] [US1] Add tests for `weekly_momentum(close)` in `tests/test_index_anchor.py`: ratio = rolling(50).mean / rolling(200).mean on each calendar week's last bar keyed by the week's Monday; `None` for weeks before the 200th bar
- [X] T005 [P] [US1] Add tests for the band in `_returns` / `fold_close` in `tests/test_index_anchor.py`: returns dropped in weeks with ratio 0.009 and 1.62, kept at exactly 0.15 and 1.5, kept when the ratio is `None`, in → out → in across three weeks (acceptance 5 / SC-005), excluded weeks recorded in the collector with their ratio, outlier-drop count unchanged, no band → identical output to today
- [X] T006 [P] [US1] Add a test in `tests/test_index_anchor.py` that `_scan` / `compute_index_series` does not count an out-of-band member's close toward `INDEX_MIN_COMPONENTS` on a candidate start date (index starts at the next week that has enough in-band members), and that an all-in-band member set yields the same `SeriesResult` levels as without a band (SC-002)
- [X] T007 [P] [US1] Add tests in `tests/test_compute_indices.py` that `BASE_WEEK_STATS_SQL` contains a parameterized `m.sma_50 / m.sma_200 BETWEEN %s AND %s` filter and that `write_index_weeks(..., band=(low, high))` passes the two values as query parameters (no interpolation)
- [X] T008 [P] [US1] Add tests in `tests/test_compute_indices.py` that `_initialize_country` passes the band to the series computation and `write_index_weeks`, and logs `Indices <c>: momentum band [low, high] excluded <n> stock-week(s) from <m> stock(s)` plus `Index band: excluded <SYMBOL> week <week_start> ratio <r>` for stocks excluded in the latest stored week (contracts/settings-and-log.md)
- [X] T009 [P] [US1] Add tests in `tests/test_fetch_sma.py` that `fold_index_history`, `_fold_missing_members`, `_start_new_sectors` and the `write_index_weeks` call in `_run_index_update` all apply the band, that the band log lines appear for the written week(s), and that `HISTORY_DAYS == 600`

### Implementation for User Story 1

- [X] T010 [US1] Implement pure `weekly_momentum(close: pd.Series) -> dict[date, float | None]` in `index_anchor.py` (full-window rolling means of the dropna'd closes, value on each week's last bar, key = Monday of that bar's date; `None` when SMA-200 is NaN or ≤ 0) (research R1)
- [X] T011 [US1] Add keyword-only `band: tuple[float, float] | None = None` and `excluded: dict[str, dict[date, float]] | None = None` (plus a `symbol` for recording) to `_returns` and `fold_close` in `index_anchor.py`: when `band` is set, compute `weekly_momentum` once and skip any return whose week's ratio is outside `[low, high]` (inclusive; `None` → kept); record `excluded[symbol][week_start] = ratio`; outlier `dropped` count unchanged (research R2)
- [X] T012 [US1] In `_scan` (and through `compute_index_series`) in `index_anchor.py`, pass `band=(settings.momentum_min, settings.momentum_max)` to every `fold_close`, count a member toward the start-date minimum only when its ratio for that week is in band or `None`, and expose the collected exclusions on `SeriesResult` (research R3)
- [X] T013 [US1] Raise `DOWNLOAD_LOOKBACK_DAYS` from 400 to 700 in `index_anchor.py` so every week in the 250-day history has 200 prior bars (research R5)
- [X] T014 [US1] Add `AND m.sma_50 / m.sma_200 BETWEEN %s AND %s` to `BASE_WEEK_STATS_SQL` and a keyword-only `band: tuple[float, float]` parameter on `write_index_weeks` that supplies the two values in the query parameters (correct order with the existing ones) in `db/indices.py` (research R4)
- [X] T015 [US1] In `compute_indices.py` `_initialize_country`, pass the band from `AnchorSettings` to `write_index_weeks`, and log the INFO summary and per-stock WARNING lines (latest stored week only) from `SeriesResult` exclusions per contracts/settings-and-log.md (research R7)
- [X] T016 [US1] In `fetch_sma.py`: raise `HISTORY_DAYS` from 400 to 600; pass the band and an exclusions collector through `fold_index_history`, `_fold_missing_members` and `_start_new_sectors`; pass `band=` to `write_index_weeks` in `_run_index_update`; log the INFO summary and one WARNING per stock excluded in the week(s) written (research R5, R7)
- [X] T017 [US1] Run `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q` and fix failures until T004–T009 and the existing suite pass

**Checkpoint**: Band applied everywhere with default limits; US1 independently testable.

---

## Phase 4: User Story 2 - The band can be tuned without a code change (Priority: P2)

**Goal**: `INDEX_MOMENTUM_MIN` / `INDEX_MOMENTUM_MAX` override the defaults; an invalid pair stops the run with a clear configuration error (FR-005, SC-004).

**Independent Test**: With env `INDEX_MOMENTUM_MIN=0.5`, `INDEX_MOMENTUM_MAX=2.0`, `get_config()` returns them and a stock at 0.3 is excluded while one at 1.8 is kept; `0.5 / 0.5` or `0 / 1.5` raises `ValueError`.

### Tests for User Story 2

- [X] T018 [P] [US2] Add tests in `tests/test_config.py`: defaults 0.15 / 1.5 with no env; env `0.5` / `2.0` read into `index_momentum_min` / `index_momentum_max`; `ValueError` naming both settings when min ≥ max and when min ≤ 0
- [X] T019 [P] [US2] Add a test in `tests/test_index_anchor.py` that `fold_close` with `band=(0.5, 2.0)` drops a ratio-0.3 week and keeps a ratio-1.8 week (acceptance US2-2)

### Implementation for User Story 2

- [X] T020 [US2] In `config.py` read `INDEX_MOMENTUM_MIN` / `INDEX_MOMENTUM_MAX` with `_env_float` (same place as `OUTLIER_MAX_GROWTH`), and raise `ValueError("INDEX_MOMENTUM_MIN must be above 0 and below INDEX_MOMENTUM_MAX …")` following the existing validation pattern
- [X] T021 [US2] Confirm `compute_indices.py` and `fetch_sma.py` surface the `ValueError` from `get_config()` as an `ERROR` log and exit 1 before any write (add handling only if they do not already, matching the outlier-limit behaviour); run `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest tests/test_config.py tests/test_index_anchor.py -q`

**Checkpoint**: US1 and US2 both pass independently.

---

## Phase 5: Polish & Cross-Cutting Concerns

- [X] T022 [P] Update `README.md`: in the equal-weighted indices section, state that a stock is a member in a week only when its SMA-50 / SMA-200 (week's last bar) is within 0.15–1.5 inclusive (no ratio → included), that it affects level, SMAs, member count and uptrend %, and add `INDEX_MOMENTUM_MIN` / `INDEX_MOMENTUM_MAX` to the settings table (FR-008, RULES rule 6)
- [X] T023 [P] Update the `indices` data-model sentence in `.cursor/rules/RULES.mdc` with the band rule and settings, plus the `fetch_sma.py` / `compute_indices.py` script descriptions where they describe members (do not edit `project-docs/`)
- [X] T024 Run the full suite `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q` and walk the unit-test scenarios in `specs/007-index-momentum-band/quickstart.md`; note in the completion summary that the owner re-runs `./scripts/run_compute_indices.sh` per country after deploy

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (T001)** → **Foundational (T002–T003)** → **US1 (T004–T017)** → **US2 (T018–T021)** → **Polish (T022–T024)**
- US2 depends only on Foundational for config fields; its `fold_close` test (T019) needs T011.

### Within User Story 1

- Tests T004–T009 first (they fail until implemented).
- T010 → T011 → T012 (same file, sequential); T013 after T012.
- T014 independent of T010–T013 (different file).
- T015 needs T012 + T014; T016 needs T011 + T014.
- T017 last.

### Parallel Opportunities

- T004–T009 (tests, different test files / independent cases).
- T014 alongside T010–T013.
- T018 and T019; T022 and T023.

---

## Parallel Example: User Story 1

```bash
Task: "weekly_momentum tests in tests/test_index_anchor.py"            # T004
Task: "BASE_WEEK_STATS_SQL band tests in tests/test_compute_indices.py" # T007
Task: "weekly path band tests in tests/test_fetch_sma.py"              # T009
Task: "band filter in db/indices.py"                                    # T014 (parallel with T010–T013)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. T001–T003 → T004–T017.
2. Validate: full suite green; default band applied in initialization and weekly update.

### Incremental Delivery

1. US1 with fixed defaults (deployable).
2. US2 adds env overrides + validation.
3. Polish: README / RULES; owner re-runs the initialization per country after deploy.

---

## Notes

- No schema change, no migration, no change to stock metrics or the outlier email (FR-009).
- SQL stays in `db/indices.py`, parameterized.
- Do not commit until asked.
