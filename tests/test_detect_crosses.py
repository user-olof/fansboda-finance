"""CLI and DB wiring tests for RFC-013 cross detection."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from cross_detection import CrossEvent, CrossPattern
from db.country import CountrySet
from db.metrics import (
    LOAD_SMA_HISTORY_FOR_SYMBOLS_SQL,
    LOAD_SMA_HISTORY_SQL,
    load_sma_history,
)
from detect_crosses import (
    build_parser,
    collect_cross_events,
    format_events,
    main,
)


def _event(**overrides: object) -> CrossEvent:
    values: dict[str, object] = {
        "pattern": CrossPattern.GOLDEN,
        "ticker": "AAPL",
        "country": "us",
        "crossover_date": date(2025, 2, 3),
        "regime_start_date": date(2025, 1, 6),
        "regime_weeks": 4,
        "convergence_first_gap": Decimal("8"),
        "convergence_last_gap": Decimal("4"),
        "sma_50": Decimal("105"),
        "sma_200": Decimal("100"),
    }
    values.update(overrides)
    return CrossEvent(**values)  # type: ignore[arg-type]


def test_build_parser_defaults() -> None:
    args = build_parser().parse_args([])
    assert args.pattern == "all"
    assert args.country is None
    assert args.symbols is None
    assert args.output_format == "table"


def test_build_parser_flags() -> None:
    args = build_parser().parse_args(
        ["--pattern", "death", "--country", "uk", "--symbols", "vod.l", "--format", "json"]
    )
    assert args.pattern == "death"
    assert args.country == "uk"
    assert args.symbols == "vod.l"
    assert args.output_format == "json"


def test_load_sma_history_sql_is_parameterized() -> None:
    assert "SELECT ticker, trading_date, sma_50, sma_200" in LOAD_SMA_HISTORY_SQL[CountrySet.US]
    assert "FROM us_metrics" in LOAD_SMA_HISTORY_SQL[CountrySet.US]
    assert "FROM swe_metrics" in LOAD_SMA_HISTORY_SQL[CountrySet.SWE]
    assert "FROM uk_metrics" in LOAD_SMA_HISTORY_SQL[CountrySet.UK]
    assert "WHERE ticker = ANY(%s)" in LOAD_SMA_HISTORY_FOR_SYMBOLS_SQL[CountrySet.US]
    assert "%s" in LOAD_SMA_HISTORY_FOR_SYMBOLS_SQL[CountrySet.US]


def test_load_sma_history_all_symbols() -> None:
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        ("AAPL", date(2025, 1, 6), Decimal("90"), Decimal("100")),
        ("AAPL", date(2025, 1, 13), Decimal("92"), Decimal("100")),
        ("MSFT", date(2025, 1, 6), Decimal("110"), Decimal("100")),
    ]
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.metrics.psycopg2.connect", return_value=mock_conn):
        history = load_sma_history("postgresql://example", country=CountrySet.US)

    mock_cursor.execute.assert_called_once_with(LOAD_SMA_HISTORY_SQL[CountrySet.US])
    assert list(history.keys()) == ["AAPL", "MSFT"]
    assert history["AAPL"][0][0] == date(2025, 1, 6)


def test_load_sma_history_filters_symbols() -> None:
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("db.metrics.psycopg2.connect", return_value=mock_conn):
        history = load_sma_history(
            "postgresql://example",
            country=CountrySet.SWE,
            symbols=["VOLV-A.ST"],
        )

    mock_cursor.execute.assert_called_once_with(
        LOAD_SMA_HISTORY_FOR_SYMBOLS_SQL[CountrySet.SWE],
        (["VOLV-A.ST"],),
    )
    assert history == {}


def test_load_sma_history_empty_symbols_short_circuits() -> None:
    with patch("db.metrics.psycopg2.connect") as mock_connect:
        assert (
            load_sma_history("postgresql://example", country=CountrySet.US, symbols=[])
            == {}
        )
    mock_connect.assert_not_called()


def test_format_events_json_and_csv() -> None:
    events = [_event()]
    json_text = format_events(events, "json")
    assert '"pattern": "golden"' in json_text
    assert '"ticker": "AAPL"' in json_text

    csv_text = format_events(events, "csv")
    assert "pattern,ticker,country,crossover_date" in csv_text
    assert "golden,AAPL,us,2025-02-03" in csv_text

    table_text = format_events(events, "table")
    assert "pattern" in table_text
    assert "AAPL" in table_text


def test_format_events_empty_table() -> None:
    assert format_events([], "table") == "(no cross detections)\n"


def test_collect_cross_events_runs_detector() -> None:
    history = {
        "AAPL": [
            (date(2025, 1, 6), Decimal("90"), Decimal("100")),
            (date(2025, 1, 13), Decimal("92"), Decimal("100")),
            (date(2025, 1, 20), Decimal("94"), Decimal("100")),
            (date(2025, 1, 27), Decimal("96"), Decimal("100")),
            (date(2025, 2, 3), Decimal("105"), Decimal("100")),
        ]
    }
    with patch("detect_crosses.load_sma_history", return_value=history) as mock_load:
        events = collect_cross_events(
            "postgresql://example",
            patterns=[CrossPattern.GOLDEN],
            country=CountrySet.US,
            symbols=["AAPL"],
            min_regime_weeks=4,
            convergence_weeks=3,
        )

    mock_load.assert_called_once_with(
        "postgresql://example", country=CountrySet.US, symbols=["AAPL"]
    )
    assert len(events) == 1
    assert events[0].pattern is CrossPattern.GOLDEN
    assert events[0].ticker == "AAPL"


def test_main_writes_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from config import BaseConfig

    config = BaseConfig(database_url="postgresql://example")
    event = _event()

    with patch("detect_crosses.get_config", return_value=config):
        with patch("detect_crosses.collect_cross_events", return_value=[event]):
            assert main(["--format", "json", "--pattern", "golden"]) == 0

    out = capsys.readouterr().out
    assert '"pattern": "golden"' in out


def test_main_rejects_empty_symbols(monkeypatch: pytest.MonkeyPatch) -> None:
    from config import BaseConfig

    with patch(
        "detect_crosses.get_config",
        return_value=BaseConfig(database_url="postgresql://example"),
    ):
        assert main(["--symbols", ",,"]) == 1
