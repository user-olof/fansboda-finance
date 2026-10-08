# Contract: `compute_indices.py` (one-off initialization)

Interface unchanged from [001](../../001-index-initial-sma/contracts/compute-indices-cli.md):

```text
pipenv run python compute_indices.py [--country us|swe|uk]
```

- Manual only, never cron. Exit 0 when every requested country was initialized; exit 1 when the
  config is invalid, an unexpected error occurs, or any country was left unchanged (all-or-nothing
  per country, 001 R11).

Behavior changes:

- Downloads daily history per country from `INDEX_START_DATE − 400` days to today (one pass, plus
  the 001 second pass for indices below the minimum on the start date).
- Every stored week's row is computed from the index's daily series (price, SMA-50, SMA-200); no
  weekly growth chaining and no weekly bridge.
- Per-index log line: `start_date`, first and last row date, `sma_50`, `sma_200`, momentum on the
  start date, and days used for the start-date SMA-200.

# Contract: weekly index update in `fetch_sma.py` (cron)

- No new arguments or settings.
- Download window per batch: 400 calendar days (was 300).
- Log lines added: supplemental download (`Index history: downloading N member(s) not in this
  run`), per country daily returns dropped as outliers, errors for indices whose previous row is
  older than the download (`run compute_indices.py --country …`).
