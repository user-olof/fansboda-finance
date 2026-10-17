# Implementation Plan: Index Momentum Band for Member Stocks

**Branch**: `007-index-momentum-band` | **Date**: 2026-10-16 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/007-index-momentum-band/spec.md`

## Summary

A stock is left out of its market and sector index in every calendar week where its SMA-50 /
SMA-200 ratio is outside `[INDEX_MOMENTUM_MIN, INDEX_MOMENTUM_MAX]` (defaults 0.15, 1.5,
inclusive). The weekly ratio is computed from the same daily closes that build the index (pure
`weekly_momentum`, research R1), and `fold_close` drops that stock's daily returns in
out-of-band weeks (R2) — one change shared by the one-off initialization, the weekly update, and
new sector starts (FR-004). The start-date minimum counts in-band members only (R3); member
count and uptrend percentage filter stored metrics by the band in SQL (R4). Download windows grow
so every week in the SMA windows has a ratio (R5). Settings + validation (R6), logging (R7),
README/RULES (R8). No schema change.

## Technical Context

**Language/Version**: Python 3.11+; SQL (Postgres 16 / Neon)

**Primary Dependencies**: none new (pandas, yfinance, psycopg2)

**Storage**: existing `indices`, `*_metrics`; no DDL

**Testing**: pytest (`PIPENV_DONT_LOAD_ENV=1 pipenv run pytest`), yfinance and DB mocked

**Target Platform**: GCP `e2-micro` VM (weekly cron) and the owner's one-off initialization

**Project Type**: Batch data pipeline (CLI scripts)

**Performance Goals**: weekly run within its current budget; per-stock weekly ratio is one
rolling pass over ≤ ~450 bars

**Constraints**: inclusive band; `None` ratio never excludes (FR-007); identical output when all
members are in band (SC-002); stock metrics untouched (FR-009)

**Scale/Scope**: `index_anchor.py`, `fetch_sma.py`, `compute_indices.py`, `db/indices.py`,
`config.py`, README, RULES, ~5 test files

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Result |
|---|---|---|
| I. Weekly batch only | Same weekly job and manual initialization; no new schedule. | Pass |
| II. Near-zero cost | Longer yfinance windows (R5): more rows per batch, same number of requests; free. | Pass |
| III. Data pipeline only | Uses only SMA-50 / SMA-200 and their ratio (existing momentum); no new indicator. | Pass |
| IV. Parameterized SQL in `db/` | Band filter in `BASE_WEEK_STATS_SQL` with `%s` parameters. | Pass |
| V. Keyless auth, no secrets | No change. | Pass |
| VI. Schema via `schema.sql` + `migrate_*.sql` | No DDL; stored history refreshed by re-running the initialization. | Pass |
| VII. Pure logic + unit tests | `weekly_momentum` and the band filter in pure `index_anchor` functions with tests; I/O paths mocked. | Pass |
| Development workflow | README + RULES updated (rule 6, published threshold); `project-docs/` untouched. | Pass |

**Post-design re-check**: unchanged — all Pass. Complexity Tracking empty.

## Project Structure

### Documentation (this feature)

```text
specs/007-index-momentum-band/
├── plan.md
├── research.md          # R1–R8
├── data-model.md        # band settings, weekly ratio, membership table
├── quickstart.md
├── contracts/
│   └── settings-and-log.md
├── checklists/
│   └── requirements.md
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
config.py            # INDEX_MOMENTUM_MIN / _MAX defaults, env, validation
index_anchor.py      # weekly_momentum; band in _returns / fold_close (+ exclusion collector);
                     # _scan start-date counts in-band only; AnchorSettings band fields;
                     # DOWNLOAD_LOOKBACK_DAYS 400 → 700
db/indices.py        # BASE_WEEK_STATS_SQL band filter; write_index_weeks(band=...)
fetch_sma.py         # HISTORY_DAYS 400 → 600; fold_index_history / _fold_missing_members /
                     # write_index_weeks pass the band; band log lines
compute_indices.py   # pass band to write_index_weeks; band log lines
README.md            # members rule + settings
.cursor/rules/RULES.mdc  # indices data-model sentence
tests/
├── test_index_anchor.py     # weekly_momentum, band drops, start-date count
├── test_compute_indices.py  # band passed, logs, SC-002 unchanged when all in band,
│                            # band parameters in BASE_WEEK_STATS_SQL / write_index_weeks
├── test_fetch_sma.py        # weekly path passes band; HISTORY_DAYS
└── test_config.py           # defaults, env, validation
```

**Structure Decision**: Existing single-project layout; no new modules.

## Rollout

1. Merge to `main` → deploy.
2. Owner re-runs the initialization per country (`./scripts/run_compute_indices.sh`) so stored
   history follows the band; check the `momentum band … excluded` lines.
3. Next Saturday run applies the band to the new week.

## Complexity Tracking

No violations.
