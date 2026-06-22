"""Tests for RFC-004 rolling data retention."""

from datetime import date
from unittest.mock import MagicMock, patch

from config import BaseConfig
from db.metrics import DELETE_STALE_SQL, purge_stale_metrics
from fetch_sma import main
from models import TickerEntry


def _mock_config(**overrides: object) -> BaseConfig:
    values: dict[str, object] = {
        "database_url": "postgresql://example",
        "metrics_retention_days": 365,
        "yf_batch_size": 40,
    }
    values.update(overrides)
    return BaseConfig(**values)  # type: ignore[arg-type]


def test_delete_stale_sql_is_parameterized() -> None:
    assert "%s" in DELETE_STALE_SQL
    assert "trading_date <" in DELETE_STALE_SQL


def test_purge_stale_metrics_executes_delete_with_cutoff() -> None:
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 5
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.metrics.psycopg2.connect", return_value=mock_conn):
        with patch("db.metrics.retention_cutoff", return_value=date(2025, 6, 19)):
            deleted = purge_stale_metrics("postgresql://example", 365)

    mock_cursor.execute.assert_called_once_with(DELETE_STALE_SQL, (date(2025, 6, 19),))
    mock_conn.commit.assert_called_once()
    assert deleted == 5


def test_purge_stale_metrics_returns_zero_when_nothing_deleted() -> None:
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 0
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.metrics.psycopg2.connect", return_value=mock_conn):
        with patch("db.metrics.retention_cutoff", return_value=date(2025, 1, 1)):
            deleted = purge_stale_metrics("postgresql://example", 365)

    assert deleted == 0


def test_main_purges_when_all_tickers_already_fresh() -> None:
    with patch("fetch_sma.get_config", return_value=_mock_config()):
        with patch(
            "fetch_sma.load_tickers_from_db",
            return_value=[TickerEntry(symbol="AAA.ST", name="Alpha")],
        ):
            with patch(
                "fetch_sma.filter_stale_tickers",
                return_value=([], 1, date(2026, 6, 19)),
            ):
                with patch(
                    "fetch_sma.purge_stale_metrics", return_value=3
                ) as mock_purge:
                    assert main() == 0

    mock_purge.assert_called_once_with("postgresql://example", 365)


def test_main_purges_after_fetch_even_when_no_metrics_collected() -> None:
    with patch("fetch_sma.get_config", return_value=_mock_config()):
        with patch(
            "fetch_sma.load_tickers_from_db",
            return_value=[TickerEntry(symbol="AAA.ST", name="Alpha")],
        ):
            with patch(
                "fetch_sma.filter_stale_tickers",
                return_value=(["AAA.ST"], 0, None),
            ):
                with patch(
                    "fetch_sma.download_batch",
                    side_effect=RuntimeError("rate limited"),
                ):
                    with patch(
                        "fetch_sma.purge_stale_metrics", return_value=2
                    ) as mock_purge:
                        assert main() == 1

    mock_purge.assert_called_once_with("postgresql://example", 365)
