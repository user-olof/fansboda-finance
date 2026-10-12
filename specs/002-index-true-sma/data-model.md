# Data Model: Index SMA-50 / SMA-200 as True Moving Averages

No schema change. Stored entities are unchanged; the rules for their values change.

## Stored: `indices` row (unchanged columns)

| Field | Rule after this feature |
|---|---|
| `trading_date` | Last date of the index's daily series in the week; on the start week, the start date |
| `current_price` | Daily level on `trading_date` (FR-003); 100 on the start date |
| `sma_50` / `sma_200` | Mean of the last 50 / 200 daily levels up to `trading_date` (FR-001); fewer when not available |
| `momentum` | `sma_50 / sma_200` (unchanged) |
| `ticker_count` | Stocks with a stored metric row that week with positive price and SMAs (R6; outlier stock-weeks no longer subtracted) |
| `pct_uptrend` | Unchanged (share of those stocks with `sma_50 > sma_200`) |
| `z_score` | Unchanged (sector momentum vs the country's sector indices that week) |

## In memory (not stored, FR-012)

### Daily average return

Per index ticker and trading date: sum and count of member daily returns (`DailyAccumulator`).

- A member's return on a day uses its own previous bar; returns above `outlier_max_growth` or below
  `outlier_min_growth` are dropped.
- Initialization / new sector: returns on or before the index's start date only from members with
  a close on the start date (001 R6); after it, all members with data.
- Weekly run: all current members with data.

### Daily level series (`dict[date, float]`)

`daily_levels(averages, pin_date, pin_level)`:

- `level(pin) = pin_level` (pin snaps to the latest series date ≤ `pin_date`).
- Forward: `level(d) = level(prev) × (1 + avg(d))`.
- Backward: `level(prev) = level(d) / (1 + avg(d))`.

### `IndexSeries`

| Field | Meaning |
|---|---|
| `ticker` | Index ticker |
| `start_date` | 001 start-date rule |
| `levels` | Daily level series pinned at `(start_date, 100)` |

Replaces 001's `Anchor` (the bridged `week_start` / `levels` are no longer needed).

### `WeekLevels`

| Field | Meaning |
|---|---|
| `trading_date` | Row date (see `indices.trading_date`) |
| `levels` | `IndexLevels(current_price, sma_50, sma_200)` as `Decimal`, six decimals |
| `days_used` | Levels in the SMA-200 mean (≤ 200), for logging |

`week_levels(levels, week_start, *, row_date=None) -> WeekLevels | None` — `None` when the series
has no date in the week (no row written).

## Rules by run

| Run | Pin | Weeks written | Downloads |
|---|---|---|---|
| Initialization (`compute_indices.py`) | `(start_date, 100)` per index | Every stored metrics week from the index's start week | All members of the country, from `start_date − 400` days to today; second pass for later start dates (001) |
| Weekly run, existing index | Latest stored row before the earliest written week | Weeks the run wrote metrics for | None extra, except members not in this run's download (skipped as fresh or failed batch) |
| Weekly run, new sector | `(start_date, 100)` | Stored weeks from its start week (`only_tickers`) | That sector's members (001 R12) |

Errors:

- Weekly run, pin older than the series' first date: no row, error log naming the initialization (R4).
- Weekly run, no series date in the week for an index: no row, warning.
