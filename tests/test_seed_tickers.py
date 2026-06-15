from unittest.mock import MagicMock, patch

import pytest

from seed_tickers import company_name_from_ticker, upsert_tickers


def test_company_name_from_ticker_prefers_long_name() -> None:
    mock_ticker = MagicMock()
    mock_ticker.info = {"longName": "Investor AB", "shortName": "Investor"}

    with patch("seed_tickers.yf.Ticker", return_value=mock_ticker):
        assert company_name_from_ticker("INVE-B.ST") == "Investor AB"


def test_company_name_from_ticker_falls_back_to_short_name() -> None:
    mock_ticker = MagicMock()
    mock_ticker.info = {"shortName": "Investor"}

    with patch("seed_tickers.yf.Ticker", return_value=mock_ticker):
        assert company_name_from_ticker("INVE-B.ST") == "Investor"


def test_company_name_from_ticker_returns_none_when_missing() -> None:
    mock_ticker = MagicMock()
    mock_ticker.info = {}

    with patch("seed_tickers.yf.Ticker", return_value=mock_ticker):
        assert company_name_from_ticker("UNKNOWN.ST") is None


def test_upsert_tickers_executes_values() -> None:
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    rows = [("AAA.ST", "Alpha AB"), ("BBB.ST", None)]

    with patch("seed_tickers.psycopg2.connect", return_value=mock_conn):
        with patch("seed_tickers.execute_values") as mock_execute:
            upsert_tickers("postgresql://example", rows)

    mock_execute.assert_called_once()
    mock_conn.commit.assert_called_once()
