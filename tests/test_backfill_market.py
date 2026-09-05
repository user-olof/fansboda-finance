from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from backfill_market import main
from config import BaseConfig
from fetch_sma import upsert_market_for_trading_dates


def _mock_config(**overrides: object) -> BaseConfig:
    values: dict[str, object] = {"database_url": "postgresql://example"}
    values.update(overrides)
    return BaseConfig(**values)  # type: ignore[arg-type]


def test_load_distinct_trading_dates_returns_sorted_dates() -> None:
    from db.metrics import load_distinct_trading_dates

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        (date(2025, 1, 3),),
        (date(2025, 1, 10),),
    ]
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.metrics.psycopg2.connect", return_value=mock_conn):
        dates = load_distinct_trading_dates("postgresql://example")

    assert dates == [date(2025, 1, 3), date(2025, 1, 10)]
    sql = mock_cursor.execute.call_args[0][0]
    assert "SELECT DISTINCT trading_date" in sql
    assert "FROM us_metrics" in sql
    assert "FROM swe_metrics" in sql
    assert "FROM uk_metrics" in sql


def test_upsert_market_for_trading_dates_loads_ratios_and_upserts() -> None:
    with patch(
        "fetch_sma.load_raw_ratios_by_market_for_date",
        side_effect=[
            {"us_market": ([Decimal("0.5")], [Decimal("0.4")])},
            {"se_market": ([Decimal("0.6")], [Decimal("0.5")])},
        ],
    ) as mock_load:
        with patch("fetch_sma.upsert_market_stats") as mock_upsert:
            upsert_market_for_trading_dates(
                "postgresql://example",
                {date(2026, 6, 6), date(2026, 6, 13)},
            )

    assert mock_load.call_count == 2
    mock_upsert.assert_called()
    assert mock_upsert.call_count == 2


def test_main_backfill_market_upserts_all_dates() -> None:
    with patch("backfill_market.get_config", return_value=_mock_config()):
        with patch(
            "backfill_market.load_distinct_trading_dates",
            return_value=[date(2025, 1, 3), date(2025, 1, 10)],
        ):
            with patch(
                "backfill_market.upsert_market_for_trading_dates"
            ) as mock_upsert:
                assert main() == 0

    mock_upsert.assert_called_once_with(
        "postgresql://example",
        {date(2025, 1, 3), date(2025, 1, 10)},
    )


def test_main_backfill_market_returns_failure_on_upsert_error() -> None:
    with patch("backfill_market.get_config", return_value=_mock_config()):
        with patch(
            "backfill_market.load_distinct_trading_dates",
            return_value=[date(2025, 1, 3)],
        ):
            with patch(
                "backfill_market.upsert_market_for_trading_dates",
                side_effect=RuntimeError("db error"),
            ):
                assert main() == 1


def test_main_backfill_market_returns_failure_when_no_dates() -> None:
    with patch("backfill_market.get_config", return_value=_mock_config()):
        with patch("backfill_market.load_distinct_trading_dates", return_value=[]):
            assert main() == 1
