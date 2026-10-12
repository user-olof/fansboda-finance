from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from db.metrics import (
    current_week_start,
    expected_latest_bar,
    filter_stale_tickers,
    insert_metrics,
    load_momentum_by_market_for_week,
)
from db.tickers import load_tickers_from_db
from fetch_sma import (
    aggregate_market_stats,
    chunked,
    compute_momentum,
    compute_smas,
    compute_z_score,
    metric_row_from_history,
    metric_rows_from_batch,
    trading_date_from_index,
    upsert_market_for_weeks,
)
from models import MarketRow, MetricRow, TickerEntry

def test_load_tickers_from_db() -> None:
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        ("AAA.ST", "Company A", "Industrials", "Machinery", "se_market", "STO"),
        ("BBB.ST", None, None, None, None, None),
        ("VOD.L", "Vodafone", "communication-services", "telecom", "gb_market", "LSE"),
    ]

    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.tickers.psycopg2.connect", return_value=mock_conn):
        entries = load_tickers_from_db("postgresql://example")

    assert entries == [
        TickerEntry(
            symbol="AAA.ST",
            company="Company A",
            sector="Industrials",
            industry="Machinery",
            market="se_market",
            exchange_name="STO",
        ),
        TickerEntry(symbol="BBB.ST", company=None),
        TickerEntry(
            symbol="VOD.L",
            company="Vodafone",
            sector="communication-services",
            industry="telecom",
            market="gb_market",
            exchange_name="LSE",
        ),
    ]
    sql = mock_cursor.execute.call_args[0][0]
    assert "FROM uk_tickers" in sql
    assert "FROM us_tickers" in sql
    assert "FROM swe_tickers" in sql


def test_load_tickers_from_db_raises_when_empty() -> None:
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []

    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.tickers.psycopg2.connect", return_value=mock_conn):
        with pytest.raises(
            ValueError,
            match="No tickers found in us_tickers, swe_tickers, or uk_tickers",
        ):
            load_tickers_from_db("postgresql://example")


def test_load_tickers_from_db_scopes_to_country() -> None:
    from db.country import CountrySet

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        ("VOD.L", "Vodafone", None, None, "gb_market", "LSE"),
    ]
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.tickers.psycopg2.connect", return_value=mock_conn):
        entries = load_tickers_from_db("postgresql://example", country=CountrySet.UK)

    assert [e.symbol for e in entries] == ["VOD.L"]
    sql = mock_cursor.execute.call_args[0][0]
    assert "FROM uk_tickers" in sql
    assert "FROM us_tickers" not in sql
    assert "FROM swe_tickers" not in sql


def test_compute_momentum_divides_sma50_by_sma200() -> None:
    assert compute_momentum(Decimal("100"), Decimal("50")) == Decimal("2.0")


def test_compute_momentum_returns_none_when_inputs_missing_or_zero() -> None:
    assert compute_momentum(None, Decimal("2")) is None
    assert compute_momentum(Decimal("1"), None) is None
    assert compute_momentum(Decimal("1"), Decimal("0")) is None


def test_compute_z_score() -> None:
    assert compute_z_score(
        Decimal("1.2"), Decimal("1.0"), Decimal("0.2")
    ) == Decimal("1.0")
    assert compute_z_score(Decimal("1"), Decimal("1"), Decimal("0")) is None
    assert compute_z_score(None, Decimal("1"), Decimal("1")) is None


def test_aggregate_market_stats_uses_population_std() -> None:
    row = aggregate_market_stats(
        date(2026, 6, 1),
        "us_market",
        [Decimal("1"), Decimal("3")],
    )

    assert row == MarketRow(
        market="us_market",
        week_start=date(2026, 6, 1),
        momentum_mean=Decimal("2"),
        momentum_std=Decimal("1"),
    )


def test_aggregate_market_stats_returns_none_when_empty() -> None:
    assert aggregate_market_stats(date(2026, 6, 6), "us_market", []) is None


def test_load_momentum_by_market_for_week_groups_by_tickers_market() -> None:
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        ("us_market", Decimal("0.5")),
        ("us_market", Decimal("0.7")),
        ("se_market", Decimal("0.6")),
        ("gb_market", Decimal("0.8")),
        (None, Decimal("0.9")),
        ("us_market", None),
    ]
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.metrics.psycopg2.connect", return_value=mock_conn):
        grouped = load_momentum_by_market_for_week(
            "postgresql://example",
            date(2026, 6, 6),
        )

    sql = mock_cursor.execute.call_args[0][0]
    assert "JOIN us_tickers t ON t.symbol = m.ticker" in sql
    assert "JOIN swe_tickers t ON t.symbol = m.ticker" in sql
    assert "JOIN uk_tickers t ON t.symbol = m.ticker" in sql
    assert "m.momentum" in sql
    assert mock_cursor.execute.call_args[0][1] == (
        date(2026, 6, 6),
        date(2026, 6, 6),
        date(2026, 6, 6),
    )
    assert grouped == {
        "us_market": [Decimal("0.5"), Decimal("0.7")],
        "se_market": [Decimal("0.6")],
        "gb_market": [Decimal("0.8")],
        None: [Decimal("0.9")],
    }


def test_upsert_market_for_weeks_upserts_per_listing_market() -> None:
    week_start = date(2026, 6, 1)
    with patch(
        "fetch_sma.load_momentum_by_market_for_week",
        return_value={
            "us_market": [Decimal("1"), Decimal("3")],
            "se_market": [Decimal("0.6")],
            "gb_market": [Decimal("0.8")],
        },
    ):
        with patch("fetch_sma.upsert_market_stats") as mock_upsert:
            with patch("fetch_sma.update_z_scores_for_week") as mock_z:
                upsert_market_for_weeks(
                    "postgresql://example",
                    {week_start},
                )

    assert mock_upsert.call_count == 3
    mock_z.assert_called_once_with(
        "postgresql://example", week_start, country=None
    )
    rows_by_market = {
        call.args[1].market: call.args[1]
        for call in mock_upsert.call_args_list
    }
    us_row = rows_by_market["us_market"]
    se_row = rows_by_market["se_market"]
    uk_row = rows_by_market["gb_market"]
    assert us_row.week_start == week_start
    assert us_row.momentum_mean == Decimal("2")
    assert us_row.momentum_std == Decimal("1")
    assert se_row.market == "se_market"
    assert se_row.momentum_mean == Decimal("0.6")
    assert uk_row.market == "gb_market"
    assert uk_row.momentum_mean == Decimal("0.8")


def test_upsert_market_for_weeks_skips_null_market_bucket() -> None:
    with patch(
        "fetch_sma.load_momentum_by_market_for_week",
        return_value={
            None: [Decimal("0.9")],
            "se_market": [Decimal("0.6")],
        },
    ):
        with patch("fetch_sma.upsert_market_stats") as mock_upsert:
            with patch("fetch_sma.update_z_scores_for_week"):
                upsert_market_for_weeks(
                    "postgresql://example",
                    {date(2026, 6, 6)},
                )

    mock_upsert.assert_called_once()
    assert mock_upsert.call_args[0][1].market == "se_market"


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
        company="Apple Inc.",
        trading_date=date(2026, 6, 5),
        sma_50=Decimal("100.0"),
        sma_200=Decimal("90.0"),
        current_price=Decimal("105.0"),
    )
    assert row.ticker == "AAPL"


def test_chunked_splits_evenly() -> None:
    assert chunked(["A", "B", "C", "D", "E"], 2) == [
        ["A", "B"],
        ["C", "D"],
        ["E"],
    ]
    assert chunked(["A"], 40) == [["A"]]
    assert chunked([], 40) == []


def test_metric_row_from_history() -> None:
    index = pd.date_range("2025-01-01", periods=220, freq="B")
    history = pd.DataFrame(
        {
            "Open": range(220),
            "High": range(220),
            "Low": range(220),
            "Close": range(1, 221),
            "Volume": [1000] * 220,
        },
        index=index,
    )

    row = metric_row_from_history(
        "VOLV-A.ST",
        history,
        company="AB Volvo",
        currency="SEK",
    )

    assert row is not None
    assert row.ticker == "VOLV-A.ST"
    assert row.company == "AB Volvo"
    assert row.currency == "SEK"
    assert row.trading_date == index[-1].date()
    assert row.sma_50 == Decimal("195.5")
    assert row.sma_200 == Decimal("120.5")
    assert row.current_price == Decimal("220")
    assert row.momentum == Decimal("1.622407")
    assert row.z_score is None

def test_metric_rows_from_batch_parses_multiindex() -> None:
    index = pd.date_range("2025-01-01", periods=220, freq="B")
    columns = pd.MultiIndex.from_product(
        [["AAA.ST", "BBB.ST"], ["Open", "High", "Low", "Close", "Volume"]]
    )
    data = pd.DataFrame(index=index, columns=columns, dtype=float)
    for field in ("Open", "High", "Low", "Close", "Volume"):
        data[("AAA.ST", field)] = 1.0
        data[("BBB.ST", field)] = 2.0
    data[("AAA.ST", "Close")] = range(1, 221)
    data[("BBB.ST", "Close")] = range(2, 222)

    companies = {"AAA.ST": "Alpha AB", "BBB.ST": "Beta AB"}
    currencies = {"AAA.ST": "SEK", "BBB.ST": "USD"}
    rows = metric_rows_from_batch(data, ["AAA.ST", "BBB.ST"], companies, currencies)

    assert len(rows) == 2
    assert {row.ticker for row in rows} == {"AAA.ST", "BBB.ST"}
    assert {row.company for row in rows} == {"Alpha AB", "Beta AB"}
    by_ticker = {row.ticker: row for row in rows}
    assert by_ticker["AAA.ST"].currency == "SEK"
    assert by_ticker["BBB.ST"].currency == "USD"


def _mock_metrics_conn(mock_cursor: MagicMock) -> MagicMock:
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    return mock_conn


def test_current_week_start_returns_monday() -> None:
    assert current_week_start(today=date(2026, 9, 24)) == date(2026, 9, 21)  # Thu
    assert current_week_start(today=date(2026, 9, 21)) == date(2026, 9, 21)  # Mon
    assert current_week_start(today=date(2026, 9, 27)) == date(2026, 9, 21)  # Sun


def test_expected_latest_bar_is_friday_on_weekends() -> None:
    assert expected_latest_bar(today=date(2026, 9, 26)) == date(2026, 9, 25)  # Sat
    assert expected_latest_bar(today=date(2026, 9, 27)) == date(2026, 9, 25)  # Sun
    assert expected_latest_bar(today=date(2026, 9, 24)) == date(2026, 9, 24)  # Thu


def test_filter_stale_tickers_skips_tickers_with_row_this_week() -> None:
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [("AAA.ST",), ("BBB.ST",)]

    with patch(
        "db.metrics.psycopg2.connect", return_value=_mock_metrics_conn(mock_cursor)
    ):
        stale, skipped, week_start = filter_stale_tickers(
            "postgresql://example",
            ["AAA.ST", "BBB.ST", "CCC.ST"],
            today=date(2026, 9, 24),
        )

    assert stale == ["CCC.ST"]
    assert skipped == 2
    assert week_start == date(2026, 9, 21)
    mock_cursor.execute.assert_called_once()
    sql, params = mock_cursor.execute.call_args[0]
    assert "FROM swe_metrics" in sql
    assert "week_start = %s" in sql
    assert "trading_date >= %s" in sql
    assert params == (
        ["AAA.ST", "BBB.ST", "CCC.ST"],
        date(2026, 9, 21),
        date(2026, 9, 24),
    )


def test_filter_stale_tickers_refetches_when_whole_table_is_behind() -> None:
    """Rows from a previous week are stale even if every ticker shares that date."""
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []

    tickers = ["AAPL", "MSFT"]
    with patch(
        "db.metrics.psycopg2.connect", return_value=_mock_metrics_conn(mock_cursor)
    ):
        stale, skipped, _week_start = filter_stale_tickers(
            "postgresql://example",
            tickers,
            today=date(2026, 9, 24),
        )

    assert stale == tickers
    assert skipped == 0


def test_filter_stale_tickers_evaluates_each_country_table() -> None:
    mock_cursor = MagicMock()
    # First-seen order: US, SWE, UK.
    mock_cursor.fetchall.side_effect = [
        [("AAPL",)],
        [("VOLV-B.ST",)],
        [("VOD.L",)],
    ]

    with patch(
        "db.metrics.psycopg2.connect", return_value=_mock_metrics_conn(mock_cursor)
    ):
        stale, skipped, _week_start = filter_stale_tickers(
            "postgresql://example",
            ["AAPL", "MSFT", "VOLV-B.ST", "ERIC-B.ST", "VOD.L", "BP.L"],
            today=date(2026, 9, 24),
        )

    assert stale == ["MSFT", "ERIC-B.ST", "BP.L"]
    assert skipped == 3
    calls = mock_cursor.execute.call_args_list
    assert "FROM us_metrics" in calls[0][0][0]
    week = (date(2026, 9, 21), date(2026, 9, 24))
    assert calls[0][0][1] == (["AAPL", "MSFT"], *week)
    assert "FROM swe_metrics" in calls[1][0][0]
    assert calls[1][0][1] == (["VOLV-B.ST", "ERIC-B.ST"], *week)
    assert "FROM uk_metrics" in calls[2][0][0]
    assert calls[2][0][1] == (["VOD.L", "BP.L"], *week)


def test_insert_metrics_executes_values() -> None:
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 1
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    rows = [
        MetricRow(
            ticker="AAA.ST",
            company="Alpha",
            trading_date=date(2026, 6, 6),
            sma_50=Decimal("1"),
            sma_200=Decimal("2"),
            current_price=Decimal("3"),
        )
    ]

    with patch("db.metrics.psycopg2.connect", return_value=mock_conn):
        with patch("db.metrics.execute_values") as mock_execute:
            inserted = insert_metrics("postgresql://example", rows)

    mock_execute.assert_called_once()
    mock_conn.commit.assert_called_once()
    assert inserted == 1
    sql = mock_execute.call_args[0][1]
    assert "company" in sql
    assert "currency" in sql
    assert "momentum" in sql
    assert "z_score" in sql
    assert "raw_50" not in sql
    assert "raw_200" not in sql
    assert "sector" not in sql
    assert "industry" not in sql
    assert "ON CONFLICT (ticker, week_start) DO UPDATE" in sql
    assert "WHERE EXCLUDED.trading_date > swe_metrics.trading_date" in sql
    values = mock_execute.call_args[0][2]
    assert values[0][1] == "Alpha"  # company
    assert values[0][2] == date(2026, 6, 1)  # week_start
    assert values[0][3] == date(2026, 6, 6)  # trading_date
    assert values[0][5] is None  # currency


def test_insert_metrics_routes_uk_ticker_to_uk_metrics() -> None:
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 1
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    rows = [
        MetricRow(
            ticker="VOD.L",
            company="Vodafone",
            trading_date=date(2026, 6, 6),
            sma_50=Decimal("1"),
            sma_200=Decimal("2"),
            current_price=Decimal("3"),
            currency="GBp",
            momentum=Decimal("0.5"),
            z_score=None,
        )
    ]
    with patch("db.metrics.psycopg2.connect", return_value=mock_conn):
        with patch("db.metrics.execute_values") as mock_execute:
            inserted = insert_metrics("postgresql://example", rows)

    mock_execute.assert_called_once()
    assert inserted == 1
    sql = mock_execute.call_args[0][1]
    assert "INSERT INTO uk_metrics" in sql
    assert "INSERT INTO us_metrics" not in sql
    assert "INSERT INTO swe_metrics" not in sql
    assert "ON CONFLICT (ticker, week_start) DO UPDATE" in sql
    values = mock_execute.call_args[0][2]
    assert values[0][0] == "VOD.L"
    assert values[0][1] == "Vodafone"
    assert values[0][5] == "GBp"


IDX_W1 = date(2026, 6, 1)
IDX_W2 = date(2026, 6, 8)
IDX_D1 = date(2026, 6, 5)
IDX_D2 = date(2026, 6, 12)
IDX_START = date(2026, 5, 29)


def _index_config(**overrides) -> "BaseConfig":
    from config import BaseConfig

    return BaseConfig(
        database_url="postgresql://example",
        index_start_date=IDX_START,
        yf_batch_delay_seconds=0,
        **overrides,
    )


def _closes_frame(closes: dict[str, list[float]], start: str = "2026-06-01") -> pd.DataFrame:
    index = pd.bdate_range(start, periods=len(next(iter(closes.values()))))
    return pd.concat(
        {symbol: pd.DataFrame({"Close": values}, index=index) for symbol, values in closes.items()},
        axis=1,
    )


def test_fold_index_history_adds_returns_to_market_and_sector() -> None:
    from db.country import CountrySet
    from fetch_sma import IndexHistory, fold_index_history

    entries = {
        "AAA": TickerEntry("AAA", "A", sector="Energy"),
        "BBB.ST": TickerEntry("BBB.ST", "B"),
    }
    data = _closes_frame(
        {"AAA": [10.0, 11.0, 12.1], "BBB.ST": [5.0, 100.0, 100.0], "ZZZ": [1.0, 1.0, 1.0]}
    )
    history = IndexHistory()
    fold_index_history(
        history, data, ["AAA", "BBB.ST", "ZZZ"], entries, max_growth=9.0, min_growth=-0.999
    )

    assert history.folded == {"AAA", "BBB.ST"}
    assert history.accumulator.averages("US-IDX") == pytest.approx(
        {date(2026, 6, 2): 0.1, date(2026, 6, 3): 0.1}
    )
    assert history.accumulator.averages("US-IDX-ENERGY") == history.accumulator.averages(
        "US-IDX"
    )
    assert history.accumulator.averages("SWE-IDX") == pytest.approx({date(2026, 6, 3): 0.0})
    assert history.dropped == {CountrySet.US: 0, CountrySet.SWE: 1}


def test_fold_missing_members_downloads_only_unfolded(caplog) -> None:
    from fetch_sma import IndexHistory, _fold_missing_members

    watchlist = [TickerEntry(s, s, sector="Energy") for s in ("A", "B", "C")]
    history = IndexHistory()
    history.folded.add("A")
    start = date(2025, 5, 1)

    def download(batch, start, **kwargs):
        if batch == ["B"]:
            raise RuntimeError("rate limited")
        return _closes_frame({s: [1.0, 1.1] for s in batch})

    with patch("fetch_sma.download_batch", side_effect=download) as mock_download:
        with caplog.at_level("INFO", logger="fetch_sma"):
            _fold_missing_members(_index_config(yf_batch_size=1), watchlist, history, start)

    assert [c.args for c in mock_download.call_args_list] == [(["B"], start), (["C"], start)]
    assert history.folded == {"A", "C"}
    assert "downloading 2 member(s) not in this run" in caplog.text
    assert "Failed index history batch 1/2" in caplog.text

    with patch("fetch_sma.download_batch") as mock_download:
        _fold_missing_members(_index_config(), watchlist[:1], history, start)
    mock_download.assert_not_called()


def _history(averages: dict[str, dict[date, float]]):
    from fetch_sma import IndexHistory

    history = IndexHistory()
    for ticker, returns in averages.items():
        history.accumulator.add([ticker], returns)
    return history


def _week_days(week: date, changes: list[float]) -> dict[date, float]:
    return {week + timedelta(days=i): change for i, change in enumerate(changes)}


def _patch_index_io(stored_tickers: dict, *, pins=None, tickers=None, series=None):
    from contextlib import ExitStack

    from db.indices import IndexWriteResult

    stack = ExitStack()
    mocks = {
        "stored": stack.enter_context(
            patch(
                "fetch_sma.load_index_tickers",
                side_effect=lambda url, country: stored_tickers.get(country, set()),
            )
        ),
        "previous": stack.enter_context(
            patch(
                "fetch_sma.load_previous_indices",
                side_effect=lambda url, country, before: (pins or {}).get(country, {}),
            )
        ),
        "weeks": stack.enter_context(
            patch(
                "fetch_sma.load_distinct_week_starts",
                return_value=[date(2026, 5, 18), IDX_W1, IDX_W2],
            )
        ),
        "write": stack.enter_context(
            patch("fetch_sma.write_index_weeks", return_value=IndexWriteResult([]))
        ),
        "outliers": stack.enter_context(patch("fetch_sma.load_outliers", return_value=[])),
        "tickers": stack.enter_context(
            patch("fetch_sma.load_tickers_from_db", return_value=tickers or [])
        ),
        "series": stack.enter_context(
            patch("fetch_sma.compute_index_series", return_value=series)
        ),
    }
    return stack, mocks


def test_run_index_update_chains_price_from_previous_row() -> None:
    """Spec US2 scenario 1: 105 and a +1% day → 105 × 1.01, SMAs from the series."""
    from db.country import CountrySet
    from fetch_sma import _run_index_update

    history = _history(
        {"US-IDX": {IDX_D1: 0.0, **_week_days(IDX_W2, [0.01, 0.0, 0.0, 0.0, 0.0])}}
    )
    stack, mocks = _patch_index_io(
        {CountrySet.US: {"US-IDX"}},
        pins={CountrySet.US: {"US-IDX": (IDX_D1, Decimal("105"))}},
    )
    with stack:
        _run_index_update(_index_config(), {IDX_W2}, history)

    mocks["previous"].assert_called_once_with("postgresql://example", CountrySet.US, IDX_W2)
    (url, levels), kwargs = mocks["write"].call_args
    assert kwargs == {"country": CountrySet.US, "only_tickers": {"US-IDX"}}
    row = levels[IDX_W2]["US-IDX"]
    assert row.trading_date == IDX_D2
    assert row.levels.current_price == Decimal("106.05")
    assert row.levels.sma_50 == Decimal(str(round((105 + 5 * 106.05) / 6, 6)))
    assert row.days_used == 6
    assert mocks["outliers"].call_count == 1


def test_run_index_update_chains_over_missed_week() -> None:
    """Spec US2 scenario 2: every day since the pin counts once."""
    from db.country import CountrySet
    from fetch_sma import _run_index_update

    history = _history(
        {
            "US-IDX": {
                IDX_START: 0.0,
                **_week_days(IDX_W1, [0.01, 0.0, 0.0, 0.0, 0.0]),
                **_week_days(IDX_W2, [0.01, 0.0, 0.0, 0.0, 0.0]),
            }
        }
    )
    stack, mocks = _patch_index_io(
        {CountrySet.US: {"US-IDX"}},
        pins={CountrySet.US: {"US-IDX": (IDX_START, Decimal("105"))}},
    )
    with stack:
        _run_index_update(_index_config(), {IDX_W2}, history)

    levels = mocks["write"].call_args.args[1]
    assert list(levels) == [IDX_W2]
    assert levels[IDX_W2]["US-IDX"].levels.current_price == Decimal("107.1105")


def test_run_index_update_errors_when_pin_older_than_history(caplog) -> None:
    from db.country import CountrySet
    from fetch_sma import _run_index_update

    history = _history({"US-IDX": _week_days(IDX_W2, [0.01, 0.0])})
    stack, mocks = _patch_index_io(
        {CountrySet.US: {"US-IDX", "US-IDX-ENERGY"}},
        pins={
            CountrySet.US: {
                "US-IDX": (date(2025, 1, 3), Decimal("90")),
                "US-IDX-ENERGY": (IDX_D1, Decimal("100")),
            }
        },
    )
    with stack, caplog.at_level("WARNING", logger="fetch_sma"):
        _run_index_update(_index_config(), {IDX_W2}, history)

    mocks["write"].assert_not_called()
    assert (
        "Index US-IDX: latest stored row 2025-01-03 is older than the downloaded daily "
        "history; run compute_indices.py --country us"
    ) in caplog.text
    assert "Index US-IDX-ENERGY: latest stored row" in caplog.text


def test_run_index_update_warns_when_week_has_no_daily_data(caplog) -> None:
    from db.country import CountrySet
    from fetch_sma import _run_index_update

    history = _history({"US-IDX": {IDX_START: 0.0, IDX_D1: 0.01}})
    stack, mocks = _patch_index_io(
        {CountrySet.US: {"US-IDX"}},
        pins={CountrySet.US: {"US-IDX": (IDX_START, Decimal("100"))}},
    )
    with stack, caplog.at_level("WARNING", logger="fetch_sma"):
        _run_index_update(_index_config(), {IDX_W2}, history)

    mocks["write"].assert_not_called()
    assert f"Index US-IDX: no daily data in week {IDX_W2.isoformat()}" in caplog.text


def test_run_index_update_warns_for_country_without_indices(caplog) -> None:
    from db.country import CountrySet
    from fetch_sma import IndexHistory, _run_index_update

    stack, mocks = _patch_index_io({CountrySet.US: {"US-IDX"}})
    with stack, caplog.at_level("WARNING", logger="fetch_sma"):
        _run_index_update(_index_config(), {IDX_W2}, IndexHistory())

    assert [c.args[1] for c in mocks["previous"].call_args_list] == [CountrySet.US]
    assert "country swe has no indices; run compute_indices.py --country swe" in caplog.text
    assert "country uk has no indices" in caplog.text


def test_run_index_update_starts_new_sector_from_its_series() -> None:
    from db.country import CountrySet
    from fetch_sma import IndexHistory, _run_index_update
    from index_anchor import IndexSeries, SeriesResult

    members = [TickerEntry(s, s, sector="Utilities") for s in "ABCDE"]
    days = pd.bdate_range(IDX_START, IDX_D2)
    series = IndexSeries("US-IDX-UTILITIES", IDX_START, {d.date(): 100.0 for d in days})
    stack, mocks = _patch_index_io(
        {CountrySet.US: {"US-IDX", "US-IDX-ENERGY"}},
        tickers=[TickerEntry("X", "X", sector="Energy"), *members],
        series=SeriesResult(series={series.ticker: series}),
    )
    with stack:
        _run_index_update(_index_config(), {IDX_W2}, IndexHistory())

    series_call = mocks["series"].call_args
    assert series_call.args == (members, CountrySet.US)
    assert series_call.kwargs["index_tickers"] == {"US-IDX-UTILITIES"}
    assert series_call.kwargs["settings"].start_date == IDX_START
    (url, levels), kwargs = mocks["write"].call_args
    assert kwargs == {"country": CountrySet.US, "only_tickers": {"US-IDX-UTILITIES"}}
    assert sorted(levels) == [IDX_W1, IDX_W2]
    assert levels[IDX_W2]["US-IDX-UTILITIES"].trading_date == IDX_D2


def test_run_index_update_new_sector_without_series_warns(caplog) -> None:
    from db.country import CountrySet
    from fetch_sma import IndexHistory, _run_index_update
    from index_anchor import SeriesResult

    members = [TickerEntry(s, s, sector="Utilities") for s in "ABCDE"]
    stack, mocks = _patch_index_io(
        {CountrySet.US: {"US-IDX"}},
        tickers=members,
        series=SeriesResult(below_minimum={"US-IDX-UTILITIES"}),
    )
    with stack, caplog.at_level("WARNING", logger="fetch_sma"):
        _run_index_update(_index_config(), {IDX_W2}, IndexHistory())

    mocks["write"].assert_not_called()
    assert "New sector index US-IDX-UTILITIES not started" in caplog.text


def test_run_index_update_skips_sector_with_too_few_stocks() -> None:
    from db.country import CountrySet
    from fetch_sma import IndexHistory, _run_index_update

    stack, mocks = _patch_index_io(
        {CountrySet.US: {"US-IDX"}},
        tickers=[TickerEntry("A", "A", sector="Utilities")],
    )
    with stack:
        _run_index_update(_index_config(), {IDX_W2}, IndexHistory())

    mocks["series"].assert_not_called()


def test_run_index_update_new_sector_failure_does_not_stop_update(caplog) -> None:
    from db.country import CountrySet
    from fetch_sma import _run_index_update

    members = [TickerEntry(s, s, sector="Utilities") for s in "ABCDE"]
    history = _history({"US-IDX": {IDX_D1: 0.0, IDX_D2: 0.01}})
    stack, mocks = _patch_index_io(
        {CountrySet.US: {"US-IDX"}},
        pins={CountrySet.US: {"US-IDX": (IDX_D1, Decimal("100"))}},
        tickers=members,
    )
    mocks["series"].side_effect = RuntimeError("yfinance down")
    with stack, caplog.at_level("ERROR", logger="fetch_sma"):
        _run_index_update(_index_config(), {IDX_W2}, history)

    assert "Failed to start new us sector indices" in caplog.text
    assert mocks["write"].call_count == 1


def test_main_folds_downloaded_batches_into_index_history() -> None:
    from contextlib import ExitStack
    from datetime import datetime, timezone

    from fetch_sma import main

    entry = TickerEntry("AAA", "Alpha", sector="Energy")
    data = _closes_frame({"AAA": [10.0, 11.0]})
    with ExitStack() as stack:
        stack.enter_context(patch("fetch_sma.get_config", return_value=_index_config()))
        stack.enter_context(patch("fetch_sma.load_tickers_from_db", return_value=[entry]))
        stack.enter_context(
            patch("fetch_sma.filter_stale_tickers", return_value=(["AAA"], 0, None))
        )
        stack.enter_context(patch("fetch_sma.load_currency_for_tickers", return_value={}))
        download = stack.enter_context(patch("fetch_sma.download_batch", return_value=data))
        stack.enter_context(
            patch(
                "fetch_sma.metric_rows_from_batch",
                return_value=[
                    MetricRow("AAA", "Alpha", date(2026, 6, 2), None, None, Decimal("11"))
                ],
            )
        )
        stack.enter_context(patch("fetch_sma.insert_metrics", return_value=1))
        stack.enter_context(patch("fetch_sma.upsert_market_for_weeks"))
        stack.enter_context(patch("fetch_sma.purge_stale_data", return_value=(0, 0, 0)))
        stack.enter_context(patch("fetch_sma._run_outlier_email", return_value=(0, 0)))
        update = stack.enter_context(patch("fetch_sma._run_index_update"))
        assert main() == 0

    download.assert_called_once()
    today = datetime.now(timezone.utc).date()
    assert download.call_args.args[1] == today - timedelta(days=400)
    history = update.call_args.args[2]
    assert history.folded == {"AAA"}
    assert history.accumulator.averages("US-IDX-ENERGY") == pytest.approx(
        {date(2026, 6, 2): 0.1}
    )


def test_fetch_sma_no_longer_imports_compute_indices() -> None:
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "fetch_sma.py").read_text()
    assert "compute_indices import" not in source
