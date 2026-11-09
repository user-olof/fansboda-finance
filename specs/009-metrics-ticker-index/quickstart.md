# Quickstart: Validate Per-Stock Lookup Indexes

**Feature**: [spec.md](./spec.md) | Contract: [migration-step-25.md](./contracts/migration-step-25.md)

Steps 1–2 never touch the `.env` / production database. Step 4 is for the owner only.

## 1. Unit tests

```bash
PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q
```

Expected: all pass, including the step 25 / schema index tests in `tests/test_schema.py`.

## 2. Step 25 on a throwaway Postgres

```bash
docker run -d --rm --name idx009-pg -e POSTGRES_PASSWORD=pg postgres:17
docker exec -i idx009-pg psql -U postgres -v ON_ERROR_STOP=1 < schema.sql
```

a. **Fresh schema**: the three indexes exist and are valid (verification query in the contract).

b. **Existing DB without the index**: drop the three indexes, insert a few thousand
`us_metrics` rows (with matching `us_tickers`), snapshot `count(*)` and a checksum of the rows,
then apply the step twice:

```bash
docker exec -i idx009-pg psql -U postgres -v ON_ERROR_STOP=1 < migrate_metrics_ticker_index.sql
docker exec -i idx009-pg psql -U postgres -v ON_ERROR_STOP=1 < migrate_metrics_ticker_index.sql
```

Expected: 3 valid indexes; second run prints only `NOTICE … already exists, skipping`; row count
and checksum unchanged.

c. **Invalid index repair**: mark one index invalid
(`UPDATE pg_index SET indisvalid = false WHERE indexrelid = 'idx_uk_metrics_ticker_trading_date'::regclass;`
as superuser — throwaway DB only), apply the step, and confirm it is valid again.

d. **Non-blocking**: in one session `BEGIN; INSERT INTO us_metrics …;` (hold it), drop the US
index, apply the step in another session — it waits for the open transaction, while new inserts
from a third session succeed; after `COMMIT` the step finishes.

e. **Plans**: `EXPLAIN` the chart-history and latest-observation lookups
(see [data-model.md](./data-model.md)) — both use `idx_us_metrics_ticker_trading_date`.

```bash
docker rm -f idx009-pg
```

## 3. Dev

Run `dev-backfill.yml` (applies `apply_migrations.sh`, including step 25) and check the job log
for `Applying migrate_metrics_ticker_index.sql...` with no error.

## 4. Production (owner)

Follow the contract's rollout: step 25 alone over the direct endpoint, then the verification
query. Then, in a read-only session (`BEGIN READ ONLY; … ROLLBACK;`), re-run the
`EXPLAIN (ANALYZE, BUFFERS)` checks from the 2026-11-09 investigation:

| Lookup | Expected after |
|---|---|
| Chart history, one US stock | index scan, < 10 ms (was 34 ms) |
| Latest observation, Swedish stock in `us_metrics` (miss) | index scan, < 10 ms (was ≈ 300 ms) |
| Latest row for 25 stocks | index scans, < 10 ms (was 107 ms) |

And confirm the next Saturday run's log and row counts look as usual (SC-005).
