# Contract: `indices` table for consumers (`fansboda`)

Columns and keys are unchanged (`ticker, sector, country, trading_date, updated_at, ticker_count,
current_price, sma_50, sma_200, momentum, currency, pct_uptrend, z_score`; PK
`(ticker, trading_date)`).

Semantics after this feature:

- Every index is anchored at `current_price = 100` on 2025-10-03. While that week is within
  retention, it is the oldest row of every index; after retention removes it, the oldest row
  shows its chained value (no rebasing).
- `sma_50` / `sma_200` on the start date are the 50- / 200-trading-day averages of the index's
  reconstructed daily price; later weeks chain by the members' average weekly SMA growth.
- No rows have `trading_date` before 2025-10-03 (the UK rows from 2025-07-25 disappear on the
  first rebuild).
- Levels of all indices are comparable: same start date, same base value.

Consumer impact: none required; values change once on the first rebuild.
