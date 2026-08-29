from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pandas as pd

from backfill_sma import (
    filter_new_rows,
    main,
    metric_rows_from_backfill_batch,
    metric_rows_from_weekly_samples,
    sample_start_weeks,
    week_index_series,
)
from config import BaseConfig
from fetch_sma import compute_raw_ratios, upsert_market_for_trading_dates
from models import MetricRow, TickerEntry


def _mock_config(**overrides: object) -> BaseConfig:
    values: dict[str, object] = {
        "database_url": "postgresql://example",
        "backfill_batch_size": 25,
        "backfill_batch_delay_seconds": 5.0,
        "backfill_history_days": 730,
        "backfill_window_weeks": 52,
        "yf_max_retries": 3,
        "yf_retry_base_seconds": 5.0,
        "yf_name_delay_seconds": 0.25,
    }
    values.update(overrides)
    return BaseConfig(**values)  # type: ignore[arg-type]


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
        "AAA.ST", history, company="Alpha AB", currency="SEK"
    )

    assert len(rows) == len(sample_start_weeks(int(week_index_series(index, pd.Timestamp(index[0])).max()), 52))
    assert rows[0].ticker == "AAA.ST"
    assert rows[0].company == "Alpha AB"
    assert rows[0].currency == "SEK"
    assert rows[0].sma_50 is not None
    assert rows[0].sma_200 is not None
    assert rows[0].current_price is not None
    expected_raw_50, expected_raw_200 = compute_raw_ratios(
        rows[0].sma_50,
        rows[0].sma_200,
        rows[0].current_price,
    )
    assert rows[0].raw_50 == expected_raw_50
    assert rows[0].raw_200 == expected_raw_200
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
    assert all(row.company == "Alpha AB" for row in rows)
    assert all(row.raw_50 is not None for row in rows)
    assert all(row.raw_200 is not None for row in rows)


def test_filter_new_rows_skips_existing_pairs() -> None:
    rows = [
        MetricRow(
            ticker="AAA.ST",
            company="Alpha",
            trading_date=date(2025, 1, 3),
            sma_50=Decimal("1"),
            sma_200=Decimal("2"),
            current_price=Decimal("3"),
        ),
        MetricRow(
            ticker="AAA.ST",
            company="Alpha",
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


def test_main_backfill_inserts_new_rows() -> None:
    metric_row = MetricRow(
        ticker="AAA.ST",
        company="Alpha AB",
        trading_date=date(2025, 6, 6),
        sma_50=Decimal("1"),
        sma_200=Decimal("2"),
        current_price=Decimal("3"),
        currency="SEK",
        raw_50=Decimal("0.333333"),
        raw_200=Decimal("0.666667"),
    )

    with patch("backfill_sma.get_config", return_value=_mock_config()):
        with patch(
            "backfill_sma.load_tickers_from_db",
            return_value=[TickerEntry(symbol="AAA.ST", company="Alpha AB")],
        ):
            with patch("backfill_sma.load_existing_metric_keys", return_value=set()):
                with patch(
                    "backfill_sma.load_currency_for_tickers",
                    return_value={"AAA.ST": "SEK"},
                ) as mock_currency:
                    with patch("backfill_sma.download_batch") as mock_download:
                        with patch(
                            "backfill_sma.metric_rows_from_backfill_batch",
                            return_value=[metric_row],
                        ):
                            with patch(
                                "backfill_sma.insert_metrics", return_value=1
                            ) as mock_insert:
                                with patch(
                                    "backfill_sma.upsert_market_for_trading_dates"
                                ) as mock_market:
                                    assert main() == 0

    mock_currency.assert_called_once()
    mock_download.assert_called_once()
    mock_insert.assert_called_once_with("postgresql://example", [metric_row])
    mock_market.assert_called_once_with(
        "postgresql://example",
        {date(2025, 6, 6)},
    )
    inserted = mock_insert.call_args[0][1][0]
    assert inserted.company == "Alpha AB"
    assert inserted.currency == "SEK"


def test_main_succeeds_when_all_rows_already_exist() -> None:
    metric_row = MetricRow(
        ticker="AAA.ST",
        company="Alpha AB",
        trading_date=date(2025, 6, 6),
        sma_50=Decimal("1"),
        sma_200=Decimal("2"),
        current_price=Decimal("3"),
        currency="SEK",
        raw_50=Decimal("0.333333"),
        raw_200=Decimal("0.666667"),
    )

    with patch("backfill_sma.get_config", return_value=_mock_config()):
        with patch(
            "backfill_sma.load_tickers_from_db",
            return_value=[TickerEntry(symbol="AAA.ST", company="Alpha AB")],
        ):
            with patch(
                "backfill_sma.load_existing_metric_keys",
                return_value={("AAA.ST", date(2025, 6, 6))},
            ):
                with patch(
                    "backfill_sma.load_currency_for_tickers",
                    return_value={"AAA.ST": "SEK"},
                ):
                    with patch("backfill_sma.download_batch"):
                        with patch(
                            "backfill_sma.metric_rows_from_backfill_batch",
                            return_value=[metric_row],
                        ):
                            with patch("backfill_sma.insert_metrics", return_value=0):
                                with patch(
                                    "backfill_sma.upsert_market_for_trading_dates"
                                ) as mock_market:
                                    assert main() == 0

    mock_market.assert_called_once_with(
        "postgresql://example",
        {date(2025, 6, 6)},
    )


def test_main_returns_failure_when_market_metrics_upsert_fails() -> None:
    metric_row = MetricRow(
        ticker="AAA.ST",
        company="Alpha AB",
        trading_date=date(2025, 6, 6),
        sma_50=Decimal("1"),
        sma_200=Decimal("2"),
        current_price=Decimal("3"),
        currency="SEK",
        raw_50=Decimal("0.333333"),
        raw_200=Decimal("0.666667"),
    )

    with patch("backfill_sma.get_config", return_value=_mock_config()):
        with patch(
            "backfill_sma.load_tickers_from_db",
            return_value=[TickerEntry(symbol="AAA.ST", company="Alpha AB")],
        ):
            with patch("backfill_sma.load_existing_metric_keys", return_value=set()):
                with patch(
                    "backfill_sma.load_currency_for_tickers",
                    return_value={"AAA.ST": "SEK"},
                ):
                    with patch("backfill_sma.download_batch"):
                        with patch(
                            "backfill_sma.metric_rows_from_backfill_batch",
                            return_value=[metric_row],
                        ):
                            with patch("backfill_sma.insert_metrics", return_value=1):
                                with patch(
                                    "backfill_sma.upsert_market_for_trading_dates",
                                    side_effect=RuntimeError("db error"),
                                ):
                                    assert main() == 1


def test_upsert_market_for_trading_dates_groups_backfill_dates_by_listing_market() -> None:
    with patch(
        "fetch_sma.load_raw_ratios_by_market_for_date",
        return_value={
            "se_market": ([Decimal("0.5")], [Decimal("0.4")]),
            "us_market": ([Decimal("0.6")], [Decimal("0.5")]),
        },
    ):
        with patch("fetch_sma.upsert_market_stats") as mock_upsert:
            upsert_market_for_trading_dates(
                "postgresql://example",
                {date(2025, 6, 6)},
            )

    assert mock_upsert.call_count == 2
    markets = {call.args[1].market for call in mock_upsert.call_args_list}
    assert markets == {"se_market", "us_market"}


def test_main_returns_failure_on_failed_batch() -> None:
    with patch("backfill_sma.get_config", return_value=_mock_config()):
        with patch(
            "backfill_sma.load_tickers_from_db",
            return_value=[TickerEntry(symbol="AAA.ST", company="Alpha AB")],
        ):
            with patch("backfill_sma.load_existing_metric_keys", return_value=set()):
                with patch(
                    "backfill_sma.load_currency_for_tickers",
                    return_value={"AAA.ST": "SEK"},
                ):
                    with patch(
                        "backfill_sma.download_batch",
                        side_effect=RuntimeError("rate limited"),
                    ):
                        assert main() == 1


def test_main_returns_failure_when_nothing_generated() -> None:
    with patch("backfill_sma.get_config", return_value=_mock_config()):
        with patch(
            "backfill_sma.load_tickers_from_db",
            return_value=[TickerEntry(symbol="AAA.ST", company="Alpha AB")],
        ):
            with patch("backfill_sma.load_existing_metric_keys", return_value=set()):
                with patch(
                    "backfill_sma.load_currency_for_tickers",
                    return_value={"AAA.ST": "SEK"},
                ):
                    with patch("backfill_sma.download_batch"):
                        with patch(
                            "backfill_sma.metric_rows_from_backfill_batch",
                            return_value=[],
                        ):
                            assert main() == 1
