"""Pure Golden Cross / Death Cross detection over weekly SMA snapshots (RFC-013).

No DB, env, or yfinance imports — callers supply ordered history and knobs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Sequence

# FR-26 defaults (mirrored on BaseConfig as CROSS_* env knobs).
DEFAULT_MIN_REGIME_WEEKS = 4
DEFAULT_CONVERGENCE_WEEKS = 3


class CrossPattern(str, Enum):
    GOLDEN = "golden"
    DEATH = "death"


@dataclass(frozen=True)
class SmaSnapshot:
    """One valid or raw weekly SMA row (NULL SMAs may be present before filtering)."""

    trading_date: date
    sma_50: Decimal | None
    sma_200: Decimal | None


@dataclass(frozen=True)
class CrossEvent:
    """A completed three-stage Golden or Death Cross detection."""

    pattern: CrossPattern
    ticker: str
    country: str
    crossover_date: date
    regime_start_date: date
    regime_weeks: int
    convergence_first_gap: Decimal
    convergence_last_gap: Decimal
    sma_50: Decimal
    sma_200: Decimal


def validate_cross_windows(min_regime_weeks: int, convergence_weeks: int) -> None:
    """Reject FR-26 configs where convergence exceeds the regime window."""
    if convergence_weeks > min_regime_weeks:
        raise ValueError(
            "cross_convergence_weeks must be <= cross_min_regime_weeks "
            f"(got convergence={convergence_weeks}, regime={min_regime_weeks})"
        )


def _is_valid(snapshot: SmaSnapshot) -> bool:
    return snapshot.sma_50 is not None and snapshot.sma_200 is not None


def _gap(sma_50: Decimal, sma_200: Decimal, pattern: CrossPattern) -> Decimal:
    if pattern is CrossPattern.GOLDEN:
        return sma_200 - sma_50
    return sma_50 - sma_200


def _in_regime(sma_50: Decimal, sma_200: Decimal, pattern: CrossPattern) -> bool:
    if pattern is CrossPattern.GOLDEN:
        return sma_50 < sma_200
    return sma_50 > sma_200


def _is_crossover(sma_50: Decimal, sma_200: Decimal, pattern: CrossPattern) -> bool:
    if pattern is CrossPattern.GOLDEN:
        return sma_50 > sma_200
    return sma_50 < sma_200


def detect_crosses(
    snapshots: Sequence[SmaSnapshot],
    *,
    pattern: CrossPattern | str,
    ticker: str = "",
    country: str = "",
    min_regime_weeks: int = DEFAULT_MIN_REGIME_WEEKS,
    convergence_weeks: int = DEFAULT_CONVERGENCE_WEEKS,
) -> list[CrossEvent]:
    """Detect completed Golden or Death Cross events in an ordered series.

    Rows with NULL ``sma_50`` or ``sma_200`` are skipped (FR-25). Regime,
    convergence, and crossover windows count **valid** snapshots only.
    Emits only when all three stages complete in order (FR-21 / FR-22).
    """
    validate_cross_windows(min_regime_weeks, convergence_weeks)
    pattern_key = (
        pattern if isinstance(pattern, CrossPattern) else CrossPattern(pattern)
    )

    valid = [snap for snap in snapshots if _is_valid(snap)]
    if len(valid) < min_regime_weeks + 1:
        return []

    events: list[CrossEvent] = []
    # Candidate crossover index t requires min_regime_weeks valid weeks before it.
    for t in range(min_regime_weeks, len(valid)):
        cross = valid[t]
        assert cross.sma_50 is not None and cross.sma_200 is not None
        if not _is_crossover(cross.sma_50, cross.sma_200, pattern_key):
            continue

        regime = valid[t - min_regime_weeks : t]
        if len(regime) != min_regime_weeks:
            continue
        if not all(
            _in_regime(row.sma_50, row.sma_200, pattern_key)  # type: ignore[arg-type]
            for row in regime
        ):
            continue

        # Convergence window ends at the last regime week (index t - 1).
        conv_start = t - convergence_weeks
        conv_window = valid[conv_start:t]
        if len(conv_window) != convergence_weeks:
            continue

        first = conv_window[0]
        last = conv_window[-1]
        assert first.sma_50 is not None and first.sma_200 is not None
        assert last.sma_50 is not None and last.sma_200 is not None
        first_gap = _gap(first.sma_50, first.sma_200, pattern_key)
        last_gap = _gap(last.sma_50, last.sma_200, pattern_key)
        if not (last_gap < first_gap):
            continue

        events.append(
            CrossEvent(
                pattern=pattern_key,
                ticker=ticker,
                country=country,
                crossover_date=cross.trading_date,
                regime_start_date=regime[0].trading_date,
                regime_weeks=min_regime_weeks,
                convergence_first_gap=first_gap,
                convergence_last_gap=last_gap,
                sma_50=cross.sma_50,
                sma_200=cross.sma_200,
            )
        )

    return events


def detect_all_patterns(
    snapshots: Sequence[SmaSnapshot],
    *,
    patterns: Sequence[CrossPattern | str] = (
        CrossPattern.GOLDEN,
        CrossPattern.DEATH,
    ),
    ticker: str = "",
    country: str = "",
    min_regime_weeks: int = DEFAULT_MIN_REGIME_WEEKS,
    convergence_weeks: int = DEFAULT_CONVERGENCE_WEEKS,
) -> list[CrossEvent]:
    """Run detection for each requested pattern and concatenate results."""
    events: list[CrossEvent] = []
    for pattern in patterns:
        events.extend(
            detect_crosses(
                snapshots,
                pattern=pattern,
                ticker=ticker,
                country=country,
                min_regime_weeks=min_regime_weeks,
                convergence_weeks=convergence_weeks,
            )
        )
    return events
