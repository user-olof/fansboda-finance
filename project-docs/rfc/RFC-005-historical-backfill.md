# RFC-005: Historical Backfill

| Field | Value |
|-------|-------|
| **Priority** | P2 |
| **Status** | Implemented |
| **Depends on** | RFC-001, RFC-002, RFC-003, RFC-006 |
| **PRD** | FR-13 – FR-17 |
| **Feature** | [Historical backfill](../FEATURES.md#historical-backfill-backfill_smapy) |

## Summary

One-off manual script to bootstrap ~2 years of rolling weekly SMA snapshots. **Not** cron-scheduled. SMA price fields, `raw_50` / `raw_200` ratios, and cross-sectional aggregate stats are backfilled from OHLCV into `us_metrics` / `swe_metrics` and `us_market_metrics` / `swe_market_metrics`. `sector`, `industry`, and listing `market` live on `us_tickers` / `swe_tickers` (RFC-002). Currency is resolved per ticker during backfill (`yfinance_client.load_currency_for_tickers`).

## Requirements

| ID | Requirement |
|----|-------------|
| FR-13 | Download ~730 days OHLCV per batch (default 25 symbols/batch); retry/backoff; inter-batch delay |
| FR-14 | Rolling 52-week windows from oldest bar (weeks 0–51, 1–52, …); one snapshot per window |
| FR-15 | Append into `us_metrics` / `swe_metrics` with `ON CONFLICT (ticker, trading_date) DO NOTHING` |
| FR-16 | Skip `(ticker, trading_date)` pairs already in the matching country metrics table |
| FR-17 | Log per-batch generated/new/inserted/skipped counts and final summary |
| — | Set `raw_50`, `raw_200` on each inserted metrics row (RFC-012) |

## Implementation

### Files

| File | Role |
|------|------|
| `backfill_sma.py` | Week indexing, rolling windows, orchestration |
| `fetch_sma.py` | Shared: `compute_smas`, `compute_raw_ratios`, `chunked`, `_to_decimal`, `trading_date_from_index` |
| `yfinance_client.py` | Shared: `download_batch`, `load_currency_for_tickers` |
| `db/metrics.py` | `insert_metrics`, `load_existing_metric_keys` |
| `db/tickers.py` | `load_tickers_from_db` |
| `config.py` | Backfill batch size, delays, history days, window weeks |
| `tests/test_backfill_sma.py` | Pure logic tests |

### Key functions (`backfill_sma.py`)

| Function | Purpose |
|----------|---------|
| `week_index_series(index, anchor)` | Map bars to week numbers from anchor |
| `sample_start_weeks(max_week, window_weeks)` | Rolling window start offsets |
| `metric_rows_from_weekly_samples(...)` | SMA rows for one ticker’s windows |
| `metric_rows_from_backfill_batch(...)` | Parse batch download for all tickers |
| `filter_new_rows(rows, existing)` | Drop already-stored keys |
| `main()` | Full backfill pipeline |

### Setup order

**Fresh database:** `schema.sql` → `seed_tickers.py` → `backfill_sma.py`

**Legacy one-row-per-ticker:** run `migrate_metrics_history.sql` first ([MIGRATIONS.md](../MIGRATIONS.md)).

```bash
pipenv run python backfill_sma.py
```

### Configuration (via `config.py`)

| Setting | Dev default | Prod default |
|---------|-------------|--------------|
| `backfill_history_days` | 730 | 730 |
| `backfill_window_weeks` | 52 | 52 |
| `backfill_batch_size` | 25 | 25 |
| `backfill_batch_delay_seconds` | 5.0 | 5.0 |

## Acceptance criteria

- [x] Downloads ~730d history in configurable batches with retry
- [x] Rolling 52-week SMA windows from oldest bar
- [x] Appends with conflict-safe insert
- [x] Skips existing `(ticker, trading_date)` pairs
- [x] Shares `db/metrics.py` insert logic with RFC-003
- [x] Uses `get_config()` (RFC-006)
- [x] Observability logs per batch and summary
- [x] Unit tests for week indexing, window logic, and `main()` orchestration
- [x] Not scheduled in cron
- [x] Populates `currency` per ticker during backfill (PRD §6)
- [x] Uses `yfinance_client.py` for batch download and currency resolution
- [x] Populates `raw_50`, `raw_200` on backfilled metrics rows (RFC-012)
- [x] Insert into `us_metrics` / `swe_metrics`; upsert `us_market_metrics` / `swe_market_metrics` (RFC-001 step 11, RFC-012)

## Open questions

- `--dry-run` flag deferred — out of PRD scope.
