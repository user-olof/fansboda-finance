# Data Model: Index Momentum Band for Member Stocks

No schema change. Membership rule added to the index computation.

## Momentum band (settings)

| Setting | Field | Default | Rule |
|---|---|---|---|
| `INDEX_MOMENTUM_MIN` | `index_momentum_min` | 0.15 | > 0 |
| `INDEX_MOMENTUM_MAX` | `index_momentum_max` | 1.5 | > min |

Inclusive: a ratio equal to a limit is inside.

## Weekly ratio (in memory, per stock)

`ratio(stock, week) = SMA50 / SMA200` on the stock's last daily bar in the calendar week, with
full 50 / 200-bar windows of adjusted closes; `None` with fewer than 200 bars.

## Membership per stock-week

| Ratio for the week | Daily returns in that week | Start-date count | `ticker_count` / `pct_uptrend` |
|---|---|---|---|
| inside band | folded (subject to the outlier filter) | counts | counted |
| outside band | dropped | does not count | not counted (stored ratio outside band) |
| `None` | folded | counts | as today (stored SMAs required) |

## Index row (`indices`)

Unchanged columns. `current_price`, `sma_50`, `sma_200`, `momentum`, `z_score` follow from the
in-band daily returns; `ticker_count`, `pct_uptrend` from in-band stored metrics.
