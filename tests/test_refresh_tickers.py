from pathlib import Path
from unittest.mock import patch

import pytest

from refresh_tickers import (
    load_symbols_for_refresh,
    main,
    refresh_tickers,
)


def test_load_symbols_for_refresh_from_explicit_list() -> None:
    symbols = load_symbols_for_refresh(
        "postgresql://example",
        tickers_path=Path("unused.txt"),
        symbols=["aaa.st", "BBB.ST"],
    )
    assert symbols == ["AAA.ST", "BBB.ST"]


def test_load_symbols_for_refresh_from_db() -> None:
    with patch(
        "refresh_tickers._load_db_symbols",
        return_value=["AAA.ST", "BBB.ST"],
    ):
        symbols = load_symbols_for_refresh(
            "postgresql://example",
            tickers_path=Path("tickers.txt"),
            from_db=True,
        )

    assert symbols == ["AAA.ST", "BBB.ST"]


def test_load_symbols_for_refresh_merges_file_and_db() -> None:
    with patch(
        "refresh_tickers._load_file_symbols",
        return_value=["AAA.ST", "CCC.ST"],
    ):
        with patch(
            "refresh_tickers._load_db_symbols",
            return_value=["BBB.ST", "CCC.ST"],
        ):
            symbols = load_symbols_for_refresh(
                "postgresql://example",
                tickers_path=Path("tickers.txt"),
            )

    assert symbols == ["AAA.ST", "BBB.ST", "CCC.ST"]


def test_load_symbols_for_refresh_from_db_raises_when_empty() -> None:
    with patch("refresh_tickers._load_db_symbols", return_value=[]):
        with pytest.raises(
            ValueError, match="No tickers found in us_tickers or swe_tickers"
        ):
            load_symbols_for_refresh(
                "postgresql://example",
                tickers_path=Path("tickers.txt"),
                from_db=True,
            )


def test_load_symbols_for_refresh_raises_when_empty() -> None:
    with patch("refresh_tickers._load_file_symbols", return_value=[]):
        with patch("refresh_tickers._load_db_symbols", return_value=[]):
            with pytest.raises(ValueError, match="No tickers to refresh"):
                load_symbols_for_refresh(
                    "postgresql://example",
                    tickers_path=Path("tickers.txt"),
                )


def test_load_db_symbols_uses_country_tickers_loader() -> None:
    from models import TickerEntry
    from refresh_tickers import _load_db_symbols

    with patch(
        "refresh_tickers.load_tickers_from_db",
        return_value=[
            TickerEntry("AAPL", "Apple", "technology", "consumer-electronics", "us_market"),
            TickerEntry("VOLV-A.ST", "Volvo", "consumer-cyclical", "auto-manufacturers", "se_market"),
        ],
    ) as mock_load:
        assert _load_db_symbols("postgresql://example") == ["AAPL", "VOLV-A.ST"]

    mock_load.assert_called_once_with("postgresql://example")


def test_refresh_tickers_delegates_to_seed_upsert() -> None:
    with patch(
        "refresh_tickers.resolve_and_upsert_symbols",
        return_value=2,
    ) as mock_upsert:
        count = refresh_tickers(
            "postgresql://example",
            ["AAA.ST", "BBB.ST"],
            name_delay=0.25,
        )

    assert count == 2
    mock_upsert.assert_called_once_with(
        "postgresql://example",
        ["AAA.ST", "BBB.ST"],
        name_delay=0.25,
    )


def test_main_refresh_from_db() -> None:
    mock_config = type(
        "Cfg",
        (),
        {
            "database_url": "postgresql://example",
            "tickers_file": Path("tickers.txt"),
            "yf_name_delay_seconds": 0.25,
        },
    )()

    with patch("refresh_tickers.get_config", return_value=mock_config):
        with patch(
            "refresh_tickers.load_symbols_for_refresh",
            return_value=["AAA.ST"],
        ) as mock_load:
            with patch(
                "refresh_tickers.refresh_tickers", return_value=1
            ) as mock_refresh:
                assert main(["--from-db"]) == 0

    mock_load.assert_called_once()
    assert mock_load.call_args.kwargs["from_db"] is True
    mock_refresh.assert_called_once()


def test_main_refresh_symbols_subset() -> None:
    mock_config = type(
        "Cfg",
        (),
        {
            "database_url": "postgresql://example",
            "tickers_file": Path("tickers.txt"),
            "yf_name_delay_seconds": 0.25,
        },
    )()

    with patch("refresh_tickers.get_config", return_value=mock_config):
        with patch(
            "refresh_tickers.load_symbols_for_refresh",
            return_value=["AAPL", "MSFT"],
        ) as mock_load:
            with patch("refresh_tickers.refresh_tickers", return_value=2):
                assert main(["--symbols", "AAPL,MSFT"]) == 0

    assert mock_load.call_args.kwargs["symbols"] == ["AAPL", "MSFT"]


def test_main_refresh_resolves_listing_market() -> None:
    mock_config = type(
        "Cfg",
        (),
        {
            "database_url": "postgresql://example",
            "tickers_file": Path("tickers.txt"),
            "yf_name_delay_seconds": 0.25,
        },
    )()

    with patch("refresh_tickers.get_config", return_value=mock_config):
        with patch(
            "refresh_tickers.load_symbols_for_refresh",
            return_value=["AAPL"],
        ):
            with patch(
                "seed_tickers.resolve_watchlist_fields",
                return_value=(
                    "Apple Inc.",
                    "technology",
                    "consumer-electronics",
                    "us_market",
                ),
            ):
                with patch("seed_tickers.upsert_tickers", return_value=1) as mock_upsert:
                    assert main(["--symbols", "AAPL"]) == 0

    mock_upsert.assert_called_once_with(
        "postgresql://example",
        [("AAPL", "Apple Inc.", "technology", "consumer-electronics", "us_market")],
    )


def test_main_rejects_from_db_and_symbols_together() -> None:
    with pytest.raises(SystemExit):
        main(["--from-db", "--symbols", "AAPL"])
