"""Tests for scripts/truncate_dev_tables.py (dev-only)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from config import require_non_production
from db.truncate import TRUNCATE_DEV_TABLES_SQL, truncate_dev_tables
from scripts.truncate_dev_tables import main


def test_truncate_sql_targets_expected_tables() -> None:
    sql = " ".join(TRUNCATE_DEV_TABLES_SQL.split())
    assert "TRUNCATE TABLE" in sql
    assert "us_market_metrics" in sql
    assert "swe_market_metrics" in sql
    assert "uk_market_metrics" in sql
    assert "us_metrics" in sql
    assert "swe_metrics" in sql
    assert "uk_metrics" in sql
    assert "us_tickers" in sql
    assert "swe_tickers" in sql
    assert "uk_tickers" in sql
    assert "RESTART IDENTITY" in sql


def test_truncate_dev_tables_executes_sql() -> None:
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.truncate.psycopg2.connect", return_value=mock_conn) as mock_connect:
        truncate_dev_tables("postgresql://example")

    mock_connect.assert_called_once_with("postgresql://example")
    mock_cursor.execute.assert_called_once_with(TRUNCATE_DEV_TABLES_SQL)
    mock_conn.commit.assert_called_once()


def test_require_non_production_allows_default_and_dev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    require_non_production()

    monkeypatch.setenv("APP_ENV", "dev")
    require_non_production()


@pytest.mark.parametrize("env", ["prod", "production", "PROD", "Production"])
def test_require_non_production_rejects_production(
    monkeypatch: pytest.MonkeyPatch,
    env: str,
) -> None:
    monkeypatch.setenv("APP_ENV", env)
    with pytest.raises(ValueError, match="development only"):
        require_non_production()


def test_main_refuses_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    assert main() == 1


def test_main_truncates_in_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    mock_config = MagicMock()
    mock_config.database_url = "postgresql://dev"

    with patch("scripts.truncate_dev_tables.get_config", return_value=mock_config):
        with patch("scripts.truncate_dev_tables.truncate_dev_tables") as mock_truncate:
            assert main() == 0

    mock_truncate.assert_called_once_with("postgresql://dev")
