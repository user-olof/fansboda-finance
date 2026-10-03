"""Tests for RFC-004 rolling data retention."""

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

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


@pytest.fixture(autouse=True)
def _stub_indices():
    with patch("fetch_sma.refresh_indices", return_value=0) as mock:
        yield mock


@pytest.fixture(autouse=True)
def _stub_sector_trends():
    with patch("fetch_sma.refresh_sector_trends", return_value=(0, 0)) as mock:
        yield mock


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
    assert len(DELETE_STALE_SQL) == 3
    for sql in DELETE_STALE_SQL:
        assert "%s" in sql
        assert "trading_date <" in sql
    assert "DELETE FROM us_metrics" in DELETE_STALE_SQL[0]
    assert "DELETE FROM swe_metrics" in DELETE_STALE_SQL[1]
    assert "DELETE FROM uk_metrics" in DELETE_STALE_SQL[2]


def test_delete_stale_market_sql_is_parameterized() -> None:
    assert len(DELETE_STALE_MARKET_SQL) == 3
    for sql in DELETE_STALE_MARKET_SQL:
        assert "%s" in sql
        assert "week_start <" in sql
    assert "DELETE FROM us_market_metrics" in DELETE_STALE_MARKET_SQL[0]
    assert "DELETE FROM swe_market_metrics" in DELETE_STALE_MARKET_SQL[1]
    assert "DELETE FROM uk_market_metrics" in DELETE_STALE_MARKET_SQL[2]


def test_purge_stale_metrics_executes_delete_with_cutoff() -> None:
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 5
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.metrics.psycopg2.connect", return_value=mock_conn):
        with patch("db.metrics.retention_cutoff", return_value=date(2025, 6, 19)):
            deleted = purge_stale_metrics("postgresql://example", 365)

    assert mock_cursor.execute.call_count == 3
    mock_cursor.execute.assert_any_call(DELETE_STALE_SQL[0], (date(2025, 6, 19),))
    mock_cursor.execute.assert_any_call(DELETE_STALE_SQL[1], (date(2025, 6, 19),))
    mock_cursor.execute.assert_any_call(DELETE_STALE_SQL[2], (date(2025, 6, 19),))
    mock_conn.commit.assert_called_once()
    assert deleted == 15


def test_purge_stale_market_executes_delete_with_cutoff() -> None:
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 2
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.market.psycopg2.connect", return_value=mock_conn):
        with patch("db.market.retention_cutoff", return_value=date(2025, 6, 19)):
            deleted = purge_stale_market("postgresql://example", 365)

    assert mock_cursor.execute.call_count == 3
    mock_cursor.execute.assert_any_call(
        DELETE_STALE_MARKET_SQL[0],
        (date(2025, 6, 19),),
    )
    mock_cursor.execute.assert_any_call(
        DELETE_STALE_MARKET_SQL[1],
        (date(2025, 6, 19),),
    )
    mock_cursor.execute.assert_any_call(
        DELETE_STALE_MARKET_SQL[2],
        (date(2025, 6, 19),),
    )
    mock_conn.commit.assert_called_once()
    assert deleted == 6


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
            with patch(
                "db.retention.purge_stale_indices", return_value=2
            ) as mock_indices:
                metrics_purged, market_metrics_purged, indices_purged = (
                    purge_stale_data("postgresql://example", 365)
                )

    mock_metrics.assert_called_once_with("postgresql://example", 365)
    mock_market_metrics.assert_called_once_with("postgresql://example", 365)
    mock_indices.assert_called_once_with("postgresql://example", 365)
    assert metrics_purged == 4
    assert market_metrics_purged == 1
    assert indices_purged == 2


def test_purge_stale_data_deletes_from_all_country_tables() -> None:
    """purge_stale_data must hit us_/swe_/uk_ metrics and market_metrics (RFC-004)."""
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 1
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.metrics.psycopg2.connect", return_value=mock_conn):
        with patch("db.market.psycopg2.connect", return_value=mock_conn):
            with patch("db.indices.psycopg2.connect", return_value=mock_conn):
                with patch(
                    "db.metrics.retention_cutoff", return_value=date(2025, 6, 19)
                ):
                    with patch(
                        "db.market.retention_cutoff", return_value=date(2025, 6, 19)
                    ):
                        with patch(
                            "db.indices.retention_cutoff",
                            return_value=date(2025, 6, 19),
                        ):
                            metrics_purged, market_purged, indices_purged = (
                                purge_stale_data("postgresql://example", 365)
                            )

    sqls = [call.args[0] for call in mock_cursor.execute.call_args_list]
    assert "DELETE FROM us_metrics WHERE trading_date < %s" in sqls
    assert "DELETE FROM swe_metrics WHERE trading_date < %s" in sqls
    assert "DELETE FROM uk_metrics WHERE trading_date < %s" in sqls
    assert "DELETE FROM us_market_metrics WHERE week_start < %s" in sqls
    assert "DELETE FROM swe_market_metrics WHERE week_start < %s" in sqls
    assert "DELETE FROM uk_market_metrics WHERE week_start < %s" in sqls
    assert "DELETE FROM indices WHERE trading_date < %s" in sqls
    assert metrics_purged == 3
    assert market_purged == 3
    assert indices_purged == 1



def test_run_retention_purge_delegates_to_purge_stale_data(caplog) -> None:
    with patch("fetch_sma.purge_stale_data", return_value=(3, 2, 1)) as mock_purge:
        with caplog.at_level(logging.INFO, logger="fetch_sma"):
            assert _run_retention_purge("postgresql://example", 365) == (3, 2, 1)

    mock_purge.assert_called_once_with("postgresql://example", 365)
    assert (
        "deleted 3 us_/swe_/uk_ metrics, 2 us_/swe_/uk_ market_metrics, "
        "and 1 indices row(s)" in caplog.text
    )


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
                    "fetch_sma.purge_stale_data", return_value=(3, 1, 0)
                ) as mock_purge:
                    with caplog.at_level(logging.INFO, logger="fetch_sma"):
                        assert main() == 0

    mock_purge.assert_called_once_with("postgresql://example", 365)
    assert "purged_market_metrics=1" in caplog.text


def test_main_refreshes_sector_trends_after_purge(
    _stub_sector_trends, _stub_indices
) -> None:
    calls: list[str] = []
    _stub_sector_trends.side_effect = lambda *a, **k: calls.append("sector") or (0, 0)

    def _purge(*_args):
        calls.append("purge")
        return (0, 0, 0)

    with patch("fetch_sma.get_config", return_value=_mock_config()):
        with patch(
            "fetch_sma.load_tickers_from_db",
            return_value=[TickerEntry(symbol="AAA.ST", company="Alpha")],
        ):
            with patch(
                "fetch_sma.filter_stale_tickers",
                return_value=([], 1, date(2026, 6, 15)),
            ):
                with patch("fetch_sma.purge_stale_data", side_effect=_purge):
                    assert main() == 0

    assert calls == ["purge", "sector"]
    _stub_sector_trends.assert_called_once_with("postgresql://example", [])
    _stub_indices.assert_not_called()


def test_main_returns_1_when_sector_trends_fail(_stub_sector_trends) -> None:
    _stub_sector_trends.side_effect = RuntimeError("db down")
    with patch("fetch_sma.get_config", return_value=_mock_config()):
        with patch(
            "fetch_sma.load_tickers_from_db",
            return_value=[TickerEntry(symbol="AAA.ST", company="Alpha")],
        ):
            with patch(
                "fetch_sma.filter_stale_tickers",
                return_value=([], 1, date(2026, 6, 15)),
            ):
                with patch("fetch_sma.purge_stale_data", return_value=(0, 0, 0)):
                    assert main() == 1


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
                            "fetch_sma.purge_stale_data", return_value=(2, 0, 0)
                        ) as mock_purge:
                            assert main() == 1

    mock_purge.assert_called_once_with("postgresql://example", 365)


def test_main_fetches_stale_tickers_and_inserts(
    _stub_sector_trends, _stub_indices
) -> None:
    metric_row = MetricRow(
        ticker="AAA.ST",
        company="Alpha",
        trading_date=date(2026, 6, 6),
        sma_50=Decimal("1"),
        sma_200=Decimal("2"),
        current_price=Decimal("3"),
        currency="SEK",
        momentum=Decimal("0.5"),
        z_score=None,
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
                                    "fetch_sma.load_momentum_by_market_for_week",
                                    return_value={
                                        "se_market": [Decimal("0.5")]
                                    },
                                ):
                                    with patch(
                                        "fetch_sma.upsert_market_stats"
                                    ) as mock_market:
                                        with patch(
                                            "fetch_sma.update_z_scores_for_week"
                                        ):
                                            with patch(
                                                "fetch_sma.purge_stale_data",
                                                return_value=(0, 0, 0),
                                            ):
                                                assert main() == 0

    mock_currency.assert_called_once()
    mock_download.assert_called_once()
    mock_rows.assert_called_once()
    mock_insert.assert_called_once()
    mock_market.assert_called_once()
    market_row = mock_market.call_args[0][1]
    assert market_row.market == "se_market"
    assert market_row.week_start == date(2026, 6, 1)
    assert market_row.momentum_mean == Decimal("0.5")
    _stub_sector_trends.assert_called_once_with(
        "postgresql://example", [date(2026, 6, 1)]
    )
    _stub_indices.assert_called_once_with("postgresql://example", [date(2026, 6, 1)])
    inserted_rows = mock_insert.call_args[0][1]
    assert inserted_rows[0].company == "Alpha"
    assert inserted_rows[0].currency == "SEK"


def test_main_fetches_uk_ticker_and_upserts_uk_market() -> None:
    metric_row = MetricRow(
        ticker="VOD.L",
        company="Vodafone",
        trading_date=date(2026, 6, 6),
        sma_50=Decimal("1"),
        sma_200=Decimal("2"),
        current_price=Decimal("3"),
        currency="GBp",
        momentum=Decimal("0.5"),
        z_score=None,
    )

    with patch("fetch_sma.get_config", return_value=_mock_config()):
        with patch(
            "fetch_sma.load_tickers_from_db",
            return_value=[
                TickerEntry(
                    symbol="VOD.L",
                    company="Vodafone",
                    market="uk_market",
                    exchange_name="LSE",
                )
            ],
        ):
            with patch(
                "fetch_sma.filter_stale_tickers",
                return_value=(["VOD.L"], 0, None),
            ):
                with patch(
                    "fetch_sma.load_currency_for_tickers",
                    return_value={"VOD.L": "GBp"},
                ):
                    with patch("fetch_sma.download_batch"):
                        with patch(
                            "fetch_sma.metric_rows_from_batch",
                            return_value=[metric_row],
                        ):
                            with patch(
                                "fetch_sma.insert_metrics", return_value=1
                            ) as mock_insert:
                                with patch(
                                    "fetch_sma.load_momentum_by_market_for_week",
                                    return_value={
                                        "uk_market": [Decimal("0.5")]
                                    },
                                ):
                                    with patch(
                                        "fetch_sma.upsert_market_stats"
                                    ) as mock_market:
                                        with patch(
                                            "fetch_sma.update_z_scores_for_week"
                                        ):
                                            with patch(
                                                "fetch_sma.purge_stale_data",
                                                return_value=(0, 0, 0),
                                            ):
                                                assert main() == 0

    mock_insert.assert_called_once()
    assert mock_insert.call_args[0][1][0].ticker == "VOD.L"
    mock_market.assert_called_once()
    market_row = mock_market.call_args[0][1]
    assert market_row.market == "uk_market"
    assert market_row.week_start == date(2026, 6, 1)
