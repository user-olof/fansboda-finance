from datetime import date
from decimal import Decimal

import pandas as pd

from backfill_sma import (
    filter_new_rows,
    metric_rows_from_backfill_batch,
    metric_rows_from_weekly_samples,
    sample_start_weeks,
    week_index_series,
)
from models import MetricRow


def test_sample_start_weeks() -> None:
    assert sample_start_weeks(max_week=51, window_weeks=52) == [0]
    assert sample_start_weeks(max_week=60, window_weeks=52) == list(range(10))
    assert sample_start_weeks(max_week=10, window_weeks=52) == []


def test_week_index_series_counts_from_anchor() -> None:
    index = pd.to_datetime(["2024-01-01", "2024-01-08", "2024-01-15"])
    anchor = pd.Timestamp("2024-01-01")
    weeks = week_index_series(index, anchor)
    assert weeks.tolist() == [0, 1, 2]


def test_metric_rows_from_weekly_samples_creates_rolling_windows() -> None:
    index = pd.date_range("2024-01-01", periods=280, freq="B")
    history = pd.DataFrame(
        {
            "Open": range(280),
            "High": range(280),
            "Low": range(280),
            "Close": range(1, 281),
            "Volume": [1000] * 280,
        },
        index=index,
    )

    rows = metric_rows_from_weekly_samples(
        "AAA.ST", history, name="Alpha AB", currency="SEK"
    )

    assert len(rows) == len(sample_start_weeks(int(week_index_series(index, pd.Timestamp(index[0])).max()), 52))
    assert rows[0].ticker == "AAA.ST"
    assert rows[0].name == "Alpha AB"
    assert rows[0].currency == "SEK"
    assert rows[0].sma_50 is not None
    assert rows[0].sma_200 is not None
    assert rows[0].current_price is not None
    assert rows[-1].trading_date >= rows[0].trading_date


def test_metric_rows_from_backfill_batch_sets_currency() -> None:
    index = pd.date_range("2024-01-01", periods=280, freq="B")
    columns = pd.MultiIndex.from_product(
        [["AAA.ST"], ["Open", "High", "Low", "Close", "Volume"]]
    )
    data = pd.DataFrame(index=index, columns=columns, dtype=float)
    for field in ("Open", "High", "Low", "Close", "Volume"):
        data[("AAA.ST", field)] = 1.0
    data[("AAA.ST", "Close")] = range(1, 281)

    rows = metric_rows_from_backfill_batch(
        data,
        ["AAA.ST"],
        {"AAA.ST": "Alpha AB"},
        {"AAA.ST": "SEK"},
    )

    assert rows
    assert all(row.currency == "SEK" for row in rows)


def test_filter_new_rows_skips_existing_pairs() -> None:
    rows = [
        MetricRow(
            ticker="AAA.ST",
            name="Alpha",
            trading_date=date(2025, 1, 3),
            sma_50=Decimal("1"),
            sma_200=Decimal("2"),
            current_price=Decimal("3"),
        ),
        MetricRow(
            ticker="AAA.ST",
            name="Alpha",
            trading_date=date(2025, 1, 10),
            sma_50=Decimal("4"),
            sma_200=Decimal("5"),
            current_price=Decimal("6"),
        ),
    ]
    existing = {("AAA.ST", date(2025, 1, 3))}
    filtered = filter_new_rows(rows, existing)

    assert len(filtered) == 1
    assert filtered[0].trading_date == date(2025, 1, 10)
