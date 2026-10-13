# Data Model: Ticker Seed Validation

No schema change. The rule applies to a resolved ticker before it is written to
`us_tickers` / `swe_tickers` / `uk_tickers`.

## Resolved ticker (in memory)

| Field | Source (yfinance `info`) | Rule |
|---|---|---|
| `symbol` | symbol file / stored watchlist | **required** |
| `company` | `longName`, else `shortName` | **required** |
| `sector` | `sectorKey`, else `sector` | **required** |
| `industry` | `industryKey`, else `industry` | **required** |
| `market` | `market` (raw; may be absent) | warn-only; stored value falls back to `infer_listing_market(symbol)` |
| `exchange_name` | `fullExchangeName` | warn-only; stored as NULL when absent |
| `business_summary` | `longBusinessSummary` | not checked |

**Missing** = `None`, empty string, or whitespace only.

## Outcome per ticker

| Outcome | Condition | Written? | Log |
|---|---|---|---|
| stored | no missing field | yes (upsert as today) | `INFO Resolved …` (as today) |
| stored with warning | required present; market and/or exchange missing | yes | `WARNING Stored <SYMBOL> with missing …` |
| discarded | any required field missing | no; existing row and metrics untouched | `WARNING Discarded <SYMBOL>: missing …` |
| discarded (lookup failed) | yfinance lookup raises | no | `ERROR Failed to resolve metadata for <SYMBOL>` + traceback |

## Run summary

`Ticker check: stored=<n> discarded=<n> warned=<n>` where `stored` includes `warned`, and
`stored + discarded` = symbols after the `--country` filter.
