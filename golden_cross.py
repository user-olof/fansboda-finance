"""Pure Golden Cross pattern detection from stored SMA history (RFC-013).

Uses weekly ``sma_50`` / ``sma_200`` snapshots only — no live market APIs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Sequence

from models import SmaSnapshot


class GoldenCrossStage(str, Enum):
    """Stages of the classic golden-cross process."""

    DOWNTREND = "downtrend"
    CONVERGENCE = "convergence"
    CROSSOVER = "crossover"


@dataclass(frozen=True)
class GoldenCrossParams:
    """Configurable windows for stages 1–2 (crossover itself is binary)."""

    min_below_weeks: int = 4
    convergence_weeks: int = 3

    def __post_init__(self) -> None:
        if self.min_below_weeks < 1:
            raise ValueError("min_below_weeks must be >= 1")
        if self.convergence_weeks < 1:
            raise ValueError("convergence_weeks must be >= 1")
        if self.convergence_weeks > self.min_below_weeks:
            raise ValueError(
                "convergence_weeks must be <= min_below_weeks "
                f"(got {self.convergence_weeks} > {self.min_below_weeks})"
            )


@dataclass(frozen=True)
class StageAnnotation:
    """Per-snapshot stage label for a ticker series."""

    trading_date: date
    stage: GoldenCrossStage
    sma_50: Decimal
    sma_200: Decimal
    gap: Decimal


@dataclass(frozen=True)
class GoldenCrossEvent:
    """A detected golden-cross crossover with stage metadata."""

    ticker: str
    country: str
    trading_date: date
    sma_50: Decimal
    sma_200: Decimal
    weeks_below: int
    gap_at_below_start: Decimal
    gap_before_cross: Decimal
    converged: bool
    stages: tuple[StageAnnotation, ...]


def _gap(sma_50: Decimal, sma_200: Decimal) -> Decimal:
    return sma_200 - sma_50


def _is_below(point: SmaSnapshot) -> bool:
    assert point.sma_50 is not None and point.sma_200 is not None
    return point.sma_50 < point.sma_200


def _is_at_or_above(point: SmaSnapshot) -> bool:
    assert point.sma_50 is not None and point.sma_200 is not None
    return point.sma_50 >= point.sma_200


def _valid_points(series: Sequence[SmaSnapshot]) -> list[SmaSnapshot]:
    """Drop rows with missing SMAs; preserve chronological order."""
    return [
        p
        for p in series
        if p.sma_50 is not None and p.sma_200 is not None
    ]


def gap_is_narrowing(gaps: Sequence[Decimal]) -> bool:
    """Return True when the absolute below-gap shrinks from first to last.

    Requires at least two gap samples. Equal gaps do not count as convergence.
    """
    if len(gaps) < 2:
        return False
    return gaps[-1] < gaps[0]


def detect_crossover_indices(points: Sequence[SmaSnapshot]) -> list[int]:
    """Return indices where sma_50 crosses from below to at/above sma_200."""
    crosses: list[int] = []
    for i in range(1, len(points)):
        if _is_below(points[i - 1]) and _is_at_or_above(points[i]):
            crosses.append(i)
    return crosses


def _consecutive_below_run_end(
    points: Sequence[SmaSnapshot], cross_index: int
) -> int:
    """Length of consecutive below-weeks ending at ``cross_index - 1``."""
    count = 0
    for i in range(cross_index - 1, -1, -1):
        if not _is_below(points[i]):
            break
        count += 1
    return count


def _stage_window_for_cross(
    points: Sequence[SmaSnapshot],
    cross_index: int,
    weeks_below: int,
    converged: bool,
    params: GoldenCrossParams,
) -> tuple[StageAnnotation, ...]:
    """Build stage annotations for the lookback + crossover week."""
    annotations: list[StageAnnotation] = []
    below_start = cross_index - weeks_below
    convergence_start = cross_index - params.convergence_weeks

    for i in range(below_start, cross_index):
        point = points[i]
        assert point.sma_50 is not None and point.sma_200 is not None
        gap = _gap(point.sma_50, point.sma_200)
        if converged and i >= convergence_start:
            stage = GoldenCrossStage.CONVERGENCE
        else:
            stage = GoldenCrossStage.DOWNTREND
        annotations.append(
            StageAnnotation(
                trading_date=point.trading_date,
                stage=stage,
                sma_50=point.sma_50,
                sma_200=point.sma_200,
                gap=gap,
            )
        )

    cross = points[cross_index]
    assert cross.sma_50 is not None and cross.sma_200 is not None
    annotations.append(
        StageAnnotation(
            trading_date=cross.trading_date,
            stage=GoldenCrossStage.CROSSOVER,
            sma_50=cross.sma_50,
            sma_200=cross.sma_200,
            gap=_gap(cross.sma_50, cross.sma_200),
        )
    )
    return tuple(annotations)


def detect_golden_crosses(
    series: Sequence[SmaSnapshot],
    *,
    ticker: str,
    country: str,
    params: GoldenCrossParams | None = None,
) -> list[GoldenCrossEvent]:
    """Detect golden-cross events in one ticker's ordered SMA history.

    Stages (user definition):
    1. Downtrend/consolidation — ``sma_50 < sma_200`` for ``min_below_weeks``.
    2. Convergence — gap narrows over the last ``convergence_weeks`` below.
    3. Crossover — ``sma_50`` moves from below to at/above ``sma_200``.

    Rows with null SMAs are skipped. Death crosses (above → below) are ignored.
    Events that lack enough below-weeks or fail convergence are not emitted.
    """
    cfg = params if params is not None else GoldenCrossParams()
    points = _valid_points(series)
    if len(points) < cfg.min_below_weeks + 1:
        return []

    events: list[GoldenCrossEvent] = []
    for cross_index in detect_crossover_indices(points):
        weeks_below = _consecutive_below_run_end(points, cross_index)
        if weeks_below < cfg.min_below_weeks:
            continue

        conv_slice = points[
            cross_index - cfg.convergence_weeks : cross_index
        ]
        gaps = [
            _gap(p.sma_50, p.sma_200)  # type: ignore[arg-type]
            for p in conv_slice
        ]
        converged = gap_is_narrowing(gaps)
        if not converged:
            continue

        cross = points[cross_index]
        below_start = points[cross_index - weeks_below]
        before = points[cross_index - 1]
        assert cross.sma_50 is not None and cross.sma_200 is not None
        assert below_start.sma_50 is not None and below_start.sma_200 is not None
        assert before.sma_50 is not None and before.sma_200 is not None

        events.append(
            GoldenCrossEvent(
                ticker=ticker,
                country=country,
                trading_date=cross.trading_date,
                sma_50=cross.sma_50,
                sma_200=cross.sma_200,
                weeks_below=weeks_below,
                gap_at_below_start=_gap(below_start.sma_50, below_start.sma_200),
                gap_before_cross=_gap(before.sma_50, before.sma_200),
                converged=True,
                stages=_stage_window_for_cross(
                    points, cross_index, weeks_below, True, cfg
                ),
            )
        )

    return events


def classify_series_stages(
    series: Sequence[SmaSnapshot],
    *,
    ticker: str,
    country: str,
    params: GoldenCrossParams | None = None,
) -> list[StageAnnotation]:
    """Return stage annotations for all detected golden-cross processes.

    Annotations cover the downtrend → convergence → crossover window for each
    accepted event (overlapping windows are concatenated in date order; later
    events win on the same date).
    """
    events = detect_golden_crosses(
        series, ticker=ticker, country=country, params=params
    )
    by_date: dict[date, StageAnnotation] = {}
    for event in events:
        for annotation in event.stages:
            by_date[annotation.trading_date] = annotation
    return [by_date[d] for d in sorted(by_date)]
