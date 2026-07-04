# RFC-002: Watchlist Seeding

| Field | Value |
|-------|-------|
| **Priority** | P1 |
| **Status** | Implemented |
| **Depends on** | RFC-001 |
| **PRD** | FR-9, FR-10, FR-11 |
| **Feature** | [Watchlist seeding](../FEATURES.md#watchlist-seeding-seed_tickerspy) |

## Summary

Ad-hoc script to load symbols from a text file, resolve company names and watchlist metadata (`sector`, `industry`) via yfinance, and upsert into the `tickers` table.

## Requirements

| ID | Requirement |
|----|-------------|
| FR-9 | Read symbols from file (one per line; `#` comments and blanks ignored); uppercase |
| FR-10 | Resolve name from yfinance (`longName`, fallback `shortName`); rate-limit delay between lookups |
| FR-11 | Upsert `(symbol, name, sector, industry)` on conflict by `symbol`; `sector` / `industry` from `sectorKey` / `industryKey` |

## Implementation

### Architecture

```
tickers.txt  →  load_tickers()  →  resolve_name()  ─┐
                      ↑              resolve_metadata() ─┤→  upsert_tickers()
                 fetch_sma.py                            ↑
                 (file parsing)                    db/tickers.py
                                                  (parameterized SQL)
```

### Files

| File | Role |
|------|------|
| `seed_tickers.py` | CLI, yfinance name resolution, orchestration |
| `db/tickers.py` | `upsert_tickers`, `load_tickers_from_db` |
| `fetch_sma.py` | `load_tickers(path)` — shared file parsing |
| `config.py` | `tickers_file`, `yf_name_delay_seconds`, `database_url` |
| `tickers.txt` | Default symbol list |
| `tests/test_seed_tickers.py` | Unit tests |

### Key functions

| Function | Module | Purpose |
|----------|--------|---------|
| `load_tickers(path)` | `fetch_sma` | Parse symbol file |
| `resolve_name(symbol)` | `seed_tickers` | yfinance name lookup |
| `resolve_metadata(symbol)` | `seed_tickers` | yfinance `sectorKey`, `industryKey` lookup (reuse in RFC-010) |
| `upsert_tickers(url, rows)` | `db.tickers` | Parameterized upsert |
| `seed_tickers_from_file(...)` | `seed_tickers` | Orchestration |
| `main()` | `seed_tickers` | CLI entry point |

### Usage

```bash
pipenv run python seed_tickers.py
pipenv run python seed_tickers.py all-tickers.txt
```

Optional CLI arg overrides default file; config provides `tickers_file` and `yf_name_delay_seconds`.

## Acceptance criteria

- [x] Symbols loaded from file, uppercased, comments skipped
- [x] Company names resolved via yfinance with configurable delay
- [x] `sector` and `industry` resolved via yfinance and upserted into `tickers` (PRD §6)
- [x] Upsert into `tickers` on conflict by `symbol`
- [x] SQL in `db/tickers.py` with parameterized queries
- [x] Uses `get_config()` for database URL and tunables (RFC-006)
- [x] Tests cover resolve, upsert, and orchestration paths

## Open questions

- FR-12 (metadata refresh for existing DB symbols) is separate — see RFC-010.
