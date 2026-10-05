"""Tests for PRD FR-5a / FR-15a / FR-16 weekly growth columns (RFC-016)."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from backfill_sma import filter_existing_rows, main, metric_rows_from_weekly_samples
from config import BaseConfig
from db.country import CountrySet
from db.metrics import (
    FILL_MISSING_GROWTH_SQL,
    INSERT_METRICS_SQL,
    _metric_values,
    fill_missing_growth,
)
from fetch_sma import (
    compute_weekly_growth,
    metric_row_from_history,
    previous_week_bar_position,
)
from models import MetricRow, TickerEntry


def _row(trading_date: date, **growth: Decimal | None) -> MetricRow:
    return MetricRow(
        ticker="AAA.ST",
        company="Alpha",
        trading_date=trading_date,
        sma_50=Decimal("1"),
        sma_200=Decimal("2"),
        current_price=Decimal("3"),
        **growth,
    )


def _history(closes: list[float], start: str = "2024-01-01") -> pd.DataFrame:
    index = pd.date_range(start, periods=len(closes), freq="B")
    return pd.DataFrame({"Close": closes}, index=index)


def test_previous_week_bar_position_finds_last_bar_of_prior_week() -> None:
    # Fri 2024-01-12 is missing (holiday): previous week's last bar is Thursday.
    index = pd.to_datetime(
        ["2024-01-08", "2024-01-09", "2024-01-11", "2024-01-15", "2024-01-17"]
    )
    assert previous_week_bar_position(index, 4) == 2
    assert previous_week_bar_position(index, 3) == 2


def test_previous_week_bar_position_none_when_prior_week_missing() -> None:
    # Week of 2024-01-08 has no bars at all.
    index = pd.to_datetime(["2024-01-05", "2024-01-15"])
    assert previous_week_bar_position(index, 1) is None
    assert previous_week_bar_position(index, 0) is None


def test_compute_weekly_growth_against_previous_week_bar() -> None:
    closes = [100.0] * 205 + [110.0] * 5
    close = _history(closes)["Close"]
    price, sma_50, sma_200 = compute_weekly_growth(close, len(close) - 1)

    assert price == Decimal("0.1")
    # SMA-50 moves from 100 to (45 * 100 + 5 * 110) / 50 = 101.
    assert sma_50 == Decimal("0.01")
    # SMA-200 moves from 100 to (195 * 100 + 5 * 110) / 200 = 100.25.
    assert sma_200 == Decimal("0.0025")


def test_compute_weekly_growth_sma_200_null_without_enough_history() -> None:
    close = _history([100.0] * 195 + [105.0] * 5)["Close"]
    price, sma_50, sma_200 = compute_weekly_growth(close, len(close) - 1)

    assert price == Decimal("0.05")
    assert sma_50 is not None
    assert sma_200 is None  # only 195 closes up to the previous-week bar


def test_compute_weekly_growth_zero_previous_close_is_null() -> None:
    close = _history([1.0] * 204 + [0.0] + [1.0] * 5)["Close"]
    price, _, _ = compute_weekly_growth(close, len(close) - 1)
    assert price is None


def test_split_adjusted_series_shows_no_fake_jump() -> None:
    """A split inside one adjusted download leaves flat prices flat (FR-5a)."""
    close = _history([10.0] * 260)["Close"]
    assert compute_weekly_growth(close, len(close) - 1) == (
        Decimal("0"),
        Decimal("0"),
        Decimal("0"),
    )


def test_metric_row_from_history_sets_growth_columns() -> None:
    row = metric_row_from_history("AAA", _history([100.0] * 205 + [110.0] * 5))
    assert row is not None
    assert row.price_growth == Decimal("0.1")
    assert row.sma_50_growth == Decimal("0.01")
    assert row.sma_200_growth == Decimal("0.0025")


def test_backfill_weekly_samples_carry_growth() -> None:
    rows = metric_rows_from_weekly_samples(
        "AAA.ST", _history([float(i) for i in range(1, 281)]), company="Alpha"
    )
    # First snapshot (bar 200): SMA-200 at the previous week's bar is NULL.
    assert rows[0].price_growth is not None
    assert rows[0].sma_200_growth is None
    assert all(row.sma_200_growth is not None for row in rows[1:])
    # Week-on-week close growth from one series: 205 / 200 - 1.
    assert rows[1].price_growth == Decimal("0.025")


def test_insert_metrics_sql_writes_growth_columns() -> None:
    sql = " ".join(INSERT_METRICS_SQL[CountrySet.US].split())
    assert "price_growth, sma_50_growth, sma_200_growth )" in sql
    for column in ("price_growth", "sma_50_growth", "sma_200_growth"):
        assert f"{column} = EXCLUDED.{column}" in sql
    values = _metric_values(
        [_row(date(2026, 6, 5), price_growth=Decimal("0.1"))],
        updated_at=None,  # type: ignore[arg-type]
    )
    assert values[0][-3:] == (Decimal("0.1"), None, None)


@pytest.mark.parametrize("country", list(CountrySet))
def test_fill_missing_growth_sql_only_touches_all_null_rows(
    country: CountrySet,
) -> None:
    sql = " ".join(FILL_MISSING_GROWTH_SQL[country].split())
    assert sql.startswith(f"UPDATE {country.value}_metrics m SET")
    assert "FROM (VALUES %s)" in sql
    assert "m.ticker = v.ticker" in sql
    assert "m.trading_date = v.trading_date::date" in sql
    for column in ("price_growth", "sma_50_growth", "sma_200_growth"):
        assert f"m.{column} IS NULL" in sql
        assert f"{column} = v.{column}::numeric" in sql
    assert "sma_50 =" not in sql.replace("sma_50_growth =", "")


def test_fill_missing_growth_skips_rows_without_growth() -> None:
    with patch("db.metrics.psycopg2.connect") as mock_connect:
        assert fill_missing_growth(
            "postgresql://example", [_row(date(2026, 6, 5))], country=CountrySet.US
        ) == 0
    mock_connect.assert_not_called()


def test_fill_missing_growth_sends_values() -> None:
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 1
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    row = _row(date(2026, 6, 5), price_growth=Decimal("0.1"))

    with patch("db.metrics.psycopg2.connect", return_value=mock_conn):
        with patch("db.metrics.execute_values") as mock_values:
            assert fill_missing_growth(
                "postgresql://example", [row], country=CountrySet.SWE
            ) == 1

    mock_values.assert_called_once_with(
        mock_cursor,
        FILL_MISSING_GROWTH_SQL[CountrySet.SWE],
        [("AAA.ST", date(2026, 6, 5), Decimal("0.1"), None, None)],
        page_size=1,
    )
    mock_conn.commit.assert_called_once()


def test_filter_existing_rows() -> None:
    rows = [_row(date(2025, 1, 3)), _row(date(2025, 1, 10))]
    assert filter_existing_rows(rows, {("AAA.ST", date(2025, 1, 3))}) == rows[:1]


def test_backfill_main_fills_growth_on_existing_rows() -> None:
    existing = _row(date(2025, 6, 6), price_growth=Decimal("0.02"))
    new = _row(date(2025, 6, 13), price_growth=Decimal("0.01"))
    config = BaseConfig(database_url="postgresql://example")

    with patch("backfill_sma.get_config", return_value=config), patch(
        "backfill_sma.load_tickers_from_db",
        return_value=[TickerEntry(symbol="AAA.ST", company="Alpha")],
    ), patch(
        "backfill_sma.load_existing_metric_keys",
        return_value={("AAA.ST", date(2025, 6, 6))},
    ), patch("backfill_sma.load_currency_for_tickers", return_value={}), patch(
        "backfill_sma.download_batch"
    ), patch(
        "backfill_sma.metric_rows_from_backfill_batch", return_value=[existing, new]
    ), patch("backfill_sma.insert_metrics", return_value=1) as mock_insert, patch(
        "backfill_sma.fill_missing_growth", return_value=1
    ) as mock_fill, patch("backfill_sma.upsert_market_for_weeks"):
        assert main(["--country", "swe"]) == 0

    mock_insert.assert_called_once_with("postgresql://example", [new])
    mock_fill.assert_called_once_with(
        "postgresql://example", [existing], country=CountrySet.SWE
    )
