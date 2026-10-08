# Implementation Plan: Rename the Market Indices

**Branch**: `003-market-index-names` | **Date**: 2026-10-08 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-market-index-names/spec.md`

## Summary

The market index labels become "NYSE & Nasdaq" (`US-IDX`), "OMX Stockholm" (`SWE-IDX`), and
"FTSE London" (`UK-IDX`). New rows get them from the three names in `INDEX_DEFINITIONS`
(`equity_index.py`), the only place the label is set (research R1). Stored rows are relabeled by a
new idempotent data step, `migrate_rename_market_indices.sql` (migration step 23), which updates
`indices.sector` only for those three exact tickers and is wired into `apply_migrations.sh` and
`verify_schema.sql` (R2). Deploy the code first, then apply step 23 (R3). The consumer `fansboda`
identifies market rows by ticker and needs no change (R4). No DDL change.

## Technical Context

**Language/Version**: Python 3.11+; SQL (Postgres 16 / Neon)

**Primary Dependencies**: none new (psycopg2, pytest)

**Storage**: Neon Postgres, existing `indices` table; data-only change to `indices.sector` on
market rows

**Testing**: pytest (`PIPENV_DONT_LOAD_ENV=1 pipenv run pytest`); manual check of step 23 on a
local Docker Postgres 16 ([quickstart.md](./quickstart.md))

**Target Platform**: GCP `e2-micro` VM (cron) and the owner's `psql` for step 23

**Project Type**: Batch data pipeline (CLI scripts)

**Performance Goals**: Step 23 updates ≈150 rows (3 tickers × ≈52 weeks) in one statement

**Constraints**: No change to tickers, values, or sector rows (FR-002); idempotent (FR-003)

**Scale/Scope**: 3 labels; ≈6 source files, 2 test files, 1 new SQL file

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Result |
|---|---|---|
| I. Weekly batch only | No change to scheduling; step 23 is run once by the owner. | Pass |
| II. Near-zero cost | No infrastructure; one `UPDATE`. | Pass |
| III. Data pipeline only | Label change only; no UI/API, no new indicator. | Pass |
| IV. Parameterized SQL in `db/` | No new runtime SQL; step 23 is a static migration file with fixed literals, no runtime values. | Pass |
| V. Keyless auth, no secrets | No auth or secret changes. | Pass |
| VI. Schema via `schema.sql` + `migrate_*.sql` | No DDL. The data step follows the migration conventions anyway: `migrate_*.sql`, step 23 documented in this spec folder, wired into `apply_migrations.sh` and `verify_schema.sql`; not destructive. | Pass |
| VII. Pure logic + unit tests | Label tests updated; new collision test; step 23 file and wiring covered in `tests/test_schema.py`. | Pass |
| Development workflow | Frozen `project-docs/` and specs 001/002 untouched; `RULES.mdc` updated (FR-005). | Pass |

**Post-design re-check (after Phase 1)**: unchanged — all Pass. No violations; Complexity Tracking
is empty.

## Project Structure

### Documentation (this feature)

```text
specs/003-market-index-names/
├── plan.md              # This file
├── research.md          # Phase 0: R1–R6
├── data-model.md        # Phase 1: indices.sector on market rows
├── quickstart.md        # Phase 1: validation guide
├── contracts/
│   ├── indices-table.md       # consumer-facing label contract
│   └── migration-step-23.md   # relabel step contract and rollout order
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks — not created here)
```

### Source Code (repository root)

```text
equity_index.py                       # INDEX_DEFINITIONS names; IndexRow docstring example
migrate_rename_market_indices.sql     # NEW — step 23, idempotent relabel by ticker
schema.sql                            # comment: label example only
scripts/apply_migrations.sh           # run step 23 after step 22 in both paths
scripts/verify_schema.sql             # expect 0 market rows with an old/other label
.cursor/rules/RULES.mdc               # example label in the indices data-model sentence
tests/
├── test_compute_indices.py           # expected market labels; collision test (FR-004)
└── test_schema.py                    # step 23 exists, wired after step 22, labels match code
```

**Structure Decision**: Existing single-project layout at the repo root; one new migration file,
no new modules.

## Rollout

1. Merge to `main` → `deploy.yml` deploys the code.
2. Owner applies step 23 on production (`psql … -f migrate_rename_market_indices.sql`) and runs
   the verify query (expect 0 rows) — see [migration-step-23.md](./contracts/migration-step-23.md).
3. Next Saturday run: the new market rows carry the new label (SC-003).

If the pending 002 rollout (`compute_indices.py --country us|swe|uk`) runs after step 1, it also
writes the new labels; step 23 is still applied for completeness and is a no-op then.

## Complexity Tracking

No violations.
