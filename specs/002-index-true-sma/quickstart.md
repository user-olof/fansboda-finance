# Quickstart: validate true index SMAs

Never run against the `.env` / production database. Use a local Docker Postgres 16 and
`PIPENV_DONT_LOAD_ENV=1` with an explicit `DATABASE_URL`. Never smoke-test with `fetch_sma.py`
against production.

## 1. Unit tests

```bash
PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q
```

Expected: all pass, including `daily_levels` / `week_levels` cases from
[data-model.md](./data-model.md) (flat prices → SMA-50 = SMA-200 = price; one-stock index momentum
equals the stock's).

## 2. Local database with a small watchlist

Follow the prerequisites and the setup steps of 001 [quickstart.md](../001-index-initial-sma/quickstart.md)
§2 (Docker Postgres, `schema.sql`, seed a small US list, `backfill_sma.py --country us`).

## 3. Initialization

```bash
PIPENV_DONT_LOAD_ENV=1 DATABASE_URL=postgresql://postgres:postgres@localhost:5432/fansboda \
  pipenv run python compute_indices.py --country us
```

Expected: exit 0; `US-IDX` has `current_price = 100` on `INDEX_START_DATE`.

Check one row against a true moving average: export `US-IDX` rows and, for its member stocks,
compute the equal-weighted daily index price from adjusted closes in a notebook; the stored
`sma_50` / `sma_200` match the 50 / 200-day means of that price to six decimals (SC-001).

## 4. Weekly update

Delete the latest week's metrics and index rows locally, then run the weekly job against the local
database. Expected: the latest week is written again with the same values (to six decimals,
barring data revisions); the log shows no supplemental download on a full run, and a
supplemental download for the skipped members when the run is repeated in the same week.

## 5. Production rollout (owner, manual)

After deploy, run `compute_indices.py` once per country (`--country us`, `swe`, `uk`) and check
exit 0 and the summary line. Until then, stored rows keep the 001 values; the weekly run chains
new weeks from the latest stored row.
