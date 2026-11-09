# Implementation Plan: Fast Per-Stock Lookups in the Metrics Tables

**Branch**: `009-metrics-ticker-index` | **Date**: 2026-11-09 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/009-metrics-ticker-index/spec.md`; plan input "don't
make any changes to technical constraints" — the spec's constraints are kept as written.

## Summary

Add a non-unique B-tree on `(ticker, trading_date)` to `us_metrics`, `swe_metrics`, and
`uk_metrics` (research R1). Fresh databases get it from `schema.sql` (R4); existing ones from a new
step 25, `migrate_metrics_ticker_index.sql`, which builds it `CONCURRENTLY` (R2), repairs an
invalid leftover via psql `\gexec` (R3), and is registered in `scripts/apply_migrations.sh`.
Production applies step 25 alone first over Neon's direct endpoint (R5). `verify_schema.sql`
checks the three indexes are valid (R6). No Python, data, column, formula, schedule, or
consumer-app change.

## Technical Context

**Language/Version**: SQL (PostgreSQL 17 on Neon; schema stays compatible with 16 for local
throwaway checks); Python 3.11+ only for tests

**Primary Dependencies**: none new; `psql` (already required by `apply_migrations.sh`)

**Storage**: Neon Postgres — `us_metrics` / `swe_metrics` / `uk_metrics` gain one index each

**Testing**: pytest textual checks in `tests/test_schema.py`; throwaway Postgres + `EXPLAIN` per
quickstart

**Target Platform**: Neon (production / dev); upgrade run by the owner with `psql`

**Project Type**: Batch data pipeline (CLI scripts)

**Performance Goals**: per-stock lookups < 10 ms database time (SC-002); step 25 < 1 min on
production (SC-004)

**Constraints**: non-blocking build; re-runnable; repairs invalid index; no row changes; no
change to columns / formulas / schedule / consumer app; free tier (< 20 MB added)

**Scale/Scope**: `schema.sql`, 1 new `migrate_*.sql`, `scripts/apply_migrations.sh`,
`scripts/verify_schema.sql`, `tests/test_schema.py`, RULES

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Result |
|---|---|---|
| I. Weekly batch only | No job change; the upgrade is a one-off manual step. | Pass |
| II. Near-zero cost | < 20 MB on a 104 MB DB, within Neon free tier; cost stated in research R6. | Pass |
| III. Data pipeline only | No UI / API; consumers just read faster. | Pass |
| IV. Parameterized SQL in `db/` | No runtime SQL change; DDL is fixed text with fixed identifiers. | Pass |
| V. Keyless auth, no secrets | Direct URL passed via environment only; nothing committed. | Pass |
| VI. Schema via migrations | `schema.sql` + `migrate_metrics_ticker_index.sql` (step 25), documented in this spec folder (contract). | Pass |
| VII. Pure logic + unit tests | No logic change; SQL files covered by `tests/test_schema.py`. | Pass |
| Operational | Idempotent; Saturday job unaffected; applied by the owner. | Pass |
| Development workflow | RULES "Legacy DB" line gains step 25; README unchanged (no published formula, window, threshold, default, or index *name* change); `project-docs/` untouched. | Pass |

**Post-design re-check**: unchanged — all Pass.

## Project Structure

### Documentation (this feature)

```text
specs/009-metrics-ticker-index/
├── plan.md
├── research.md          # R1–R6
├── data-model.md        # new / kept indexes, lookups served
├── quickstart.md
├── contracts/
│   └── migration-step-25.md
├── checklists/
│   └── requirements.md
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
schema.sql                          # + CREATE INDEX IF NOT EXISTS idx_<set>_metrics_ticker_trading_date ×3
migrate_metrics_ticker_index.sql    # new step 25: \gexec drop-invalid + CREATE INDEX CONCURRENTLY IF NOT EXISTS ×3
scripts/apply_migrations.sh         # run step 25 on both paths (+ header comment)
scripts/verify_schema.sql           # step 25 check: 3 rows, indisvalid
.cursor/rules/RULES.mdc             # Legacy DB: … step 25 migrate_metrics_ticker_index.sql (spec 009)
tests/test_schema.py                # MIGRATIONS entry; schema + step-file + apply_migrations assertions
```

**Structure Decision**: Existing single-project layout; one new SQL file, no new modules.

## Rollout

1. Merge to `main` → deploy (code unchanged at runtime; only SQL files ship).
2. Dev: run `dev-backfill.yml` or apply step 25 to a Neon branch.
3. Production (owner): step 25 alone over the direct endpoint, verification query, `EXPLAIN`
   checks (quickstart §4).

## Complexity Tracking

No violations.
