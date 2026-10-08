"""Tests for index start levels from daily history (specs/001-index-initial-sma)."""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from backfill_sma import metric_rows_from_weekly_samples
from db.country import CountrySet
from equity_index import IndexLevels
from index_anchor import (
    AnchorSettings,
    DailyAccumulator,
    WeeklyAccumulator,
    build_anchor,
    candidate_dates,
    compute_anchors,
    daily_returns,
    find_start_date,
    index_tickers_for,
    initial_smas,
    missing_sector_indices,
    reconstruct_levels,
    sector_key,
)
from models import MetricRow, TickerEntry, week_start_of

START = date(2025, 10, 3)  # a Friday
DAYS = pd.bdate_range("2024-06-03", "2025-12-31")


def _series(values, index=DAYS) -> pd.Series:
    """Synthetic daily closes indexed by business days."""
    return pd.Series(np.asarray(values, dtype=float), index=index[: len(values)])


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


def test_reconstruct_levels_works_backwards_from_100() -> None:
    acc = DailyAccumulator()
    acc.add(["X"], {date(2025, 10, 2): 0.0, START: 0.01})
    acc.add(["X"], {START: 0.01})
    levels = reconstruct_levels(acc.averages("X"), START, 250)
    assert levels[-1] == 100
    assert levels[-2] == pytest.approx(100 / 1.01)
    assert levels[-3] == pytest.approx(100 / 1.01)
    assert len(levels) == 3


def test_reconstruct_levels_uses_last_trading_days_up_to_start() -> None:
    averages = {START - timedelta(days=i): 0.001 for i in range(1, 400)}
    averages[START + timedelta(days=3)] = 0.5
    levels = reconstruct_levels(averages, START, 250)
    assert len(levels) == 251
    assert levels[-1] == 100


def test_initial_smas_are_means_of_last_50_and_200_levels() -> None:
    levels = [float(i) for i in range(1, 252)]
    sma_50, sma_200, days_used = initial_smas(levels)
    assert sma_50 == Decimal(str(round(sum(range(202, 252)) / 50, 6)))
    assert sma_200 == Decimal(str(round(sum(range(52, 252)) / 200, 6)))
    assert days_used == 200


def test_initial_smas_with_fewer_than_200_levels() -> None:
    sma_50, sma_200, days_used = initial_smas([90.0, 100.0])
    assert (sma_50, sma_200, days_used) == (Decimal("95.0"), Decimal("95.0"), 2)


def test_extreme_stock_moves_initial_sma_200_by_its_equal_weighted_share() -> None:
    """SC-003: one of 50 stocks falling 99% over the window."""
    end = list(DAYS.date).index(START) + 1
    index = DAYS[:end]
    falling = _trend((0.01) ** (1 / 250) - 1, index)
    acc = DailyAccumulator()
    for i in range(49):
        acc.add(["IDX"], daily_returns(_trend(0.0, index), end_date=START, max_growth=9, min_growth=-0.999))
    acc.add(["IDX"], daily_returns(falling, end_date=START, max_growth=9, min_growth=-0.999))
    alone = DailyAccumulator()
    alone.add(["S"], daily_returns(falling, end_date=START, max_growth=9, min_growth=-0.999))

    index_sma_200 = initial_smas(reconstruct_levels(acc.averages("IDX"), START, 250))[1]
    stock_sma_200 = initial_smas(reconstruct_levels(alone.averages("S"), START, 250))[1]
    assert stock_sma_200 > 1000
    assert 0 < index_sma_200 - 100 <= (stock_sma_200 - 100) / 50


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


# --- weekly bridge ------------------------------------------------------------


def _metric(week_day: date, growth: str, **overrides) -> MetricRow:
    values = dict(
        ticker="A",
        company=None,
        trading_date=week_day,
        sma_50=Decimal("10"),
        sma_200=Decimal("9"),
        current_price=Decimal("11"),
        price_growth=Decimal(growth),
        sma_50_growth=Decimal(growth),
        sma_200_growth=Decimal(growth),
    )
    values.update(overrides)
    return MetricRow(**values)


def test_weekly_accumulator_matches_chained_sql_rules() -> None:
    w1, w2, w3 = date(2025, 10, 10), date(2025, 10, 17), date(2025, 10, 24)
    acc = WeeklyAccumulator()
    acc.add(
        ["IDX"],
        [
            _metric(w1, "0.10"),
            _metric(w1, "0.30"),
            _metric(w1, "50"),  # above max growth
            _metric(w1, "0.10", sma_200=Decimal("0")),  # not positive
            _metric(w1, "0.10", sma_50_growth=None),  # missing growth
            _metric(w3, "-0.5"),
        ],
        max_growth=9.0,
        min_growth=-0.999,
    )
    start = IndexLevels(Decimal("100"), Decimal("98"), Decimal("96"))
    levels, last_date = acc.chain(
        "IDX", start, [week_start_of(w) for w in (w3, w1, w2)]
    )
    assert levels.current_price == Decimal("100") * Decimal("1.2") * Decimal("0.5")
    assert levels.sma_200 == Decimal("96") * Decimal("1.2") * Decimal("0.5")
    assert last_date == w3
    assert acc.chain("OTHER", start, [week_start_of(w1)]) == (start, None)


def test_build_anchor_without_bridge_is_on_start_week() -> None:
    anchor = build_anchor(
        "IDX",
        {START: 0.01},
        WeeklyAccumulator(),
        start_date=START,
        trading_days=250,
        first_stored_week=week_start_of(START),
    )
    assert anchor is not None
    assert (anchor.week_start, anchor.trading_date) == (week_start_of(START), START)
    assert anchor.levels.current_price == Decimal("100")
    assert anchor.days_used == 2
    assert build_anchor(
        "IDX", {}, WeeklyAccumulator(), start_date=START, trading_days=250, first_stored_week=None
    ) is None


def test_build_anchor_bridges_to_week_before_oldest_stored_week() -> None:
    weekly = WeeklyAccumulator()
    weekly.add(
        ["IDX"], [_metric(date(2025, 10, 10), "0.10")], max_growth=9.0, min_growth=-0.999
    )
    anchor = build_anchor(
        "IDX",
        {START: 0.0},
        weekly,
        start_date=START,
        trading_days=250,
        first_stored_week=date(2025, 10, 20),
    )
    assert anchor is not None
    assert anchor.week_start == date(2025, 10, 13)
    assert anchor.trading_date == date(2025, 10, 10)
    assert anchor.levels.current_price == Decimal("110.0")
    assert anchor.start_date == START


# --- compute_anchors with mocked downloads -----------------------------------


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


def test_compute_anchors_market_and_sector_on_common_start_date(caplog) -> None:
    closes = {s: _trend(0.001 * (i + 1)) for i, s in enumerate("ABCDEF")}
    entries = [_entry(s) for s in "ABCDE"] + [_entry("F", None), _entry("G")]
    download, calls = _fake_download(closes, fail={"G"})
    with patch("index_anchor.download_batch", side_effect=download), patch(
        "index_anchor.time.sleep"
    ):
        result = compute_anchors(entries, CountrySet.US, settings=SETTINGS)

    assert set(result.anchors) == {"US-IDX", "US-IDX-ENERGY"}
    assert "G" in result.missing_symbols
    assert calls[0][1] == START - timedelta(days=400)
    for anchor in result.anchors.values():
        assert anchor.start_date == START
        assert anchor.week_start == week_start_of(START)
        assert anchor.levels.current_price == Decimal("100")
        assert anchor.levels.sma_200 < anchor.levels.sma_50 < Decimal("100")
        assert anchor.days_used == 200
    assert "no daily history" in caplog.text


def test_compute_anchors_later_start_date_via_second_pass() -> None:
    late = DAYS[DAYS >= pd.Timestamp("2025-10-08")]
    closes = {s: _trend(0.001) for s in "ABCD"}
    closes["E"] = _trend(0.001, late)
    entries = [_entry(s) for s in "ABCDE"]
    download, calls = _fake_download(closes)
    settings = AnchorSettings(start_date=START, batch_size=10, batch_delay_seconds=0)
    with patch("index_anchor.download_batch", side_effect=download), patch(
        "index_anchor.time.sleep"
    ):
        result = compute_anchors(
            entries, CountrySet.US, settings=settings, index_tickers={"US-IDX-ENERGY"}
        )

    anchor = result.anchors["US-IDX-ENERGY"]
    assert anchor.start_date == date(2025, 10, 10)
    assert anchor.week_start == date(2025, 10, 6)
    assert anchor.levels.current_price == Decimal("100")
    assert [c[1] for c in calls] == [
        START - timedelta(days=400),
        date(2025, 10, 10) - timedelta(days=400),
    ]
    assert "US-IDX" not in result.anchors


def test_compute_anchors_index_never_reaching_minimum() -> None:
    closes = {s: _trend(0.001) for s in "ABC"}
    download, _ = _fake_download(closes)
    with patch("index_anchor.download_batch", side_effect=download), patch(
        "index_anchor.time.sleep"
    ):
        result = compute_anchors([_entry(s) for s in "ABC"], CountrySet.UK, settings=SETTINGS)

    assert result.anchors == {}
    assert result.below_minimum == {"UK-IDX", "UK-IDX-ENERGY"}


def test_compute_anchors_single_ticker_frame() -> None:
    settings = AnchorSettings(start_date=START, min_components=1, batch_delay_seconds=0)
    frame = pd.DataFrame({"Close": _trend(0.001)})
    with patch("index_anchor.download_batch", return_value=frame):
        result = compute_anchors([_entry("A")], CountrySet.SWE, settings=settings)

    assert set(result.anchors) == {"SWE-IDX", "SWE-IDX-ENERGY"}


def test_compute_anchors_bridge_equals_chaining_stored_weeks() -> None:
    """Start week purged: levels bridged with the weekly rules from the same data."""
    closes = {s: _trend(0.0005 * (i + 1)) for i, s in enumerate("ABCDE")}
    entries = [_entry(s) for s in "ABCDE"]
    first_stored = date(2025, 10, 27)
    download, _ = _fake_download(closes)
    with patch("index_anchor.download_batch", side_effect=download), patch(
        "index_anchor.time.sleep"
    ):
        unbridged = compute_anchors(entries, CountrySet.US, settings=SETTINGS)
        bridged = compute_anchors(
            entries, CountrySet.US, settings=SETTINGS, first_stored_week=first_stored
        )

    weekly = WeeklyAccumulator()
    for symbol, close in closes.items():
        rows = metric_rows_from_weekly_samples(
            symbol,
            pd.DataFrame({"Close": close[close.index < pd.Timestamp(first_stored)]}),
            company=None,
        )
        weekly.add(
            ["US-IDX"],
            [r for r in rows if r.week_start > week_start_of(START)],
            max_growth=9.0,
            min_growth=-0.999,
        )
    expected, last_date = weekly.chain(
        "US-IDX",
        unbridged.anchors["US-IDX"].levels,
        [date(2025, 10, 6), date(2025, 10, 13), date(2025, 10, 20)],
    )
    anchor = bridged.anchors["US-IDX"]
    assert anchor.week_start == date(2025, 10, 20)
    assert anchor.trading_date == last_date == date(2025, 10, 24)
    assert anchor.levels == expected
    assert anchor.levels.current_price > Decimal("100")
