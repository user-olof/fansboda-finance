from unittest.mock import MagicMock, patch

from yfinance_client import (
    load_currency_for_tickers,
    resolve_currency,
    resolve_metadata,
    resolve_name,
    resolve_watchlist_fields,
)


def test_resolve_name_prefers_long_name() -> None:
    mock_ticker = MagicMock()
    mock_ticker.info = {"longName": "Investor AB", "shortName": "Investor"}

    with patch("yfinance_client.yf.Ticker", return_value=mock_ticker):
        assert resolve_name("INVE-B.ST") == "Investor AB"


def test_resolve_name_falls_back_to_short_name() -> None:
    mock_ticker = MagicMock()
    mock_ticker.info = {"shortName": "Investor"}

    with patch("yfinance_client.yf.Ticker", return_value=mock_ticker):
        assert resolve_name("INVE-B.ST") == "Investor"


def test_resolve_name_returns_none_when_missing() -> None:
    mock_ticker = MagicMock()
    mock_ticker.info = {}

    with patch("yfinance_client.yf.Ticker", return_value=mock_ticker):
        assert resolve_name("UNKNOWN.ST") is None


def test_resolve_metadata_uses_yfinance_keys() -> None:
    mock_ticker = MagicMock()
    mock_ticker.info = {
        "sectorKey": "technology",
        "industryKey": "consumer-electronics",
    }

    with patch("yfinance_client.yf.Ticker", return_value=mock_ticker):
        assert resolve_metadata("AAPL") == (
            "technology",
            "consumer-electronics",
        )


def test_resolve_metadata_falls_back_to_sector_and_industry() -> None:
    mock_ticker = MagicMock()
    mock_ticker.info = {
        "sector": "Industrials",
        "industry": "Farm & Heavy Construction Machinery",
    }

    with patch("yfinance_client.yf.Ticker", return_value=mock_ticker):
        assert resolve_metadata("VOLV-A.ST") == (
            "Industrials",
            "Farm & Heavy Construction Machinery",
        )


def test_resolve_watchlist_fields_uses_single_yfinance_lookup() -> None:
    mock_ticker = MagicMock()
    mock_ticker.info = {
        "longName": "Apple Inc.",
        "sectorKey": "technology",
        "industryKey": "consumer-electronics",
        "market": "us_market",
        "fullExchangeName": "NasdaqGS",
    }

    with patch("yfinance_client.yf.Ticker", return_value=mock_ticker) as mock_ctor:
        assert resolve_watchlist_fields("AAPL") == (
            "Apple Inc.",
            "technology",
            "consumer-electronics",
            "us_market",
            "NasdaqGS",
        )

    mock_ctor.assert_called_once_with("AAPL")


def test_resolve_watchlist_fields_infers_us_market_when_missing(caplog) -> None:
    mock_ticker = MagicMock()
    mock_ticker.info = {
        "longName": "Unknown Co",
        "sectorKey": "technology",
        "industryKey": "software",
    }

    with patch("yfinance_client.yf.Ticker", return_value=mock_ticker):
        assert resolve_watchlist_fields("UNKNOWN") == (
            "Unknown Co",
            "technology",
            "software",
            "us_market",
            None,
        )

    assert "No listing market found for UNKNOWN; inferring us_market" in caplog.text


def test_resolve_watchlist_fields_infers_se_market_for_st_suffix(caplog) -> None:
    mock_ticker = MagicMock()
    mock_ticker.info = {
        "longName": "Alpha AB",
        "sectorKey": "industrials",
        "industryKey": "machinery",
    }

    with patch("yfinance_client.yf.Ticker", return_value=mock_ticker):
        assert resolve_watchlist_fields("AAA.ST") == (
            "Alpha AB",
            "industrials",
            "machinery",
            "se_market",
            None,
        )

    assert "No listing market found for AAA.ST; inferring se_market" in caplog.text


def test_resolve_watchlist_fields_infers_uk_market_for_l_suffix(caplog) -> None:
    mock_ticker = MagicMock()
    mock_ticker.info = {
        "longName": "Vodafone Group",
        "sectorKey": "communication-services",
        "industryKey": "telecom",
        "fullExchangeName": "LSE",
    }

    with patch("yfinance_client.yf.Ticker", return_value=mock_ticker):
        assert resolve_watchlist_fields("VOD.L") == (
            "Vodafone Group",
            "communication-services",
            "telecom",
            "uk_market",
            "LSE",
        )

    assert "No listing market found for VOD.L; inferring uk_market" in caplog.text


def test_resolve_watchlist_fields_exchange_name_none_when_missing() -> None:
    mock_ticker = MagicMock()
    mock_ticker.info = {
        "longName": "Apple Inc.",
        "sectorKey": "technology",
        "industryKey": "consumer-electronics",
        "market": "us_market",
    }

    with patch("yfinance_client.yf.Ticker", return_value=mock_ticker):
        assert resolve_watchlist_fields("AAPL") == (
            "Apple Inc.",
            "technology",
            "consumer-electronics",
            "us_market",
            None,
        )


def test_resolve_currency_uses_yfinance_info() -> None:
    mock_ticker = MagicMock()
    mock_ticker.info = {"currency": "USD"}

    with patch("yfinance_client.yf.Ticker", return_value=mock_ticker):
        assert resolve_currency("AAPL") == "USD"


def test_load_currency_for_tickers_applies_delay() -> None:
    with patch(
        "yfinance_client.resolve_currency", return_value="SEK"
    ) as mock_resolve:
        with patch("yfinance_client.time.sleep") as mock_sleep:
            currencies = load_currency_for_tickers(
                ["AAA.ST", "BBB.ST"],
                name_delay=0.25,
            )

    assert currencies == {"AAA.ST": "SEK", "BBB.ST": "SEK"}
    mock_resolve.assert_any_call("AAA.ST")
    mock_resolve.assert_any_call("BBB.ST")
    mock_sleep.assert_called_once_with(0.25)


def test_load_currency_for_tickers_records_none_on_failure() -> None:
    with patch(
        "yfinance_client.resolve_currency",
        side_effect=RuntimeError("boom"),
    ):
        with patch("yfinance_client.time.sleep"):
            currencies = load_currency_for_tickers(["AAA.ST"], name_delay=0.25)

    assert currencies == {"AAA.ST": None}
