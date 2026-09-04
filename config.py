"""Centralized configuration for fansboda-finance (PRD §5.5, RFC-006)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_TICKERS_FILE = REPO_ROOT / "tickers.txt"

# Shared defaults — referenced by BaseConfig and pure-logic default args.
DEFAULT_YF_BATCH_SIZE = 40
DEFAULT_YF_BATCH_DELAY_SECONDS = 2.0
DEFAULT_YF_MAX_RETRIES = 3
DEFAULT_YF_RETRY_BASE_SECONDS = 5.0
DEFAULT_YF_NAME_DELAY_SECONDS = 0.25
DEFAULT_METRICS_RETENTION_DAYS = 365
DEFAULT_BACKFILL_HISTORY_DAYS = 730
DEFAULT_BACKFILL_WINDOW_WEEKS = 52
DEFAULT_BACKFILL_BATCH_SIZE = 25
DEFAULT_BACKFILL_BATCH_DELAY_SECONDS = 5.0

_PRODUCTION_APP_ENVS = frozenset({"prod", "production"})


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return float(raw)


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return Path(raw)


def get_app_env() -> str:
    """Return normalized APP_ENV (default ``dev``)."""
    return os.environ.get("APP_ENV", "dev").lower()


def is_production_env(app_env: str | None = None) -> bool:
    """Return True when APP_ENV selects ProdConfig."""
    env = get_app_env() if app_env is None else app_env.lower()
    return env in _PRODUCTION_APP_ENVS


def require_non_production() -> None:
    """Raise if APP_ENV is production (for destructive dev-only tools)."""
    env = get_app_env()
    if is_production_env(env):
        raise ValueError(
            f"This operation is for development only (APP_ENV={env!r})"
        )


@dataclass(frozen=True)
class BaseConfig:
    database_url: str
    tickers_file: Path = DEFAULT_TICKERS_FILE
    yf_batch_size: int = DEFAULT_YF_BATCH_SIZE
    yf_batch_delay_seconds: float = DEFAULT_YF_BATCH_DELAY_SECONDS
    yf_max_retries: int = DEFAULT_YF_MAX_RETRIES
    yf_retry_base_seconds: float = DEFAULT_YF_RETRY_BASE_SECONDS
    yf_name_delay_seconds: float = DEFAULT_YF_NAME_DELAY_SECONDS
    metrics_retention_days: int = DEFAULT_METRICS_RETENTION_DAYS
    backfill_history_days: int = DEFAULT_BACKFILL_HISTORY_DAYS
    backfill_window_weeks: int = DEFAULT_BACKFILL_WINDOW_WEEKS
    backfill_batch_size: int = DEFAULT_BACKFILL_BATCH_SIZE
    backfill_batch_delay_seconds: float = DEFAULT_BACKFILL_BATCH_DELAY_SECONDS

    @classmethod
    def _from_env(cls, *, require_database_url: bool = True) -> BaseConfig:
        database_url = os.environ.get("DATABASE_URL", "")
        if require_database_url and not database_url:
            raise ValueError("DATABASE_URL is not set")

        return cls(
            database_url=database_url,
            tickers_file=_env_path("TICKERS_FILE", DEFAULT_TICKERS_FILE),
            yf_batch_size=_env_int("YF_BATCH_SIZE", DEFAULT_YF_BATCH_SIZE),
            yf_batch_delay_seconds=_env_float(
                "YF_BATCH_DELAY_SECONDS", DEFAULT_YF_BATCH_DELAY_SECONDS
            ),
            yf_max_retries=_env_int("YF_MAX_RETRIES", DEFAULT_YF_MAX_RETRIES),
            yf_retry_base_seconds=_env_float(
                "YF_RETRY_BASE_SECONDS", DEFAULT_YF_RETRY_BASE_SECONDS
            ),
            yf_name_delay_seconds=_env_float(
                "YF_NAME_DELAY_SECONDS", DEFAULT_YF_NAME_DELAY_SECONDS
            ),
            metrics_retention_days=_env_int(
                "METRICS_RETENTION_DAYS", DEFAULT_METRICS_RETENTION_DAYS
            ),
            backfill_history_days=_env_int(
                "BACKFILL_HISTORY_DAYS", DEFAULT_BACKFILL_HISTORY_DAYS
            ),
            backfill_window_weeks=_env_int(
                "BACKFILL_WINDOW_WEEKS", DEFAULT_BACKFILL_WINDOW_WEEKS
            ),
            backfill_batch_size=_env_int(
                "BACKFILL_BATCH_SIZE", DEFAULT_BACKFILL_BATCH_SIZE
            ),
            backfill_batch_delay_seconds=_env_float(
                "BACKFILL_BATCH_DELAY_SECONDS",
                DEFAULT_BACKFILL_BATCH_DELAY_SECONDS,
            ),
        )


@dataclass(frozen=True)
class DevConfig(BaseConfig):
    @classmethod
    def load(cls) -> DevConfig:
        from dotenv import load_dotenv

        load_dotenv()
        return cls._from_env(require_database_url=True)


@dataclass(frozen=True)
class ProdConfig(BaseConfig):
    @classmethod
    def load(cls) -> ProdConfig:
        return cls._from_env(require_database_url=True)


def get_config() -> BaseConfig:
    if is_production_env():
        return ProdConfig.load()
    return DevConfig.load()
