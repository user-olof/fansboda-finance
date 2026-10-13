---

description: "Task list for 006-ticker-seed-validation"
---

# Tasks: Ticker Seed Validation

**Input**: Design documents from `/specs/006-ticker-seed-validation/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included — constitution Principle VII requires unit tests with every logic change. Run
with `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q`; yfinance and the database are always mocked,
never the `.env` or production database.

**Organization**: Grouped by user story. Both stories share the pure check (Phase 2); US1
(discard) and US2 (warn) can then be built independently in `seed_tickers.py`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1, US2
- Paths are repository-root relative

---

## Phase 1: Setup

None — no new dependencies, settings, or modules.

---

## Phase 2: Foundational (blocks US1 and US2)

**Purpose**: The pure field check and a raw yfinance market, so "missing" is detectable
(research R1–R3).

- [X] T001 [P] In `yfinance_client.py`, make `_watchlist_fields_from_info` return the raw
  `info.get("market")` as `str | None` (no inference), delete `_listing_market_from_info`, and
  remove the `"No company name found for %s"` warning; update the return annotations of
  `_watchlist_fields_from_info` and `resolve_watchlist_fields` (market `str | None`) and the
  `resolve_watchlist_fields` docstring (market is raw; seeding infers the stored value)
- [X] T002 [P] In `tests/test_yfinance_client.py`, replace
  `test_resolve_watchlist_fields_infers_us_market_when_missing` with a test that a missing
  `market` returns `None` and logs no inference warning; keep
  `test_resolve_watchlist_fields_uses_single_yfinance_lookup` passing
- [X] T003 Add pure `check_ticker_fields(symbol, company, sector, industry, market, exchange_name)
  -> tuple[list[str], list[str]]` to `seed_tickers.py` (next to `filter_symbols_for_country`):
  returns `(missing_required, missing_warn)` using field names `symbol`, `company`, `sector`,
  `industry` and `market`, `exchange` in that order; `None`, `""`, or whitespace-only count as
  missing (data-model.md)
- [X] T004 Add unit tests for `check_ticker_fields` in `tests/test_seed_tickers.py`: complete
  ticker → `([], [])`; each required field missing alone; whitespace-only value; market and
  exchange missing → warn list only; everything missing → all six names in order

**Checkpoint**: `pytest tests/test_yfinance_client.py tests/test_seed_tickers.py -q` passes
(existing seed tests may need T005 for the market change — fix them there).

---

## Phase 3: User Story 1 - Incomplete tickers are not stored (Priority: P1) 🎯 MVP

**Goal**: Tickers missing symbol, company, sector, or industry, and failed lookups, are not
upserted; stored rows are left untouched; run summary logged (FR-001–FR-003, FR-005–FR-007).

**Independent Test**: Seed a mocked mix of complete, incomplete, and failing symbols; only the
complete ones reach `upsert_tickers`, each discard is logged, and the summary counts match.

- [X] T005 [US1] In `seed_tickers.resolve_and_upsert_symbols`, call `check_ticker_fields` after
  `resolve_watchlist_fields`; when `missing_required` is non-empty log
  `logger.warning("Discarded %s: missing %s", symbol, ", ".join(missing_required + missing_warn))`
  and skip the row; otherwise append the row with
  `infer_listing_market(market=market, symbol=symbol)` as the stored market (contracts/seed-log.md)
- [X] T006 [US1] In the same function, remove the fallback row appended in the `except` branch:
  keep `logger.exception("Failed to resolve metadata for %s", symbol)` and count the symbol as
  discarded (research R4)
- [X] T007 [US1] Track `stored` / `discarded` / `warned` counters in `resolve_and_upsert_symbols`
  and log `logger.info("Ticker check: stored=%d discarded=%d warned=%d", ...)` before the upsert;
  keep returning `upsert_tickers(...)` (returns 0 with no rows) and keep the
  `Seeded %d ticker(s) from %s` lines in `main` unchanged (research R5); update the function
  docstring
- [X] T008 [US1] In `tests/test_seed_tickers.py`, replace
  `test_seed_tickers_from_file_infers_market_on_resolve_failure` with
  `test_seed_tickers_from_file_discards_failed_lookups` (all lookups raise → `upsert_tickers`
  called with `[]` or count 0, summary `stored=0 discarded=3`)
- [X] T009 [US1] Add tests in `tests/test_seed_tickers.py`: a mix of complete, no-company,
  no-sector, no-industry, and whitespace-industry symbols → only the complete row is upserted;
  `caplog` contains one `Discarded <SYMBOL>: missing …` per discard with the right fields and the
  `Ticker check: stored=1 discarded=4 warned=0` line
- [X] T010 [P] [US1] Add a test in `tests/test_refresh_tickers.py` (same pattern as the existing
  `seed_tickers.resolve_watchlist_fields` patches near line 201) that a refreshed stored symbol
  whose lookup lacks a sector is not passed to `upsert_tickers` (FR-005, FR-007)

**Checkpoint**: US1 scenarios 1–5 covered; `pytest -q` passes.

---

## Phase 4: User Story 2 - Missing market or exchange is flagged (Priority: P2)

**Goal**: Complete tickers without a provided market or exchange are stored with a warning and
counted (FR-004, FR-006).

**Independent Test**: Seed mocked complete symbols with no market and/or no exchange; they are
upserted (market inferred, exchange `None`) and each has a `Stored <SYMBOL> with missing …`
warning; the summary `warned` count matches.

- [X] T011 [US2] In `seed_tickers.resolve_and_upsert_symbols`, when `missing_required` is empty
  and `missing_warn` is non-empty, log
  `logger.warning("Stored %s with missing %s", symbol, ", ".join(missing_warn))` and increment
  `warned` (row is still stored)
- [X] T012 [US2] Add tests in `tests/test_seed_tickers.py`: no market for `AAA.ST` / `VOD.L` /
  `AAPL` → stored as `se_market` / `gb_market` / `us_market` with a `missing market` warning;
  no exchange → stored with `None` and a `missing exchange` warning; both missing → one warning
  naming both; summary `warned` equals the number of such symbols; a discarded symbol missing
  market too is not counted as warned
- [X] T013 [US2] (No change needed — existing complete fixtures upsert unchanged.) Update `test_resolve_and_upsert_symbols_resolves_market_and_upserts` and
  `test_seed_tickers_from_file_resolves_and_upserts` in `tests/test_seed_tickers.py` only if
  needed so complete fixtures still upsert unchanged (no warnings expected)

**Checkpoint**: US2 scenarios 1–4 covered; `pytest -q` passes.

---

## Phase 5: Polish & Cross-Cutting

- [X] T014 [P] Update the `seed_tickers.py` row of the Scripts table in `.cursor/rules/RULES.mdc`:
  tickers missing company name, sector, or industry (or whose lookup fails) are discarded;
  missing market / exchange logged as a warning (research R6); do not edit `project-docs/` or
  `README.md`
- [X] T015 Confirm `scripts/verify_dev_backfill.py` `SEED_SUMMARY_RE` still matches the unchanged
  `Seeded N ticker(s) from` line (no edit expected)
- [X] T016 Run `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q`; all tests pass
- [ ] T017 Owner (optional, dev database only): run the manual check in
  [quickstart.md](./quickstart.md) and review the `Discarded` lines before the next production
  seed

---

## Dependencies & Execution Order

- Phase 2 (T001–T004) blocks both stories. T001/T002 (yfinance) and T003/T004 (check) are
  independent pairs.
- US1 (T005–T010) and US2 (T011–T013) both edit `resolve_and_upsert_symbols`; do them in order
  US1 → US2 to avoid conflicting edits, though US2 does not depend on US1's behaviour.
- T010 (`tests/test_refresh_tickers.py`) can run in parallel with T008/T009.
- Polish after both stories; T014 can run any time.

## Parallel Example

```text
Phase 2:  T001 + T002 (yfinance_client)  ‖  T003 + T004 (seed_tickers check)
US1:      T008/T009 (test_seed_tickers)  ‖  T010 (test_refresh_tickers)
Polish:   T014 (RULES.mdc)               ‖  any remaining test work
```

## Implementation Strategy

1. MVP: Phase 2 + US1 — incomplete and failed tickers no longer reach the database.
2. Add US2 — warnings for missing market/exchange.
3. Polish — RULES row, full test run, optional dev check.

No rollout step: the rule applies the next time the owner seeds or refreshes tickers.
