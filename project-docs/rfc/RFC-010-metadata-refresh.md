# RFC-010: Ad-hoc Metadata Refresh

| Field | Value |
|-------|-------|
| **Priority** | P3 |
| **Status** | Planned |
| **Depends on** | RFC-002, RFC-006 |
| **PRD** | FR-12 |
| **Feature** | [Planned features](../FEATURES.md#planned-features) |

## Summary

New script to refresh watchlist metadata (company names and future fields) without a full re-seed. Handles existing DB symbols and new symbols from the tickers file.

## Requirements (FR-12)

- Refresh names for symbols already in `tickers`
- Add new symbols from file not yet in `tickers`
- Same rate-limiting and upsert-on-conflict as `seed_tickers.py`
- Optional: accept a subset of symbols via CLI (e.g. `--symbols AAPL,MSFT.ST`)
- Optional: `--from-db` to refresh all DB symbols without reading file

## Implementation

### Current state

Not implemented. `seed_tickers.py` always reads the full file and upserts all symbols — no subset refresh or DB-only mode.

### Target design

#### New script: `refresh_tickers.py`

```
resolve_name()          # reuse from seed_tickers
upsert_tickers()          # reuse from db/tickers
load_tickers_from_db()    # existing symbols from DB
load_tickers(path)        # symbols from file
get_config()              # database_url, yf_name_delay_seconds
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
| `db/tickers.py` | Optional: add `list_symbols()` if needed |
| `tests/test_refresh_tickers.py` | **New** — unit tests |
| `project-docs/rfc/README.md` | Update status when done |

### Reuse from RFC-002

- `resolve_name()` from `seed_tickers.py`
- `upsert_tickers()` from `db/tickers.py`
- `get_config()` from `config.py`

## Acceptance criteria

- [ ] Refreshes metadata for existing `tickers` rows
- [ ] Adds new symbols from file with resolved names
- [ ] Rate limiting matches seed script
- [ ] Optional subset and `--from-db` modes
- [ ] Uses `get_config()` — no direct `os.getenv`
- [ ] Unit tests with mocked yfinance and DB
- [ ] Not cron-scheduled

## Open questions

- Should refresh update `tickers.updated_at` when that column is added (RFC-001)?
- Share CLI parsing with `seed_tickers.py` or keep scripts independent?
