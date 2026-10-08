# Quickstart: Validate the Market Index Rename

**Feature**: [spec.md](./spec.md) | Contracts: [indices-table.md](./contracts/indices-table.md),
[migration-step-23.md](./contracts/migration-step-23.md)

Never run these against the `.env` / production database. Use a local Docker Postgres.

## 1. Unit tests

```bash
PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q
```

Expected: all pass, including the market-label tests in `tests/test_compute_indices.py`, the
collision test (FR-004), and the step 23 file / wiring tests in `tests/test_schema.py`.

## 2. Relabel step on a local database (User Story 2)

```bash
docker run -d --name idx-pg -e POSTGRES_PASSWORD=pg -p 55432:5432 postgres:16
export DATABASE_URL=postgresql://postgres:pg@localhost:55432/postgres
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f schema.sql
```

Insert one row per market ticker with the old label and one sector row (e.g. `US-IDX` /
`US Equity Index`, `SWE-IDX` / `OMX Equity Index`, `UK-IDX` / `FTSE Equity Index`,
`US-IDX-TECHNOLOGY` / `Technology`), snapshot the table, then:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrate_rename_market_indices.sql   # UPDATE 3
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrate_rename_market_indices.sql   # UPDATE 0
```

Expected:
- market rows read `NYSE & Nasdaq`, `OMX Stockholm`, `FTSE London`;
- `US-IDX-TECHNOLOGY` still reads `Technology`;
- every other column equals the snapshot (SC-002);
- the step 23 query in `scripts/verify_schema.sql` returns 0 rows (SC-001).

## 3. New rows carry the new label (User Story 1)

On the same local database with seeded tickers/metrics (as in the 002 quickstart), run
`PIPENV_DONT_LOAD_ENV=1 DATABASE_URL=... pipenv run python compute_indices.py --country swe`.

Expected: `SELECT DISTINCT sector FROM indices WHERE ticker = 'SWE-IDX'` returns only
`OMX Stockholm`; sector rows keep their sector names.

## 4. Clean up

```bash
docker rm -f idx-pg
```
