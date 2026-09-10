"""Unit tests for Golden Cross detection (RFC-013)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from config import (
    DEFAULT_GOLDEN_CROSS_CONVERGENCE_WEEKS,
    DEFAULT_GOLDEN_CROSS_MIN_BELOW_WEEKS,
    BaseConfig,
    DevConfig,
)
from db.country import CountrySet
from db.metrics import load_sma_history
from detect_golden_cross import (
    build_parser,
    collect_events,
    format_events_csv,
    format_events_json,
    format_events_table,
    main,
)
from golden_cross import (
    GoldenCrossParams,
    GoldenCrossStage,
    classify_series_stages,
    detect_crossover_indices,
    detect_golden_crosses,
    gap_is_narrowing,
)
from models import SmaSnapshot


def _d(n: int) -> date:
    """Thursday-ish weekly dates from a fixed epoch."""
    return date(2025, 1, 2) + timedelta(weeks=n)


def _pt(week: int, sma_50: str | None, sma_200: str | None) -> SmaSnapshot:
    return SmaSnapshot(
        trading_date=_d(week),
        sma_50=None if sma_50 is None else Decimal(sma_50),
        sma_200=None if sma_200 is None else Decimal(sma_200),
    )


def _clear_golden_series() -> list[SmaSnapshot]:
    """Below for 5 weeks with narrowing gap, then cross above."""
    return [
        _pt(0, "90", "100"),  # gap 10
        _pt(1, "91", "100"),  # gap 9
        _pt(2, "93", "100"),  # gap 7
        _pt(3, "95", "100"),  # gap 5
        _pt(4, "98", "100"),  # gap 2  (convergence window start default=3 → weeks 2–4)
        _pt(5, "101", "100"),  # cross
        _pt(6, "103", "100"),
    ]


def test_gap_is_narrowing_requires_shrink() -> None:
    assert gap_is_narrowing([Decimal("10"), Decimal("8"), Decimal("5")])
    assert not gap_is_narrowing([Decimal("5"), Decimal("5")])
    assert not gap_is_narrowing([Decimal("5"), Decimal("7")])
    assert not gap_is_narrowing([Decimal("5")])


def test_detect_crossover_indices_finds_below_to_above() -> None:
    series = [
        _pt(0, "90", "100"),
        _pt(1, "95", "100"),
        _pt(2, "100", "100"),  # at/above
        _pt(3, "105", "100"),
    ]
    assert detect_crossover_indices(series) == [2]


def test_clear_golden_cross_emits_event_with_stages() -> None:
    events = detect_golden_crosses(
        _clear_golden_series(), ticker="AAPL", country="us"
    )
    assert len(events) == 1
    event = events[0]
    assert event.ticker == "AAPL"
    assert event.country == "us"
    assert event.trading_date == _d(5)
    assert event.weeks_below == 5
    assert event.converged is True
    assert event.gap_before_cross == Decimal("2")
    assert event.sma_50 == Decimal("101")
    assert event.sma_200 == Decimal("100")

    stages = [a.stage for a in event.stages]
    assert stages[-1] is GoldenCrossStage.CROSSOVER
    assert GoldenCrossStage.DOWNTREND in stages
    assert GoldenCrossStage.CONVERGENCE in stages
    # Last 3 below weeks are convergence under defaults
    assert [a.stage for a in event.stages[-4:-1]] == [
        GoldenCrossStage.CONVERGENCE,
        GoldenCrossStage.CONVERGENCE,
        GoldenCrossStage.CONVERGENCE,
    ]


def test_no_cross_while_sma50_stays_below() -> None:
    series = [
        _pt(0, "80", "100"),
        _pt(1, "82", "100"),
        _pt(2, "85", "100"),
        _pt(3, "88", "100"),
        _pt(4, "90", "100"),
        _pt(5, "92", "100"),
    ]
    assert detect_golden_crosses(series, ticker="X", country="us") == []


def test_death_cross_is_not_golden_cross() -> None:
    """Above → below must not emit a golden-cross event."""
    series = [
        _pt(0, "110", "100"),
        _pt(1, "108", "100"),
        _pt(2, "105", "100"),
        _pt(3, "102", "100"),
        _pt(4, "99", "100"),  # death cross
        _pt(5, "95", "100"),
    ]
    assert detect_golden_crosses(series, ticker="X", country="us") == []


def test_cross_without_enough_below_weeks_rejected() -> None:
    series = [
        _pt(0, "110", "100"),
        _pt(1, "99", "100"),  # only 1 week below
        _pt(2, "98", "100"),
        _pt(3, "101", "100"),  # cross after 2 below — default needs 4
    ]
    assert detect_golden_crosses(series, ticker="X", country="us") == []


def test_cross_without_convergence_rejected() -> None:
    """Gap widens into the cross — stage 2 fails."""
    series = [
        _pt(0, "95", "100"),  # gap 5
        _pt(1, "94", "100"),  # gap 6
        _pt(2, "93", "100"),  # gap 7
        _pt(3, "92", "100"),  # gap 8
        _pt(4, "91", "100"),  # gap 9
        _pt(5, "101", "100"),  # abrupt cross without narrowing
    ]
    assert detect_golden_crosses(series, ticker="X", country="us") == []


def test_null_sma_rows_are_skipped() -> None:
    series = [
        _pt(0, "90", "100"),
        _pt(1, None, "100"),
        _pt(2, "91", None),
        _pt(3, "93", "100"),
        _pt(4, "95", "100"),
        _pt(5, "98", "100"),
        _pt(6, "101", "100"),
    ]
    events = detect_golden_crosses(series, ticker="AAPL", country="us")
    assert len(events) == 1
    assert events[0].trading_date == _d(6)
    assert events[0].weeks_below == 4  # null rows dropped from run


def test_equal_smas_count_as_crossover() -> None:
    series = [
        _pt(0, "90", "100"),
        _pt(1, "92", "100"),
        _pt(2, "94", "100"),
        _pt(3, "96", "100"),
        _pt(4, "98", "100"),
        _pt(5, "100", "100"),  # at/above
    ]
    events = detect_golden_crosses(series, ticker="EQ", country="us")
    assert len(events) == 1
    assert events[0].sma_50 == Decimal("100")


def test_multi_ticker_and_country_via_collect() -> None:
    history = {
        (CountrySet.US, "AAPL"): _clear_golden_series(),
        (CountrySet.SWE, "VOLV-B.ST"): [
            _pt(0, "80", "100"),
            _pt(1, "81", "100"),
            _pt(2, "82", "100"),
            _pt(3, "83", "100"),
            _pt(4, "84", "100"),
        ],
        (CountrySet.UK, "VOD.L"): _clear_golden_series(),
    }

    with patch(
        "detect_golden_cross.load_sma_history", return_value=history
    ):
        events = collect_events(
            "postgresql://example",
            country=None,
            tickers=None,
            params=GoldenCrossParams(),
        )

    tickers = {(e.country, e.ticker) for e in events}
    assert tickers == {("us", "AAPL"), ("uk", "VOD.L")}
    assert all(e.trading_date == _d(5) for e in events)


def test_classify_series_stages_labels_process() -> None:
    annotations = classify_series_stages(
        _clear_golden_series(), ticker="AAPL", country="us"
    )
    by_date = {a.trading_date: a.stage for a in annotations}
    assert by_date[_d(0)] is GoldenCrossStage.DOWNTREND
    assert by_date[_d(4)] is GoldenCrossStage.CONVERGENCE
    assert by_date[_d(5)] is GoldenCrossStage.CROSSOVER
    assert _d(6) not in by_date  # post-cross not part of process window


def test_params_validation() -> None:
    with pytest.raises(ValueError, match="min_below_weeks"):
        GoldenCrossParams(min_below_weeks=0)
    with pytest.raises(ValueError, match="convergence_weeks"):
        GoldenCrossParams(min_below_weeks=4, convergence_weeks=5)


def test_load_sma_history_all_countries() -> None:
    mock_cursor = MagicMock()
    mock_cursor.fetchall.side_effect = [
        [("AAPL", date(2025, 1, 2), Decimal("10"), Decimal("20"))],
        [("VOLV-B.ST", date(2025, 1, 2), Decimal("1"), Decimal("2"))],
        [("VOD.L", date(2025, 1, 2), Decimal("3"), Decimal("4"))],
    ]
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.metrics.psycopg2.connect", return_value=mock_conn):
        history = load_sma_history("postgresql://example")

    assert set(history) == {
        (CountrySet.US, "AAPL"),
        (CountrySet.SWE, "VOLV-B.ST"),
        (CountrySet.UK, "VOD.L"),
    }
    assert history[(CountrySet.US, "AAPL")][0].sma_50 == Decimal("10")
    assert mock_cursor.execute.call_count == 3


def test_load_sma_history_scopes_country_and_tickers() -> None:
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        ("AAPL", date(2025, 1, 2), Decimal("10"), Decimal("20")),
    ]
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.metrics.psycopg2.connect", return_value=mock_conn):
        history = load_sma_history(
            "postgresql://example",
            country=CountrySet.US,
            tickers=["AAPL"],
        )

    assert list(history) == [(CountrySet.US, "AAPL")]
    sql = mock_cursor.execute.call_args[0][0]
    assert "FROM us_metrics" in sql
    assert "WHERE ticker = ANY(%s)" in sql
    assert mock_cursor.execute.call_args[0][1] == (["AAPL"],)


def test_format_table_and_json_and_csv() -> None:
    events = detect_golden_crosses(
        _clear_golden_series(), ticker="AAPL", country="us"
    )
    table = StringIO()
    format_events_table(events, table)
    assert "AAPL" in table.getvalue()
    assert "2025-02-06" in table.getvalue() or _d(5).isoformat() in table.getvalue()

    empty = StringIO()
    format_events_table([], empty)
    assert "No golden-cross" in empty.getvalue()

    js = StringIO()
    format_events_json(events, js)
    assert '"ticker": "AAPL"' in js.getvalue()
    assert '"stage": "crossover"' in js.getvalue()

    csv_buf = StringIO()
    format_events_csv(events, csv_buf)
    assert "ticker,country,trading_date" in csv_buf.getvalue()
    assert "AAPL,us," in csv_buf.getvalue()


def test_cli_parser_country_choices() -> None:
    parser = build_parser()
    args = parser.parse_args(["--country", "swe", "--format", "json"])
    assert args.country == "swe"
    assert args.format == "json"


def test_main_prints_events(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://example")
    history = {(CountrySet.US, "AAPL"): _clear_golden_series()}

    with (
        patch("detect_golden_cross.get_config") as mock_config,
        patch("detect_golden_cross.load_sma_history", return_value=history),
        patch("sys.stdout", new_callable=StringIO) as stdout,
    ):
        mock_config.return_value = BaseConfig(
            database_url="postgresql://example",
            golden_cross_min_below_weeks=DEFAULT_GOLDEN_CROSS_MIN_BELOW_WEEKS,
            golden_cross_convergence_weeks=(
                DEFAULT_GOLDEN_CROSS_CONVERGENCE_WEEKS
            ),
        )
        code = main([])

    assert code == 0
    assert "AAPL" in stdout.getvalue()


def test_main_rejects_bad_params(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://example")
    with patch("detect_golden_cross.get_config") as mock_config:
        mock_config.return_value = BaseConfig(database_url="postgresql://example")
        code = main(["--min-below-weeks", "2", "--convergence-weeks", "5"])
    assert code == 1


def test_dev_config_loads_golden_cross_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://dev")
    monkeypatch.setenv("GOLDEN_CROSS_MIN_BELOW_WEEKS", "6")
    monkeypatch.setenv("GOLDEN_CROSS_CONVERGENCE_WEEKS", "4")

    with patch("dotenv.load_dotenv"):
        config = DevConfig.load()

    assert config.golden_cross_min_below_weeks == 6
    assert config.golden_cross_convergence_weeks == 4
