# RFC-004: Rolling Data Retention

| Field | Value |
|-------|-------|
| **Priority** | P1 |
| **Status** | Implemented |
| **Depends on** | RFC-003 |
| **PRD** | FR-7 |
| **Feature** | [Data retention](../FEATURES.md#data-retention) |

## Summary

After each weekly `fetch_sma.py` run, delete `metrics` and `market_metrics` rows where `trading_date` is older than the configured retention window (default 365 days).

## Requirements

| ID | Requirement |
|----|-------------|
| FR-7 | Purge rows with `trading_date` older than one year after inserts |
| — | Purge runs even when all tickers are already fresh (nothing to fetch) |
| — | Purge count included in job summary logs |
| — | Parameterized SQL in `db/metrics.py` and `db/market.py` (→ `market_metrics` after step 10) |
| — | Cutoff uses UTC date |
| — | Purge aggregate rows with `trading_date` &lt; cutoff alongside `metrics` |

## Implementation

### Files

| File | Role |
|------|------|
| `db/retention.py` | `purge_stale_data` — orchestrates metrics + aggregate purge |
| `db/metrics.py` | `retention_cutoff`, `purge_stale_metrics`, `DELETE_STALE_SQL` |
| `db/market.py` | `purge_stale_market`, `DELETE_STALE_MARKET_SQL` → `market_metrics` table |
| `fetch_sma.py` | Calls `_run_retention_purge` at end of every successful `main()` path |
| `config.py` | `metrics_retention_days` (default 365) |
| `tests/test_retention.py` | Cutoff math, SQL, purge DB call, `main()` integration |

### Key functions

```python
def retention_cutoff(retention_days: int, *, today: date | None = None) -> date
def purge_stale_metrics(database_url: str, retention_days: int) -> int
def purge_stale_market(database_url: str, retention_days: int) -> int
def purge_stale_data(database_url: str, retention_days: int) -> tuple[int, int]
```

SQL:

```sql
DELETE FROM metrics WHERE trading_date < %s;
DELETE FROM market_metrics WHERE trading_date < %s;
```

Index `idx_metrics_trading_date` and `idx_market_metrics_trading_date` (RFC-001, RFC-004) support efficient deletes. `market_metrics` uses `(market, trading_date)` as primary key.

### Configuration

| Setting | Dev default | Prod default | Env override |
|---------|-------------|--------------|--------------|
| `metrics_retention_days` | 365 | 365 | `METRICS_RETENTION_DAYS` |

## Acceptance criteria

- [x] `purge_stale_metrics` deletes rows with `trading_date` &lt; today − retention_days (UTC)
- [x] Called at end of every `fetch_sma.py` run (including all-fresh path)
- [x] Purge count logged in summary
- [x] Parameterized SQL in `db/metrics.py` and `db/market.py`
- [x] `purge_stale_data` in `db/retention.py` purges both tables
- [x] Unit tests in `tests/test_retention.py`
- [x] `purge_stale_market` deletes stale `market_metrics` rows with same cutoff

## Open questions

- None.
