# Implementation Plan: Weekly Fetch for a Missed Trading Date

**Branch**: `008-fetch-trading-date` | **Date**: 2026-11-07 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/008-fetch-trading-date/spec.md`

## Summary

`fetch_sma.py` gets an optional `--trading_date YYYY-MM-DD`. The job resolves one run date (today
by default) and uses it for the freshness check, the download window start, and a new inclusive
download end (research R1, R2), so a manual run for a missed week stores exactly what a Saturday
run on that date would have: stock rows, market stats, z-scores, index rows, and the outlier
email (R5). Future dates, dates older than the retention window, and malformed values stop the run
before any I/O (R3). No change to the cron line, schema, or formulas.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: none new (argparse stdlib, pandas, yfinance, psycopg2)

**Storage**: existing `*_metrics`, `*_market_metrics`, `indices`; no DDL

**Testing**: pytest (`PIPENV_DONT_LOAD_ENV=1 pipenv run pytest`), yfinance and DB mocked

**Target Platform**: GCP `e2-micro` VM; manual run as `fansboda`

**Project Type**: Batch data pipeline (CLI scripts)

**Performance Goals**: one run per missed week takes the same time as a Saturday run

**Constraints**: no future data in any value; idempotent; Saturday behaviour unchanged without the
option

**Scale/Scope**: `fetch_sma.py`, `yfinance_client.py`, RULES, 2 test files

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Result |
|---|---|---|
| I. Weekly batch only | Same weekly job; the option is used manually, never scheduled; cron unchanged. | Pass |
| II. Near-zero cost | One extra weekly-sized run per missed week; no new infrastructure. | Pass |
| III. Data pipeline only | No UI/API; email behaviour unchanged (same rule, filled week). | Pass |
| IV. Parameterized SQL in `db/` | No SQL change; existing `filter_stale_tickers(today=…)` reused. | Pass |
| V. Keyless auth, no secrets | No change. | Pass |
| VI. Schema via migrations | No DDL. | Pass |
| VII. Pure logic + unit tests | `resolve_run_date` pure with tests; `main` / `download_batch` tested with mocks. | Pass |
| Operational: reuse shared logic | Reuses `download_batch`, `metric_rows_from_batch`, index update — no new script. | Pass |
| Development workflow | RULES updated; README unchanged (no published formula/threshold change); `project-docs/` untouched. | Pass |

**Post-design re-check**: unchanged — all Pass.

## Project Structure

### Documentation (this feature)

```text
specs/008-fetch-trading-date/
├── plan.md
├── research.md          # R1–R6
├── data-model.md        # run date and derived values
├── quickstart.md
├── contracts/
│   └── cli.md
├── checklists/
│   └── requirements.md
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
yfinance_client.py       # download_batch(..., end=None) — inclusive end
fetch_sma.py             # build_parser, resolve_run_date, main(argv); run date → freshness,
                         # download window/end, _fold_missing_members(end)
.cursor/rules/RULES.mdc  # fetch_sma.py row mentions --trading_date
tests/
├── test_fetch_sma.py        # parser, resolve_run_date, main with/without the option
└── test_yfinance_client.py  # end passed as end + 1 day
```

**Structure Decision**: Existing single-project layout; no new modules or scripts.

## Rollout

1. Merge to `main` → deploy.
2. On the VM, run `fetch_sma.py --trading_date <Friday>` once per missed week (quickstart.md).
3. Optionally re-run `./scripts/run_compute_indices.sh` (still pending for spec 007).

## Complexity Tracking

No violations.
