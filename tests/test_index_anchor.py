"""Tests for index daily series (specs/001-index-initial-sma, specs/002-index-true-sma)."""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from db.country import CountrySet
from equity_index import IndexLevels
from fetch_sma import compute_smas
from index_anchor import (
    AnchorSettings,
    DailyAccumulator,
    IndexSeries,
    candidate_dates,
    compute_index_series,
    daily_levels,
    daily_returns,
    find_start_date,
    fold_close,
    index_tickers_for,
    missing_sector_indices,
    sector_key,
    series_week_levels,
    week_levels,
)
from models import TickerEntry, week_start_of

START = date(2025, 10, 3)  # a Friday
DAYS = pd.bdate_range("2024-06-03", "2025-12-31")
BOUNDS = {"max_growth": 9.0, "min_growth": -0.999}


def _trend(daily_change: float, index=DAYS, base: float = 50.0) -> pd.Series:
    return pd.Series(base * (1 + daily_change) ** np.arange(len(index)), index=index)


def _entry(symbol: str, sector: str | None = "Energy") -> TickerEntry:
    return TickerEntry(symbol, symbol, sector=sector)


# --- sector keys and membership -------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Consumer Cyclical", "consumer-cyclical"),
        (" Technology ", "technology"),
        ("consumer-cyclical", "consumer-cyclical"),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_sector_key_matches_sql_normalization(raw, expected) -> None:
    assert sector_key(raw) == expected


def test_index_tickers_for_market_and_sector() -> None:
    assert index_tickers_for(_entry("A", "Financial Services"), CountrySet.SWE) == [
        "SWE-IDX",
        "SWE-IDX-FINANCIAL-SERVICES",
    ]
    assert index_tickers_for(_entry("B", None), CountrySet.US) == ["US-IDX"]


def test_missing_sector_indices_groups_members_and_filters() -> None:
    entries = [
        _entry("A", "Energy"),
        _entry("B", "Utilities"),
        _entry("C", "utilities"),
        _entry("D", " "),
        _entry("E", "Real Estate"),
    ]
    missing = missing_sector_indices(entries, {"US-IDX", "US-IDX-ENERGY"}, CountrySet.US)
    assert missing == {
        "US-IDX-REAL-ESTATE": [entries[4]],
        "US-IDX-UTILITIES": [entries[1], entries[2]],
    }
    assert list(
        missing_sector_indices(entries, set(), CountrySet.US, min_components=2)
    ) == ["US-IDX-UTILITIES"]


# --- daily reconstruction ---------------------------------------------------


def test_daily_returns_uses_consecutive_bars_drops_outliers_and_stops_at_end() -> None:
    index = pd.DatetimeIndex(["2025-09-29", "2025-09-30", "2025-10-02", "2025-10-03", "2025-10-06"])
    close = pd.Series([10.0, 11.0, 121.0, np.nan, 12.1], index=index)
    returns = daily_returns(close, end_date=START, max_growth=9.0, min_growth=-0.999)
    assert returns == pytest.approx({date(2025, 9, 30): 0.1})
    assert daily_returns(
        close, end_date=START, max_growth=20.0, min_growth=-0.999
    ) == pytest.approx({date(2025, 9, 30): 0.1, date(2025, 10, 2): 10.0})


def test_daily_accumulator_averages_over_stocks_with_data() -> None:
    acc = DailyAccumulator()
    acc.add(["US-IDX", "US-IDX-ENERGY"], {date(2025, 10, 2): 0.02, date(2025, 10, 3): 0.04})
    acc.add(["US-IDX"], {date(2025, 10, 3): 0.0})
    assert acc.averages("US-IDX") == pytest.approx({date(2025, 10, 2): 0.02, date(2025, 10, 3): 0.02})
    assert acc.averages("US-IDX-ENERGY") == pytest.approx(
        {date(2025, 10, 2): 0.02, date(2025, 10, 3): 0.04}
    )
    assert acc.averages("UK-IDX") == {}


def test_fold_close_windows_and_dropped_count() -> None:
    index = pd.DatetimeIndex(
        ["2025-09-29", "2025-09-30", "2025-10-01", "2025-10-02", "2025-10-03"]
    )
    close = pd.Series([10.0, 11.0, 121.0, 12.1, 13.31], index=index)

    acc = DailyAccumulator()
    assert fold_close(acc, ["X"], close, **BOUNDS) == 1
    assert acc.averages("X") == pytest.approx(
        {date(2025, 9, 30): 0.1, date(2025, 10, 2): -0.9, date(2025, 10, 3): 0.1}
    )

    until = DailyAccumulator()
    fold_close(until, ["X"], close, until=date(2025, 10, 2), **BOUNDS)
    assert set(until.averages("X")) == {date(2025, 9, 30), date(2025, 10, 2)}

    after = DailyAccumulator()
    assert fold_close(after, ["X"], close, after=date(2025, 10, 2), **BOUNDS) == 0
    assert after.averages("X") == pytest.approx({date(2025, 10, 3): 0.1})


# --- daily level series -------------------------------------------------------

D1, D2, D3, D4 = date(2025, 10, 6), date(2025, 10, 7), date(2025, 10, 8), date(2025, 10, 9)


def test_daily_levels_forward_and_backward_from_pin() -> None:
    averages = {D1: 0.1, D2: 0.25, D3: -0.5, D4: 1.0}
    levels = daily_levels(averages, D2, 125.0)
    assert levels == pytest.approx({D1: 100.0, D2: 125.0, D3: 62.5, D4: 125.0})
    assert daily_levels(averages, D1, 100.0) == pytest.approx(levels)
    assert daily_levels(averages, D4, 125.0) == pytest.approx(levels)


def test_daily_levels_pin_without_return_is_a_flat_day() -> None:
    friday, saturday, monday = date(2025, 10, 3), date(2025, 10, 4), date(2025, 10, 6)
    levels = daily_levels({friday: 0.1, monday: 0.2}, saturday, 100.0)
    assert levels == pytest.approx({friday: 100.0, saturday: 100.0, monday: 120.0})
    early = daily_levels({D2: 0.1}, D1, 100.0)
    assert early == pytest.approx({D1: 100.0, D2: 110.0})


def _numbered(days: pd.DatetimeIndex) -> dict[date, float]:
    return {day.date(): float(i + 1) for i, day in enumerate(days)}


def test_week_levels_sma_means_of_last_levels() -> None:
    days = pd.bdate_range("2025-01-01", periods=260)
    levels = _numbered(days)
    last = days[-1].date()
    row = week_levels(levels, week_start_of(last))
    assert row is not None
    assert row.trading_date == last
    assert row.levels.current_price == Decimal("260.0")
    assert row.levels.sma_50 == Decimal(str(sum(range(211, 261)) / 50))
    assert row.levels.sma_200 == Decimal(str(sum(range(61, 261)) / 200))
    assert row.days_used == 200


def test_week_levels_row_date_and_missing_week() -> None:
    days = pd.bdate_range("2025-09-29", "2025-10-10")
    levels = _numbered(days)
    wednesday = date(2025, 10, 8)
    row = week_levels(levels, date(2025, 10, 6), row_date=wednesday)
    assert row is not None
    assert row.trading_date == wednesday
    assert row.levels.current_price == Decimal("8.0")
    assert row.levels.sma_200 == Decimal(str(sum(range(1, 9)) / 8))
    assert row.days_used == 8
    assert week_levels(levels, date(2025, 10, 13)) is None
    assert week_levels(levels, date(2025, 10, 6), row_date=date(2025, 10, 11)) is None


def test_week_levels_flat_series_has_momentum_one() -> None:
    days = pd.bdate_range("2025-01-01", periods=220)
    row = week_levels({d.date(): 105.0 for d in days}, week_start_of(days[-1].date()))
    assert row is not None
    assert row.levels == IndexLevels(Decimal("105.0"), Decimal("105.0"), Decimal("105.0"))


def test_one_stock_index_momentum_equals_stock_momentum() -> None:
    """Spec US1 scenario 3: the index SMAs use the same definition as a stock's."""
    close = _trend(0.0007) * (1 + 0.05 * np.sin(np.arange(len(DAYS)) / 9))
    acc = DailyAccumulator()
    fold_close(acc, ["IDX"], close, **BOUNDS)
    last = DAYS[-1].date()
    levels = daily_levels(acc.averages("IDX"), last, 100.0)
    row = week_levels(levels, week_start_of(last))
    assert row is not None

    sma_50, sma_200 = compute_smas(close)
    stock_momentum = float(sma_50) / float(sma_200)
    index_momentum = float(row.levels.sma_50) / float(row.levels.sma_200)
    assert index_momentum == pytest.approx(stock_momentum, abs=1e-6)


def test_extreme_stock_moves_sma_200_by_its_equal_weighted_share() -> None:
    """SC-003 (001): one of 50 stocks falling 99% over the window."""
    end = list(DAYS.date).index(START) + 1
    index = DAYS[:end]
    falling = _trend((0.01) ** (1 / 250) - 1, index)
    acc = DailyAccumulator()
    for _ in range(49):
        fold_close(acc, ["IDX"], _trend(0.0, index), **BOUNDS)
    fold_close(acc, ["IDX"], falling, **BOUNDS)
    alone = DailyAccumulator()
    fold_close(alone, ["S"], falling, **BOUNDS)

    week = week_start_of(START)
    index_sma_200 = week_levels(daily_levels(acc.averages("IDX"), START, 100.0), week)
    stock_sma_200 = week_levels(daily_levels(alone.averages("S"), START, 100.0), week)
    assert stock_sma_200.levels.sma_200 > 1000
    assert 0 < index_sma_200.levels.sma_200 - 100 <= (stock_sma_200.levels.sma_200 - 100) / 50


def test_series_week_levels_from_start_week() -> None:
    wednesday = date(2025, 10, 1)
    days = pd.bdate_range("2025-09-22", "2025-10-17")
    series = IndexSeries("IDX", wednesday, {d.date(): 100.0 for d in days})
    weeks = [date(2025, 9, 22), date(2025, 9, 29), date(2025, 10, 6), date(2025, 10, 20)]
    result = series_week_levels([series], weeks)
    assert sorted(result) == [date(2025, 9, 29), date(2025, 10, 6)]
    assert result[date(2025, 9, 29)]["IDX"].trading_date == wednesday
    assert result[date(2025, 10, 6)]["IDX"].trading_date == date(2025, 10, 10)


# --- start date rule --------------------------------------------------------


def test_candidate_dates_are_start_then_later_week_ends() -> None:
    days = [START, date(2025, 10, 6), date(2025, 10, 9), date(2025, 10, 10), date(2025, 10, 14)]
    assert candidate_dates(days, START) == [
        START,
        date(2025, 10, 10),
        date(2025, 10, 14),
    ]


@pytest.mark.parametrize(
    ("counts", "minimum", "expected"),
    [
        ({START: 5}, 5, START),
        ({START: 4, date(2025, 10, 10): 5}, 5, date(2025, 10, 10)),
        ({START: 4, date(2025, 10, 10): 4}, 5, None),
        ({START: 2}, 2, START),
    ],
)
def test_find_start_date(counts, minimum, expected) -> None:
    assert find_start_date(counts, [START, date(2025, 10, 10)], minimum) == expected


# --- compute_index_series with mocked downloads --------------------------------


def _frame(closes: dict[str, pd.Series]) -> pd.DataFrame:
    return pd.concat({symbol: pd.DataFrame({"Close": s}) for symbol, s in closes.items()}, axis=1)


def _fake_download(closes: dict[str, pd.Series], fail: set[str] | None = None):
    calls = []

    def download(batch, start, **kwargs):
        calls.append((list(batch), start))
        if fail and fail & set(batch):
            raise RuntimeError("rate limited")
        available = {s: closes[s] for s in batch if s in closes}
        if not available:
            raise ValueError("Empty dataframe")
        return _frame(available)

    return download, calls


SETTINGS = AnchorSettings(start_date=START, batch_size=2, batch_delay_seconds=0)


def _run(entries, closes, settings=SETTINGS, fail=None, **kwargs):
    download, calls = _fake_download(closes, fail=fail)
    with patch("index_anchor.download_batch", side_effect=download), patch(
        "index_anchor.time.sleep"
    ):
        return compute_index_series(entries, CountrySet.US, settings=settings, **kwargs), calls


def test_compute_index_series_market_and_sector_on_common_start_date(caplog) -> None:
    closes = {s: _trend(0.001 * (i + 1)) for i, s in enumerate("ABCDEF")}
    entries = [_entry(s) for s in "ABCDE"] + [_entry("F", None), _entry("G")]
    result, calls = _run(entries, closes, fail={"G"})

    assert set(result.series) == {"US-IDX", "US-IDX-ENERGY"}
    assert "G" in result.missing_symbols
    assert calls[0][1] == START - timedelta(days=400)
    for series in result.series.values():
        assert series.start_date == START
        assert series.levels[START] == 100.0
        assert max(series.levels) == DAYS[-1].date()
        row = week_levels(series.levels, week_start_of(START), row_date=START)
        assert row.levels.current_price == Decimal("100.0")
        assert row.levels.sma_200 < row.levels.sma_50 < Decimal("100")
        assert row.days_used == 200
        assert len([d for d in series.levels if d < START]) == SETTINGS.trading_days - 1
    assert "no daily history" in caplog.text


def test_compute_index_series_returns_before_start_only_from_listed_members() -> None:
    flat = {s: _trend(0.0) for s in "ABCDE"}
    gap = _trend(0.01)
    flat["F"] = gap[gap.index != pd.Timestamp(START)]
    result, _ = _run([_entry(s) for s in "ABCDEF"], flat)

    levels = result.series["US-IDX"].levels
    assert all(level == pytest.approx(100.0) for d, level in levels.items() if d <= START)
    monday = date(2025, 10, 6)
    assert levels[monday] == pytest.approx(100.0 * (1 + (1.01**2 - 1) / 6))


def test_compute_index_series_counts_dropped_returns() -> None:
    closes = {s: _trend(0.0) for s in "ABCDE"}
    jump = _trend(0.0)
    jump.iloc[-5:] *= 20
    closes["E"] = jump
    result, _ = _run([_entry(s) for s in "ABCDE"], closes)
    assert result.dropped_returns == 1


def test_compute_index_series_later_start_date_via_second_pass() -> None:
    late = DAYS[DAYS >= pd.Timestamp("2025-10-08")]
    closes = {s: _trend(0.001) for s in "ABCD"}
    closes["E"] = _trend(0.001, late)
    settings = AnchorSettings(start_date=START, batch_size=10, batch_delay_seconds=0)
    result, calls = _run(
        [_entry(s) for s in "ABCDE"], closes, settings=settings, index_tickers={"US-IDX-ENERGY"}
    )

    series = result.series["US-IDX-ENERGY"]
    assert series.start_date == date(2025, 10, 10)
    assert series.levels[date(2025, 10, 10)] == 100.0
    assert [c[1] for c in calls] == [
        START - timedelta(days=400),
        date(2025, 10, 10) - timedelta(days=400),
    ]
    assert "US-IDX" not in result.series


def test_compute_index_series_index_never_reaching_minimum() -> None:
    closes = {s: _trend(0.001) for s in "ABC"}
    result, _ = _run([_entry(s) for s in "ABC"], closes)
    assert result.series == {}
    assert result.below_minimum == {"US-IDX", "US-IDX-ENERGY"}


def test_compute_index_series_single_ticker_frame() -> None:
    settings = AnchorSettings(start_date=START, min_components=1, batch_delay_seconds=0)
    frame = pd.DataFrame({"Close": _trend(0.001)})
    with patch("index_anchor.download_batch", return_value=frame):
        result = compute_index_series([_entry("A")], CountrySet.SWE, settings=settings)

    assert set(result.series) == {"SWE-IDX", "SWE-IDX-ENERGY"}
