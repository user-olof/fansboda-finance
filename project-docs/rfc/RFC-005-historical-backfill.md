# RFC-005: Historical Backfill

| Field | Value |
|-------|-------|
| **Priority** | P2 |
| **Status** | Implemented |
| **Depends on** | RFC-001, RFC-002, RFC-003, RFC-006 |
| **PRD** | FR-13 – FR-18 |
| **Feature** | [Historical backfill](../FEATURES.md#historical-backfill-backfill_smapy) |

## Summary

One-off manual script to bootstrap ~2 years of rolling weekly SMA snapshots. **Not** cron-scheduled. SMA price fields, **`momentum` / `z_score`**, and cross-sectional **`momentum_mean` / `momentum_std`** are backfilled from OHLCV into `us_metrics` / `swe_metrics` / `uk_metrics` and `us_market_metrics` / `swe_market_metrics` / `uk_market_metrics` (RFC-012). `sector`, `industry`, listing `market`, and `exchange_name` live on `*_tickers` (RFC-002). Currency is resolved per ticker during backfill (`yfinance_client.load_currency_for_tickers`).

**Country scope (FR-18):** each run targets **exactly one** country set via required `--country us|swe|uk`. Adding UK later must not re-download or re-touch an already-backfilled US (or SWE) set.

## Requirements

| ID | Requirement |
|----|-------------|
| FR-13 | Download ~730 days OHLCV per batch (default 25 symbols/batch); retry/backoff; inter-batch delay |
| FR-14 | Rolling 52-week windows from oldest bar (weeks 0–51, 1–52, …); one snapshot per window |
| FR-15 | Append into the selected country `*_metrics` with `ON CONFLICT (ticker, trading_date) DO NOTHING` |
| FR-16 | Skip `(ticker, trading_date)` pairs already in the matching country metrics table |
| FR-17 | Log per-batch generated/new/inserted/skipped counts and final summary |
| FR-18 | Required `--country us|swe|uk`: load only that set's `*_tickers`; write only that set's `*_metrics` / `*_market_metrics` |
| — | Set `momentum`, `z_score` on each inserted metrics row; upsert `momentum_mean` / `momentum_std` (RFC-012) |

## Implementation

### Files

| File | Role |
|------|------|
| `backfill_sma.py` | Week indexing, rolling windows, orchestration; required `--country` |
| `fetch_sma.py` | Shared: `compute_smas`, `compute_momentum`, `chunked`, `_to_decimal`, `trading_date_from_index`, country-scoped `upsert_market_for_trading_dates` |
| `yfinance_client.py` | Shared: `download_batch`, `load_currency_for_tickers` |
| `db/metrics.py` | `insert_metrics`, `load_existing_metric_keys` |
| `db/tickers.py` | `load_tickers_from_db(..., country=)` loads one `*_tickers` table when set |
| `config.py` | Backfill batch size, delays, history days, window weeks |
| `tests/test_backfill_sma.py` | Pure logic + scoped `--country` orchestration tests |

### Key functions (`backfill_sma.py`)

| Function | Purpose |
|----------|---------|
| `week_index_series(index, anchor)` | Map bars to week numbers from anchor |
| `sample_start_weeks(max_week, window_weeks)` | Rolling window start offsets |
| `metric_rows_from_weekly_samples(...)` | SMA rows for one ticker’s windows |
| `metric_rows_from_backfill_batch(...)` | Parse batch download for all tickers |
| `filter_new_rows(rows, existing)` | Drop already-stored keys |
| `build_parser()` / `main()` | Required `--country`; scoped load + market upsert |

### Setup order

**Fresh database:** `schema.sql` → `seed_tickers.py --country us` → `backfill_sma.py --country us` (repeat for `swe` / `uk` when ready).

**Legacy one-row-per-ticker:** run `migrate_metrics_history.sql` first ([MIGRATIONS.md](../MIGRATIONS.md)).

```bash
pipenv run python backfill_sma.py --country us
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
- [x] Populates `momentum` / `z_score` on backfilled metrics rows (RFC-012)
- [x] Upserts `momentum_mean` / `momentum_std` on country market tables (RFC-012)
- [x] Can insert into `us_metrics` / `swe_metrics` / `uk_metrics` and upsert matching market tables (RFC-001, RFC-012)
- [x] Required CLI `--country us|swe|uk`
- [x] Watchlist load and writes scoped to that country set only (no yfinance / market upserts for other sets)
- [x] Tests cover scoped backfill (US-only run ignores SWE/UK tickers)

## Open questions

- `--dry-run` flag deferred — out of PRD scope.
- Omitting `--country` errors via required argparse flag (FR-18).

## Related RFCs

| RFC | Relationship |
|-----|--------------|
| RFC-002 | Seed `--country` used before backfill in the same bootstrap/dev-backfill run |
| RFC-011 | Dev-backfill passes `--country` into this script |
| RFC-012 | Scoped backfill only upserts market aggregates for the selected set |
