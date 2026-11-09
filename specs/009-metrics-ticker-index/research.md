# Research: Fast Per-Stock Lookups in the Metrics Tables

**Feature**: [spec.md](./spec.md) | **Date**: 2026-11-09

User input for the plan: "don't make any changes to technical constraints" — the spec's
constraints (no data change, no column / formula / schedule / consumer-app change, re-runnable,
non-blocking on production, free tier) are taken as fixed.

## R1 — Index shape

- **Decision**: one plain B-tree per country set on `(ticker, trading_date)`:
  `idx_us_metrics_ticker_trading_date`, `idx_swe_metrics_ticker_trading_date`,
  `idx_uk_metrics_ticker_trading_date`.
- **Rationale**: every slow lookup measured on 2026-11-09 filters on `ticker` (equality or `IN`)
  and orders / bounds by `trading_date`:
  `ticker = ? AND trading_date >= ? ORDER BY trading_date` (chart history),
  `ticker = ? ORDER BY trading_date DESC LIMIT 1` (latest observation, also the US-table miss for
  a Swedish / UK stock), `MAX(trading_date) … WHERE ticker IN (…) GROUP BY ticker` (latest row for
  a page), `DISTINCT ticker WHERE ticker IN (…)`. A `(ticker, trading_date)` B-tree answers all of
  them with an index range scan; a backward scan serves the `DESC` cases, so no `DESC` column is
  needed. Naming follows the existing `idx_<table>_trading_date`.
- **Alternatives considered**:
  - `(ticker)` alone — serves equality but not the date order / latest-row lookups.
  - `(ticker, week_start)` — the app filters and orders on `trading_date`, not `week_start`.
  - Covering index `INCLUDE (sma_50, sma_200, …)` — larger, more write cost, and the per-stock
    lookups touch ≤ 53 heap rows anyway; not needed for the success criteria.
  - Reordering the existing unique `(week_start, ticker)` to `(ticker, week_start)` — rewrites a
    constraint the upserts depend on (`ON CONFLICT (ticker, week_start)` is order-independent, but
    the weekly purge / week queries benefit from `week_start` first); higher risk, no gain.
  - Changing the consumer app's queries (e.g. try the right country table first) — out of scope
    (separate repository); the index already makes the US-table miss cheap.

## R2 — Non-blocking build on production

- **Decision**: the upgrade step builds the indexes with
  `CREATE INDEX CONCURRENTLY IF NOT EXISTS`, one statement per table, with no `BEGIN` / `COMMIT`
  in the file.
- **Rationale**: `CONCURRENTLY` takes only a `SHARE UPDATE EXCLUSIVE` lock — reads and the
  Saturday job's writes continue (FR-004). It cannot run inside a transaction block; `psql -f`
  (how `apply_migrations.sh` runs every file) runs each statement in autocommit unless `-1` is
  given, which the script does not use. Measured table size (US ≈ 259 k rows, 46 MB heap) means
  each build takes seconds, well under SC-004's minute.
- **Alternatives considered**: plain `CREATE INDEX` — takes a `SHARE` lock that blocks inserts /
  updates for the build's duration; acceptable only on empty or small tables (see R4).

## R3 — Repairing an interrupted build (FR-005)

- **Decision**: before the creates, drop any **invalid** index of the three names with a psql
  `\gexec` query: select `DROP INDEX CONCURRENTLY IF EXISTS <name>` for each matching
  `pg_index.indisvalid = false` entry, and let `\gexec` run each result as its own statement.
- **Rationale**: an interrupted `CREATE INDEX CONCURRENTLY` leaves an `INVALID` index under the
  name; `IF NOT EXISTS` would then skip it and the step would "succeed" with an unusable index.
  `DROP INDEX CONCURRENTLY` also cannot run in a transaction or a `DO` block, so the
  conditional drop must be issued as top-level statements — `\gexec` does exactly that and is
  available because the step is applied with `psql`. Identifiers come from fixed names in the
  file, formatted with `%I`; no runtime data.
- **Alternatives considered**:
  - `REINDEX INDEX CONCURRENTLY` on invalid ones — also cannot be conditional without `\gexec`,
    and fails on a missing index; same mechanism, more cases.
  - A `DO` block — cannot run `CONCURRENTLY` statements.
  - Always drop then create — rebuilds valid indexes on every re-run (not "without changes").

## R4 — Fresh databases and `schema.sql`

- **Decision**: `schema.sql` gets plain
  `CREATE INDEX IF NOT EXISTS idx_<set>_metrics_ticker_trading_date ON <set>_metrics (ticker,
  trading_date);` next to each existing `idx_<set>_metrics_trading_date` (FR-002).
- **Rationale**: matches the existing style; on a fresh database the tables are empty so the
  lock is irrelevant. `apply_migrations.sh` runs `schema.sql` first on **every** run, so on an
  existing database where step 25 has not run yet, this line would build the index with a short
  write-blocking lock (seconds; reads unaffected). The rollout therefore applies step 25 **on its
  own first** (quickstart, contract); `schema.sql`'s `IF NOT EXISTS` is then a no-op. If the owner
  runs the full script first instead, the result is the same index after a brief write pause —
  acceptable fallback, not the documented path.
- **Alternatives considered**: `CONCURRENTLY` in `schema.sql` — breaks anyone applying
  `schema.sql` inside a transaction (e.g. `psql -1`, SQL editors); keep schema.sql transaction-safe.

## R5 — Which Neon connection to use

- **Decision**: apply step 25 to production over the **direct** (non-pooler) endpoint: the same
  `DATABASE_URL` with `-pooler` removed from the host. `apply_migrations.sh` is unchanged; the
  owner passes that URL in the environment.
- **Rationale**: the stored `DATABASE_URL` uses Neon's PgBouncer pooler in transaction mode. A
  `CONCURRENTLY` build waits for older transactions and runs as several internal transactions
  inside one statement; Neon recommends direct connections for schema migrations, and a direct
  session avoids any pooler statement / idle limits during the build.
- **Alternatives considered**: pooler URL — likely works for a single autocommit statement, but
  unverified and not recommended for DDL; no reason to risk it.

## R6 — Verification and cost

- **Decision**: `scripts/verify_schema.sql` gets a query listing the three indexes with
  `indisvalid` (expect 3 valid rows) (FR-006); `tests/test_schema.py` asserts the schema lines,
  the step file (names, `CONCURRENTLY`, invalid-index repair, no `BEGIN`), its registration in
  `apply_migrations.sh`, and its place in `MIGRATIONS`. Validation of the lookups' plans is
  manual with `EXPLAIN (ANALYZE, BUFFERS)` in a read-only session (quickstart).
- **Rationale**: the repository has no live-DB tests; SQL files are checked textually and on a
  throwaway Postgres, as in specs 003 / 005.
- **Cost**: the existing `(week_start, ticker)` unique index on `us_metrics` is 15 MB and the
  `id` primary key 6.9 MB; the new index holds the same key widths, so ≈ 7–15 MB for US and
  ≈ 2–4 MB for Swedish + UK together — under 20 MB on a 104 MB database, within the Neon free tier
  (0.5 GB). Weekly write cost: one extra index entry per stored row (~6 500 rows / week) —
  negligible.
