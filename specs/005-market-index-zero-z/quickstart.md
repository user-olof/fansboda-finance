# Quickstart: Validate Market Index Z-Score 0

**Feature**: [spec.md](./spec.md) | Contract: [migration-step-24.md](./contracts/migration-step-24.md)

Never run these against the `.env` / production database.

## 1. Unit tests

```bash
PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q
```

Expected: all pass, including the updated `with_sector_z_scores` / `write_index_weeks` tests
(market row z-score 0, sector z-scores unchanged) and the step 24 tests in `tests/test_schema.py`.

## 2. Step 24 on a throwaway Postgres

```bash
docker run -d --rm --name idx005-pg -e POSTGRES_PASSWORD=pg postgres:16
docker exec -i idx005-pg psql -U postgres -v ON_ERROR_STOP=1 < schema.sql
```

Insert market rows (`US-IDX`, `SWE-IDX`, `UK-IDX`) with `z_score` NULL, one sector row with a
z-score and one sector row with NULL; snapshot the table; then apply the step twice:

```bash
docker exec -i idx005-pg psql -U postgres -v ON_ERROR_STOP=1 < migrate_market_index_zero_z.sql  # UPDATE 3
docker exec -i idx005-pg psql -U postgres -v ON_ERROR_STOP=1 < migrate_market_index_zero_z.sql  # UPDATE 0
```

Expected: market rows `z_score = 0`; both sector rows unchanged (including the NULL one); every
other column equals the snapshot; the step 24 query in `scripts/verify_schema.sql` returns 0 rows.

```bash
docker rm -f idx005-pg
```

## 3. Docs

```bash
rg -n -i "market.*(no z-score|null)|always on market rows" README.md .cursor/rules/RULES.mdc equity_index.py
```

Expected: no matches; README and RULES describe 0 on market rows.
