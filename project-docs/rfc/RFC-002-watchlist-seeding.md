# RFC-002: Watchlist Seeding

| Field | Value |
|-------|-------|
| **Priority** | P1 |
| **Status** | Implemented |
| **Depends on** | RFC-001 |
| **PRD** | FR-9, FR-10, FR-11 |
| **Feature** | [Watchlist seeding](../FEATURES.md#watchlist-seeding-seed_tickerspy) |

## Summary

Ad-hoc script to load symbols from a text file, resolve company names and watchlist metadata (`sector`, `industry`, listing `market`, `exchange_name`) via yfinance, and upsert into `us_tickers`, `swe_tickers`, or `uk_tickers` (country chosen by listing market / symbol suffix — PRD §6).

## Requirements

| ID | Requirement |
|----|-------------|
| FR-9 | Read symbols from file (one per line; `#` comments and blanks ignored); uppercase |
| FR-10 | Resolve company name from yfinance (`longName`, fallback `shortName`); rate-limit delay between lookups |
| FR-11 | Upsert `(symbol, company, sector, industry, market, exchange_name)` into `us_tickers`, `swe_tickers`, or `uk_tickers` on conflict by `symbol`; `sector` / `industry` from `sectorKey` / `industryKey`; listing `market` from yfinance; `exchange_name` from `fullExchangeName` |

## Implementation

### Architecture

```
tickers.txt  →  load_tickers()  →  resolve_watchlist_fields()  ─┐
                      ↑                    (yfinance_client)     ┤→  upsert_tickers()
                 symbols.py                                      ↑
                                                            db/tickers.py
                                              (us_tickers / swe_tickers / uk_tickers)
```

### Files

| File | Role |
|------|------|
| `seed_tickers.py` | CLI, orchestration, `resolve_and_upsert_symbols` |
| `symbols.py` | `load_tickers(path)` — shared file parsing |
| `yfinance_client.py` | `resolve_watchlist_fields`, metadata lookups |
| `db/country.py` | `country_set_for`, `infer_listing_market` |
| `db/tickers.py` | `upsert_tickers`, `load_tickers_from_db` |
| `config.py` | `tickers_file`, `yf_name_delay_seconds`, `database_url` |
| `tickers.txt` | Default symbol list |
| `tests/test_seed_tickers.py`, `tests/test_symbols.py`, `tests/test_yfinance_client.py` | Unit tests |

### Key functions

| Function | Module | Purpose |
|----------|--------|---------|
| `load_tickers(path)` | `symbols` | Parse symbol file |
| `resolve_watchlist_fields(symbol)` | `yfinance_client` | Single yfinance lookup for company + sector + industry + listing `market` + `exchange_name` (`fullExchangeName`) |
| `infer_listing_market(...)` | `db.country` | Fallback `se_market` / `uk_market` / `us_market` when yfinance omits `market` |
| `resolve_and_upsert_symbols(...)` | `seed_tickers` | Rate-limited resolve loop + upsert |
| `upsert_tickers(url, rows)` | `db.tickers` | Parameterized upsert into `us_tickers` / `swe_tickers` / `uk_tickers` |
| `seed_tickers_from_file(...)` | `seed_tickers` | Orchestration |
| `main()` | `seed_tickers` | CLI entry point |

### Country routing

| Set | Condition | Target table |
|-----|-----------|--------------|
| Swedish | `market = se_market` or symbol ends with `.ST` | `swe_tickers` |
| UK | `market = uk_market` or symbol ends with `.L` | `uk_tickers` |
| US | default / other | `us_tickers` |

When yfinance omits `market`, `infer_listing_market` fills `se_market` / `uk_market` / `us_market` from the symbol so both routing and the `market` column are set.

### Usage

```bash
pipenv run python seed_tickers.py
pipenv run python seed_tickers.py all-tickers.txt
```

Optional CLI arg overrides default file; config provides `tickers_file` and `yf_name_delay_seconds`.

## Acceptance criteria

- [x] Symbols loaded from file, uppercased, comments skipped
- [x] Company names resolved via yfinance with configurable delay
- [x] `sector` and `industry` resolved via yfinance and upserted (PRD §6)
- [x] Upsert stores company name in the `company` column (PRD §6)
- [x] Upsert into `us_tickers` / `swe_tickers` / `uk_tickers` by listing country
- [x] Listing `market` resolved from yfinance (with symbol-based fallback)
- [x] Resolve and upsert `exchange_name` from yfinance `fullExchangeName` (FR-11)
- [x] Route `.L` / `uk_market` → `uk_tickers`
- [x] `infer_listing_market` fallback includes `uk_market` for `.L` symbols
- [x] SQL in `db/tickers.py` with parameterized queries
- [x] Uses `get_config()` for database URL and tunables (RFC-006)
- [x] Tests cover resolve, country routing (incl. UK), `exchange_name` persistence, upsert, and orchestration paths

## Open questions

- FR-12 (metadata refresh for existing DB symbols) is separate — see RFC-010.
