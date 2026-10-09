# Research: Market Index Z-Score Set to 0

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

## R1 — Where the market row's z-score is set

**Decision**: In `equity_index.with_sector_z_scores`, give rows with `sector_key is None` (market
rows) `z_score = Decimal(0)`; sector rows unchanged.

**Rationale**: Every `indices` write goes through `db.indices.write_index_weeks`, which passes the
week's rows through `with_sector_z_scores` in both branches (full week, and `only_tickers` where
kept rows are re-read without `z_score` and recomputed). The weekly run, new-sector start, and
`compute_indices.py` all use that path, so one change covers FR-001. The function already
collects momenta only from rows with a `sector_key`, so the market's 0 never enters the sector
mean / spread (FR-002).

**Alternatives considered**:
- Set 0 in `build_index_row` / `_row` for market definitions — rejected: `with_sector_z_scores`
  rebuilds `z_score` for every row and would overwrite it.
- Set 0 in SQL (`INSERT … COALESCE`) — rejected: logic belongs in pure Python (constitution VII),
  and the in-memory rows returned to callers would disagree with the database.
- Market z-score 0 even when market momentum is NULL — chosen: the 0 is a convention ("the
  reference level"), not computed from momentum; spec FR-001 says every market row.

## R2 — Stored rows: one-time step

**Decision**: Migration step 24, `migrate_market_index_zero_z.sql`:

```sql
UPDATE indices
SET z_score = 0
WHERE ticker IN ('US-IDX', 'SWE-IDX', 'UK-IDX')
  AND z_score IS DISTINCT FROM 0;
```

Exact-ticker match (never `LIKE`, which would include sector rows), only `z_score` changes, a
second run updates 0 rows. Wired after step 23 in both paths of `scripts/apply_migrations.sh`;
`scripts/verify_schema.sql` gets "market rows with z_score not 0 — expect 0 rows".

**Rationale**: Same pattern as step 23 (specs/003-market-index-names), the established upgrade
path for existing databases.

**Alternatives considered**: rerun `compute_indices.py` per country — also writes 0 but rewrites
every value and takes ~1 hour of downloads (fails FR-003's "no other column").

## R3 — Deploy order

**Decision**: Deploy the code first, then apply step 24; re-applying is always safe.

**Rationale**: If step 24 runs first, a weekly run on old code writes NULL for that week's market
rows; running step 24 again fixes it (spec edge case). After deploy, the weekly run itself keeps
writing 0.

## R4 — Consumer (`fansboda`)

**Decision**: No consumer change required.

**Rationale**: `fansboda/src/routes/stocks.py::_sector_row` reads `z_score` into
`heat_color_from_z(z)` / `_heat_title(z)`; 0 yields the neutral heat colour and
`heat_hot = round(0, 2) > 1` is False. Market rows are identified by ticker
(`MARKET_INDEX_TICKERS`).

## R5 — Documentation

**Decision**: Update `README.md` (Sector z-score paragraph: "Market index rows have z-score 0 by
convention — the market is the reference its sectors are compared with"; "When a value is empty"
table row for index `z_score`: drop "always on market rows"), `RULES.mdc` (`z_score` … "0 on market
rows"), the `with_sector_z_scores` and `IndexRow` docstrings where they say NULL on market rows,
and the `schema.sql` comment if it mentions it. Leave `project-docs/` and earlier specs unchanged.
