"""Tests for RFC-004 rolling data retention."""

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from config import BaseConfig
from db.market import DELETE_STALE_MARKET_SQL, purge_stale_market
from db.metrics import DELETE_STALE_SQL, purge_stale_metrics, retention_cutoff
from db.retention import purge_stale_data
from fetch_sma import _run_retention_purge, main
from models import MetricRow, TickerEntry


def _mock_config(**overrides: object) -> BaseConfig:
    values: dict[str, object] = {
        "database_url": "postgresql://example",
        "metrics_retention_days": 365,
        "yf_batch_size": 40,
    }
    values.update(overrides)
    return BaseConfig(**values)  # type: ignore[arg-type]


def test_retention_cutoff_subtracts_days_from_utc_today() -> None:
    assert retention_cutoff(365, today=date(2026, 6, 6)) == date(2025, 6, 6)
    assert retention_cutoff(30, today=date(2026, 3, 31)) == date(2026, 3, 1)


def test_retention_cutoff_defaults_to_utc_today() -> None:
    with patch("db.metrics.datetime") as mock_datetime:
        mock_datetime.now.return_value = datetime(
            2026, 6, 6, 15, 30, tzinfo=timezone.utc
        )
        assert retention_cutoff(365) == date(2025, 6, 6)


def test_delete_stale_sql_is_parameterized() -> None:
    assert "%s" in DELETE_STALE_SQL
    assert "trading_date <" in DELETE_STALE_SQL
    assert "DELETE FROM metrics" in DELETE_STALE_SQL


def test_delete_stale_market_sql_is_parameterized() -> None:
    assert "%s" in DELETE_STALE_MARKET_SQL
    assert "trading_date <" in DELETE_STALE_MARKET_SQL
    assert "DELETE FROM market_metrics" in DELETE_STALE_MARKET_SQL


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


def test_purge_stale_market_executes_delete_with_cutoff() -> None:
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 2
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.market.psycopg2.connect", return_value=mock_conn):
        with patch("db.market.retention_cutoff", return_value=date(2025, 6, 19)):
            deleted = purge_stale_market("postgresql://example", 365)

    mock_cursor.execute.assert_called_once_with(
        DELETE_STALE_MARKET_SQL,
        (date(2025, 6, 19),),
    )
    mock_conn.commit.assert_called_once()
    assert deleted == 2


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


def test_purge_stale_data_purges_metrics_and_market_metrics() -> None:
    with patch("db.retention.purge_stale_metrics", return_value=4) as mock_metrics:
        with patch(
            "db.retention.purge_stale_market", return_value=1
        ) as mock_market_metrics:
            metrics_purged, market_metrics_purged = purge_stale_data(
                "postgresql://example",
                365,
            )

    mock_metrics.assert_called_once_with("postgresql://example", 365)
    mock_market_metrics.assert_called_once_with("postgresql://example", 365)
    assert metrics_purged == 4
    assert market_metrics_purged == 1


def test_run_retention_purge_delegates_to_purge_stale_data(caplog) -> None:
    with patch("fetch_sma.purge_stale_data", return_value=(3, 2)) as mock_purge:
        with caplog.at_level(logging.INFO, logger="fetch_sma"):
            metrics_purged, market_metrics_purged = _run_retention_purge(
                "postgresql://example",
                365,
            )

    mock_purge.assert_called_once_with("postgresql://example", 365)
    assert metrics_purged == 3
    assert market_metrics_purged == 2
    assert "deleted 3 metrics and 2 market_metrics row(s)" in caplog.text


def test_main_purges_when_all_tickers_already_fresh(caplog) -> None:
    with patch("fetch_sma.get_config", return_value=_mock_config()):
        with patch(
            "fetch_sma.load_tickers_from_db",
            return_value=[TickerEntry(symbol="AAA.ST", company="Alpha")],
        ):
            with patch(
                "fetch_sma.filter_stale_tickers",
                return_value=([], 1, date(2026, 6, 19)),
            ):
                with patch(
                    "fetch_sma.purge_stale_data", return_value=(3, 1)
                ) as mock_purge:
                    with caplog.at_level(logging.INFO, logger="fetch_sma"):
                        assert main() == 0

    mock_purge.assert_called_once_with("postgresql://example", 365)
    assert "purged_market_metrics=1" in caplog.text


def test_main_purges_after_fetch_even_when_no_metrics_collected() -> None:
    with patch("fetch_sma.get_config", return_value=_mock_config()):
        with patch(
            "fetch_sma.load_tickers_from_db",
            return_value=[TickerEntry(symbol="AAA.ST", company="Alpha")],
        ):
            with patch(
                "fetch_sma.filter_stale_tickers",
                return_value=(["AAA.ST"], 0, None),
            ):
                with patch(
                    "fetch_sma.load_currency_for_tickers",
                    return_value={"AAA.ST": "SEK"},
                ):
                    with patch(
                        "fetch_sma.download_batch",
                        side_effect=RuntimeError("rate limited"),
                    ):
                        with patch(
                            "fetch_sma.purge_stale_data", return_value=(2, 0)
                        ) as mock_purge:
                            assert main() == 1

    mock_purge.assert_called_once_with("postgresql://example", 365)


def test_main_fetches_stale_tickers_and_inserts() -> None:
    metric_row = MetricRow(
        ticker="AAA.ST",
        company="Alpha",
        trading_date=date(2026, 6, 6),
        sma_50=Decimal("1"),
        sma_200=Decimal("2"),
        current_price=Decimal("3"),
        currency="SEK",
        raw_50=Decimal("0.333333"),
        raw_200=Decimal("0.666667"),
    )

    with patch("fetch_sma.get_config", return_value=_mock_config()):
        with patch(
            "fetch_sma.load_tickers_from_db",
            return_value=[TickerEntry(symbol="AAA.ST", company="Alpha")],
        ):
            with patch(
                "fetch_sma.filter_stale_tickers",
                return_value=(["AAA.ST"], 0, None),
            ):
                with patch(
                    "fetch_sma.load_currency_for_tickers",
                    return_value={"AAA.ST": "SEK"},
                ) as mock_currency:
                    with patch("fetch_sma.download_batch") as mock_download:
                        with patch(
                            "fetch_sma.metric_rows_from_batch",
                            return_value=[metric_row],
                        ) as mock_rows:
                            with patch(
                                "fetch_sma.insert_metrics", return_value=1
                            ) as mock_insert:
                                with patch(
                                    "fetch_sma.load_raw_ratios_by_market_for_date",
                                    return_value={
                                        "se_market": (
                                            [Decimal("0.333333")],
                                            [Decimal("0.666667")],
                                        )
                                    },
                                ):
                                    with patch(
                                        "fetch_sma.upsert_market_stats"
                                    ) as mock_market:
                                        with patch(
                                            "fetch_sma.purge_stale_data",
                                            return_value=(0, 0),
                                        ):
                                            assert main() == 0

    mock_currency.assert_called_once()
    mock_download.assert_called_once()
    mock_rows.assert_called_once()
    mock_insert.assert_called_once()
    mock_market.assert_called_once()
    market_row = mock_market.call_args[0][1]
    assert market_row.market == "se_market"
    assert market_row.trading_date == date(2026, 6, 6)
    inserted_rows = mock_insert.call_args[0][1]
    assert inserted_rows[0].company == "Alpha"
    assert inserted_rows[0].currency == "SEK"
