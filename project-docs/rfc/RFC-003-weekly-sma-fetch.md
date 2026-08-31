# RFC-003: Weekly SMA Fetch

| Field | Value |
|-------|-------|
| **Priority** | P1 |
| **Status** | Implemented |
| **Depends on** | RFC-001, RFC-002, RFC-006 |
| **PRD** | FR-1 – FR-8 |
| **Feature** | [Weekly SMA fetch](../FEATURES.md#weekly-sma-fetch-fetch_smapy) |

## Summary

Core weekly job (`fetch_sma.py`): load watchlist, skip tickers that already have a row at their latest `trading_date`, batch-download ~300 days OHLCV from yfinance, compute SMA-50/200, copy `company` from `tickers`, capture `currency` from yfinance, compute `raw_50`/`raw_200`, append metrics rows, upsert cross-sectional aggregate stats (legacy watchlist-wide `market` today; target `market_metrics` grouped by `tickers.market`), purge stale history. Runs **Thursdays 11:00 UTC** via cron (RFC-008).

## Requirements

| ID | Requirement |
|----|-------------|
| FR-1 | Load watchlist from `tickers`; fail clearly if empty |
| FR-2 | Skip tickers that already have a `metrics` row at their latest `trading_date` |
| FR-3 | Batch download ~300d OHLCV (default 40 symbols/batch, delay between batches) |
| FR-4 | Retry 429, rate, timeout, connection, empty frames with exponential backoff |
| FR-5 | Compute SMA-50/200; skip if &lt;200 closes; set `current_price`, `trading_date`, `currency`; copy `company` from `tickers` |
| FR-5a | Set `raw_50 = sma_50 / current_price`, `raw_200 = sma_200 / current_price` |
| FR-5b | Upsert aggregate row per (`trading_date`, listing `market`) into `market_metrics` — mean/std of `raw_50` / `raw_200` from metrics whose tickers share that `tickers.market` on that date |
| FR-6 | Append with `ON CONFLICT (ticker, trading_date) DO NOTHING` |
| FR-7 | Retention purge after run (RFC-004) |
| FR-8 | Log batch progress, per-ticker results, summary; non-zero exit on fatal errors |

## Implementation

### Module layout

| Layer | Module | Responsibility |
|-------|--------|----------------|
| Config | `config.py` | `get_config()` — all tunables |
| Domain | `models.py` | `TickerEntry`, `MetricRow`, `MarketRow` |
| Symbols | `symbols.py` | `load_tickers` — file parsing (RFC-002, RFC-010) |
| yfinance | `yfinance_client.py` | `download_batch`, `load_currency_for_tickers`, metadata lookups |
| DB | `db/tickers.py` | `load_tickers_from_db` |
| DB | `db/metrics.py` | `filter_stale_tickers`, `insert_metrics`, `load_raw_ratios_for_date`, `purge_stale_metrics` |
| DB | `db/market.py` | `upsert_market_stats`, `purge_stale_market` |
| Job | `fetch_sma.py` | Orchestration, SMA math, ratio/aggregate logic |
| Tests | `tests/test_fetch_sma.py`, `tests/test_retention.py` | Pure logic + mocked DB/yfinance |

### Key functions (`fetch_sma.py`)

| Function | Purpose |
|----------|---------|
| `compute_smas(close)` | SMA-50 and SMA-200 from close series |
| `compute_raw_ratios(...)` | `sma / current_price` with divide-by-zero guards |
| `aggregate_market_stats(...)` | Population mean/std for aggregate table (watchlist-wide today; per listing `market` pending) |
| `metric_row_from_history(...)` | Single-ticker metric from OHLCV frame |
| `metric_rows_from_batch(...)` | Parse MultiIndex download into `MetricRow` list |
| `upsert_market_for_trading_dates(...)` | Load ratios from DB and upsert legacy `market` (target: `market_metrics` by `tickers.market`) |
| `_run_retention_purge(...)` | Purge stale `metrics` and aggregate rows |
| `main()` | Full weekly pipeline |

yfinance I/O lives in `yfinance_client.py` (`download_batch`, `load_currency_for_tickers`).

### `main()` flow

1. `config = get_config()`
2. `watchlist = load_tickers_from_db(config.database_url)`
3. `stale, skipped, max_date = filter_stale_tickers(...)`
4. If all fresh: retention purge only, exit 0
5. For each batch: `load_currency_for_tickers` → `download_batch` → `metric_rows_from_batch` → `insert_metrics`
6. `upsert_market_for_trading_dates` — reload ratios for each session date from `metrics`, upsert legacy watchlist-wide `market` (target: group by `tickers.market` → `market_metrics`)
7. `_run_retention_purge` — `purge_stale_metrics` + `purge_stale_market` (→ `market_metrics` after step 10)
8. Log summary; exit 1 if no metrics collected or fatal DB error

### Cron (production)

Installed by `scripts/bootstrap-vm.sh` — see RFC-008.

## Acceptance criteria

- [x] Loads watchlist; fails clearly if empty
- [x] Skips fresh tickers per FR-2 (ticker latest `trading_date` equals global max)
- [x] Batched yfinance download with retry/backoff
- [x] Computes SMA-50, SMA-200, current price
- [x] Copies `company` from `tickers` into each metrics row (PRD §6)
- [x] Populates `currency` on each metrics row (PRD §6)
- [x] Computes and stores `raw_50`, `raw_200` on each metrics row
- [x] Upserts legacy watchlist-wide `market` stats per processed `trading_date`
- [x] Appends with `ON CONFLICT (ticker, trading_date) DO NOTHING`
- [x] SQL in `db/` modules, not in job script
- [x] Retention purge on every run (RFC-004), including legacy `market`
- [x] Uses `get_config()` (RFC-006)
- [x] Logs batch progress and summary
- [x] Unit tests with mocked DB and yfinance
- [x] yfinance batch/metadata I/O in `yfinance_client.py`

### Pending (PRD §6)

- [ ] Upsert `market_metrics` grouped by `tickers.market` (FR-5b target layout)
- [ ] Retention and `db/market.py` use `market_metrics` table name after step 10 migration

## Open questions

- None.
