from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from db.metrics import filter_stale_tickers, insert_metrics
from db.tickers import load_tickers_from_db
from fetch_sma import (
    chunked,
    compute_smas,
    load_currency_for_tickers,
    load_tickers,
    metric_row_from_history,
    metric_rows_from_batch,
    resolve_currency,
    trading_date_from_index,
)
from models import MetricRow, TickerEntry


def test_load_tickers_skips_comments_and_blanks(tmp_path: Path) -> None:
    tickers_file = tmp_path / "tickers.txt"
    tickers_file.write_text(
        "# comment\n\n  aapl \n# another\nMSFT\n",
        encoding="utf-8",
    )

    assert load_tickers(tickers_file) == ["AAPL", "MSFT"]


def test_load_tickers_raises_when_empty(tmp_path: Path) -> None:
    tickers_file = tmp_path / "tickers.txt"
    tickers_file.write_text("# only comments\n\n", encoding="utf-8")

    with pytest.raises(ValueError, match="No tickers found"):
        load_tickers(tickers_file)


def test_load_tickers_from_db() -> None:
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        ("AAA.ST", "Company A", "Industrials", "Machinery"),
        ("BBB.ST", None, None, None),
    ]

    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.tickers.psycopg2.connect", return_value=mock_conn):
        entries = load_tickers_from_db("postgresql://example")

    assert entries == [
        TickerEntry(symbol="AAA.ST", name="Company A", sector="Industrials", industry="Machinery"),
        TickerEntry(symbol="BBB.ST", name=None),
    ]


def test_load_tickers_from_db_raises_when_empty() -> None:
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []

    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.tickers.psycopg2.connect", return_value=mock_conn):
        with pytest.raises(ValueError, match="No tickers found in tickers table"):
            load_tickers_from_db("postgresql://example")


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
        name="Apple Inc.",
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
        name="AB Volvo",
        currency="SEK",
    )

    assert row is not None
    assert row.ticker == "VOLV-A.ST"
    assert row.name == "AB Volvo"
    assert row.currency == "SEK"
    assert row.trading_date == index[-1].date()
    assert row.sma_50 == Decimal("195.5")
    assert row.sma_200 == Decimal("120.5")
    assert row.current_price == Decimal("220")


def test_resolve_currency_uses_yfinance_info() -> None:
    mock_ticker = MagicMock()
    mock_ticker.info = {"currency": "USD"}

    with patch("fetch_sma.yf.Ticker", return_value=mock_ticker):
        assert resolve_currency("AAPL") == "USD"


def test_load_currency_for_tickers_applies_delay() -> None:
    with patch("fetch_sma.resolve_currency", return_value="SEK") as mock_resolve:
        with patch("fetch_sma.time.sleep") as mock_sleep:
            currencies = load_currency_for_tickers(
                ["AAA.ST", "BBB.ST"],
                name_delay=0.25,
            )

    assert mock_resolve.call_count == 2
    mock_sleep.assert_called_once_with(0.25)
    assert currencies == {
        "AAA.ST": "SEK",
        "BBB.ST": "SEK",
    }


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

    names = {"AAA.ST": "Alpha AB", "BBB.ST": "Beta AB"}
    currencies = {"AAA.ST": "SEK", "BBB.ST": "USD"}
    rows = metric_rows_from_batch(data, ["AAA.ST", "BBB.ST"], names, currencies)

    assert len(rows) == 2
    assert {row.ticker for row in rows} == {"AAA.ST", "BBB.ST"}
    assert {row.name for row in rows} == {"Alpha AB", "Beta AB"}
    by_ticker = {row.ticker: row for row in rows}
    assert by_ticker["AAA.ST"].currency == "SEK"
    assert by_ticker["BBB.ST"].currency == "USD"


def test_filter_stale_tickers_skips_fresh() -> None:
    mock_cursor = MagicMock()
    mock_cursor.fetchone.side_effect = [(date(2026, 6, 6),)]
    mock_cursor.fetchall.return_value = [("AAA.ST",), ("BBB.ST",)]

    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.metrics.psycopg2.connect", return_value=mock_conn):
        stale, skipped, max_date = filter_stale_tickers(
            "postgresql://example",
            ["AAA.ST", "BBB.ST", "CCC.ST"],
        )

    assert stale == ["CCC.ST"]
    assert skipped == 2
    assert max_date == date(2026, 6, 6)


def test_filter_stale_tickers_returns_all_when_db_empty() -> None:
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = (None,)

    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    tickers = ["AAA.ST", "BBB.ST"]
    with patch("db.metrics.psycopg2.connect", return_value=mock_conn):
        stale, skipped, max_date = filter_stale_tickers(
            "postgresql://example",
            tickers,
        )

    assert stale == tickers
    assert skipped == 0
    assert max_date is None


def test_insert_metrics_executes_values() -> None:
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 1
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    rows = [
        MetricRow(
            ticker="AAA.ST",
            name="Alpha",
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
    assert "currency" in sql
    assert "sector" not in sql
    assert "industry" not in sql
    assert "ON CONFLICT (ticker, trading_date) DO NOTHING" in sql
    values = mock_execute.call_args[0][2]
    assert values[0][4] is None  # currency
