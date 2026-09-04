# RFC-003: Weekly SMA Fetch

| Field | Value |
|-------|-------|
| **Priority** | P1 |
| **Status** | Implemented |
| **Depends on** | RFC-001, RFC-002, RFC-006 |
| **PRD** | FR-1 – FR-8 |
| **Feature** | [Weekly SMA fetch](../FEATURES.md#weekly-sma-fetch-fetch_smapy) |

## Summary

Core weekly job (`fetch_sma.py`): load watchlists from `us_tickers` and `swe_tickers`, skip tickers that already have a row at their latest `trading_date` in the matching country metrics table, batch-download ~300 days OHLCV from yfinance, compute SMA-50/200, copy `company` from the matching tickers table, capture `currency` from yfinance, compute `raw_50`/`raw_200`, append into `us_metrics` / `swe_metrics`, upsert cross-sectional stats into `us_market_metrics` / `swe_market_metrics`, purge stale history. Runs **Thursdays 11:00 UTC** via cron (RFC-008).

## Requirements

| ID | Requirement |
|----|-------------|
| FR-1 | Load watchlist from `us_tickers` and `swe_tickers`; fail clearly if both are empty |
| FR-2 | Skip tickers that already have a row in the matching `*_metrics` table at that table's latest `trading_date` (US and SWE calendars evaluated separately) |
| FR-3 | Batch download ~300d OHLCV (default 40 symbols/batch, delay between batches) |
| FR-4 | Retry 429, rate, timeout, connection, empty frames with exponential backoff |
| FR-5 | Compute SMA-50/200; skip if &lt;200 closes; set `current_price`, `trading_date`, `currency`; copy `company` from the matching `*_tickers` table |
| FR-5a | Set `raw_50 = sma_50 / current_price`, `raw_200 = sma_200 / current_price` |
| FR-5b | Upsert aggregate row per `trading_date` into `us_market_metrics` / `swe_market_metrics` — mean/std of `raw_50` / `raw_200` from that country set's metrics on that date |
| FR-6 | Append with `ON CONFLICT (ticker, trading_date) DO NOTHING` into `us_metrics` / `swe_metrics` |
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
| DB | `db/tickers.py` | `load_tickers_from_db` (both country tickers tables) |
| DB | `db/metrics.py` | `filter_stale_tickers`, `insert_metrics`, `load_raw_ratios_by_market_for_date`, `purge_stale_metrics` |
| DB | `db/market.py` | `upsert_market_stats`, `purge_stale_market` |
| DB | `db/country.py` | Country routing for inserts and freshness |
| Job | `fetch_sma.py` | Orchestration, SMA math, ratio/aggregate logic |
| Tests | `tests/test_fetch_sma.py`, `tests/test_retention.py` | Pure logic + mocked DB/yfinance |

### Key functions (`fetch_sma.py`)

| Function | Purpose |
|----------|---------|
| `compute_smas(close)` | SMA-50 and SMA-200 from close series |
| `compute_raw_ratios(...)` | `sma / current_price` with divide-by-zero guards |
| `aggregate_market_stats(...)` | Population mean/std for one country-set aggregate row |
| `metric_row_from_history(...)` | Single-ticker metric from OHLCV frame |
| `metric_rows_from_batch(...)` | Parse MultiIndex download into `MetricRow` list |
| `upsert_market_for_trading_dates(...)` | Load ratios from DB and upsert `*_market_metrics` |
| `_run_retention_purge(...)` | Purge stale `*_metrics` and `*_market_metrics` rows |
| `main()` | Full weekly pipeline |

yfinance I/O lives in `yfinance_client.py` (`download_batch`, `load_currency_for_tickers`).

### `main()` flow

1. `config = get_config()`
2. `watchlist = load_tickers_from_db(config.database_url)` — both country tickers tables
3. `stale, skipped, max_date = filter_stale_tickers(...)` — per-country `*_metrics` max date
4. If all fresh: retention purge only, exit 0
5. For each batch: `load_currency_for_tickers` → `download_batch` → `metric_rows_from_batch` → `insert_metrics` into `us_metrics` / `swe_metrics`
6. `upsert_market_for_trading_dates` — reload ratios per country set → `us_market_metrics` / `swe_market_metrics`
7. `_run_retention_purge` — purge stale rows from all four history/aggregate tables
8. Log summary; exit 1 if no metrics collected or fatal DB error

### Cron (production)

Installed by `scripts/bootstrap-vm.sh` — see RFC-008.

## Acceptance criteria

- [x] Loads watchlist from `us_tickers` / `swe_tickers`; fails clearly if both empty
- [x] Skips fresh tickers per FR-2 using **per-country** max `trading_date`
- [x] Batched yfinance download with retry/backoff
- [x] Computes SMA-50, SMA-200, current price
- [x] Copies `company` from tickers into each metrics row (PRD §6)
- [x] Populates `currency` on each metrics row (PRD §6)
- [x] Computes and stores `raw_50`, `raw_200` on each metrics row
- [x] Upserts `us_market_metrics` / `swe_market_metrics` per processed `trading_date`
- [x] Appends into `us_metrics` / `swe_metrics` with `ON CONFLICT (ticker, trading_date) DO NOTHING`
- [x] SQL in `db/` modules, not in job script
- [x] Retention purge on every run targets all four country history/aggregate tables (RFC-004)
- [x] Uses `get_config()` (RFC-006)
- [x] Logs batch progress and summary
- [x] Unit tests with mocked DB and yfinance
- [x] yfinance batch/metadata I/O in `yfinance_client.py`

## Open questions

- None.
