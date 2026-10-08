# Contract: `compute_indices.py` CLI (one-off initialization)

```text
pipenv run python compute_indices.py [--country us|swe|uk]
```

| Aspect | Before | After |
|---|---|---|
| Role | Full rebuild, also called incrementally by `fetch_sma.py` | One-off manual initialization only (never cron, never called by `fetch_sma.py`) |
| Flags | `--country` | unchanged |
| Effect | Deletes the country's `indices` rows, rebuilds from the oldest stored metrics week | Deletes the country's rows, rebuilds from the start date `INDEX_START_DATE` (default 2025-10-03); no rows before it |
| Network | None | One batched yfinance download per country (≈400 days before the start date to today) |
| Exit code | 0 success, 1 on error | unchanged; a failed download batch is logged and does not fail the run; if any index the country already has gets no anchor, that country is left unchanged (no delete, no write) and the run exits 1 after the other countries; a new sector without data is skipped and logged |
| Logs | Per market row levels; outliers; summary | + per index: anchor week, initial SMA-50 / SMA-200, days used, members missing from the download |
| Duration | Seconds | ≈20–25 minutes for all three countries |

Environment: `DATABASE_URL`, `APP_ENV`, `INDEX_START_DATE`, `INDEX_HISTORY_TRADING_DAYS`,
`INDEX_MIN_COMPONENTS`,
existing `YF_*` and `OUTLIER_*` variables.

`fetch_sma.py` (weekly job) does the weekly index update itself and no longer imports this script:
after the metrics upsert and retention purge it chains the new week onto existing indices without
downloading. A new sector index is created with the same start-date rule (2025-10-03 if at least
5 of its stocks have a price on it, else the first later week-end with 5) and initial SMAs from
the same `index_anchor.compute_anchors` (download of that sector's stocks only); its rows are
written from its start week, the other indices' levels are kept. A country without
any index rows is skipped and logged as "country <c> has no indices; run compute_indices.py
--country <c>".
