from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pandas as pd

import pytest

from backfill_sma import (
    build_parser,
    filter_by_exchange,
    filter_new_rows,
    main,
    metric_rows_from_backfill_batch,
    last_bar_positions_per_week,
    metric_rows_from_weekly_samples,
)
from config import BaseConfig
from db.country import CountrySet
from db.metrics import INSERT_METRICS_SQL, load_existing_metric_keys
from db.tickers import load_tickers_from_db
from fetch_sma import compute_momentum, upsert_market_for_weeks
from models import MetricRow, TickerEntry


def _mock_config(**overrides: object) -> BaseConfig:
    values: dict[str, object] = {
        "database_url": "postgresql://example",
        "backfill_batch_size": 25,
        "backfill_batch_delay_seconds": 5.0,
        "backfill_history_days": 730,
        "yf_max_retries": 3,
        "yf_retry_base_seconds": 5.0,
        "yf_name_delay_seconds": 0.25,
    }
    values.update(overrides)
    return BaseConfig(**values)  # type: ignore[arg-type]


def test_last_bar_positions_per_week_picks_last_bar_of_each_calendar_week() -> None:
    # Wed 2024-01-03 .. Tue 2024-01-16; Friday 2024-01-12 is a holiday.
    index = pd.to_datetime(
        [
            "2024-01-03",
            "2024-01-04",
            "2024-01-05",
            "2024-01-08",
            "2024-01-11",
            "2024-01-15",
            "2024-01-16",
        ]
    )
    assert last_bar_positions_per_week(index) == [2, 4, 6]


def test_metric_rows_from_weekly_samples_one_row_per_calendar_week() -> None:
    index = pd.date_range("2024-01-01", periods=280, freq="B")
    history = pd.DataFrame(
        {
            "Open": range(280),
            "High": range(280),
            "Low": range(280),
            "Close": range(1, 281),
            "Volume": [1000] * 280,
        },
        index=index,
    )

    rows = metric_rows_from_weekly_samples(
        "AAA.ST", history, company="Alpha AB", currency="SEK"
    )

    # Bar 200 lands on Fri 2024-10-04; weekly rows follow from that week on.
    assert rows[0].trading_date == date(2024, 10, 4)
    assert rows[0].current_price == Decimal("200")
    assert rows[0].sma_200 == Decimal("100.5")
    assert rows[-1].trading_date == date(2025, 1, 24)
    week_starts = [row.week_start for row in rows]
    assert len(week_starts) == len(set(week_starts))
    assert all(row.week_start.weekday() == 0 for row in rows)
    assert all(row.trading_date.weekday() == 4 for row in rows[:-1])
    assert rows[0].ticker == "AAA.ST"
    assert rows[0].company == "Alpha AB"
    assert rows[0].currency == "SEK"
    assert rows[0].sma_50 is not None
    assert rows[0].sma_200 is not None
    assert rows[0].current_price is not None
    assert rows[0].momentum == compute_momentum(rows[0].sma_50, rows[0].sma_200)
    assert rows[0].z_score is None
    assert rows[-1].trading_date >= rows[0].trading_date


def test_metric_rows_from_backfill_batch_sets_currency() -> None:
    index = pd.date_range("2024-01-01", periods=280, freq="B")
    columns = pd.MultiIndex.from_product(
        [["AAA.ST"], ["Open", "High", "Low", "Close", "Volume"]]
    )
    data = pd.DataFrame(index=index, columns=columns, dtype=float)
    for field in ("Open", "High", "Low", "Close", "Volume"):
        data[("AAA.ST", field)] = 1.0
    data[("AAA.ST", "Close")] = range(1, 281)

    rows = metric_rows_from_backfill_batch(
        data,
        ["AAA.ST"],
        {"AAA.ST": "Alpha AB"},
        {"AAA.ST": "SEK"},
    )

    assert rows
    assert all(row.currency == "SEK" for row in rows)
    assert all(row.company == "Alpha AB" for row in rows)
    assert all(row.momentum is not None for row in rows)
    assert all(row.z_score is None for row in rows)


def test_filter_new_rows_skips_existing_pairs() -> None:
    rows = [
        MetricRow(
            ticker="AAA.ST",
            company="Alpha",
            trading_date=date(2025, 1, 3),
            sma_50=Decimal("1"),
            sma_200=Decimal("2"),
            current_price=Decimal("3"),
        ),
        MetricRow(
            ticker="AAA.ST",
            company="Alpha",
            trading_date=date(2025, 1, 10),
            sma_50=Decimal("4"),
            sma_200=Decimal("5"),
            current_price=Decimal("6"),
        ),
    ]
    existing = {("AAA.ST", date(2025, 1, 3))}
    filtered = filter_new_rows(rows, existing)

    assert len(filtered) == 1
    assert filtered[0].trading_date == date(2025, 1, 10)


def test_main_backfill_inserts_new_rows() -> None:
    metric_row = MetricRow(
        ticker="AAA.ST",
        company="Alpha AB",
        trading_date=date(2025, 6, 6),
        sma_50=Decimal("1"),
        sma_200=Decimal("2"),
        current_price=Decimal("3"),
        currency="SEK",
        momentum=Decimal("0.5"),
        z_score=None,
    )

    with patch("backfill_sma.get_config", return_value=_mock_config()):
        with patch(
            "backfill_sma.load_tickers_from_db",
            return_value=[TickerEntry(symbol="AAA.ST", company="Alpha AB")],
        ):
            with patch(
                "backfill_sma.load_existing_metric_keys", return_value=set()
            ) as mock_existing:
                with patch(
                    "backfill_sma.load_currency_for_tickers",
                    return_value={"AAA.ST": "SEK"},
                ) as mock_currency:
                    with patch("backfill_sma.download_batch") as mock_download:
                        with patch(
                            "backfill_sma.metric_rows_from_backfill_batch",
                            return_value=[metric_row],
                        ):
                            with patch(
                                "backfill_sma.insert_metrics", return_value=1
                            ) as mock_insert:
                                with patch(
                                    "backfill_sma.upsert_market_for_weeks"
                                ) as mock_market:
                                    assert main(['--country', 'swe']) == 0

    mock_existing.assert_called_once_with(
        "postgresql://example", ["AAA.ST"], country=CountrySet.SWE
    )
    mock_currency.assert_called_once()
    mock_download.assert_called_once()
    mock_insert.assert_called_once_with("postgresql://example", [metric_row])
    mock_market.assert_called_once_with(
        "postgresql://example",
        {date(2025, 6, 2)},
        country=CountrySet.SWE,
    )
    inserted = mock_insert.call_args[0][1][0]
    assert inserted.company == "Alpha AB"
    assert inserted.currency == "SEK"


def test_main_succeeds_when_all_rows_already_exist() -> None:
    metric_row = MetricRow(
        ticker="AAA.ST",
        company="Alpha AB",
        trading_date=date(2025, 6, 6),
        sma_50=Decimal("1"),
        sma_200=Decimal("2"),
        current_price=Decimal("3"),
        currency="SEK",
        momentum=Decimal("0.5"),
        z_score=None,
    )

    with patch("backfill_sma.get_config", return_value=_mock_config()):
        with patch(
            "backfill_sma.load_tickers_from_db",
            return_value=[TickerEntry(symbol="AAA.ST", company="Alpha AB")],
        ):
            with patch(
                "backfill_sma.load_existing_metric_keys",
                return_value={("AAA.ST", date(2025, 6, 6))},
            ):
                with patch(
                    "backfill_sma.load_currency_for_tickers",
                    return_value={"AAA.ST": "SEK"},
                ):
                    with patch("backfill_sma.download_batch"):
                        with patch(
                            "backfill_sma.metric_rows_from_backfill_batch",
                            return_value=[metric_row],
                        ):
                            with patch("backfill_sma.insert_metrics", return_value=0):
                                with patch(
                                    "backfill_sma.upsert_market_for_weeks"
                                ) as mock_market:
                                    assert main(['--country', 'swe']) == 0

    mock_market.assert_called_once_with(
        "postgresql://example",
        {date(2025, 6, 2)},
        country=CountrySet.SWE,
    )


def test_main_returns_failure_when_market_metrics_upsert_fails() -> None:
    metric_row = MetricRow(
        ticker="AAA.ST",
        company="Alpha AB",
        trading_date=date(2025, 6, 6),
        sma_50=Decimal("1"),
        sma_200=Decimal("2"),
        current_price=Decimal("3"),
        currency="SEK",
        momentum=Decimal("0.5"),
        z_score=None,
    )

    with patch("backfill_sma.get_config", return_value=_mock_config()):
        with patch(
            "backfill_sma.load_tickers_from_db",
            return_value=[TickerEntry(symbol="AAA.ST", company="Alpha AB")],
        ):
            with patch("backfill_sma.load_existing_metric_keys", return_value=set()):
                with patch(
                    "backfill_sma.load_currency_for_tickers",
                    return_value={"AAA.ST": "SEK"},
                ):
                    with patch("backfill_sma.download_batch"):
                        with patch(
                            "backfill_sma.metric_rows_from_backfill_batch",
                            return_value=[metric_row],
                        ):
                            with patch("backfill_sma.insert_metrics", return_value=1):
                                with patch(
                                    "backfill_sma.upsert_market_for_weeks",
                                    side_effect=RuntimeError("db error"),
                                ):
                                    assert main(['--country', 'swe']) == 1


def test_upsert_market_for_weeks_groups_backfill_dates_by_listing_market() -> None:
    with patch(
        "fetch_sma.load_momentum_by_market_for_week",
        return_value={
            "se_market": [Decimal("0.5")],
            "us_market": [Decimal("0.6")],
        },
    ):
        with patch("fetch_sma.upsert_market_stats") as mock_upsert:
            with patch("fetch_sma.update_z_scores_for_week"):
                upsert_market_for_weeks(
                    "postgresql://example",
                    {date(2025, 6, 6)},
                )

    assert mock_upsert.call_count == 2
    markets = {call.args[1].market for call in mock_upsert.call_args_list}
    assert markets == {"se_market", "us_market"}


def test_upsert_market_for_weeks_scopes_to_country() -> None:
    with patch(
        "fetch_sma.load_momentum_by_market_for_week",
        return_value={
            "se_market": [Decimal("0.5")],
            "us_market": [Decimal("0.6")],
            "gb_market": [Decimal("0.7")],
        },
    ):
        with patch("fetch_sma.upsert_market_stats") as mock_upsert:
            with patch("fetch_sma.update_z_scores_for_week") as mock_z:
                upsert_market_for_weeks(
                    "postgresql://example",
                    {date(2025, 6, 6)},
                    country=CountrySet.US,
                )

    assert mock_upsert.call_count == 1
    assert mock_upsert.call_args.args[1].market == "us_market"
    mock_z.assert_called_once_with(
        "postgresql://example", date(2025, 6, 6), country=CountrySet.US
    )

def test_main_us_only_ignores_swe_and_uk_tickers() -> None:
    metric_row = MetricRow(
        ticker="AAPL",
        company="Apple",
        trading_date=date(2025, 6, 6),
        sma_50=Decimal("1"),
        sma_200=Decimal("2"),
        current_price=Decimal("3"),
        currency="USD",
        momentum=Decimal("0.5"),
        z_score=None,
    )

    with patch("backfill_sma.get_config", return_value=_mock_config()):
        with patch(
            "backfill_sma.load_tickers_from_db",
            return_value=[
                TickerEntry(symbol="AAPL", company="Apple", market="us_market"),
            ],
        ) as mock_load:
            with patch(
                "backfill_sma.load_existing_metric_keys", return_value=set()
            ) as mock_existing:
                with patch(
                    "backfill_sma.load_currency_for_tickers",
                    return_value={"AAPL": "USD"},
                ) as mock_currency:
                    with patch("backfill_sma.download_batch") as mock_download:
                        with patch(
                            "backfill_sma.metric_rows_from_backfill_batch",
                            return_value=[metric_row],
                        ):
                            with patch(
                                "backfill_sma.insert_metrics", return_value=1
                            ) as mock_insert:
                                with patch(
                                    "backfill_sma.upsert_market_for_weeks"
                                ) as mock_market:
                                    assert main(["--country", "us"]) == 0

    mock_load.assert_called_once_with(
        "postgresql://example",
        country=CountrySet.US,
    )
    mock_existing.assert_called_once_with(
        "postgresql://example", ["AAPL"], country=CountrySet.US
    )
    mock_currency.assert_called_once()
    assert mock_currency.call_args.args[0] == ["AAPL"]
    mock_download.assert_called_once()
    assert mock_download.call_args.args[0] == ["AAPL"]
    mock_insert.assert_called_once_with("postgresql://example", [metric_row])
    mock_market.assert_called_once_with(
        "postgresql://example",
        {date(2025, 6, 2)},
        country=CountrySet.US,
    )


def test_main_returns_failure_on_failed_batch() -> None:
    with patch("backfill_sma.get_config", return_value=_mock_config()):
        with patch(
            "backfill_sma.load_tickers_from_db",
            return_value=[TickerEntry(symbol="AAA.ST", company="Alpha AB")],
        ):
            with patch("backfill_sma.load_existing_metric_keys", return_value=set()):
                with patch(
                    "backfill_sma.load_currency_for_tickers",
                    return_value={"AAA.ST": "SEK"},
                ):
                    with patch(
                        "backfill_sma.download_batch",
                        side_effect=RuntimeError("rate limited"),
                    ):
                        assert main(['--country', 'swe']) == 1


def test_main_returns_failure_when_nothing_generated() -> None:
    with patch("backfill_sma.get_config", return_value=_mock_config()):
        with patch(
            "backfill_sma.load_tickers_from_db",
            return_value=[TickerEntry(symbol="AAA.ST", company="Alpha AB")],
        ):
            with patch("backfill_sma.load_existing_metric_keys", return_value=set()):
                with patch(
                    "backfill_sma.load_currency_for_tickers",
                    return_value={"AAA.ST": "SEK"},
                ):
                    with patch("backfill_sma.download_batch"):
                        with patch(
                            "backfill_sma.metric_rows_from_backfill_batch",
                            return_value=[],
                        ):
                            assert main(['--country', 'swe']) == 1


def test_load_existing_metric_keys_queries_uk_metrics() -> None:
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        ("VOD.L", date(2025, 1, 3)),
    ]
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.metrics.psycopg2.connect", return_value=mock_conn):
        keys = load_existing_metric_keys("postgresql://example", ["VOD.L"])

    assert keys == {("VOD.L", date(2025, 1, 3))}
    sql = mock_cursor.execute.call_args[0][0]
    assert "FROM us_metrics" in sql
    assert "FROM swe_metrics" in sql
    assert "FROM uk_metrics" in sql
    assert mock_cursor.execute.call_args[0][1] == (["VOD.L"], ["VOD.L"], ["VOD.L"])


def test_load_existing_metric_keys_with_country_queries_only_that_table() -> None:
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [("VOD.L", date(2025, 1, 3))]
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.metrics.psycopg2.connect", return_value=mock_conn):
        keys = load_existing_metric_keys(
            "postgresql://example", ["VOD.L"], country=CountrySet.UK
        )

    assert keys == {("VOD.L", date(2025, 1, 3))}
    sql = mock_cursor.execute.call_args[0][0]
    assert "FROM uk_metrics" in sql
    assert "us_metrics" not in sql
    assert "swe_metrics" not in sql
    assert "UNION ALL" not in sql
    assert mock_cursor.execute.call_args[0][1] == (["VOD.L"],)


def test_insert_metrics_sql_targets_uk_metrics() -> None:
    assert "INSERT INTO uk_metrics" in INSERT_METRICS_SQL[CountrySet.UK]
    sql = INSERT_METRICS_SQL[CountrySet.UK]
    assert "ON CONFLICT (ticker, week_start) DO UPDATE" in sql
    assert "WHERE EXCLUDED.trading_date > uk_metrics.trading_date" in sql


def test_load_tickers_from_db_scopes_to_country() -> None:
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        ("AAPL", "Apple", "Technology", "Consumer", "us_market", "NMS"),
    ]
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.tickers.psycopg2.connect", return_value=mock_conn):
        entries = load_tickers_from_db(
            "postgresql://example",
            country=CountrySet.US,
        )

    assert [entry.symbol for entry in entries] == ["AAPL"]
    sql = mock_cursor.execute.call_args[0][0]
    assert "FROM us_tickers" in sql
    assert "FROM swe_tickers" not in sql
    assert "FROM uk_tickers" not in sql


def test_main_backfill_routes_uk_ticker() -> None:
    metric_row = MetricRow(
        ticker="VOD.L",
        company="Vodafone",
        trading_date=date(2025, 6, 6),
        sma_50=Decimal("1"),
        sma_200=Decimal("2"),
        current_price=Decimal("3"),
        currency="GBP",
        momentum=Decimal("0.5"),
        z_score=None,
    )

    with patch("backfill_sma.get_config", return_value=_mock_config()):
        with patch(
            "backfill_sma.load_tickers_from_db",
            return_value=[
                TickerEntry(
                    symbol="VOD.L",
                    company="Vodafone",
                    market="gb_market",
                    exchange_name="LSE",
                )
            ],
        ) as mock_load:
            with patch(
                "backfill_sma.load_existing_metric_keys", return_value=set()
            ) as mock_existing:
                with patch(
                    "backfill_sma.load_currency_for_tickers",
                    return_value={"VOD.L": "GBP"},
                ):
                    with patch("backfill_sma.download_batch"):
                        with patch(
                            "backfill_sma.metric_rows_from_backfill_batch",
                            return_value=[metric_row],
                        ):
                            with patch(
                                "backfill_sma.insert_metrics", return_value=1
                            ) as mock_insert:
                                with patch(
                                    "backfill_sma.upsert_market_for_weeks"
                                ) as mock_market:
                                    assert main(["--country", "uk"]) == 0

    mock_load.assert_called_once_with(
        "postgresql://example",
        country=CountrySet.UK,
    )
    mock_existing.assert_called_once_with(
        "postgresql://example", ["VOD.L"], country=CountrySet.UK
    )
    mock_insert.assert_called_once_with("postgresql://example", [metric_row])
    mock_market.assert_called_once_with(
        "postgresql://example",
        {date(2025, 6, 2)},
        country=CountrySet.UK,
    )
    assert mock_insert.call_args[0][1][0].ticker == "VOD.L"
    assert mock_insert.call_args[0][1][0].currency == "GBP"


def test_upsert_market_for_weeks_includes_uk_market() -> None:
    with patch(
        "fetch_sma.load_momentum_by_market_for_week",
        return_value={
            "gb_market": [Decimal("0.7")],
            "us_market": [Decimal("0.6")],
        },
    ):
        with patch("fetch_sma.upsert_market_stats") as mock_upsert:
            with patch("fetch_sma.update_z_scores_for_week"):
                upsert_market_for_weeks(
                    "postgresql://example",
                    {date(2025, 6, 6)},
                )

    assert mock_upsert.call_count == 2
    markets = {call.args[1].market for call in mock_upsert.call_args_list}
    assert markets == {"gb_market", "us_market"}


def test_upsert_market_for_weeks_scopes_to_uk_country() -> None:
    with patch(
        "fetch_sma.load_momentum_by_market_for_week",
        return_value={
            "gb_market": [Decimal("0.7")],
            "us_market": [Decimal("0.6")],
            "se_market": [Decimal("0.5")],
        },
    ):
        with patch("fetch_sma.upsert_market_stats") as mock_upsert:
            with patch("fetch_sma.update_z_scores_for_week") as mock_z:
                upsert_market_for_weeks(
                    "postgresql://example",
                    {date(2025, 6, 6)},
                    country=CountrySet.UK,
                )

    assert mock_upsert.call_count == 1
    assert mock_upsert.call_args.args[1].market == "gb_market"
    mock_z.assert_called_once_with(
        "postgresql://example", date(2025, 6, 6), country=CountrySet.UK
    )

def test_build_parser_requires_country() -> None:
    from backfill_sma import build_parser

    parser = build_parser()
    args = parser.parse_args(["--country", "us"])
    assert args.country == "us"
    try:
        parser.parse_args([])
        raise AssertionError("expected SystemExit")
    except SystemExit as exc:
        assert exc.code == 2


def _exchange_watchlist() -> list[TickerEntry]:
    return [
        TickerEntry(symbol="AAPL", company="Apple", market="us_market", exchange_name="NasdaqGS"),
        TickerEntry(symbol="IBM", company="IBM", market="us_market", exchange_name="NYSE"),
        TickerEntry(symbol="ABCL", company="AbCellera", market="us_market", exchange_name="NasdaqGM"),
        TickerEntry(symbol="NEW", company="New", market="us_market", exchange_name=None),
    ]


def test_filter_by_exchange_matches_case_insensitively() -> None:
    entries = _exchange_watchlist()
    assert [e.symbol for e in filter_by_exchange(entries, ["nasdaqgs"])] == ["AAPL"]
    assert [e.symbol for e in filter_by_exchange(entries, ["NasdaqGS", "NasdaqGM"])] == [
        "AAPL",
        "ABCL",
    ]
    assert filter_by_exchange(entries, ["Nasdaq"]) == []
    assert filter_by_exchange(entries, None) == entries
    assert filter_by_exchange(entries, []) == entries


def test_build_parser_exchange_is_optional_and_repeatable() -> None:
    parser = build_parser()
    assert parser.parse_args(["--country", "us"]).exchange is None
    args = parser.parse_args(
        ["--country", "us", "--exchange", "NasdaqGS", "--exchange", "NYSE"]
    )
    assert args.exchange == ["NasdaqGS", "NYSE"]


def test_main_backfills_only_selected_exchange() -> None:
    with patch("backfill_sma.get_config", return_value=_mock_config()):
        with patch(
            "backfill_sma.load_tickers_from_db", return_value=_exchange_watchlist()
        ):
            with patch(
                "backfill_sma.load_existing_metric_keys", return_value=set()
            ) as mock_existing:
                with patch("backfill_sma.load_currency_for_tickers", return_value={}):
                    with patch("backfill_sma.download_batch") as mock_download:
                        with patch(
                            "backfill_sma.metric_rows_from_backfill_batch",
                            return_value=[],
                        ):
                            with patch("backfill_sma.insert_metrics", return_value=0):
                                main(["--country", "us", "--exchange", "NYSE"])

    mock_existing.assert_called_once_with(
        "postgresql://example", ["IBM"], country=CountrySet.US
    )
    assert mock_download.call_args.args[0] == ["IBM"]


def test_main_fails_when_no_ticker_on_exchange(caplog) -> None:
    with patch("backfill_sma.get_config", return_value=_mock_config()):
        with patch(
            "backfill_sma.load_tickers_from_db", return_value=_exchange_watchlist()
        ):
            with patch("backfill_sma.download_batch") as mock_download:
                assert main(["--country", "us", "--exchange", "Stockholm"]) == 1

    mock_download.assert_not_called()
    assert "available: NYSE, NasdaqGM, NasdaqGS" in caplog.text
