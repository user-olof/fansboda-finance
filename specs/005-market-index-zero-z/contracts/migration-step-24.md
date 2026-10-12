# Contract: Migration step 24 — `migrate_market_index_zero_z.sql`

Follows step 23 (specs/003-market-index-names).

| Property | Value |
|---|---|
| File | `migrate_market_index_zero_z.sql` (repo root) |
| Kind | Data only (`UPDATE`); no DDL; `schema.sql` unchanged except comments |
| Prerequisite | Step 21 (`indices.z_score` exists); runs after step 23 |
| Idempotent | Yes — second run updates 0 rows |
| Destructive | No — only `indices.z_score` on the three market tickers |
| Scope | `ticker IN ('US-IDX', 'SWE-IDX', 'UK-IDX')`; sector rows untouched |
| Wiring | `scripts/apply_migrations.sh`: after `migrate_rename_market_indices.sql` in both the "past step 14" block and the full path |
| Verification | `scripts/verify_schema.sql`: market rows with `z_score IS DISTINCT FROM 0` — expect 0 rows |

## Order on production

1. Deploy the code (merge to `main`; `deploy.yml`).
2. `psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrate_market_index_zero_z.sql`
3. Run the verify query; expect 0 rows.

If step 2 ran before the deploy and a weekly run on the old code wrote a market row in between,
run step 2 again.

## Consumer-facing change

`indices.z_score` on market rows: NULL → 0. All other columns and all sector rows unchanged.
