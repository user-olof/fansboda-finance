# Research: Rename the Market Indices

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

No open `NEEDS CLARIFICATION` items remained in the Technical Context; the decisions below record
how each part of the spec is met.

## R1 — Where the label comes from

**Decision**: Change the three market names in `INDEX_DEFINITIONS` (`equity_index.py`) to
"NYSE & Nasdaq", "OMX Stockholm", "FTSE London". Nothing else in the code holds the label.

**Rationale**: Every market row is built by `build_index_row(INDEX_DEFINITIONS[country], …)` in
`db/indices.write_index_weeks` (weekly run, new sectors, initialization), which stores
`definition.name` in `indices.sector`. Sector names come from `sector_index_definition` and do not
depend on the market name, so sector rows are unaffected (FR-002).

**Alternatives considered**: A config setting per country (`US_INDEX_NAME`, …) — rejected: the
labels are fixed product names, not tunables, and config would add three settings for no use.

## R2 — Stored rows: relabel step

**Decision**: A new idempotent data step `migrate_rename_market_indices.sql` (migration step 23):

```sql
UPDATE indices AS i
SET sector = v.label
FROM (VALUES ('US-IDX', 'NYSE & Nasdaq'), ('SWE-IDX', 'OMX Stockholm'), ('UK-IDX', 'FTSE London'))
     AS v (ticker, label)
WHERE i.ticker = v.ticker AND i.sector IS DISTINCT FROM v.label;
```

It matches on the market **ticker** (exact equality, so `US-IDX-TECHNOLOGY` and other sector rows
are never touched — FR-003), changes only `sector`, and a second run updates 0 rows. Wired into
`scripts/apply_migrations.sh` after step 22 in both paths; `scripts/verify_schema.sql` gets a check
that expects 0 market rows with a label other than the new one.

**Rationale**: The repo's upgrade path for existing databases is `migrate_*.sql` applied by
`apply_migrations.sh` (constitution VI, Development Workflow). A data-only step keeps the change
reviewable and runnable by the owner with `psql`, and the dev-backfill CI applies it for free.
Matching on ticker rather than the old label also fixes any row with an unexpected label.

**Alternatives considered**:
- Rerun `compute_indices.py --country us|swe|uk` — relabels as a side effect, but rewrites every
  value (FR-002 / SC-002 require "no other column changes") and needs ~1 hour of downloads. It
  remains a valid path when the 002 rollout (002 T031) runs anyway after this deploy.
- Python one-off script — rejected: SQL belongs in `migrate_*.sql` / `db/`, and a script would
  pollute the repo for a single `UPDATE`.
- Let retention age the old labels out (≤ 365 days) — rejected by User Story 2.

## R3 — Deploy order and interaction with the weekly run

**Decision**: Deploy the code first, then apply step 23. Re-applying is safe at any time.

**Rationale**: The weekly run writes the market row from code and re-inserts the week's other rows
with their stored labels (`write_index_weeks(..., only_tickers=...)` → `_stored_row`). So:
- code deployed, step 23 not yet run: new weeks get the new label, older weeks keep the old one
  until step 23 runs;
- step 23 run before the deploy: a weekly run on the old code writes one market row with the old
  label; re-running step 23 fixes it (spec edge case).

## R4 — Consumer (`fansboda`)

**Decision**: No consumer change is required.

**Rationale**: `fansboda/src/routes/stocks.py` identifies market rows by ticker
(`MARKET_INDEX_TICKERS = {"US-IDX", "SWE-IDX"}`, queries by `Indice.ticker`) and only displays
`sector` via `_display_sector`, which replaces dashes with spaces and collapses whitespace —
"NYSE & Nasdaq" passes through unchanged and Jinja autoescapes the `&`. Its tests seed rows with
the old labels as fixture data, which still pass; updating them is optional and outside this repo.

## R5 — Label collisions (FR-004)

**Decision**: Add a unit test that the three market names differ from the sector-index names of
all yfinance sector keys and from each other.

**Rationale**: Sector names are `sectorKey.replace("-", " ").title()` (e.g. "Technology",
"Financial Services"); none can contain "&" or equal an exchange name, but a test keeps that true
if names change again.

## R6 — Documentation

**Decision**: Update `schema.sql` comment (label example), the `IndexRow` docstring, and
`.cursor/rules/RULES.mdc` (example label `US Equity Index` → `NYSE & Nasdaq`). Leave
`migrate_indices_sectors.sql` (step 21 describes the data at that time), `project-docs/` (frozen),
and specs 001/002 unchanged (FR-005).
