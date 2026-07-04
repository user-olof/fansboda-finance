# RFC-010: Ad-hoc Metadata Refresh

| Field | Value |
|-------|-------|
| **Priority** | P3 |
| **Status** | Planned |
| **Depends on** | RFC-002, RFC-006 |
| **PRD** | FR-12 |
| **Feature** | [Planned features](../FEATURES.md#planned-features) |

## Summary

New script to refresh watchlist metadata (`name`, `sector`, `industry`) without a full re-seed. Handles existing DB symbols and new symbols from the tickers file.

**Scope note (PRD §6):** `sector` and `industry` live on **`tickers`** and are refreshed by this script (and `seed_tickers.py`). `currency` lives on **`metrics`** snapshots and is populated by the weekly fetch (RFC-003) — out of scope for this script.

## Requirements (FR-12)

- Refresh `name`, `sector`, and `industry` for symbols already in `tickers`
- Add new symbols from file not yet in `tickers` (resolve all three fields)
- Same rate-limiting and upsert-on-conflict as `seed_tickers.py`
- Optional: accept a subset of symbols via CLI (e.g. `--symbols AAPL,MSFT.ST`)
- Optional: `--from-db` to refresh all DB symbols without reading file

## Implementation

### Current state

Not implemented. `seed_tickers.py` always reads the full file and upserts all symbols — no subset refresh or DB-only mode. `seed_tickers.py` populates `name`, `sector`, and `industry` (RFC-002).

### Target design

#### New script: `refresh_tickers.py`

```
resolve_name()          # reuse from seed_tickers
resolve_metadata()      # reuse from seed_tickers (sectorKey, industryKey)
upsert_tickers()        # reuse from db/tickers
load_tickers_from_db()  # existing symbols from DB
load_tickers(path)      # symbols from file
get_config()            # database_url, yf_name_delay_seconds
```

#### CLI (proposed)

```bash
pipenv run python refresh_tickers.py                    # file + DB merge
pipenv run python refresh_tickers.py --from-db          # all DB symbols
pipenv run python refresh_tickers.py --symbols AAPL,MSFT.ST
```

#### Files to create/modify

| File | Action |
|------|--------|
| `refresh_tickers.py` | **New** — orchestration and CLI |
| `db/tickers.py` | Extend upsert for `sector`, `industry` if not done in RFC-002 |
| `tests/test_refresh_tickers.py` | **New** — unit tests |
| `project-docs/rfc/README.md` | Update status when done |

### Reuse from RFC-002

- `resolve_name()` from `seed_tickers.py`
- `resolve_metadata()` from `seed_tickers.py` (or shared module)
- `upsert_tickers()` from `db/tickers.py`
- `get_config()` from `config.py`

## Acceptance criteria

- [ ] Refreshes `name`, `sector`, and `industry` for existing `tickers` rows
- [ ] Adds new symbols from file with resolved watchlist metadata
- [ ] Rate limiting matches seed script
- [ ] Optional subset and `--from-db` modes
- [ ] Uses `get_config()` — no direct `os.getenv`
- [ ] Unit tests with mocked yfinance and DB
- [ ] Not cron-scheduled

## Open questions

- Share CLI parsing with `seed_tickers.py` or keep scripts independent?
- Extract shared `resolve_name()` / `resolve_metadata()` into a module used by seed, refresh, and tests?
