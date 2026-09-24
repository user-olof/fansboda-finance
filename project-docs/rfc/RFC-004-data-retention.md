# RFC-004: Rolling Data Retention

| Field | Value |
|-------|-------|
| **Priority** | P1 |
| **Status** | Implemented |
| **Depends on** | RFC-003 |
| **PRD** | FR-7 |
| **Feature** | [Data retention](../FEATURES.md#data-retention) |

## Summary

After each weekly `fetch_sma.py` run, delete rows from `us_metrics` / `swe_metrics` / `uk_metrics` and `us_market_metrics` / `swe_market_metrics` / `uk_market_metrics` where `trading_date` is older than the configured retention window (default 365 days).

UK purge is included via the same `DELETE_STALE_*` lists in `db/metrics.py` and `db/market.py` (country sets from RFC-001); `db/retention.purge_stale_data` orchestrates all six tables.

## Requirements

| ID | Requirement |
|----|-------------|
| FR-7 | Purge rows with `trading_date` older than one year after inserts |
| — | Purge runs even when all tickers are already fresh (nothing to fetch) |
| — | Purge count included in job summary logs |
| — | Parameterized SQL in `db/metrics.py` and `db/market.py` for all country history/aggregate tables |
| — | Cutoff uses UTC date |
| — | Purge aggregate rows with `trading_date` &lt; cutoff alongside metrics |

## Implementation

### Files

| File | Role |
|------|------|
| `db/retention.py` | `purge_stale_data` — orchestrates metrics + aggregate purge |
| `db/metrics.py` | `retention_cutoff`, `purge_stale_metrics`, `DELETE_STALE_SQL` |
| `db/market.py` | `purge_stale_market`, `DELETE_STALE_MARKET_SQL` |
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

SQL (all three country sets):

```sql
DELETE FROM us_metrics WHERE trading_date < %s;
DELETE FROM swe_metrics WHERE trading_date < %s;
DELETE FROM uk_metrics WHERE trading_date < %s;
DELETE FROM us_market_metrics WHERE trading_date < %s;
DELETE FROM swe_market_metrics WHERE trading_date < %s;
DELETE FROM uk_market_metrics WHERE trading_date < %s;
```

Indexes on each `*_metrics.trading_date` and `*_market_metrics.trading_date` (RFC-001) support efficient deletes. Each `*_market_metrics` table uses `(market, trading_date)` as primary key.

### Configuration

| Setting | Dev default | Prod default | Env override |
|---------|-------------|--------------|--------------|
| `metrics_retention_days` | 365 | 365 | `METRICS_RETENTION_DAYS` |

## Acceptance criteria

- [x] `purge_stale_metrics` deletes from `us_metrics`, `swe_metrics`, and `uk_metrics` where `trading_date` &lt; today − retention_days (UTC)
- [x] `purge_stale_market` deletes from `us_market_metrics`, `swe_market_metrics`, and `uk_market_metrics` with the same cutoff
- [x] `purge_stale_data` covers all six country history/aggregate tables
- [x] Called at end of every `fetch_sma.py` run (including all-fresh path)
- [x] Purge count logged in summary
- [x] Parameterized SQL in `db/metrics.py` and `db/market.py`
- [x] Unit tests in `tests/test_retention.py` assert UK purge alongside US/SWE

## Open questions

- None.
