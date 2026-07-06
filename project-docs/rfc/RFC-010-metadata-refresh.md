# RFC-010: Ad-hoc Metadata Refresh

| Field | Value |
|-------|-------|
| **Priority** | P3 |
| **Status** | Implemented |
| **Depends on** | RFC-002, RFC-006 |
| **PRD** | FR-12 |
| **Feature** | [Watchlist metadata refresh](../FEATURES.md#watchlist-metadata-refresh-refresh_tickerspy) |

## Summary

Ad-hoc script to refresh watchlist metadata (`company`, `sector`, `industry`) without a full re-seed. Handles existing DB symbols and new symbols from the tickers file.

**Scope note (PRD §6):** `company`, `sector`, and `industry` live on **`tickers`** and are refreshed by this script (and `seed_tickers.py`). `currency` lives on **`metrics`** snapshots and is populated by the weekly fetch (RFC-003) and backfill (RFC-005) — out of scope for this script.

## Requirements (FR-12)

- Refresh `company`, `sector`, and `industry` for symbols already in `tickers`
- Add new symbols from file not yet in `tickers` (resolve all three fields)
- Same rate-limiting and upsert-on-conflict as `seed_tickers.py`
- Optional: accept a subset of symbols via CLI (e.g. `--symbols AAPL,MSFT.ST`)
- Optional: `--from-db` to refresh all DB symbols without reading file

## Implementation

### Files

| File | Role |
|------|------|
| `refresh_tickers.py` | CLI, symbol selection, orchestration |
| `seed_tickers.py` | Shared `resolve_and_upsert_symbols`, `resolve_watchlist_fields` |
| `db/tickers.py` | `upsert_tickers`, `load_tickers_from_db` |
| `fetch_sma.py` | `load_tickers(path)` — shared file parsing |
| `tests/test_refresh_tickers.py` | Unit tests |

### Key functions (`refresh_tickers.py`)

| Function | Purpose |
|----------|---------|
| `load_symbols_for_refresh(...)` | Build symbol list (file ∪ DB, `--from-db`, or `--symbols`) |
| `refresh_tickers(...)` | Resolve metadata and upsert |
| `main()` | CLI entry point |

### CLI

```bash
pipenv run python refresh_tickers.py                    # file ∪ DB merge
pipenv run python refresh_tickers.py --from-db          # all DB symbols
pipenv run python refresh_tickers.py --symbols AAPL,MSFT.ST
pipenv run python refresh_tickers.py custom-tickers.txt   # optional file path
```

### Reuse from RFC-002

- `resolve_and_upsert_symbols()` from `seed_tickers.py`
- `upsert_tickers()` from `db/tickers.py`
- `get_config()` from `config.py`

## Acceptance criteria

- [x] Refreshes `company`, `sector`, and `industry` for existing `tickers` rows
- [x] Adds new symbols from file with resolved watchlist metadata
- [x] Rate limiting matches seed script
- [x] Optional subset and `--from-db` modes
- [x] Uses `get_config()` — no direct `os.getenv`
- [x] Unit tests with mocked yfinance and DB
- [x] Not cron-scheduled

## Open questions

- Share CLI parsing with `seed_tickers.py` or keep scripts independent? **Kept independent** — refresh has argparse flags; seed keeps positional file arg.
- Extract shared `resolve_name()` / `resolve_metadata()` into a module used by seed, refresh, and tests? **Deferred** — `resolve_and_upsert_symbols` shared via `seed_tickers.py`.
