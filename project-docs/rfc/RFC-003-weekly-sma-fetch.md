# RFC-003: Weekly SMA Fetch

| Field | Value |
|-------|-------|
| **Priority** | P1 |
| **Status** | Implemented |
| **Depends on** | RFC-001, RFC-002, RFC-006 |
| **PRD** | FR-1 – FR-8 |
| **Feature** | [Weekly SMA fetch](../FEATURES.md#weekly-sma-fetch-fetch_smapy) |

## Summary

Core weekly job (`fetch_sma.py`): load watchlist, skip tickers already at the global max `trading_date`, batch-download ~300 days OHLCV from yfinance, compute SMA-50/200, copy `name` from `tickers`, capture `currency` from yfinance, append metrics rows, purge stale history. Runs **Thursdays 11:00 UTC** via cron (RFC-008).

## Requirements

| ID | Requirement |
|----|-------------|
| FR-1 | Load watchlist from `tickers`; fail clearly if empty |
| FR-2 | Skip tickers already fresh at global max `trading_date` |
| FR-3 | Batch download ~300d OHLCV (default 40 symbols/batch, delay between batches) |
| FR-4 | Retry 429, rate, timeout, connection, empty frames with exponential backoff |
| FR-5 | Compute SMA-50/200; skip if &lt;200 closes; set `current_price`, `trading_date`, `currency`; copy `name` from `tickers` |
| FR-6 | Append with `ON CONFLICT (ticker, trading_date) DO NOTHING` |
| FR-7 | Retention purge after run (RFC-004) |
| FR-8 | Log batch progress, per-ticker results, summary; non-zero exit on fatal errors |

## Implementation

### Module layout

| Layer | Module | Responsibility |
|-------|--------|----------------|
| Config | `config.py` | `get_config()` — all tunables |
| Domain | `models.py` | `TickerEntry`, `MetricRow` |
| DB | `db/tickers.py` | `load_tickers_from_db` |
| DB | `db/metrics.py` | `filter_stale_tickers`, `insert_metrics`, `purge_stale_metrics` |
| Job | `fetch_sma.py` | Orchestration, yfinance, SMA math |
| Tests | `tests/test_fetch_sma.py` | Pure logic + mocked DB/yfinance |

### Key functions (`fetch_sma.py`)

| Function | Purpose |
|----------|---------|
| `load_tickers(path)` | Parse symbol file (shared with seed script) |
| `compute_smas(close)` | SMA-50 and SMA-200 from close series |
| `metric_row_from_history(...)` | Single-ticker metric from OHLCV frame; copies `name` from watchlist |
| `resolve_currency(symbol)` | yfinance `.info` lookup for `currency` |
| `download_batch(...)` | yfinance batch with retry/backoff, `threads=False` |
| `metric_rows_from_batch(...)` | Parse MultiIndex download into `MetricRow` list |
| `main()` | Full weekly pipeline |

### `main()` flow

1. `config = get_config()`
2. `watchlist = load_tickers_from_db(config.database_url)`
3. `stale, skipped, max_date = filter_stale_tickers(...)`
4. If all fresh: retention purge only, exit 0
5. For each batch: resolve `currency` per ticker → `download_batch` → `metric_rows_from_batch` → `insert_metrics`
6. `purge_stale_metrics(config.database_url, config.metrics_retention_days)`
7. Log summary; exit 1 if no metrics collected or fatal DB error

### Cron (production)

Installed by `scripts/bootstrap-vm.sh` — see RFC-008.

## Acceptance criteria

- [x] Loads watchlist; fails clearly if empty
- [x] Skips fresh tickers at global max `trading_date`
- [x] Batched yfinance download with retry/backoff
- [x] Computes SMA-50, SMA-200, current price
- [x] Copies `name` from `tickers` into each metrics row (PRD §6)
- [x] Populates `currency` on each metrics row (PRD §6)
- [x] Appends with `ON CONFLICT (ticker, trading_date) DO NOTHING`
- [x] SQL in `db/` modules, not in job script
- [x] Retention purge on every run (RFC-004)
- [x] Uses `get_config()` (RFC-006)
- [x] Logs batch progress and summary
- [x] Unit tests with mocked DB and yfinance

## Open questions

- **Global vs per-ticker stale check:** Implementation uses global max `trading_date`. Intentional for weekly job where all tickers share the same latest session date. PRD FR-2 wording is per-ticker; behavior matches “skip if already at latest week’s date” in practice when all tickers are fetched together.
