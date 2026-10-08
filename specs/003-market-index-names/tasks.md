---

description: "Task list for 003-market-index-names"
---

# Tasks: Rename the Market Indices

**Input**: Design documents from `/specs/003-market-index-names/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included — constitution Principle VII requires unit tests with every logic change. Run
with `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q`; never against the `.env` or production
database, and never by running `fetch_sma.py`.

**Organization**: Tasks are grouped by user story (spec.md). US1 (new rows) and US2 (stored rows)
are independent; both use the same three labels.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2)
- Paths are repository-root relative (single project, see plan.md)

New labels (data-model.md): `US-IDX` → `NYSE & Nasdaq`, `SWE-IDX` → `OMX Stockholm`,
`UK-IDX` → `FTSE London`.

---

## Phase 1: Setup

None — no new dependencies, settings, or modules.

---

## Phase 2: Foundational

None — the two stories share only the label values, listed above.

---

## Phase 3: User Story 1 - Market indices carry exchange-based names (Priority: P1) 🎯 MVP

**Goal**: Every market row written by the weekly run, new sector starts, or the initialization
carries the new label; sector rows unchanged (FR-001, FR-002, FR-004).

**Independent Test**: `tests/test_compute_indices.py` passes with the new labels; on a local
database `compute_indices.py --country swe` stores `SWE-IDX` rows labeled `OMX Stockholm`
(quickstart §3).

### Tests for User Story 1

- [X] T001 [US1] In `tests/test_compute_indices.py` update `test_index_definitions_match_prd`
  (lines ~74–76) to expect `("US-IDX", "NYSE & Nasdaq")`, `("SWE-IDX", "OMX Stockholm")`,
  `("UK-IDX", "FTSE London")`, and replace every other `"US Equity Index"` expectation / fixture
  in the file (lines ~96, 185, 230, 269, 414) with `"NYSE & Nasdaq"`; confirm with
  `rg -n "Equity Index" tests/` that no old label is left in the tests
- [X] T002 [US1] In `tests/test_compute_indices.py` add `test_market_labels_do_not_collide_with_sector_labels`
  (FR-004, research R5): the three `INDEX_DEFINITIONS` names are distinct, and none equals
  `sector_index_definition(country, key).name` for any country and every yfinance sector key
  (`basic-materials`, `communication-services`, `consumer-cyclical`, `consumer-defensive`,
  `energy`, `financial-services`, `healthcare`, `industrials`, `real-estate`, `technology`,
  `utilities`)

### Implementation for User Story 1

- [X] T003 [US1] In `equity_index.py` change the `INDEX_DEFINITIONS` names to `"NYSE & Nasdaq"`
  (US), `"OMX Stockholm"` (SWE), `"FTSE London"` (UK), and the `IndexRow` docstring example
  ``US Equity Index`` → ``NYSE & Nasdaq``; tickers unchanged. Run
  `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q tests/test_compute_indices.py tests/test_fetch_sma.py`

**Checkpoint**: New rows carry the new labels; US1 complete and deployable on its own.

---

## Phase 4: User Story 2 - Stored market rows are relabeled (Priority: P1)

**Goal**: One idempotent data step relabels every stored market row and nothing else (FR-003,
SC-001, SC-002); contract [migration-step-23.md](./contracts/migration-step-23.md).

**Independent Test**: `tests/test_schema.py` passes; on a local Docker Postgres the step updates 3
rows the first time and 0 the second, sector rows and all other columns unchanged (quickstart §2).

### Tests for User Story 2

- [X] T004 [P] [US2] In `tests/test_schema.py` add `REPO_ROOT / "migrate_rename_market_indices.sql"`
  to `MIGRATIONS`, and add:
  - `test_step_23_relabels_only_market_tickers`: the file has no DDL (`CREATE`, `ALTER`, `DROP`,
    `TRUNCATE`, `DELETE`), contains `UPDATE indices`, matches by exact ticker
    (`'US-IDX'`, `'SWE-IDX'`, `'UK-IDX'`; no `LIKE`), and guards with `IS DISTINCT FROM`
  - `test_step_23_labels_match_index_definitions`: for each `INDEX_DEFINITIONS` entry the SQL
    contains `('<ticker>', '<name>')` — keeps code and migration in sync
  - `test_apply_migrations_runs_step_23_after_step_22_in_both_paths`: same pattern as
    `test_apply_migrations_runs_steps_21_22_last_in_both_paths` (skip block via `index`, full
    path via `rindex`), `migrate_drop_by_sector_tables.sql` < `migrate_rename_market_indices.sql`

### Implementation for User Story 2

- [X] T005 [US2] Create `migrate_rename_market_indices.sql` (repo root): header comment in the
  style of `migrate_indices_sectors.sql` (step 23, data only, safe to repeat, apply after
  deploying the 003 code, re-run if an older deployment wrote a row in between), then the single
  statement from research R2:
  `UPDATE indices AS i SET sector = v.label FROM (VALUES ('US-IDX', 'NYSE & Nasdaq'), ('SWE-IDX', 'OMX Stockholm'), ('UK-IDX', 'FTSE London')) AS v (ticker, label) WHERE i.ticker = v.ticker AND i.sector IS DISTINCT FROM v.label;`
- [X] T006 [US2] In `scripts/apply_migrations.sh` add
  `run_sql "$REPO_DIR/migrate_rename_market_indices.sql"` after `migrate_drop_by_sector_tables.sql`
  in the "past step 14" block, and after step 22 in the full path with a comment
  `# Step 23: market index labels (NYSE & Nasdaq / OMX Stockholm / FTSE London), spec 003.`
- [X] T007 [US2] In `scripts/verify_schema.sql` append a check: market rows
  (`ticker IN ('US-IDX', 'SWE-IDX', 'UK-IDX')`) whose `sector` is not the new label for its ticker
  — `-- expect 0 rows` (SC-001). Run `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q tests/test_schema.py`

**Checkpoint**: Step 23 written, wired, verified by tests.

---

## Phase 5: Polish & Cross-Cutting Concerns

- [X] T008 [P] In `schema.sql` change the `indices` comment example `("US Equity Index")` to
  `("NYSE & Nasdaq")`; leave `migrate_indices_sectors.sql` unchanged (research R6)
- [X] T009 [P] In `.cursor/rules/RULES.mdc` change the example label `` `US Equity Index` `` to
  `` `NYSE & Nasdaq` `` in the `indices` data-model sentence, and in the "Fresh DB / Legacy DB"
  line say migrations run "through step 23 (spec 003: market index labels)"; do not edit
  `project-docs/` or specs 001/002 (FR-005)
- [X] T010 Run the full suite `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q` and
  `rg -n "Equity Index" --glob '!project-docs/**' --glob '!specs/**'` — only
  `migrate_indices_sectors.sql` (historic comment) may remain
- [ ] T011 Manual (owner): quickstart §2–§3 on a local Docker Postgres 16 — step 23 updates 3 rows
  then 0, sector rows and values unchanged, `compute_indices.py --country swe` writes
  `OMX Stockholm`
  - *2026-10-08: §2 run on a throwaway Postgres 16 — UPDATE 4 then UPDATE 0, sector row and all
    other columns unchanged, verify query 0 rows. §3 (`compute_indices.py` run) still open.*
- [ ] T012 Manual (owner): production rollout per
  [migration-step-23.md](./contracts/migration-step-23.md) — deploy, apply step 23, run the
  verify query (expect 0 rows), confirm next Saturday's market rows carry the new labels (SC-003)

---

## Dependencies & Execution Order

- **US1** (T001–T003): T001–T002 before T003 (tests first; they fail until T003).
- **US2** (T004–T007): independent of US1 code; T004 before T005–T007; T005 → T006 → T007.
  `test_step_23_labels_match_index_definitions` passes only once T003 is done.
- **Polish**: T008, T009 any time; T010 after all code tasks; T011 after T010; T012 after merge.
- Rollout order (R3): deploy code (US1) before applying step 23 on production.

## Parallel Opportunities

- T004 (US2 tests, `tests/test_schema.py`) in parallel with T001–T003 (US1, other files).
- T008 and T009 in parallel with everything (doc-only files).

```text
# Example: run US1 and US2 side by side
Agent A: T001 → T002 → T003   (tests/test_compute_indices.py, equity_index.py)
Agent B: T004 → T005 → T006 → T007   (tests/test_schema.py, migrate_*.sql, scripts/)
```

## Implementation Strategy

1. **MVP = US1** (T001–T003): new rows get the new labels; safe to deploy alone — history would
   then mix labels until step 23 runs.
2. **US2** (T004–T007): add step 23 so history is consistent.
3. **Polish** (T008–T010), then owner checks T011–T012.
