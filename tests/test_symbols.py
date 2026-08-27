from pathlib import Path

import pytest

from symbols import load_tickers, parse_symbols_arg


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


def test_parse_symbols_arg_uppercases_and_skips_blanks() -> None:
    assert parse_symbols_arg(" aapl, MSFT.ST ,,bbb.st ") == [
        "AAPL",
        "MSFT.ST",
        "BBB.ST",
    ]
