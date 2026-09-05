# RFC-006: Centralized Configuration

| Field | Value |
|-------|-------|
| **Priority** | P2 |
| **Status** | Implemented |
| **Depends on** | — (applies to all scripts) |
| **PRD** | §5.5 |
| **Feature** | [Configuration](../FEATURES.md#configuration) |

## Summary

Replace scattered `os.getenv` / `os.environ` reads with `config.py` exposing `DevConfig`, `ProdConfig`, and `get_config()`. Scripts read tunables from the config object at startup. Country-partitioned tables (PRD §6) do not add new env vars — retention still uses `metrics_retention_days` for all `us_*` / `swe_*` / `uk_*` history and market-metrics tables.

## Requirements

- `DevConfig`: load `.env` via `python-dotenv`; read secrets locally
- `ProdConfig`: read from VM environment / `.env` written by deploy
- All PRD §5.5 settings as config attributes
- Job / utility scripts must not call `os.getenv` / `os.environ` directly (only `config.py` reads env)
- Select active config via `APP_ENV`

## Implementation

### Files

| File | Role |
|------|------|
| `config.py` | `BaseConfig`, `DevConfig`, `ProdConfig`, `get_config()`, `get_app_env()`, `require_non_production()` |
| `fetch_sma.py` | Uses `get_config()` in `main()` |
| `seed_tickers.py` | Uses `get_config()` in `main()` |
| `refresh_tickers.py` | Uses `get_config()` in `main()` |
| `backfill_sma.py` | Uses `get_config()` in `main()` |
| `backfill_market.py` | Uses `get_config()` in `main()` |
| `scripts/truncate_dev_tables.py` | Uses `require_non_production()` + `get_config()` |
| `tests/test_config.py` | Defaults, overrides, `APP_ENV` selection |
| `.github/workflows/deploy.yml` | Writes VM `.env` (`DATABASE_URL` + `APP_ENV`; temporary `APP_ENV=dev` while validating) |

### Settings (PRD §5.5)

| Attribute | Dev default | Prod default | Env var | Notes |
|-----------|-------------|--------------|---------|-------|
| `database_url` | from `.env` (required) | from VM `.env` (required) | `DATABASE_URL` | Neon connection string |
| `tickers_file` | `tickers.txt` | `tickers.txt` | `TICKERS_FILE` | Seed/refresh symbol file |
| `yf_batch_size` | 40 | 40 | `YF_BATCH_SIZE` | Weekly fetch batch size |
| `yf_batch_delay_seconds` | 2.0 | 2.0 | `YF_BATCH_DELAY_SECONDS` | Delay between fetch batches |
| `yf_max_retries` | 3 | 3 | `YF_MAX_RETRIES` | Max retries per batch |
| `yf_retry_base_seconds` | 5.0 | 5.0 | `YF_RETRY_BASE_SECONDS` | Backoff base |
| `yf_name_delay_seconds` | 0.25 | 0.25 | `YF_NAME_DELAY_SECONDS` | Seed/refresh name lookup delay |
| `metrics_retention_days` | 365 | 365 | `METRICS_RETENTION_DAYS` | Purge cutoff for `us_metrics` / `swe_metrics` / `uk_metrics` / matching `*_market_metrics` |
| `backfill_history_days` | 730 | 730 | `BACKFILL_HISTORY_DAYS` | Backfill OHLCV window |
| `backfill_window_weeks` | 52 | 52 | `BACKFILL_WINDOW_WEEKS` | Rolling SMA window length |
| `backfill_batch_size` | 25 | 25 | `BACKFILL_BATCH_SIZE` | Backfill batch size |
| `backfill_batch_delay_seconds` | 5.0 | 5.0 | `BACKFILL_BATCH_DELAY_SECONDS` | Delay between backfill batches |

`DevConfig` and `ProdConfig` may override shared defaults per environment.

### Selection logic

```python
def get_app_env() -> str:
    return os.environ.get("APP_ENV", "dev").lower()

def get_config() -> BaseConfig:
    if is_production_env():
        return ProdConfig.load()
    return DevConfig.load()
```

- `DevConfig.load()` calls `load_dotenv()` then `_from_env()`.
- `ProdConfig.load()` calls `_from_env()` only — cron sources `.env` into shell (RFC-008).
- `require_non_production()` raises when `APP_ENV` is `prod` / `production` (dev-only tools).

### VM `.env` (written by deploy)

```
DATABASE_URL=postgresql://...
APP_ENV=dev
```

**Temporary (VM validation):** deploy currently writes `APP_ENV=dev` (not production cutover). Switch to `APP_ENV=production` when ready (RFC-007). No UK-specific env vars are required — country routing is code/schema, not config.

## Acceptance criteria

- [x] `DevConfig` and `ProdConfig` with all PRD §5.5 settings
- [x] `get_config()` selects by `APP_ENV`
- [x] Job scripts (`fetch_sma`, `seed_tickers`, `refresh_tickers`, `backfill_sma`, `backfill_market`) use config object
- [x] No direct `os.getenv` / `os.environ` in those scripts (env reads live in `config.py`)
- [x] `metrics_retention_days` applies to all country-partitioned history/market tables (`us_*` / `swe_*` / `uk_*`; RFC-004)
- [x] Deploy writes `APP_ENV` on VM (temporary `APP_ENV=dev` during validation; production cutover tracked in RFC-007)
- [x] Unit tests in `tests/test_config.py`
- [x] No UK-specific config attributes needed (country sets share the same tunables)

## Open questions

- `ProdConfig` could use more conservative batch delays in production — PRD permits; currently identical defaults.
- Production cutover: flip deploy `.env` from `APP_ENV=dev` to `APP_ENV=production` when VM validation is complete (RFC-007).
