---

description: "Task list for 008 — weekly fetch for a missed trading date"
---

# Tasks: Weekly Fetch for a Missed Trading Date

**Input**: Design documents from `/specs/008-fetch-trading-date/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli.md, quickstart.md

**Tests**: Included — constitution VII requires unit tests for pure logic and mocked I/O tests.

**Organization**: Tasks are grouped by user story so each story can be implemented and tested independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1 = fill a missed week by running for a past date (P1); US2 = unsafe dates are refused (P2)
- Single project at repository root; tests in `tests/`; run with `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest`

---

## Phase 1: Setup

**Purpose**: Confirm a green baseline.

- [X] T001 Run `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q` from the repo root and confirm the current suite passes (baseline for "unchanged without the option")

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The download can stop at a date, and `fetch_sma.py` parses its command line; both stories build on these.

- [X] T002 [P] Add keyword-only `end: date | None = None` to `download_batch` in `yfinance_client.py` (inclusive last calendar day; pass `(end + timedelta(days=1)).isoformat()` as yfinance's exclusive `end`, `None` when not given; import `timedelta`; docstring notes the inclusive end) (research R2)
- [X] T003 [P] Add a test in `tests/test_yfinance_client.py` that patches `yfinance_client.yf.download` and checks `download_batch(["AAA"], date(2025, 3, 1), end=date(2026, 10, 30))` passes `start="2025-03-01"`, `end="2026-10-31"`, and that without `end` it passes `end=None`
- [X] T004 Add `import argparse`, a `build_parser()` with `--trading_date` (alias `--trading-date`, `dest="trading_date"`, `default=None`, `metavar="YYYY-MM-DD"`, help per contracts/cli.md; plain `date.fromisoformat` type for now) and change `main()` to `main(argv: list[str] | None = None)` that parses `argv if argv is not None else []`; `__main__` calls `sys.exit(main(sys.argv[1:]))` in `fetch_sma.py` (research R4)

**Checkpoint**: Existing suite still green (`main()` with no args behaves as before).

---

## Phase 3: User Story 1 - Fill a missed week by running the weekly job for a past date (Priority: P1) 🎯 MVP

**Goal**: `fetch_sma.py --trading_date D` stores for D's week exactly what a Saturday run on D would have — freshness check, download window, and download end all from the run date; index update and outlier email for that week as today (FR-001–FR-005, FR-007).

**Independent Test**: `main(["--trading_date", D])` with mocked I/O calls the freshness check with `today=D`, downloads from `D − HISTORY_DAYS` with `end=D`, downloads missing index members with the same window, and updates indices for D's week; `main()` without the option is unchanged.

### Tests for User Story 1

- [X] T005 [P] [US1] Add `test_main_trading_date_runs_as_of_that_date` in `tests/test_fetch_sma.py` (pattern of `test_main_folds_downloaded_batches_into_index_history`): `run_date = today − 14 days`; patch I/O including `_fold_missing_members` and `_run_index_update`; assert `filter_stale_tickers` got `today=run_date`, `download_batch` got `args[1] == run_date − timedelta(days=HISTORY_DAYS)` and `kwargs["end"] == run_date`, `_fold_missing_members` got `(start, run_date)` as its last two args, `_run_index_update` got `{week_start_of(run_date)}`, and the log contains `Running for trading_date=<run_date>`
- [X] T006 [P] [US1] Add `test_build_parser_trading_date` in `tests/test_fetch_sma.py`, parametrized over `--trading_date` / `--trading-date`: value `2026-10-30` parses to `date(2026, 10, 30)`; no option → `None`
- [X] T007 [P] [US1] Extend `test_main_folds_downloaded_batches_into_index_history` in `tests/test_fetch_sma.py` to assert `download_batch` was called with `end=None` (unchanged default run)

### Implementation for User Story 1

- [X] T008 [US1] In `fetch_sma.py` add keyword `end: date | None = None` to `_fold_missing_members` and pass `end=end` to its `download_batch` call; update its docstring ("through ``end`` (default: today)")
- [X] T009 [US1] In `fetch_sma.py` `main`: compute `run_date` (today UTC, or `args.trading_date`) and `end` (`args.trading_date`, else `None`); log `Running for trading_date=%s` when given; call `filter_stale_tickers(database_url, all_tickers, today=run_date)`; set `start = run_date - timedelta(days=HISTORY_DAYS)`; pass `end=end` to the main `download_batch` call and `end` to `_fold_missing_members` (research R1, R5)
- [X] T010 [US1] Run `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest tests/test_fetch_sma.py tests/test_yfinance_client.py tests/test_retention.py -q` and fix failures

**Checkpoint**: A past date fills its week; default runs unchanged.

---

## Phase 4: User Story 2 - Unsafe dates are refused (Priority: P2)

**Goal**: A future date, a date older than the retention window, or a malformed value stops the run before any download or write (FR-006, SC-005).

**Independent Test**: `resolve_run_date` returns / raises as specified; `main` with a future date exits 1 without loading tickers; a malformed value exits with a usage error.

### Tests for User Story 2

- [X] T011 [P] [US2] Add `test_resolve_run_date` in `tests/test_fetch_sma.py`: `today = date(2026, 11, 7)`, retention 365 → `None` → today; `date(2026, 10, 30)` → itself; `date(2026, 11, 8)` → `ValueError` matching "in the future"; `date(2025, 11, 6)` → `ValueError` matching "retention window"
- [X] T012 [P] [US2] Add `test_main_rejects_future_trading_date` in `tests/test_fetch_sma.py`: `main(["--trading_date", "2999-01-01"]) == 1`, `load_tickers_from_db` not called, log contains "is in the future"
- [X] T013 [P] [US2] Extend `test_build_parser_trading_date` in `tests/test_fetch_sma.py`: `" 2026-10-30 "` (spaces) parses; `"2026/10/30"` raises `SystemExit`

### Implementation for User Story 2

- [X] T014 [US2] Add `_iso_date(raw: str) -> date` (strip, `date.fromisoformat`, raise `argparse.ArgumentTypeError("must be an ISO date (YYYY-MM-DD), got '…'")`) and use it as the `--trading_date` type in `build_parser` in `fetch_sma.py` (contracts/cli.md)
- [X] T015 [US2] Add pure `resolve_run_date(trading_date: date | None, *, today: date, retention_days: int) -> date` in `fetch_sma.py` with the errors and messages from contracts/cli.md (`--trading_date D is in the future`; `--trading_date D is older than the N-day retention window (oldest YYYY-MM-DD)`), and call it in `main` right after `get_config()` (log the `ValueError` and return 1 before loading tickers), replacing the run-date computation from T009 (research R3)
- [X] T016 [US2] Run `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest tests/test_fetch_sma.py -q` and fix failures

**Checkpoint**: US1 and US2 both pass independently.

---

## Phase 5: Polish & Cross-Cutting Concerns

- [X] T017 [P] Update the `fetch_sma.py` row in the Scripts table of `.cursor/rules/RULES.mdc`: append "optional `--trading_date YYYY-MM-DD` re-runs a missed week as of that date (download ends on it; must be past and within retention)"; do not edit `project-docs/` or `README.md` (research R6)
- [X] T018 Run the full suite `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q` and walk the unit-test scenarios in `specs/008-fetch-trading-date/quickstart.md`; note in the completion summary the production commands from quickstart.md for the missed weeks

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (T001)** → **Foundational (T002–T004)** → **US1 (T005–T010)** → **US2 (T011–T016)** → **Polish (T017–T018)**
- US2 depends on US1 only through `main` (T015 replaces T009's run-date line); its pure function and parser tests are independent.

### Within Each Story

- Tests first (fail until implemented).
- US1: T008 → T009 (same file) → T010.
- US2: T014 → T015 (same file) → T016.

### Parallel Opportunities

- T002 and T003 (different files) alongside T004.
- T005–T007 (independent test cases).
- T011–T013.
- T017 alongside T016.

---

## Parallel Example: User Story 1

```bash
Task: "main --trading_date test in tests/test_fetch_sma.py"     # T005
Task: "parser test in tests/test_fetch_sma.py"                  # T006
Task: "download_batch end test in tests/test_yfinance_client.py" # T003 (Foundational)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. T001–T004 → T005–T010.
2. Validate: a past date fills its week; the Saturday run is unchanged.

### Incremental Delivery

1. US1 (usable for the missed weeks; dates must be typed correctly).
2. US2 adds the guards.
3. Polish: RULES; deploy; run quickstart.md commands for the missed weeks.

---

## Notes

- No schema change, no new script, cron unchanged (FR-009).
- The filled week's outlier email is sent as by the Saturday run (clarified).
- Do not commit until asked.
