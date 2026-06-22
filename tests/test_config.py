"""Tests for RFC-006 centralized configuration."""

from pathlib import Path
from unittest.mock import patch

import pytest

from config import (
    DEFAULT_BACKFILL_BATCH_SIZE,
    DEFAULT_METRICS_RETENTION_DAYS,
    DEFAULT_YF_BATCH_SIZE,
    DevConfig,
    ProdConfig,
    get_config,
)


def test_dev_config_loads_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://dev")
    monkeypatch.delenv("YF_BATCH_SIZE", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)

    with patch("dotenv.load_dotenv"):
        config = DevConfig.load()

    assert config.database_url == "postgresql://dev"
    assert config.yf_batch_size == DEFAULT_YF_BATCH_SIZE
    assert config.metrics_retention_days == DEFAULT_METRICS_RETENTION_DAYS
    assert config.backfill_batch_size == DEFAULT_BACKFILL_BATCH_SIZE


def test_dev_config_applies_env_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://dev")
    monkeypatch.setenv("YF_BATCH_SIZE", "10")
    monkeypatch.setenv("METRICS_RETENTION_DAYS", "180")

    with patch("dotenv.load_dotenv"):
        config = DevConfig.load()

    assert config.yf_batch_size == 10
    assert config.metrics_retention_days == 180


def test_dev_config_requires_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with patch("dotenv.load_dotenv"):
        with pytest.raises(ValueError, match="DATABASE_URL is not set"):
            DevConfig.load()


def test_prod_config_does_not_call_load_dotenv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://prod")

    with patch("dotenv.load_dotenv") as mock_load:
        config = ProdConfig.load()

    mock_load.assert_not_called()
    assert config.database_url == "postgresql://prod"


def test_get_config_selects_dev_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://dev")
    monkeypatch.delenv("APP_ENV", raising=False)

    with patch("config.DevConfig.load") as mock_dev:
        mock_dev.return_value = DevConfig(database_url="postgresql://dev")
        config = get_config()

    mock_dev.assert_called_once()
    assert config.database_url == "postgresql://dev"


@pytest.mark.parametrize("app_env", ["prod", "production", "PRODUCTION"])
def test_get_config_selects_prod(
    app_env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("DATABASE_URL", "postgresql://prod")

    with patch("config.ProdConfig.load") as mock_prod:
        mock_prod.return_value = ProdConfig(database_url="postgresql://prod")
        config = get_config()

    mock_prod.assert_called_once()
    assert config.database_url == "postgresql://prod"


def test_tickers_file_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://dev")
    monkeypatch.setenv("TICKERS_FILE", "/tmp/custom.txt")

    with patch("dotenv.load_dotenv"):
        config = DevConfig.load()

    assert config.tickers_file == Path("/tmp/custom.txt")
