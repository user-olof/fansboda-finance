# RFC-005: Historical Backfill

| Field | Value |
|-------|-------|
| **Priority** | P2 |
| **Status** | Implemented |
| **Depends on** | RFC-001, RFC-002, RFC-003, RFC-006 |
| **PRD** | FR-13 – FR-17 |
| **Feature** | [Historical backfill](../FEATURES.md#historical-backfill-backfill_smapy) |

## Summary

One-off manual script to bootstrap ~2 years of rolling weekly SMA snapshots. **Not** cron-scheduled. SMA price fields are backfilled from OHLCV. `sector` and `industry` live on `tickers` (RFC-002); `metrics.currency` may remain `NULL` on backfilled rows until populated by the weekly fetch (see RFC-001 open question).

## Requirements

| ID | Requirement |
|----|-------------|
| FR-13 | Download ~730 days OHLCV per batch (default 25 symbols/batch); retry/backoff; inter-batch delay |
| FR-14 | Rolling 52-week windows from oldest bar (weeks 0–51, 1–52, …); one snapshot per window |
| FR-15 | Append with `ON CONFLICT (ticker, trading_date) DO NOTHING` |
| FR-16 | Skip `(ticker, trading_date)` pairs already in database |
| FR-17 | Log per-batch generated/new/inserted/skipped counts and final summary |

## Implementation

### Files

| File | Role |
|------|------|
| `backfill_sma.py` | Week indexing, rolling windows, orchestration |
| `fetch_sma.py` | Shared: `download_batch`, `compute_smas`, `chunked`, `_to_decimal` |
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

| Setting | Default |
|---------|---------|
| `backfill_history_days` | 730 |
| `backfill_window_weeks` | 52 |
| `backfill_batch_size` | 25 |
| `backfill_batch_delay_seconds` | 5.0 |

## Acceptance criteria

- [x] Downloads ~730d history in configurable batches with retry
- [x] Rolling 52-week SMA windows from oldest bar
- [x] Appends with conflict-safe insert
- [x] Skips existing `(ticker, trading_date)` pairs
- [x] Shares `db/metrics.py` insert logic with RFC-003
- [x] Uses `get_config()` (RFC-006)
- [x] Observability logs per batch and summary
- [x] Unit tests for week indexing and window logic
- [x] Not scheduled in cron
- [ ] Documented behavior for `metrics.currency` on backfilled rows (`NULL` until weekly fetch)

## Open questions

- `--dry-run` flag deferred — out of PRD scope.
- Populate `currency` during backfill, or leave `NULL` until `fetch_sma.py` runs? (aligned with RFC-001)
