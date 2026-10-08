# Contract: `indices` table for consumers (`fansboda`)

Columns and keys are unchanged (`ticker, sector, country, trading_date, updated_at, ticker_count,
current_price, sma_50, sma_200, momentum, currency, pct_uptrend, z_score`; PK
`(ticker, trading_date)`).

Semantics after this feature:

- `current_price` is the index's daily price on `trading_date`: 100 on the start date, then
  compounded by the members' equal-weighted daily returns (daily rebalancing; before: weekly).
- `sma_50` / `sma_200` are the 50- / 200-trading-day averages of that daily price ending on
  `trading_date` — the same definition as the stocks' `*_metrics.sma_50` / `sma_200`.
- `momentum = sma_50 / sma_200` is therefore directly comparable with stock momentum.
- `ticker_count` counts every stock with a stored row that week (outlier stock-weeks are no longer
  subtracted; outliers are dropped per day instead).
- Start date, 100 base, and no rows before the start date are unchanged from 001.

Consumer impact: none required; all stored values change once when the owner runs the
initialization after deploy, and price levels differ slightly from 001's (daily vs weekly
rebalancing).
