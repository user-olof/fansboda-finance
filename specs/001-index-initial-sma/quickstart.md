# Quickstart: validate Index Initial SMA from Daily History

## Prerequisites

- `pipenv install --dev`
- Docker (local Postgres 16) for the end-to-end check; never the `.env` / production database
  for write tests.

## 1. Unit tests

```bash
PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q
```

Expected: all tests pass, including `tests/test_index_anchor.py` (reconstruction, initial SMAs,
bridge, sector keys, missing data, outlier days) and the updated `tests/test_compute_indices.py`.

## 2. Local end-to-end rebuild

```bash
docker run -d --name fb-pg -e POSTGRES_PASSWORD=pw -p 55432:5432 postgres:16-alpine
export PIPENV_DONT_LOAD_ENV=1 APP_ENV=dev DATABASE_URL=postgresql://postgres:pw@localhost:55432/postgres
psql "$DATABASE_URL" -f schema.sql
pipenv run python seed_tickers.py small-tickers.txt --country swe
pipenv run python backfill_sma.py --country swe
pipenv run python compute_indices.py --country swe
```

Expected (see [contracts/compute-indices-cli.md](./contracts/compute-indices-cli.md)):

- Every `SWE-IDX*` ticker has its oldest row on 2025-10-03 with `current_price = 100`.
- No `indices` row before 2025-10-03.
- Logs show the anchor SMA-50 / SMA-200 and days used (250 → SMA-200 from 200 levels).

```sql
SELECT ticker, min(trading_date) FROM indices GROUP BY 1 HAVING min(trading_date) <> '2025-10-03';
-- 0 rows
SELECT ticker, current_price, sma_50, sma_200 FROM indices WHERE trading_date = '2025-10-03';
-- current_price = 100.000000 for every index
```

## 3. Bridge after retention

```sql
DELETE FROM swe_metrics WHERE week_start < '2025-10-13';
```

```bash
pipenv run python compute_indices.py --country swe
```

Expected: the oldest index row is in the week of 2025-10-13, and its levels match (to six
decimals, see SC-004) the same week from step 2.

## 4. New sector in the weekly path

Delete one sector's rows (`DELETE FROM indices WHERE ticker = 'SWE-IDX-ENERGY'`) and call the
weekly update step from a Python shell, `fetch_sma._run_index_update(config, {latest_week})`
(never run `fetch_sma.py` itself). Expected: a download for the energy stocks only, all other
`SWE-IDX*` levels unchanged, and `SWE-IDX-ENERGY` rows again from its start date — 2025-10-03 if
at least 5 energy stocks have a price on it — with the same levels as step 2 (logged with the
start date and `days_used`). With fewer than 5 energy stocks in `small-tickers.txt`, the warning
names the sector instead.

## 4b. Moving the start date

Set `INDEX_START_DATE` (ISO date, a week's last trading day) in `.env`, or in the GitHub
`production` environment for the VM, for example `INDEX_START_DATE=2025-10-10`, then rerun
`pipenv run python compute_indices.py` (all countries). Expected: every index with at least 5
stocks priced on the new date has price 100 on it, and no row is dated before it.

## 5. Production rollout

1. Merge and deploy.
2. On the VM (or locally against production, read-write, once): `pipenv run python
   compute_indices.py` — ≈20–25 minutes.
3. Read-only check: the two queries in step 2 against production.
