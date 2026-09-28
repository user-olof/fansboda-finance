from unittest.mock import MagicMock, patch

from db.country import CountrySet
from db.tickers import (
    UPDATE_BUSINESS_SUMMARY_SQL,
    UPSERT_TICKER_SQL,
    update_business_summaries,
    upsert_tickers,
)
from models import TickerEntry
from seed_tickers import (
    build_parser,
    filter_symbols_for_country,
    main,
    resolve_and_upsert_symbols,
    seed_tickers_from_file,
    update_business_summaries_from_db,
)


def test_upsert_tickers_routes_to_country_tables() -> None:
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 1
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    rows = [
        ("AAPL", "Apple Inc.", "technology", "consumer-electronics", "us_market", "NasdaqGS", None),
        ("AAA.ST", "Alpha AB", "Industrials", "Machinery", "se_market", "STO", None),
        ("VOD.L", "Vodafone", "communication-services", "telecom", "uk_market", "LSE", None),
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
    assert "business_summary = EXCLUDED.business_summary" in UPSERT_TICKER_SQL[
        CountrySet.US
    ]
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
                None,
            ),
            ("Alpha AB", "Industrials", "Machinery", "se_market", "STO", None),
            (
                "Vodafone",
                "communication-services",
                "telecom",
                "uk_market",
                "LSE",
                None,
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
                None,
            ),
            ("AAA.ST", "Alpha AB", "Industrials", "Machinery", "se_market", "STO", None),
            (
                "VOD.L",
                "Vodafone",
                "communication-services",
                "telecom",
                "uk_market",
                "LSE",
                None,
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
                None,
            ),
            ("Alpha AB", "Industrials", "Machinery", "se_market", "STO", None),
            (
                "Vodafone",
                "communication-services",
                "telecom",
                "uk_market",
                "LSE",
                None,
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
                None,
            ),
            ("AAA.ST", "Alpha AB", "Industrials", "Machinery", "se_market", "STO", None),
            (
                "VOD.L",
                "Vodafone",
                "communication-services",
                "telecom",
                "uk_market",
                "LSE",
                None,
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
            ("AAA.ST", None, None, None, "se_market", None, None),
            ("AAPL", None, None, None, "us_market", None, None),
            ("VOD.L", None, None, None, "uk_market", None, None),
        ],
    )


def test_filter_symbols_for_country() -> None:
    symbols = ["AAPL", "AAA.ST", "VOD.L", "MSFT"]
    assert filter_symbols_for_country(symbols, None) == symbols
    assert filter_symbols_for_country(symbols, CountrySet.US) == ["AAPL", "MSFT"]
    assert filter_symbols_for_country(symbols, CountrySet.SWE) == ["AAA.ST"]
    assert filter_symbols_for_country(symbols, CountrySet.UK) == ["VOD.L"]


def test_resolve_and_upsert_symbols_filters_by_country() -> None:
    with patch(
        "seed_tickers.resolve_watchlist_fields",
        return_value=(
            "Vodafone",
            "communication-services",
            "telecom",
            "uk_market",
            "LSE",
            None,
        ),
    ) as mock_resolve:
        with patch("seed_tickers.time.sleep") as mock_sleep:
            with patch("seed_tickers.upsert_tickers", return_value=1) as mock_upsert:
                count = resolve_and_upsert_symbols(
                    "postgresql://example",
                    ["AAPL", "AAA.ST", "VOD.L"],
                    name_delay=0.25,
                    country=CountrySet.UK,
                )

    assert count == 1
    mock_resolve.assert_called_once_with("VOD.L")
    mock_sleep.assert_not_called()
    mock_upsert.assert_called_once_with(
        "postgresql://example",
        [
            (
                "VOD.L",
                "Vodafone",
                "communication-services",
                "telecom",
                "uk_market",
                "LSE",
                None,
            ),
        ],
    )


def test_seed_tickers_from_file_filters_by_country(tmp_path) -> None:
    tickers_file = tmp_path / "tickers.txt"
    tickers_file.write_text("aapl\naaa.st\nvod.l\n", encoding="utf-8")

    with patch(
        "seed_tickers.resolve_watchlist_fields",
        return_value=("Alpha AB", "Industrials", "Machinery", "se_market", "STO", None),
    ) as mock_resolve:
        with patch("seed_tickers.time.sleep"):
            with patch("seed_tickers.upsert_tickers", return_value=1) as mock_upsert:
                count = seed_tickers_from_file(
                    "postgresql://example",
                    tickers_file,
                    country=CountrySet.SWE,
                )

    assert count == 1
    mock_resolve.assert_called_once_with("AAA.ST")
    mock_upsert.assert_called_once_with(
        "postgresql://example",
        [("AAA.ST", "Alpha AB", "Industrials", "Machinery", "se_market", "STO", None)],
    )


def test_build_parser_accepts_country_and_optional_file() -> None:
    parser = build_parser()
    args = parser.parse_args(["--country", "uk", "all-tickers.txt"])
    assert args.country == "uk"
    assert args.tickers_file == "all-tickers.txt"

    args_default = parser.parse_args([])
    assert args_default.country is None
    assert args_default.tickers_file is None


def test_update_business_summaries_routes_to_country_tables() -> None:
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 1
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    summaries = [
        (TickerEntry(symbol="AAPL", company=None, market="us_market"), "Apple."),
        (TickerEntry(symbol="VOD.L", company=None, market="uk_market"), None),
    ]
    with patch("db.tickers.psycopg2.connect", return_value=mock_conn):
        updated = update_business_summaries("postgresql://example", summaries)

    assert updated == 2
    calls = mock_cursor.execute.call_args_list
    assert calls[0].args == (UPDATE_BUSINESS_SUMMARY_SQL[CountrySet.US], ("Apple.", "AAPL"))
    assert calls[1].args == (UPDATE_BUSINESS_SUMMARY_SQL[CountrySet.UK], (None, "VOD.L"))
    assert "UPDATE uk_tickers" in UPDATE_BUSINESS_SUMMARY_SQL[CountrySet.UK]
    assert "SET business_summary = %s" in UPDATE_BUSINESS_SUMMARY_SQL[CountrySet.UK]
    mock_conn.commit.assert_called_once()


def test_update_business_summaries_returns_zero_for_empty_input() -> None:
    with patch("db.tickers.psycopg2.connect") as mock_connect:
        assert update_business_summaries("postgresql://example", []) == 0
    mock_connect.assert_not_called()


def test_update_business_summaries_from_db_skips_failed_lookups() -> None:
    entries = [
        TickerEntry(symbol="AAPL", company="Apple", market="us_market"),
        TickerEntry(symbol="MSFT", company="Microsoft", market="us_market"),
        TickerEntry(symbol="GONE", company="Gone", market="us_market"),
    ]
    with patch("seed_tickers.load_tickers_from_db", return_value=entries) as mock_load:
        with patch(
            "seed_tickers.resolve_business_summary",
            side_effect=["Apple designs.", None, RuntimeError("404")],
        ):
            with patch("seed_tickers.time.sleep") as mock_sleep:
                with patch(
                    "seed_tickers.update_business_summaries", return_value=2
                ) as mock_update:
                    updated, failed = update_business_summaries_from_db(
                        "postgresql://example",
                        name_delay=0.25,
                        country=CountrySet.US,
                    )

    assert (updated, failed) == (2, 1)
    mock_load.assert_called_once_with("postgresql://example", country=CountrySet.US)
    assert mock_sleep.call_count == 2
    mock_update.assert_called_once_with(
        "postgresql://example",
        [(entries[0], "Apple designs."), (entries[1], None)],
    )


def test_main_update_business_summary_mode_skips_symbol_file() -> None:
    mock_config = MagicMock(database_url="postgresql://example", yf_name_delay_seconds=0.25)
    with patch("seed_tickers.get_config", return_value=mock_config):
        with patch(
            "seed_tickers.update_business_summaries_from_db", return_value=(3, 0)
        ) as mock_update:
            with patch("seed_tickers.seed_tickers_from_file") as mock_seed:
                assert main(["--update-business-summary", "--country", "swe"]) == 0

    mock_update.assert_called_once_with(
        "postgresql://example", name_delay=0.25, country=CountrySet.SWE
    )
    mock_seed.assert_not_called()


def test_build_parser_update_business_summary_flag_defaults_off() -> None:
    parser = build_parser()
    assert parser.parse_args([]).update_business_summary is False
    assert parser.parse_args(["--update-business-summary"]).update_business_summary
