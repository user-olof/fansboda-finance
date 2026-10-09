---

description: "Task list for 005-market-index-zero-z"
---

# Tasks: Market Index Z-Score Set to 0

**Input**: Design documents from `/specs/005-market-index-zero-z/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included — constitution Principle VII requires unit tests with every logic change. Run
with `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q`; never against the `.env` or production
database, and never by running `fetch_sma.py`.

**Organization**: Grouped by user story. US1 (new rows) and US2 (stored rows) are independent.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1, US2
- Paths are repository-root relative

---

## Phase 1: Setup

None — no new dependencies, settings, or modules.

## Phase 2: Foundational

None.

---

## Phase 3: User Story 1 - New market index rows carry z-score 0 (Priority: P1) 🎯 MVP

**Goal**: Every market row written from now on has `z_score = 0`; sector z-scores unchanged
(FR-001, FR-002, research R1).

**Independent Test**: `tests/test_compute_indices.py` passes with market z-score 0 and unchanged
sector expectations.

### Tests for User Story 1

- [X] T001 [US1] In `tests/test_compute_indices.py`:
  - `test_with_sector_z_scores_uses_population_std_over_sectors`: expect the first row
    (`sector_key=None`, momentum 5) to get `Decimal("0")` instead of `None`; the sector
    expectations stay the same (proves the market's momentum 5 is not in the mean / std)
  - `test_with_sector_z_scores_null_without_spread`: unchanged (sector rows only)
  - add `test_with_sector_z_scores_market_zero_without_momentum`: a market row with momentum
    `None` plus one sector row → market `z_score == Decimal("0")`, sector `None`
  - `test_write_index_weeks_*` market assertion (~line 252): expect `market.z_score ==
    Decimal("0")` instead of `None`

### Implementation for User Story 1

- [X] T002 [US1] In `equity_index.py` `with_sector_z_scores`: market rows
  (`row.sector_key is None`) get `z_score = Decimal(0)`; sector rows keep the current
  calculation; update the docstring ("market rows (``sector_key is None``) get 0 — the market is
  the reference its sectors are compared with"). Run
  `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q tests/test_compute_indices.py tests/test_fetch_sma.py`

**Checkpoint**: New rows carry 0; US1 deployable alone.

---

## Phase 4: User Story 2 - Stored market index rows are set to 0 (Priority: P1)

**Goal**: One idempotent data step sets stored market rows to 0 and nothing else (FR-003,
SC-001, SC-002); contract [migration-step-24.md](./contracts/migration-step-24.md).

**Independent Test**: `tests/test_schema.py` passes; on a throwaway Postgres the step updates
3 rows then 0, sector rows and other columns unchanged (quickstart §2).

### Tests for User Story 2

- [X] T003 [P] [US2] In `tests/test_schema.py` add `REPO_ROOT / "migrate_market_index_zero_z.sql"`
  to `MIGRATIONS` and add, reusing `_sql_statements`:
  - `test_step_24_zeroes_only_market_index_z_scores`: no `CREATE` / `ALTER` / `DROP` /
    `TRUNCATE` / `DELETE` / `LIKE`; contains `UPDATE indices`, `SET z_score = 0`,
    `ticker IN ('US-IDX', 'SWE-IDX', 'UK-IDX')`, and `z_score IS DISTINCT FROM 0`
  - `test_step_24_tickers_match_index_definitions`: every `INDEX_DEFINITIONS` ticker appears
    quoted in the SQL
  - `test_apply_migrations_runs_step_24_after_step_23_in_both_paths`: same pattern as the step 23
    test (`migrate_rename_market_indices.sql` < `migrate_market_index_zero_z.sql`)

### Implementation for User Story 2

- [X] T004 [US2] Create `migrate_market_index_zero_z.sql` (repo root): header comment in the
  style of `migrate_rename_market_indices.sql` (step 24, specs/005-market-index-zero-z, data only,
  sector rows untouched, safe to repeat, apply after deploying the 005 code and after step 23),
  then:
  `UPDATE indices SET z_score = 0 WHERE ticker IN ('US-IDX', 'SWE-IDX', 'UK-IDX') AND z_score IS DISTINCT FROM 0;`
- [X] T005 [US2] In `scripts/apply_migrations.sh` add
  `run_sql "$REPO_DIR/migrate_market_index_zero_z.sql"` after
  `migrate_rename_market_indices.sql` in the "past step 14" block, and after step 23 in the full
  path with `# Step 24: market index z_score 0 (spec 005).`
- [X] T006 [US2] In `scripts/verify_schema.sql` append: market rows
  (`ticker IN ('US-IDX', 'SWE-IDX', 'UK-IDX')`) with `z_score IS DISTINCT FROM 0`, grouped by
  ticker — `-- expect 0 rows`. Run `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q tests/test_schema.py`

**Checkpoint**: Step 24 written, wired, tested.

---

## Phase 5: Polish & Cross-Cutting Concerns

- [X] T007 [P] In `README.md` (RULES rule 6): `#### Sector z-score` — replace "Market index rows
  have no z-score." with "Market index rows have z-score 0 by convention: the market is the
  reference its sectors are compared with."; in `### When a value is empty` change the index
  `z_score` row to "on sector rows with fewer than 2 sectors or $`\sigma_S = 0`$ (market rows are
  always 0)"
- [X] T008 [P] In `.cursor/rules/RULES.mdc`: in the `indices` data-model sentence change "NULL on
  market rows" to "0 on market rows (spec 005)", and extend the Legacy DB migration note with
  "then step 24 `migrate_market_index_zero_z.sql` (market index `z_score` 0,
  specs/005-market-index-zero-z)"; in `schema.sql` change the comment "(sector rows) z_score" to
  "z_score (sector rows; 0 on market rows)"
- [X] T009 Run `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q` and quickstart §3
  (`rg` for leftover "no z-score" / "NULL on market rows" wording)
- [X] T010 Quickstart §2 on a throwaway Docker Postgres 16: step 24 updates 3 rows then 0; sector
  rows (with and without a z-score) and all other columns unchanged; verify query 0 rows
- [ ] T011 Manual (owner): production rollout per
  [migration-step-24.md](./contracts/migration-step-24.md) — deploy, apply step 23 if not yet
  done, apply step 24, verify (expect 0 rows), confirm next Saturday's market rows have
  z-score 0 (SC-003)

---

## Dependencies & Execution Order

- US1: T001 → T002.
- US2: T003 → T004 → T005 → T006; independent of US1.
- Polish: T007, T008 any time; T009 after T002–T008; T010 after T004; T011 after merge.

## Parallel Opportunities

- T003 (`tests/test_schema.py`) alongside T001–T002 (`tests/test_compute_indices.py`,
  `equity_index.py`).
- T007 (`README.md`) and T008 (`RULES.mdc`, `schema.sql`) alongside everything.

```text
Agent A: T001 → T002            (US1)
Agent B: T003 → T004 → T005 → T006   (US2)
Agent C: T007, T008             (docs)
```

## Implementation Strategy

1. **MVP = US1** (T001–T002): new weeks get 0.
2. **US2** (T003–T006): history consistent after step 24.
3. **Polish** (T007–T010), then the owner's rollout T011.
