---

description: "Task list for 009 — per-stock lookup indexes on the metrics tables"
---

# Tasks: Fast Per-Stock Lookups in the Metrics Tables

**Input**: Design documents from `/specs/009-metrics-ticker-index/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/migration-step-25.md, quickstart.md

**Tests**: Included — SQL files are covered textually in `tests/test_schema.py` (as for steps 20–24) and on a throwaway Postgres per quickstart.

**Organization**: Tasks are grouped by user story so each story can be implemented and tested independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1 = stock pages respond quickly again (P1); US2 = the upgrade is safe to apply to production (P1)
- Single project at repository root; tests in `tests/`; run with `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest`
- Never run anything in this list against the `.env` / production database; production is the owner's (contract "Production rollout")

---

## Phase 1: Setup

**Purpose**: Confirm a green baseline.

- [X] T001 Run `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q` from the repo root and confirm the current suite passes

---

## Phase 2: Foundational (Blocking Prerequisites)

None — both stories only add SQL next to existing files; no shared code to build first.

---

## Phase 3: User Story 1 - Stock pages respond quickly again (Priority: P1) 🎯 MVP

**Goal**: Every metrics table has a `(ticker, trading_date)` lookup path, so per-stock lookups (chart history, latest row, US-table miss for a Swedish / UK stock, latest row for a page) stop reading the whole table (FR-001, FR-002).

**Independent Test**: On a throwaway Postgres built from `schema.sql`, the three indexes exist and `EXPLAIN` of the chart-history and latest-observation lookups (data-model.md) uses `idx_us_metrics_ticker_trading_date`.

### Tests for User Story 1

- [X] T002 [P] [US1] Add `test_schema_ticker_trading_date_indexes` in `tests/test_schema.py` (pattern of `test_schema_retention_indexes`): for `us`, `swe`, `uk` assert `CREATE INDEX IF NOT EXISTS idx_<set>_metrics_ticker_trading_date` and `ON <set>_metrics (ticker, trading_date)` are in `schema.sql`, and keep asserting `UNIQUE (ticker, trading_date)` is absent

### Implementation for User Story 1

- [X] T003 [US1] In `schema.sql`, directly after each `CREATE INDEX IF NOT EXISTS idx_<set>_metrics_trading_date ON <set>_metrics (trading_date);` (us ~line 47, swe ~93, uk ~139), add `CREATE INDEX IF NOT EXISTS idx_<set>_metrics_ticker_trading_date ON <set>_metrics (ticker, trading_date);` with a one-line comment "per-stock lookups (spec 009)" matching the neighbouring comment style (research R1, R4)
- [X] T004 [US1] Run `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest tests/test_schema.py -q` and fix failures

**Checkpoint**: Fresh databases get the indexes; US1 is testable via quickstart §2a and §2e.

---

## Phase 4: User Story 2 - The upgrade is safe to apply to production (Priority: P1)

**Goal**: Existing databases get the indexes through step 25 without blocking reads / writes, without changing rows, re-runnable, repairing an invalid leftover; verifiable afterwards (FR-003–FR-006; contract migration-step-25.md).

**Independent Test**: On a throwaway Postgres with the indexes dropped and rows inserted, applying `migrate_metrics_ticker_index.sql` twice yields 3 valid indexes, unchanged rows, and a no-op second run; an index marked invalid is rebuilt (quickstart §2b–§2d).

### Tests for User Story 2

- [X] T005 [P] [US2] In `tests/test_schema.py` append `REPO_ROOT / "migrate_metrics_ticker_index.sql"` to `MIGRATIONS` and add `STEP_25_SQL` plus `test_step_25_builds_ticker_indexes_concurrently` (using `_sql_statements`): for each set `CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_<set>_metrics_ticker_trading_date ON <set>_metrics (ticker, trading_date)` is present; `BEGIN`, `COMMIT`, `UPDATE`, `DELETE`, `INSERT`, `TRUNCATE`, `ALTER` are absent (uppercase check on statements, as for step 24)
- [X] T006 [P] [US2] Add `test_step_25_drops_only_invalid_indexes` in `tests/test_schema.py`: the step contains `DROP INDEX CONCURRENTLY IF EXISTS`, `indisvalid`, and `\gexec`, and every index name it drops is one of the three `idx_<set>_metrics_ticker_trading_date` names (no other `DROP`)
- [X] T007 [P] [US2] Add `test_apply_migrations_runs_step_25_after_step_24_in_both_paths` in `tests/test_schema.py` (pattern of the step 24 test): `migrate_market_index_zero_z.sql` < `migrate_metrics_ticker_index.sql` in the skip block and in the full path, and the script does not pass `-1` / `--single-transaction` to psql
- [X] T008 [P] [US2] Add `test_verify_schema_checks_ticker_indexes_valid` in `tests/test_schema.py`: `scripts/verify_schema.sql` mentions all three index names and `indisvalid`

### Implementation for User Story 2

- [X] T009 [US2] Create `migrate_metrics_ticker_index.sql` at the repo root per contracts/migration-step-25.md: header comment (`-- Step 25: per-stock lookup indexes on the metrics tables (specs/009-metrics-ticker-index).`, what it does, "Safe to repeat; repairs an index left invalid by an interrupted build.", "Run with psql outside a transaction (no -1); on Neon use the direct (non-pooler) endpoint."); then a `SELECT format('DROP INDEX CONCURRENTLY IF EXISTS %I', c.relname) FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid WHERE NOT i.indisvalid AND c.relname IN ('idx_us_metrics_ticker_trading_date', 'idx_swe_metrics_ticker_trading_date', 'idx_uk_metrics_ticker_trading_date')` terminated by `\gexec`; then the three `CREATE INDEX CONCURRENTLY IF NOT EXISTS … ON <set>_metrics (ticker, trading_date);` statements; no `BEGIN` / `COMMIT` (research R2, R3)
- [X] T010 [US2] In `scripts/apply_migrations.sh` add `run_sql "$REPO_DIR/migrate_metrics_ticker_index.sql"` after `migrate_market_index_zero_z.sql` in the "already past step 14" block, and in the full path add `# Step 25: per-stock lookup indexes on *_metrics (spec 009).` + the same `run_sql` after step 24
- [X] T011 [US2] In `scripts/verify_schema.sql` append the step 25 check from contracts/migration-step-25.md (`-- step 25: per-stock lookup indexes (spec 009)` … `-- expect 3 rows, indisvalid = true`)
- [X] T012 [US2] Run `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest tests/test_schema.py -q` and fix failures
- [X] T013 [US2] Validate on a throwaway Postgres per quickstart.md §2a–§2e (`docker run … postgres:17`; fresh schema, existing-DB apply twice with row checksum, invalid-index repair, non-blocking with an open transaction, `EXPLAIN` plans); `docker rm -f idx009-pg` afterwards

**Checkpoint**: Step 25 is safe, idempotent, self-repairing, and registered; both stories complete.

---

## Phase 5: Polish & Cross-Cutting Concerns

- [X] T014 [P] In `.cursor/rules/RULES.mdc` "Legacy DB" sentence add `and step 25 migrate_metrics_ticker_index.sql (per-stock lookup indexes, specs/009-metrics-ticker-index; apply alone first over the direct endpoint)` after step 24; README unchanged (no published formula / window / threshold / default / index-name change); `project-docs/` untouched
- [X] T015 Run the full suite `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q` and confirm all pass
- [X] T016 Hand the owner the production rollout (contract "Production rollout", quickstart §4): step 25 alone over the direct endpoint, verification query, read-only `EXPLAIN (ANALYZE, BUFFERS)` re-checks — not run by the agent

---

## Dependencies & Execution Order

- **Setup (T001)** → both stories.
- **US1 (T002–T004)** and **US2 (T005–T013)** touch different files except `tests/test_schema.py`; tests T002 and T005–T008 edit the same file, so write them sequentially even though they are logically independent.
- US2's step 25 is independent of US1's `schema.sql` change, but T013 §2a (fresh schema) needs T003.
- **Polish (T014–T016)** after both stories.

### Parallel Opportunities

- T002 (test) alongside T003 (schema) — different files.
- T009 (step file), T010 (apply_migrations), T011 (verify_schema), T014 (RULES) — four different files, no mutual dependency.

## Parallel Example: User Story 2

```text
T009 Create migrate_metrics_ticker_index.sql
T010 Register step 25 in scripts/apply_migrations.sh
T011 Add step 25 check to scripts/verify_schema.sql
```

## Implementation Strategy

### MVP (User Story 1)

T001 → T002–T004: fresh databases get the indexes. Alone this does not help production (existing DB), so ship US1 and US2 together.

### Full delivery

1. US1 + US2 → T013 throwaway validation → T014–T015.
2. Commit `schema.sql` and `migrate_metrics_ticker_index.sql` together (RULES "When implementing changes" 4).
3. Merge to `main`; owner applies step 25 to production (T016).
