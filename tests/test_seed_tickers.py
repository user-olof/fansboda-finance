from unittest.mock import MagicMock, patch

from db.country import CountrySet
from db.tickers import UPSERT_TICKER_SQL, upsert_tickers
from seed_tickers import resolve_and_upsert_symbols, seed_tickers_from_file


def test_upsert_tickers_routes_to_country_tables() -> None:
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 1
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    rows = [
        ("AAPL", "Apple Inc.", "technology", "consumer-electronics", "us_market", "NasdaqGS"),
        ("AAA.ST", "Alpha AB", "Industrials", "Machinery", "se_market", "STO"),
        ("VOD.L", "Vodafone", "communication-services", "telecom", "uk_market", "LSE"),
    ]

    with patch("db.tickers.psycopg2.connect", return_value=mock_conn):
        with patch("db.tickers.execute_values") as mock_execute:
            affected = upsert_tickers("postgresql://example", rows)

    assert mock_execute.call_count == 3
    sqls = {call_args.args[1] for call_args in mock_execute.call_args_list}
    assert UPSERT_TICKER_SQL[CountrySet.US] in sqls
    assert UPSERT_TICKER_SQL[CountrySet.SWE] in sqls
    assert UPSERT_TICKER_SQL[CountrySet.UK] in sqls
    assert "INSERT INTO us_tickers" in UPSERT_TICKER_SQL[CountrySet.US]
    assert "INSERT INTO swe_tickers" in UPSERT_TICKER_SQL[CountrySet.SWE]
    assert "INSERT INTO uk_tickers" in UPSERT_TICKER_SQL[CountrySet.UK]
    assert "exchange_name" in UPSERT_TICKER_SQL[CountrySet.US]
    mock_conn.commit.assert_called_once()
    assert affected == 3


def test_upsert_tickers_returns_zero_for_empty_rows() -> None:
    with patch("db.tickers.psycopg2.connect") as mock_connect:
        assert upsert_tickers("postgresql://example", []) == 0
    mock_connect.assert_not_called()


def test_resolve_and_upsert_symbols_resolves_market_and_upserts() -> None:
    with patch(
        "seed_tickers.resolve_watchlist_fields",
        side_effect=[
            (
                "Apple Inc.",
                "technology",
                "consumer-electronics",
                "us_market",
                "NasdaqGS",
            ),
            ("Alpha AB", "Industrials", "Machinery", "se_market", "STO"),
            (
                "Vodafone",
                "communication-services",
                "telecom",
                "uk_market",
                "LSE",
            ),
        ],
    ):
        with patch("seed_tickers.time.sleep") as mock_sleep:
            with patch("seed_tickers.upsert_tickers", return_value=3) as mock_upsert:
                count = resolve_and_upsert_symbols(
                    "postgresql://example",
                    ["AAPL", "AAA.ST", "VOD.L"],
                    name_delay=0.25,
                )

    assert count == 3
    assert mock_sleep.call_count == 2
    mock_upsert.assert_called_once_with(
        "postgresql://example",
        [
            (
                "AAPL",
                "Apple Inc.",
                "technology",
                "consumer-electronics",
                "us_market",
                "NasdaqGS",
            ),
            ("AAA.ST", "Alpha AB", "Industrials", "Machinery", "se_market", "STO"),
            (
                "VOD.L",
                "Vodafone",
                "communication-services",
                "telecom",
                "uk_market",
                "LSE",
            ),
        ],
    )


def test_seed_tickers_from_file_resolves_and_upserts(tmp_path) -> None:
    tickers_file = tmp_path / "tickers.txt"
    tickers_file.write_text(
        "aapl\n# comment\n\naaa.st\nvod.l\n", encoding="utf-8"
    )

    with patch(
        "seed_tickers.resolve_watchlist_fields",
        side_effect=[
            (
                "Apple Inc.",
                "technology",
                "consumer-electronics",
                "us_market",
                "NasdaqGS",
            ),
            ("Alpha AB", "Industrials", "Machinery", "se_market", "STO"),
            (
                "Vodafone",
                "communication-services",
                "telecom",
                "uk_market",
                "LSE",
            ),
        ],
    ):
        with patch("seed_tickers.time.sleep") as mock_sleep:
            with patch("seed_tickers.upsert_tickers", return_value=3) as mock_upsert:
                count = seed_tickers_from_file(
                    "postgresql://example",
                    tickers_file,
                    name_delay=0.25,
                )

    assert count == 3
    assert mock_sleep.call_count == 2
    mock_upsert.assert_called_once_with(
        "postgresql://example",
        [
            (
                "AAPL",
                "Apple Inc.",
                "technology",
                "consumer-electronics",
                "us_market",
                "NasdaqGS",
            ),
            ("AAA.ST", "Alpha AB", "Industrials", "Machinery", "se_market", "STO"),
            (
                "VOD.L",
                "Vodafone",
                "communication-services",
                "telecom",
                "uk_market",
                "LSE",
            ),
        ],
    )


def test_seed_tickers_from_file_infers_market_on_resolve_failure(tmp_path) -> None:
    tickers_file = tmp_path / "tickers.txt"
    tickers_file.write_text("aaa.st\naapl\nvod.l\n", encoding="utf-8")

    with patch("seed_tickers.resolve_watchlist_fields", side_effect=RuntimeError("boom")):
        with patch("seed_tickers.time.sleep"):
            with patch("seed_tickers.upsert_tickers", return_value=3) as mock_upsert:
                count = seed_tickers_from_file("postgresql://example", tickers_file)

    assert count == 3
    mock_upsert.assert_called_once_with(
        "postgresql://example",
        [
            ("AAA.ST", None, None, None, "se_market", None),
            ("AAPL", None, None, None, "us_market", None),
            ("VOD.L", None, None, None, "uk_market", None),
        ],
    )
