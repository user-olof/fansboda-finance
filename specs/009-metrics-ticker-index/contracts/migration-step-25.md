# Contract: Migration Step 25 — `migrate_metrics_ticker_index.sql`

**Feature**: [spec.md](../spec.md) | Research: R2–R5

## Order

Step 25, after step 24 (`migrate_market_index_zero_z.sql`). Registered at the end of both paths
in `scripts/apply_migrations.sh` (the "already past step 14" fast path and the full path).

## Effect

For each of `us_metrics`, `swe_metrics`, `uk_metrics`:

1. If an index named `idx_<set>_metrics_ticker_trading_date` exists and is **invalid**
   (`pg_index.indisvalid = false`, left by an interrupted build), drop it with
   `DROP INDEX CONCURRENTLY IF EXISTS` (issued through psql `\gexec`).
2. `CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_<set>_metrics_ticker_trading_date
   ON <set>_metrics (ticker, trading_date);`

No other object or row changes.

## File rules

- Header comment: step number, spec folder, what it does, "Safe to repeat", and that it must not
  run in a transaction (`psql -f` without `-1` / `--single-transaction`), plus the direct
  (non-pooler) connection note for Neon.
- No `BEGIN` / `COMMIT`; every `CONCURRENTLY` statement is top-level.
- Only fixed identifiers; no runtime values.
- Requires `psql` (uses `\gexec`), as every step applied by `apply_migrations.sh` does.

## Guarantees

| Situation | Result |
|---|---|
| Index missing | built without blocking reads / writes |
| Index valid | nothing happens (no rebuild) |
| Index invalid | dropped and rebuilt |
| Applied twice | second run changes nothing |
| Fresh DB from `schema.sql` | indexes already present (plain `CREATE INDEX IF NOT EXISTS`); step is a no-op |
| Rows | 0 added / removed / changed |

## Verification

`scripts/verify_schema.sql`:

```sql
-- step 25: per-stock lookup indexes (spec 009)
SELECT c.relname AS indexname, i.indisvalid
FROM pg_index i
JOIN pg_class c ON c.oid = i.indexrelid
WHERE c.relname IN (
    'idx_us_metrics_ticker_trading_date',
    'idx_swe_metrics_ticker_trading_date',
    'idx_uk_metrics_ticker_trading_date'
  )
ORDER BY 1;
-- expect 3 rows, indisvalid = true
```

## Production rollout

1. Apply step 25 **alone first**, over the direct endpoint (host without `-pooler`):
   `psql "$DIRECT_DATABASE_URL" -v ON_ERROR_STOP=1 -f migrate_metrics_ticker_index.sql`.
2. Run the verification query (3 valid rows).
3. Later full `apply_migrations.sh` runs are no-ops for these indexes (`schema.sql` and step 25 both
   use `IF NOT EXISTS`). Running the full script first instead still works but builds the indexes
   through `schema.sql` with a short write-blocking lock (research R4).
