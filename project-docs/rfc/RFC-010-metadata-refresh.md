# RFC-010: Ad-hoc Metadata Refresh

| Field | Value |
|-------|-------|
| **Priority** | P3 |
| **Status** | Implemented |
| **Depends on** | RFC-002, RFC-006 |
| **PRD** | FR-12 |
| **Feature** | [Watchlist metadata refresh](../FEATURES.md#watchlist-metadata-refresh-refresh_tickerspy) |

## Summary

Ad-hoc script to refresh watchlist metadata (`company`, `sector`, `industry`, listing `market`) without a full re-seed. Handles existing DB symbols and new symbols from the tickers file. Upserts into `us_tickers` / `swe_tickers` via the same country routing as `seed_tickers.py` (RFC-002).

**Scope note (PRD §6):** `company`, `sector`, `industry`, and listing `market` live on **`us_tickers` / `swe_tickers`** and are refreshed by this script (and `seed_tickers.py`). `currency` lives on **`us_metrics` / `swe_metrics`** snapshots and is populated by the weekly fetch (RFC-003) and backfill (RFC-005) — out of scope for this script.

## Requirements (FR-12)

- Refresh `company`, `sector`, `industry`, and listing `market` for symbols already in `us_tickers` / `swe_tickers`
- Add new symbols from file not yet in either tickers table (resolve all four fields)
- Same rate-limiting and upsert-on-conflict as `seed_tickers.py`
- Optional: accept a subset of symbols via CLI (e.g. `--symbols AAPL,MSFT.ST`)
- Optional: `--from-db` to refresh all DB symbols without reading file

## Implementation

### Files

| File | Role |
|------|------|
| `refresh_tickers.py` | CLI, symbol selection, orchestration |
| `symbols.py` | `load_tickers`, `parse_symbols_arg` |
| `seed_tickers.py` | Shared `resolve_and_upsert_symbols` |
| `yfinance_client.py` | `resolve_watchlist_fields` (via seed) |
| `db/tickers.py` | `upsert_tickers`, `load_tickers_from_db` (country tables) |
| `db/country.py` | Country routing for upsert target |
| `tests/test_refresh_tickers.py`, `tests/test_symbols.py` | Unit tests |

### Key functions (`refresh_tickers.py`)

| Function | Purpose |
|----------|---------|
| `load_symbols_for_refresh(...)` | Build symbol list (file ∪ DB, `--from-db`, or `--symbols`) |
| `refresh_tickers(...)` | Resolve metadata and upsert into `us_tickers` / `swe_tickers` |
| `main()` | CLI entry point |

### CLI

```bash
pipenv run python refresh_tickers.py                    # file ∪ DB merge
pipenv run python refresh_tickers.py --from-db          # all DB symbols
pipenv run python refresh_tickers.py --symbols AAPL,MSFT.ST
pipenv run python refresh_tickers.py custom-tickers.txt   # optional file path
```

### Reuse from RFC-002

- `resolve_and_upsert_symbols()` from `seed_tickers.py` → country-aware `upsert_tickers()`
- `load_tickers_from_db()` from `db/tickers.py` (both country tickers tables)
- `get_config()` from `config.py`

## Acceptance criteria

- [x] Refreshes `company`, `sector`, and `industry` for existing watchlist rows
- [x] Refreshes listing `market` via yfinance (RFC-002)
- [x] Adds new symbols from file with resolved watchlist metadata
- [x] Upserts into `us_tickers` / `swe_tickers` by listing country (RFC-001 / RFC-002)
- [x] Rate limiting matches seed script
- [x] Optional subset and `--from-db` modes
- [x] Uses `get_config()` — no direct `os.getenv`
- [x] Unit tests with mocked yfinance and DB
- [x] Not cron-scheduled

## Open questions

- Share CLI parsing with `seed_tickers.py` or keep scripts independent? **Kept independent** — refresh has argparse flags; seed keeps positional file arg.
- Extract shared `resolve_name()` / `resolve_metadata()` into a module used by seed, refresh, and tests? **Done** — `yfinance_client.py`.
