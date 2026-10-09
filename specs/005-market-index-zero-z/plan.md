# Implementation Plan: Market Index Z-Score Set to 0

**Branch**: `005-market-index-zero-z` | **Date**: 2026-10-09 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/005-market-index-zero-z/spec.md`

## Summary

Market index rows (`US-IDX`, `SWE-IDX`, `UK-IDX`) get `z_score = 0` instead of NULL. New rows:
one change in the pure function `equity_index.with_sector_z_scores`, through which every
`indices` write passes; sector z-scores keep using sector rows only (research R1). Stored rows:
idempotent data step `migrate_market_index_zero_z.sql` (migration step 24), exact-ticker
`UPDATE`, wired into `apply_migrations.sh` and `verify_schema.sql` (R2). Deploy code first, then
step 24 (R3). `fansboda` needs no change — 0 renders as the neutral heat colour (R4). README,
RULES, and docstrings updated (R5). No DDL.

## Technical Context

**Language/Version**: Python 3.11+; SQL (Postgres 16 / Neon)

**Primary Dependencies**: none new

**Storage**: Neon Postgres, existing `indices`; data-only change to `z_score` on market rows

**Testing**: pytest (`PIPENV_DONT_LOAD_ENV=1 pipenv run pytest`); step 24 checked on a throwaway
Docker Postgres 16 ([quickstart.md](./quickstart.md))

**Target Platform**: GCP `e2-micro` VM (cron) and the owner's `psql` for step 24

**Project Type**: Batch data pipeline (CLI scripts)

**Performance Goals**: Step 24 updates ≈ 150 rows (3 tickers × ≈ 52 weeks) in one statement

**Constraints**: Sector rows and all other columns unchanged (FR-002–FR-004); idempotent

**Scale/Scope**: 1 code line + docstrings, 1 new SQL file, 2 scripts, 2 test files, 2 docs

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Result |
|---|---|---|
| I. Weekly batch only | No scheduling change; step 24 run once by the owner. | Pass |
| II. Near-zero cost | One `UPDATE`; no infrastructure. | Pass |
| III. Data pipeline only | Existing field's value convention; no new indicator, UI, or API. | Pass |
| IV. Parameterized SQL in `db/` | No new runtime SQL; step 24 is a static migration with fixed literals. | Pass |
| V. Keyless auth, no secrets | No change. | Pass |
| VI. Schema via `schema.sql` + `migrate_*.sql` | No DDL; data step follows the migration conventions (step 24 documented here, wired into `apply_migrations.sh` and `verify_schema.sql`; not destructive). | Pass |
| VII. Pure logic + unit tests | Change in the pure `with_sector_z_scores`, with updated unit tests; step 24 file and wiring tested. | Pass |
| Development workflow | `README.md` updated per RULES rule 6; `project-docs/` untouched. | Pass |

**Post-design re-check**: unchanged — all Pass. Complexity Tracking empty.

## Project Structure

### Documentation (this feature)

```text
specs/005-market-index-zero-z/
├── plan.md
├── research.md          # R1–R5
├── data-model.md        # indices.z_score on market vs sector rows
├── quickstart.md
├── contracts/
│   └── migration-step-24.md
├── checklists/
│   └── requirements.md
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
equity_index.py                    # with_sector_z_scores: market rows → Decimal(0); docstrings
migrate_market_index_zero_z.sql    # NEW — step 24
scripts/apply_migrations.sh        # run step 24 after step 23 in both paths
scripts/verify_schema.sql          # expect 0 market rows with z_score ≠ 0
README.md                          # sector z-score paragraph, empty-values table
.cursor/rules/RULES.mdc            # indices data-model sentence: 0 on market rows; step 24
tests/
├── test_compute_indices.py        # market z_score 0 in with_sector_z_scores / write_index_weeks
└── test_schema.py                 # step 24 exists, only market tickers, after step 23
```

**Structure Decision**: Existing single-project layout; one new migration file.

## Rollout

1. Merge to `main` → deploy.
2. Owner applies step 24 on production and runs the verify query (expect 0 rows) — see
   [migration-step-24.md](./contracts/migration-step-24.md).
3. Next Saturday run: market rows written with z-score 0 (SC-003).

Step 23 (spec 003) must already be applied or be applied in the same session; order 23 → 24.

## Complexity Tracking

No violations.
