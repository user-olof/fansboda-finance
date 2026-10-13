# Implementation Plan: Ticker Seed Validation

**Branch**: `006-ticker-seed-validation` | **Date**: 2026-10-12 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/006-ticker-seed-validation/spec.md`

## Summary

Seeding checks every resolved ticker before the upsert. A pure `check_ticker_fields` in
`seed_tickers.py` reports missing required fields (symbol, company, sector, industry) and missing
warn-only fields (market, exchange) (research R1). `resolve_and_upsert_symbols`, the single store
path used by `seed_tickers.py` and `refresh_tickers.py`, discards incomplete tickers and failed
lookups (R4), warns on missing market/exchange, and logs a `Ticker check:` summary (R5).
`yfinance_client` returns the raw market so "missing" is detectable; the stored market is still
inferred from the symbol (R2). No schema change, no new dependency.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: none new (yfinance, psycopg2 as today)

**Storage**: Neon Postgres, existing `*_tickers`; no DDL, no migration

**Testing**: pytest (`PIPENV_DONT_LOAD_ENV=1 pipenv run pytest`), yfinance and DB mocked

**Target Platform**: Owner's machine / dev CI (`dev-backfill.yml`) running `seed_tickers.py`;
`refresh_tickers.py` ad hoc

**Project Type**: Batch data pipeline (CLI scripts)

**Performance Goals**: No extra yfinance calls; the check is O(1) per ticker

**Constraints**: Existing rows never deleted or blanked (FR-005); `Seeded N ticker(s) from`
log format unchanged (parsed by `scripts/verify_dev_backfill.py`); exit code unaffected by
discards

**Scale/Scope**: 2 source files, 3 test files, 1 rules file

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Result |
|---|---|---|
| I. Weekly batch only | One-off seed/refresh scripts only; weekly job untouched. | Pass |
| II. Near-zero cost | No new calls or infrastructure. | Pass |
| III. Data pipeline only | Data-quality rule on existing columns; no UI, API, alerting. | Pass |
| IV. Parameterized SQL in `db/` | No SQL change; `upsert_tickers` receives fewer rows. | Pass |
| V. Keyless auth, no secrets | No change. | Pass |
| VI. Schema via `schema.sql` + `migrate_*.sql` | No DDL (NOT NULL constraints rejected, R1). | Pass |
| VII. Pure logic + unit tests | `check_ticker_fields` pure with unit tests; I/O paths tested with mocks. | Pass |
| Development workflow | RULES updated; `README.md` not affected (rule 6, R6); `project-docs/` untouched. | Pass |

**Post-design re-check**: unchanged — all Pass. Complexity Tracking empty.

## Project Structure

### Documentation (this feature)

```text
specs/006-ticker-seed-validation/
├── plan.md
├── research.md          # R1–R6
├── data-model.md        # field rules and outcomes
├── quickstart.md
├── contracts/
│   └── seed-log.md      # log lines and summary
├── checklists/
│   └── requirements.md
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
seed_tickers.py            # check_ticker_fields (pure); resolve_and_upsert_symbols discards/warns,
                           # infers stored market, drops failed-lookup fallback row, logs summary
yfinance_client.py         # _watchlist_fields_from_info returns raw market; remove
                           # _listing_market_from_info and the duplicate company warning
.cursor/rules/RULES.mdc    # seed_tickers.py row: discard / warn rule
tests/
├── test_seed_tickers.py   # check_ticker_fields cases; discard, warn, failed lookup, summary;
│                          # replace test_seed_tickers_from_file_infers_market_on_resolve_failure
├── test_refresh_tickers.py# discarded stored ticker not upserted
└── test_yfinance_client.py# market None when absent (replaces inference test)
```

**Structure Decision**: Existing single-project layout; no new files outside the spec folder.

## Rollout

1. Merge to `main` → deploy. Nothing to run: the rule applies the next time the owner seeds or
   refreshes tickers.
2. Optional: re-seed a country on dev and review the `Discarded` lines before the next production
   seed.

## Complexity Tracking

No violations.
