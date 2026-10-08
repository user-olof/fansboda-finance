# Contract: Migration step 23 — `migrate_rename_market_indices.sql`

Continues the step numbering of the frozen `project-docs/MIGRATIONS.md` (last step 22).

| Property | Value |
|---|---|
| File | `migrate_rename_market_indices.sql` (repo root) |
| Kind | Data only (`UPDATE`); no DDL; `schema.sql` unchanged except a comment |
| Prerequisite | Step 21 (`indices.sector` exists); runs after step 22 |
| Idempotent | Yes — second run updates 0 rows |
| Destructive | No — only `indices.sector` on the three market tickers |
| Scope | Rows with `ticker` exactly `US-IDX`, `SWE-IDX`, or `UK-IDX`; sector rows untouched |
| Wiring | `scripts/apply_migrations.sh`: after `migrate_drop_by_sector_tables.sql` in both the "past step 14" block and the full path |
| Verification | `scripts/verify_schema.sql`: market rows with a label other than the new one — expect 0 rows |

## Order on production

1. Deploy the code (merge to `main`; `deploy.yml`).
2. `psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrate_rename_market_indices.sql`
3. Run the verify query; expect 0 rows.

If step 2 ran before the deploy and a weekly run on the old code wrote a market row in between,
run step 2 again.

If the 002 rollout (`compute_indices.py --country us|swe|uk`) runs after this deploy, it also
rewrites every market row with the new label; step 23 stays harmless.
