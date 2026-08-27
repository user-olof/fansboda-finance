# RFC-006: Centralized Configuration

| Field | Value |
|-------|-------|
| **Priority** | P2 |
| **Status** | Implemented |
| **Depends on** | — (applies to all scripts) |
| **PRD** | §5.5 |
| **Feature** | [Configuration](../FEATURES.md#configuration) |

## Summary

Replace scattered `os.getenv` calls with `config.py` exposing `DevConfig`, `ProdConfig`, and `get_config()`. Scripts read tunables from the config object at startup.

## Requirements

- `DevConfig`: load `.env` via `python-dotenv`; read secrets locally
- `ProdConfig`: read from VM environment / `.env` written by deploy
- All PRD §5.5 settings as config attributes
- Job scripts must not call `os.getenv` directly (only `config.py` reads env)
- Select active config via `APP_ENV`

## Implementation

### Files

| File | Role |
|------|------|
| `config.py` | `BaseConfig`, `DevConfig`, `ProdConfig`, `get_config()` |
| `fetch_sma.py` | Uses `get_config()` in `main()` |
| `seed_tickers.py` | Uses `get_config()` in `main()` |
| `backfill_sma.py` | Uses `get_config()` in `main()` |
| `tests/test_config.py` | Defaults, overrides, `APP_ENV` selection |
| `.github/workflows/deploy.yml` | Writes `APP_ENV=production` to VM `.env` |

### Settings (PRD §5.5)

| Attribute | Dev default | Prod default | Env var |
|-----------|-------------|--------------|---------|
| `database_url` | from `.env` (required) | from VM `.env` (required) | `DATABASE_URL` |
| `tickers_file` | `tickers.txt` | `tickers.txt` | `TICKERS_FILE` |
| `yf_batch_size` | 40 | 40 | `YF_BATCH_SIZE` |
| `yf_batch_delay_seconds` | 2.0 | 2.0 | `YF_BATCH_DELAY_SECONDS` |
| `yf_max_retries` | 3 | 3 | `YF_MAX_RETRIES` |
| `yf_retry_base_seconds` | 5.0 | 5.0 | `YF_RETRY_BASE_SECONDS` |
| `yf_name_delay_seconds` | 0.25 | 0.25 | `YF_NAME_DELAY_SECONDS` |
| `metrics_retention_days` | 365 | 365 | `METRICS_RETENTION_DAYS` |
| `backfill_history_days` | 730 | 730 | `BACKFILL_HISTORY_DAYS` |
| `backfill_window_weeks` | 52 | 52 | `BACKFILL_WINDOW_WEEKS` |
| `backfill_batch_size` | 25 | 25 | `BACKFILL_BATCH_SIZE` |
| `backfill_batch_delay_seconds` | 5.0 | 5.0 | `BACKFILL_BATCH_DELAY_SECONDS` |

`DevConfig` and `ProdConfig` may override shared defaults per environment.

### Selection logic

```python
def get_config() -> BaseConfig:
    env = os.environ.get("APP_ENV", "dev").lower()
    if env in ("prod", "production"):
        return ProdConfig.load()
    return DevConfig.load()
```

- `DevConfig.load()` calls `load_dotenv()` then `_from_env()`.
- `ProdConfig.load()` calls `_from_env()` only — cron sources `.env` into shell (RFC-008).

### VM `.env` (written by deploy)

```
DATABASE_URL=postgresql://...
APP_ENV=production
```

## Acceptance criteria

- [x] `DevConfig` and `ProdConfig` with all PRD §5.5 settings
- [x] `get_config()` selects by `APP_ENV`
- [x] All three job scripts use config object
- [x] No direct `os.getenv` in job scripts
- [x] Deploy writes `APP_ENV=production` on VM
- [x] Unit tests in `tests/test_config.py`

## Open questions

- `ProdConfig` could use more conservative batch delays in production — PRD permits; currently identical defaults.
