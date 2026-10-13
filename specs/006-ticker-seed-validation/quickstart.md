# Quickstart: Ticker Seed Validation

## Unit tests (offline)

```bash
PIPENV_DONT_LOAD_ENV=1 pipenv run pytest tests/test_seed_tickers.py tests/test_refresh_tickers.py tests/test_yfinance_client.py
PIPENV_DONT_LOAD_ENV=1 pipenv run pytest
```

Expected: all pass. Scenarios covered (see [data-model.md](./data-model.md)):

1. Complete ticker → stored unchanged.
2. Missing company / sector / industry (one test each, plus whitespace-only) → not in the upsert
   rows; `Discarded <SYMBOL>: missing …` logged.
3. Lookup raises → not in the upsert rows; counted as discarded.
4. Missing market → stored with the inferred market; `Stored <SYMBOL> with missing market`.
5. Missing exchange → stored with NULL exchange; warning logged.
6. All discarded → `upsert_tickers` gets no rows (returns 0); run exits 0.
7. Summary line `Ticker check: stored=… discarded=… warned=…` matches the outcomes.
8. Refresh path: a discarded stored ticker is not passed to the upsert (row left untouched).

## Manual check (dev database only)

Use a small symbol file with one good and a few bad symbols (e.g. a fund or a mistyped symbol):

```bash
printf 'AAPL\nSPY\nNOTAREALTICKER\n' > /tmp/seed-006.txt
pipenv run python seed_tickers.py /tmp/seed-006.txt --country us
```

Expected log: `Discarded SPY: missing sector, industry` (funds have no sector),
a discard for `NOTAREALTICKER`, `Ticker check: stored=1 discarded=2 warned=0`, and
`Seeded 1 ticker(s) from /tmp/seed-006.txt (country=us)`. Never run this against production.

## Contract

Log lines: [contracts/seed-log.md](./contracts/seed-log.md).
