# Contract: `indices` market labels (consumer-facing)

Consumers (`fansboda`) read `indices` directly. This feature changes one documented value.

## Unchanged

- Table shape, primary key `(ticker, trading_date)`, all columns and types.
- Tickers: `US-IDX`, `SWE-IDX`, `UK-IDX` (market) and `<market>-<SECTOR>` (sector).
- Sector rows' `sector` (sector name, e.g. `Technology`).
- All values (`current_price`, `sma_50`, `sma_200`, `momentum`, `pct_uptrend`, `z_score`,
  `ticker_count`, `currency`, `trading_date`).

## Changed

`sector` on market rows:

| `ticker` | Before | After |
|---|---|---|
| `US-IDX` | `US Equity Index` | `NYSE & Nasdaq` |
| `SWE-IDX` | `OMX Equity Index` | `OMX Stockholm` |
| `UK-IDX` | `FTSE Equity Index` | `FTSE London` |

Applies to every stored row after step 23 and to every row written by the new code.

## Consumer guidance

- Identify market rows by `ticker`, never by `sector`. `fansboda` already does
  (`MARKET_INDEX_TICKERS`); no change needed.
- The label contains `&`; render it escaped in HTML (Jinja autoescape does this).
