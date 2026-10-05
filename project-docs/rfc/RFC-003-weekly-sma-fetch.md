# RFC-003: Weekly SMA Fetch

| Field | Value |
|-------|-------|
| **Priority** | P1 |
| **Status** | Implemented |
| **Depends on** | RFC-001, RFC-002, RFC-006 |
| **PRD** | FR-1 – FR-8 |
| **Feature** | [Weekly SMA fetch](../FEATURES.md#weekly-sma-fetch-fetch_smapy) |

## Summary

Core weekly job (`fetch_sma.py`): load watchlists from `us_tickers`, `swe_tickers`, and `uk_tickers`, skip tickers whose current-week row already holds the newest expected bar, batch-download ~300 days OHLCV from yfinance, compute SMA-50/200, copy `company` from the matching tickers table, capture `currency` from yfinance, compute **`momentum`** / **`z_score`** (RFC-012), upsert one row per ticker per calendar week (`week_start`) into `us_metrics` / `swe_metrics` / `uk_metrics`, upsert **`momentum_mean` / `momentum_std`** into `us_market_metrics` / `swe_market_metrics` / `uk_market_metrics`, purge stale history. Runs **Saturdays 11:00 UTC** via cron (RFC-008), after every market's Friday close.

## Requirements

| ID | Requirement |
|----|-------------|
| FR-1 | Load watchlist from `us_tickers`, `swe_tickers`, and `uk_tickers`; fail clearly if all three are empty |
| FR-2 | Skip tickers whose row for the current UTC week (`week_start`) in the matching `*_metrics` table has `trading_date` ≥ the newest expected bar (Friday on weekends, otherwise today) |
| FR-3 | Batch download ~300d OHLCV (default 40 symbols/batch, delay between batches) |
| FR-4 | Retry 429, rate, timeout, connection, empty frames with exponential backoff |
| FR-5 | Compute SMA-50/200; skip if &lt;200 closes; set `current_price`, `trading_date`, `currency`; copy `company` from the matching `*_tickers` table |
| FR-5 (cont.) | Set `momentum = sma_50 / sma_200`; set `z_score` from market aggregates (RFC-012) |
| FR-5a | Weekly `price_growth` / `sma_50_growth` / `sma_200_growth` vs the previous calendar week's last bar, from the same download ([RFC-016](./RFC-016-weekly-growth-columns.md)) |
| FR-5b | Upsert aggregate row per `week_start` into `us_market_metrics` / `swe_market_metrics` / `uk_market_metrics` — `momentum_mean` / `momentum_std` from that country set's metrics in that week |
| FR-6 | Upsert with `ON CONFLICT (ticker, week_start) DO UPDATE … WHERE EXCLUDED.trading_date > existing` into `us_metrics` / `swe_metrics` / `uk_metrics` (newer bar replaces the week's row) |
| FR-7 | Retention purge after run (RFC-004) |
| FR-7a / FR-7b | FR-7a retired ([RFC-018](./RFC-018-sector-indices.md)); after the purge, `indices` (RFC-015 / RFC-018) gets market + sector index rows for the weeks written |
| FR-7c | Email newly detected implausible weekly moves ([RFC-017](./RFC-017-outlier-guard-email.md)) |
| FR-8 | Log batch progress, per-ticker results, summary; non-zero exit on fatal errors |

## Implementation

### Module layout

| Layer | Module | Responsibility |
|-------|--------|----------------|
| Config | `config.py` | `get_config()` — all tunables |
| Domain | `models.py` | `TickerEntry`, `MetricRow`, `MarketRow` |
| Symbols | `symbols.py` | `load_tickers` — file parsing (RFC-002, RFC-010) |
| yfinance | `yfinance_client.py` | `download_batch`, `load_currency_for_tickers`, metadata lookups |
| DB | `db/tickers.py` | `load_tickers_from_db` (all country tickers tables) |
| DB | `db/metrics.py` | `filter_stale_tickers`, `expected_latest_bar`, `insert_metrics`, `load_momentum_by_market_for_week`, `update_z_scores_for_week`, `purge_stale_metrics` |
| DB | `db/market.py` | `upsert_market_stats`, `purge_stale_market` |
| DB | `db/country.py` | Country routing for inserts and freshness |
| Job | `fetch_sma.py` | Orchestration, SMA math, ratio/aggregate logic |
| Tests | `tests/test_fetch_sma.py`, `tests/test_retention.py` | Pure logic + mocked DB/yfinance |

### Key functions (`fetch_sma.py`)

| Function | Purpose |
|----------|---------|
| `compute_smas(close)` | SMA-50 and SMA-200 from close series |
| `compute_momentum(...)` | `sma_50 / sma_200` with divide-by-zero guards |
| `aggregate_market_stats(...)` | Population mean/std of momentum for one country-set aggregate row |
| `metric_row_from_history(...)` | Single-ticker metric from OHLCV frame |
| `metric_rows_from_batch(...)` | Parse MultiIndex download into `MetricRow` list |
| `upsert_market_for_weeks(...)` | Load momentum per week from DB, upsert `*_market_metrics`, update z_scores |
| `_run_retention_purge(...)` | Purge stale `*_metrics` and `*_market_metrics` rows |
| `main()` | Full weekly pipeline |

yfinance I/O lives in `yfinance_client.py` (`download_batch`, `load_currency_for_tickers`).

### `main()` flow

1. `config = get_config()`
2. `watchlist = load_tickers_from_db(config.database_url)` — all country tickers tables
3. `stale, skipped, week_start = filter_stale_tickers(...)` — tickers whose current-week row is missing or holds an older bar than expected
4. If all fresh: retention purge only, exit 0
5. For each batch: `load_currency_for_tickers` → `download_batch` → `metric_rows_from_batch` → `insert_metrics` into `us_metrics` / `swe_metrics` / `uk_metrics`
6. `upsert_market_for_weeks` — reload momentum per country set and week → `us_market_metrics` / `swe_market_metrics` / `uk_market_metrics`, then set `z_score`
7. `_run_retention_purge` — purge stale rows from all country history/aggregate tables (delegates to `db/retention.purge_stale_data`, which includes UK; see RFC-004)
8. Log summary; exit 1 if no metrics collected or fatal DB error

### Cron (production)

Installed by `scripts/bootstrap-vm.sh` — see RFC-008.

## Acceptance criteria

- [x] Loads watchlist from `us_tickers` / `swe_tickers` / `uk_tickers`; fails clearly if all three empty
- [x] Skips fresh tickers per FR-2 only when their current-week row already holds the newest expected bar (a stale table no longer freezes the weekly fetch; a mid-week run no longer blocks the Saturday update)
- [x] Batched yfinance download with retry/backoff
- [x] Computes SMA-50, SMA-200, current price
- [x] Copies `company` from tickers into each metrics row (PRD §6)
- [x] Populates `currency` on each metrics row (PRD §6)
- [x] Computes and stores `momentum` and `z_score` on each metrics row (RFC-012)
- [x] Upserts `momentum_mean` / `momentum_std` into country `*_market_metrics` (RFC-012)
- [x] Upserts one row per `(ticker, week_start)` into `us_metrics` / `swe_metrics` / `uk_metrics`, replacing only with a newer bar
- [x] SQL in `db/` modules, not in job script
- [x] Retention purge on every run targets US/SWE/UK history/aggregate tables via `db/retention.py` (RFC-004)
- [x] Uses `get_config()` (RFC-006)
- [x] Logs batch progress and summary
- [x] Unit tests with mocked DB and yfinance, including UK country-set paths
- [x] yfinance batch/metadata I/O in `yfinance_client.py`

## Open questions

- None.
