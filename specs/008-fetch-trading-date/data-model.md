# Data Model: Weekly Fetch for a Missed Trading Date

No schema change. One run-time value is added.

## Run date

| Source | Value | Rule |
|---|---|---|
| no `--trading_date` | today (UTC) | unchanged behaviour |
| `--trading_date D` | `D` | `today − METRICS_RETENTION_DAYS ≤ D ≤ today`, else error, nothing written |

Derived:

| Derived value | From run date |
|---|---|
| Target week | Monday of the run date's week (`week_start`) |
| Expected latest bar (freshness) | `min(run date, Friday of its week)` |
| Download window | `run date − 600 days` … `run date` (inclusive) |

## Stored rows (unchanged definitions)

- `*_metrics`: one row per `(ticker, week_start)`; a stored row is replaced only by a newer bar.
- `*_market_metrics`, stock `z_score`: recomputed for the weeks written.
- `indices`: rows for the weeks written, continued from the latest stored row before them.
- Outlier email: newly detected outliers of the weeks written.
