from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from fetch_sma import (
    MetricRow,
    compute_smas,
    load_tickers,
    trading_date_from_index,
)


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
        trading_date=date(2026, 6, 5),
        sma_50=Decimal("100.0"),
        sma_200=Decimal("90.0"),
    )
    assert row.ticker == "AAPL"
