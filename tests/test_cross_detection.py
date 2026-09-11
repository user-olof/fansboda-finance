"""Unit tests for RFC-013 Golden / Death Cross pure detection."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from cross_detection import (
    CrossPattern,
    SmaSnapshot,
    detect_all_patterns,
    detect_crosses,
    validate_cross_windows,
)


def _d(n: int) -> date:
    """Monday-aligned weekly dates starting 2025-01-06."""
    return date(2025, 1, 6) + timedelta(weeks=n)


def _snap(week: int, sma_50: str | None, sma_200: str | None) -> SmaSnapshot:
    return SmaSnapshot(
        trading_date=_d(week),
        sma_50=None if sma_50 is None else Decimal(sma_50),
        sma_200=None if sma_200 is None else Decimal(sma_200),
    )


def _golden_series() -> list[SmaSnapshot]:
    """Four below-regime weeks with narrowing gaps, then a strict crossover.

    Gaps (sma_200 - sma_50) over regime: 10, 8, 6, 4 → convergence last 3:
    first=8, last=4 (strict narrowing). Crossover week: 105 > 100.
    """
    return [
        _snap(0, "90", "100"),  # gap 10
        _snap(1, "92", "100"),  # gap 8
        _snap(2, "94", "100"),  # gap 6
        _snap(3, "96", "100"),  # gap 4  (last regime)
        _snap(4, "105", "100"),  # crossover
    ]


def _death_series() -> list[SmaSnapshot]:
    """Mirror of golden: above-regime with narrowing gaps, then crossover down."""
    return [
        _snap(0, "110", "100"),  # gap 10
        _snap(1, "108", "100"),  # gap 8
        _snap(2, "106", "100"),  # gap 6
        _snap(3, "104", "100"),  # gap 4
        _snap(4, "95", "100"),  # crossover
    ]


def test_validate_cross_windows_rejects_convergence_above_regime() -> None:
    with pytest.raises(ValueError, match="cross_convergence_weeks"):
        validate_cross_windows(4, 5)


def test_validate_cross_windows_allows_equal() -> None:
    validate_cross_windows(4, 4)


def test_golden_cross_emits_when_all_stages_complete() -> None:
    events = detect_crosses(
        _golden_series(),
        pattern=CrossPattern.GOLDEN,
        ticker="AAPL",
        country="us",
        min_regime_weeks=4,
        convergence_weeks=3,
    )
    assert len(events) == 1
    event = events[0]
    assert event.pattern is CrossPattern.GOLDEN
    assert event.ticker == "AAPL"
    assert event.country == "us"
    assert event.crossover_date == _d(4)
    assert event.regime_start_date == _d(0)
    assert event.regime_weeks == 4
    assert event.convergence_first_gap == Decimal("8")
    assert event.convergence_last_gap == Decimal("4")
    assert event.sma_50 == Decimal("105")
    assert event.sma_200 == Decimal("100")


def test_death_cross_emits_when_all_stages_complete() -> None:
    events = detect_crosses(
        _death_series(),
        pattern="death",
        ticker="MSFT",
        country="us",
        min_regime_weeks=4,
        convergence_weeks=3,
    )
    assert len(events) == 1
    event = events[0]
    assert event.pattern is CrossPattern.DEATH
    assert event.crossover_date == _d(4)
    assert event.convergence_first_gap == Decimal("8")
    assert event.convergence_last_gap == Decimal("4")
    assert event.sma_50 == Decimal("95")
    assert event.sma_200 == Decimal("100")


def test_equal_smas_do_not_count_as_crossover() -> None:
    series = [
        _snap(0, "90", "100"),
        _snap(1, "92", "100"),
        _snap(2, "94", "100"),
        _snap(3, "96", "100"),
        _snap(4, "100", "100"),  # equal — not a cross
    ]
    assert detect_crosses(series, pattern="golden") == []


def test_equal_smas_break_regime() -> None:
    series = [
        _snap(0, "90", "100"),
        _snap(1, "92", "100"),
        _snap(2, "100", "100"),  # equal breaks below-regime
        _snap(3, "96", "100"),
        _snap(4, "105", "100"),
    ]
    assert detect_crosses(series, pattern="golden") == []


def test_null_sma_rows_are_skipped() -> None:
    series = [
        _snap(0, "90", "100"),
        _snap(1, None, "100"),  # skipped
        _snap(2, "92", None),  # skipped
        _snap(3, "92", "100"),
        _snap(4, "94", "100"),
        _snap(5, "96", "100"),
        _snap(6, "105", "100"),
    ]
    events = detect_crosses(
        series,
        pattern="golden",
        min_regime_weeks=4,
        convergence_weeks=3,
    )
    assert len(events) == 1
    assert events[0].crossover_date == _d(6)
    assert events[0].regime_start_date == _d(0)


def test_incomplete_regime_does_not_emit() -> None:
    # Only 3 below weeks before crossover (need 4).
    series = [
        _snap(0, "92", "100"),
        _snap(1, "94", "100"),
        _snap(2, "96", "100"),
        _snap(3, "105", "100"),
    ]
    assert detect_crosses(series, pattern="golden") == []


def test_non_converging_gap_does_not_emit() -> None:
    # Gaps widen over the last 3 regime weeks: 4, 6, 8.
    series = [
        _snap(0, "96", "100"),  # gap 4
        _snap(1, "94", "100"),  # gap 6
        _snap(2, "92", "100"),  # gap 8
        _snap(3, "90", "100"),  # gap 10 — last regime; conv first=6 last=10
        _snap(4, "105", "100"),
    ]
    assert detect_crosses(series, pattern="golden") == []


def test_flat_gap_is_not_convergence() -> None:
    series = [
        _snap(0, "90", "100"),
        _snap(1, "92", "100"),  # gap 8
        _snap(2, "93", "100"),  # gap 7
        _snap(3, "92", "100"),  # gap 8 — last == first of conv window
        _snap(4, "105", "100"),
    ]
    # convergence window weeks 1–3: first_gap=8, last_gap=8 → not strict <
    assert detect_crosses(series, pattern="golden") == []


def test_wrong_pattern_does_not_emit_on_golden_series() -> None:
    assert detect_crosses(_golden_series(), pattern="death") == []


def test_detect_all_patterns_runs_both() -> None:
    # Concatenate golden then death histories under one ticker walk is N/A;
    # run separately via detect_all_patterns on golden series → golden only.
    events = detect_all_patterns(_golden_series(), ticker="AAPL", country="us")
    assert [e.pattern for e in events] == [CrossPattern.GOLDEN]


def test_detect_crosses_rejects_bad_windows() -> None:
    with pytest.raises(ValueError, match="cross_convergence_weeks"):
        detect_crosses(_golden_series(), pattern="golden", min_regime_weeks=3, convergence_weeks=4)
