from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from db.metrics import (
    current_week_start,
    expected_latest_bar,
    filter_stale_tickers,
    insert_metrics,
    load_momentum_by_market_for_week,
)
from db.tickers import load_tickers_from_db
from fetch_sma import (
    aggregate_market_stats,
    chunked,
    compute_momentum,
    compute_smas,
    compute_z_score,
    metric_row_from_history,
    metric_rows_from_batch,
    trading_date_from_index,
    upsert_market_for_weeks,
)
from models import MarketRow, MetricRow, TickerEntry

def test_load_tickers_from_db() -> None:
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        ("AAA.ST", "Company A", "Industrials", "Machinery", "se_market", "STO"),
        ("BBB.ST", None, None, None, None, None),
        ("VOD.L", "Vodafone", "communication-services", "telecom", "uk_market", "LSE"),
    ]

    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.tickers.psycopg2.connect", return_value=mock_conn):
        entries = load_tickers_from_db("postgresql://example")

    assert entries == [
        TickerEntry(
            symbol="AAA.ST",
            company="Company A",
            sector="Industrials",
            industry="Machinery",
            market="se_market",
            exchange_name="STO",
        ),
        TickerEntry(symbol="BBB.ST", company=None),
        TickerEntry(
            symbol="VOD.L",
            company="Vodafone",
            sector="communication-services",
            industry="telecom",
            market="uk_market",
            exchange_name="LSE",
        ),
    ]
    sql = mock_cursor.execute.call_args[0][0]
    assert "FROM uk_tickers" in sql
    assert "FROM us_tickers" in sql
    assert "FROM swe_tickers" in sql


def test_load_tickers_from_db_raises_when_empty() -> None:
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []

    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.tickers.psycopg2.connect", return_value=mock_conn):
        with pytest.raises(
            ValueError,
            match="No tickers found in us_tickers, swe_tickers, or uk_tickers",
        ):
            load_tickers_from_db("postgresql://example")


def test_load_tickers_from_db_scopes_to_country() -> None:
    from db.country import CountrySet

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        ("VOD.L", "Vodafone", None, None, "uk_market", "LSE"),
    ]
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.tickers.psycopg2.connect", return_value=mock_conn):
        entries = load_tickers_from_db("postgresql://example", country=CountrySet.UK)

    assert [e.symbol for e in entries] == ["VOD.L"]
    sql = mock_cursor.execute.call_args[0][0]
    assert "FROM uk_tickers" in sql
    assert "FROM us_tickers" not in sql
    assert "FROM swe_tickers" not in sql


def test_compute_momentum_divides_sma50_by_sma200() -> None:
    assert compute_momentum(Decimal("100"), Decimal("50")) == Decimal("2.0")


def test_compute_momentum_returns_none_when_inputs_missing_or_zero() -> None:
    assert compute_momentum(None, Decimal("2")) is None
    assert compute_momentum(Decimal("1"), None) is None
    assert compute_momentum(Decimal("1"), Decimal("0")) is None


def test_compute_z_score() -> None:
    assert compute_z_score(
        Decimal("1.2"), Decimal("1.0"), Decimal("0.2")
    ) == Decimal("1.0")
    assert compute_z_score(Decimal("1"), Decimal("1"), Decimal("0")) is None
    assert compute_z_score(None, Decimal("1"), Decimal("1")) is None


def test_aggregate_market_stats_uses_population_std() -> None:
    row = aggregate_market_stats(
        date(2026, 6, 1),
        "us_market",
        [Decimal("1"), Decimal("3")],
    )

    assert row == MarketRow(
        market="us_market",
        week_start=date(2026, 6, 1),
        momentum_mean=Decimal("2"),
        momentum_std=Decimal("1"),
    )


def test_aggregate_market_stats_returns_none_when_empty() -> None:
    assert aggregate_market_stats(date(2026, 6, 6), "us_market", []) is None


def test_load_momentum_by_market_for_week_groups_by_tickers_market() -> None:
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        ("us_market", Decimal("0.5")),
        ("us_market", Decimal("0.7")),
        ("se_market", Decimal("0.6")),
        ("uk_market", Decimal("0.8")),
        (None, Decimal("0.9")),
        ("us_market", None),
    ]
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.metrics.psycopg2.connect", return_value=mock_conn):
        grouped = load_momentum_by_market_for_week(
            "postgresql://example",
            date(2026, 6, 6),
        )

    sql = mock_cursor.execute.call_args[0][0]
    assert "JOIN us_tickers t ON t.symbol = m.ticker" in sql
    assert "JOIN swe_tickers t ON t.symbol = m.ticker" in sql
    assert "JOIN uk_tickers t ON t.symbol = m.ticker" in sql
    assert "m.momentum" in sql
    assert mock_cursor.execute.call_args[0][1] == (
        date(2026, 6, 6),
        date(2026, 6, 6),
        date(2026, 6, 6),
    )
    assert grouped == {
        "us_market": [Decimal("0.5"), Decimal("0.7")],
        "se_market": [Decimal("0.6")],
        "uk_market": [Decimal("0.8")],
        None: [Decimal("0.9")],
    }


def test_upsert_market_for_weeks_upserts_per_listing_market() -> None:
    week_start = date(2026, 6, 1)
    with patch(
        "fetch_sma.load_momentum_by_market_for_week",
        return_value={
            "us_market": [Decimal("1"), Decimal("3")],
            "se_market": [Decimal("0.6")],
            "uk_market": [Decimal("0.8")],
        },
    ):
        with patch("fetch_sma.upsert_market_stats") as mock_upsert:
            with patch("fetch_sma.update_z_scores_for_week") as mock_z:
                upsert_market_for_weeks(
                    "postgresql://example",
                    {week_start},
                )

    assert mock_upsert.call_count == 3
    mock_z.assert_called_once_with(
        "postgresql://example", week_start, country=None
    )
    rows_by_market = {
        call.args[1].market: call.args[1]
        for call in mock_upsert.call_args_list
    }
    us_row = rows_by_market["us_market"]
    se_row = rows_by_market["se_market"]
    uk_row = rows_by_market["uk_market"]
    assert us_row.week_start == week_start
    assert us_row.momentum_mean == Decimal("2")
    assert us_row.momentum_std == Decimal("1")
    assert se_row.market == "se_market"
    assert se_row.momentum_mean == Decimal("0.6")
    assert uk_row.market == "uk_market"
    assert uk_row.momentum_mean == Decimal("0.8")


def test_upsert_market_for_weeks_skips_null_market_bucket() -> None:
    with patch(
        "fetch_sma.load_momentum_by_market_for_week",
        return_value={
            None: [Decimal("0.9")],
            "se_market": [Decimal("0.6")],
        },
    ):
        with patch("fetch_sma.upsert_market_stats") as mock_upsert:
            with patch("fetch_sma.update_z_scores_for_week"):
                upsert_market_for_weeks(
                    "postgresql://example",
                    {date(2026, 6, 6)},
                )

    mock_upsert.assert_called_once()
    assert mock_upsert.call_args[0][1].market == "se_market"


def test_compute_smas_on_fixed_series() -> None:
    close = pd.Series(range(1, 201), dtype=float)
    sma_50, sma_200 = compute_smas(close)

    assert sma_50 == Decimal("175.5")
    assert sma_200 == Decimal("100.5")


def test_compute_smas_returns_none_for_empty_series() -> None:
    close = pd.Series(dtype=float)
    sma_50, sma_200 = compute_smas(close)

    assert sma_50 is None
    assert sma_200 is None


def test_trading_date_from_index() -> None:
    index = pd.to_datetime(["2026-06-01", "2026-06-05"])
    assert trading_date_from_index(index) == date(2026, 6, 5)


def test_metric_row_is_immutable() -> None:
    row = MetricRow(
        ticker="AAPL",
        company="Apple Inc.",
        trading_date=date(2026, 6, 5),
        sma_50=Decimal("100.0"),
        sma_200=Decimal("90.0"),
        current_price=Decimal("105.0"),
    )
    assert row.ticker == "AAPL"


def test_chunked_splits_evenly() -> None:
    assert chunked(["A", "B", "C", "D", "E"], 2) == [
        ["A", "B"],
        ["C", "D"],
        ["E"],
    ]
    assert chunked(["A"], 40) == [["A"]]
    assert chunked([], 40) == []


def test_metric_row_from_history() -> None:
    index = pd.date_range("2025-01-01", periods=220, freq="B")
    history = pd.DataFrame(
        {
            "Open": range(220),
            "High": range(220),
            "Low": range(220),
            "Close": range(1, 221),
            "Volume": [1000] * 220,
        },
        index=index,
    )

    row = metric_row_from_history(
        "VOLV-A.ST",
        history,
        company="AB Volvo",
        currency="SEK",
    )

    assert row is not None
    assert row.ticker == "VOLV-A.ST"
    assert row.company == "AB Volvo"
    assert row.currency == "SEK"
    assert row.trading_date == index[-1].date()
    assert row.sma_50 == Decimal("195.5")
    assert row.sma_200 == Decimal("120.5")
    assert row.current_price == Decimal("220")
    assert row.momentum == Decimal("1.622407")
    assert row.z_score is None

def test_metric_rows_from_batch_parses_multiindex() -> None:
    index = pd.date_range("2025-01-01", periods=220, freq="B")
    columns = pd.MultiIndex.from_product(
        [["AAA.ST", "BBB.ST"], ["Open", "High", "Low", "Close", "Volume"]]
    )
    data = pd.DataFrame(index=index, columns=columns, dtype=float)
    for field in ("Open", "High", "Low", "Close", "Volume"):
        data[("AAA.ST", field)] = 1.0
        data[("BBB.ST", field)] = 2.0
    data[("AAA.ST", "Close")] = range(1, 221)
    data[("BBB.ST", "Close")] = range(2, 222)

    companies = {"AAA.ST": "Alpha AB", "BBB.ST": "Beta AB"}
    currencies = {"AAA.ST": "SEK", "BBB.ST": "USD"}
    rows = metric_rows_from_batch(data, ["AAA.ST", "BBB.ST"], companies, currencies)

    assert len(rows) == 2
    assert {row.ticker for row in rows} == {"AAA.ST", "BBB.ST"}
    assert {row.company for row in rows} == {"Alpha AB", "Beta AB"}
    by_ticker = {row.ticker: row for row in rows}
    assert by_ticker["AAA.ST"].currency == "SEK"
    assert by_ticker["BBB.ST"].currency == "USD"


def _mock_metrics_conn(mock_cursor: MagicMock) -> MagicMock:
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    return mock_conn


def test_current_week_start_returns_monday() -> None:
    assert current_week_start(today=date(2026, 9, 24)) == date(2026, 9, 21)  # Thu
    assert current_week_start(today=date(2026, 9, 21)) == date(2026, 9, 21)  # Mon
    assert current_week_start(today=date(2026, 9, 27)) == date(2026, 9, 21)  # Sun


def test_expected_latest_bar_is_friday_on_weekends() -> None:
    assert expected_latest_bar(today=date(2026, 9, 26)) == date(2026, 9, 25)  # Sat
    assert expected_latest_bar(today=date(2026, 9, 27)) == date(2026, 9, 25)  # Sun
    assert expected_latest_bar(today=date(2026, 9, 24)) == date(2026, 9, 24)  # Thu


def test_filter_stale_tickers_skips_tickers_with_row_this_week() -> None:
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [("AAA.ST",), ("BBB.ST",)]

    with patch(
        "db.metrics.psycopg2.connect", return_value=_mock_metrics_conn(mock_cursor)
    ):
        stale, skipped, week_start = filter_stale_tickers(
            "postgresql://example",
            ["AAA.ST", "BBB.ST", "CCC.ST"],
            today=date(2026, 9, 24),
        )

    assert stale == ["CCC.ST"]
    assert skipped == 2
    assert week_start == date(2026, 9, 21)
    mock_cursor.execute.assert_called_once()
    sql, params = mock_cursor.execute.call_args[0]
    assert "FROM swe_metrics" in sql
    assert "week_start = %s" in sql
    assert "trading_date >= %s" in sql
    assert params == (
        ["AAA.ST", "BBB.ST", "CCC.ST"],
        date(2026, 9, 21),
        date(2026, 9, 24),
    )


def test_filter_stale_tickers_refetches_when_whole_table_is_behind() -> None:
    """Rows from a previous week are stale even if every ticker shares that date."""
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []

    tickers = ["AAPL", "MSFT"]
    with patch(
        "db.metrics.psycopg2.connect", return_value=_mock_metrics_conn(mock_cursor)
    ):
        stale, skipped, _week_start = filter_stale_tickers(
            "postgresql://example",
            tickers,
            today=date(2026, 9, 24),
        )

    assert stale == tickers
    assert skipped == 0


def test_filter_stale_tickers_evaluates_each_country_table() -> None:
    mock_cursor = MagicMock()
    # First-seen order: US, SWE, UK.
    mock_cursor.fetchall.side_effect = [
        [("AAPL",)],
        [("VOLV-B.ST",)],
        [("VOD.L",)],
    ]

    with patch(
        "db.metrics.psycopg2.connect", return_value=_mock_metrics_conn(mock_cursor)
    ):
        stale, skipped, _week_start = filter_stale_tickers(
            "postgresql://example",
            ["AAPL", "MSFT", "VOLV-B.ST", "ERIC-B.ST", "VOD.L", "BP.L"],
            today=date(2026, 9, 24),
        )

    assert stale == ["MSFT", "ERIC-B.ST", "BP.L"]
    assert skipped == 3
    calls = mock_cursor.execute.call_args_list
    assert "FROM us_metrics" in calls[0][0][0]
    week = (date(2026, 9, 21), date(2026, 9, 24))
    assert calls[0][0][1] == (["AAPL", "MSFT"], *week)
    assert "FROM swe_metrics" in calls[1][0][0]
    assert calls[1][0][1] == (["VOLV-B.ST", "ERIC-B.ST"], *week)
    assert "FROM uk_metrics" in calls[2][0][0]
    assert calls[2][0][1] == (["VOD.L", "BP.L"], *week)


def test_insert_metrics_executes_values() -> None:
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 1
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    rows = [
        MetricRow(
            ticker="AAA.ST",
            company="Alpha",
            trading_date=date(2026, 6, 6),
            sma_50=Decimal("1"),
            sma_200=Decimal("2"),
            current_price=Decimal("3"),
        )
    ]

    with patch("db.metrics.psycopg2.connect", return_value=mock_conn):
        with patch("db.metrics.execute_values") as mock_execute:
            inserted = insert_metrics("postgresql://example", rows)

    mock_execute.assert_called_once()
    mock_conn.commit.assert_called_once()
    assert inserted == 1
    sql = mock_execute.call_args[0][1]
    assert "company" in sql
    assert "currency" in sql
    assert "momentum" in sql
    assert "z_score" in sql
    assert "raw_50" not in sql
    assert "raw_200" not in sql
    assert "sector" not in sql
    assert "industry" not in sql
    assert "ON CONFLICT (ticker, week_start) DO UPDATE" in sql
    assert "WHERE EXCLUDED.trading_date > swe_metrics.trading_date" in sql
    values = mock_execute.call_args[0][2]
    assert values[0][1] == "Alpha"  # company
    assert values[0][2] == date(2026, 6, 1)  # week_start
    assert values[0][3] == date(2026, 6, 6)  # trading_date
    assert values[0][5] is None  # currency


def test_insert_metrics_routes_uk_ticker_to_uk_metrics() -> None:
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 1
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    rows = [
        MetricRow(
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
    ]
    with patch("db.metrics.psycopg2.connect", return_value=mock_conn):
        with patch("db.metrics.execute_values") as mock_execute:
            inserted = insert_metrics("postgresql://example", rows)

    mock_execute.assert_called_once()
    assert inserted == 1
    sql = mock_execute.call_args[0][1]
    assert "INSERT INTO uk_metrics" in sql
    assert "INSERT INTO us_metrics" not in sql
    assert "INSERT INTO swe_metrics" not in sql
    assert "ON CONFLICT (ticker, week_start) DO UPDATE" in sql
    values = mock_execute.call_args[0][2]
    assert values[0][0] == "VOD.L"
    assert values[0][1] == "Vodafone"
    assert values[0][5] == "GBp"
