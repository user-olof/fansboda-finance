from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from backfill_market import build_parser, main
from config import BaseConfig
from db.country import CountrySet
from db.metrics import load_distinct_week_starts, recompute_momentum_from_smas
from fetch_sma import upsert_market_for_weeks


def _mock_config(**overrides: object) -> BaseConfig:
    values: dict[str, object] = {"database_url": "postgresql://example"}
    values.update(overrides)
    return BaseConfig(**values)  # type: ignore[arg-type]


def test_load_distinct_week_starts_returns_sorted_dates() -> None:
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        (date(2025, 1, 3),),
        (date(2025, 1, 10),),
    ]
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.metrics.psycopg2.connect", return_value=mock_conn):
        dates = load_distinct_week_starts("postgresql://example")

    assert dates == [date(2025, 1, 3), date(2025, 1, 10)]
    sql = mock_cursor.execute.call_args[0][0]
    assert "SELECT DISTINCT week_start" in sql
    assert "FROM us_metrics" in sql
    assert "FROM swe_metrics" in sql
    assert "FROM uk_metrics" in sql


def test_load_distinct_week_starts_scopes_to_country() -> None:
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [(date(2025, 1, 3),)]
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.metrics.psycopg2.connect", return_value=mock_conn):
        dates = load_distinct_week_starts(
            "postgresql://example", country=CountrySet.SWE
        )

    assert dates == [date(2025, 1, 3)]
    sql = mock_cursor.execute.call_args[0][0]
    assert "FROM swe_metrics" in sql
    assert "FROM us_metrics" not in sql


def test_recompute_momentum_from_smas_updates_all_countries() -> None:
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 2
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.metrics.psycopg2.connect", return_value=mock_conn):
        updated = recompute_momentum_from_smas("postgresql://example")

    assert updated == 6
    assert mock_cursor.execute.call_count == 3
    sqls = [call.args[0] for call in mock_cursor.execute.call_args_list]
    assert any("UPDATE us_metrics" in sql for sql in sqls)
    assert any("UPDATE swe_metrics" in sql for sql in sqls)
    assert any("UPDATE uk_metrics" in sql for sql in sqls)
    assert all("sma_50 / sma_200" in sql for sql in sqls)
    mock_conn.commit.assert_called_once()


def test_recompute_momentum_from_smas_scopes_to_country() -> None:
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 4
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.metrics.psycopg2.connect", return_value=mock_conn):
        updated = recompute_momentum_from_smas(
            "postgresql://example", country=CountrySet.SWE
        )

    assert updated == 4
    mock_cursor.execute.assert_called_once()
    sql = mock_cursor.execute.call_args[0][0]
    assert "UPDATE swe_metrics" in sql
    assert "UPDATE us_metrics" not in sql


def test_upsert_market_for_weeks_loads_ratios_and_upserts() -> None:
    with patch(
        "fetch_sma.load_momentum_by_market_for_week",
        side_effect=[
            {"us_market": [Decimal("0.5")]},
            {"se_market": [Decimal("0.6")]},
        ],
    ) as mock_load:
        with patch("fetch_sma.upsert_market_stats") as mock_upsert:
            with patch("fetch_sma.update_z_scores_for_week"):
                upsert_market_for_weeks(
                    "postgresql://example",
                    {date(2026, 6, 6), date(2026, 6, 13)},
                )

    assert mock_load.call_count == 2
    mock_upsert.assert_called()
    assert mock_upsert.call_count == 2


def test_main_backfill_market_recomputes_momentum_then_upserts() -> None:
    with patch("backfill_market.get_config", return_value=_mock_config()):
        with patch(
            "backfill_market.recompute_momentum_from_smas", return_value=10
        ) as mock_momentum:
            with patch(
                "backfill_market.load_distinct_week_starts",
                return_value=[date(2025, 1, 3), date(2025, 1, 10)],
            ) as mock_dates:
                with patch(
                    "backfill_market.upsert_market_for_weeks"
                ) as mock_upsert:
                    assert main([]) == 0

    mock_momentum.assert_called_once_with("postgresql://example", country=None)
    mock_dates.assert_called_once_with("postgresql://example", country=None)
    mock_upsert.assert_called_once_with(
        "postgresql://example",
        {date(2025, 1, 3), date(2025, 1, 10)},
        country=None,
    )


def test_main_backfill_market_scopes_to_country() -> None:
    with patch("backfill_market.get_config", return_value=_mock_config()):
        with patch(
            "backfill_market.recompute_momentum_from_smas", return_value=5
        ) as mock_momentum:
            with patch(
                "backfill_market.load_distinct_week_starts",
                return_value=[date(2025, 1, 3)],
            ) as mock_dates:
                with patch(
                    "backfill_market.upsert_market_for_weeks"
                ) as mock_upsert:
                    assert main(["--country", "swe"]) == 0

    mock_momentum.assert_called_once_with(
        "postgresql://example", country=CountrySet.SWE
    )
    mock_dates.assert_called_once_with(
        "postgresql://example", country=CountrySet.SWE
    )
    mock_upsert.assert_called_once_with(
        "postgresql://example",
        {date(2025, 1, 3)},
        country=CountrySet.SWE,
    )


def test_main_backfill_market_returns_failure_on_upsert_error() -> None:
    with patch("backfill_market.get_config", return_value=_mock_config()):
        with patch("backfill_market.recompute_momentum_from_smas", return_value=1):
            with patch(
                "backfill_market.load_distinct_week_starts",
                return_value=[date(2025, 1, 3)],
            ):
                with patch(
                    "backfill_market.upsert_market_for_weeks",
                    side_effect=RuntimeError("db error"),
                ):
                    assert main([]) == 1


def test_main_backfill_market_returns_failure_when_no_dates() -> None:
    with patch("backfill_market.get_config", return_value=_mock_config()):
        with patch("backfill_market.recompute_momentum_from_smas", return_value=0):
            with patch(
                "backfill_market.load_distinct_week_starts", return_value=[]
            ):
                assert main([]) == 1


def test_main_backfill_market_returns_failure_on_momentum_error() -> None:
    with patch("backfill_market.get_config", return_value=_mock_config()):
        with patch(
            "backfill_market.recompute_momentum_from_smas",
            side_effect=RuntimeError("db error"),
        ):
            assert main([]) == 1


def test_build_parser_optional_country() -> None:
    parser = build_parser()
    assert parser.parse_args([]).country is None
    assert parser.parse_args(["--country", "swe"]).country == "swe"
