"""Pure equal-weighted country index logic (PRD §5.8 / RFC-015). No I/O."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from db.country import CountrySet

BASE_INDEX_PRICE = Decimal("100")


@dataclass(frozen=True)
class IndexDefinition:
    ticker: str
    name: str
    country: CountrySet


INDEX_DEFINITIONS: dict[CountrySet, IndexDefinition] = {
    CountrySet.US: IndexDefinition("US-IDX", "US Equity Index", CountrySet.US),
    CountrySet.SWE: IndexDefinition("SWE-IDX", "OMX Equity Index", CountrySet.SWE),
    CountrySet.UK: IndexDefinition("UK-IDX", "FTSE Equity Index", CountrySet.UK),
}


@dataclass(frozen=True)
class IndexLevels:
    current_price: Decimal
    sma_50: Decimal
    sma_200: Decimal


@dataclass(frozen=True)
class IndexRow:
    ticker: str
    name: str
    country: CountrySet
    trading_date: date
    ticker_count: int
    current_price: Decimal
    sma_50: Decimal
    sma_200: Decimal
    momentum: Decimal | None

    @property
    def levels(self) -> IndexLevels:
        return IndexLevels(self.current_price, self.sma_50, self.sma_200)


def is_outlier(
    growths: dict[str, Decimal | None],
    *,
    max_growth: float,
    min_growth: float,
) -> str | None:
    """Return the first crossed bound (e.g. ``"price_growth > 4.0"``), else None.

    A stock-week is an outlier when any weekly growth is above ``max_growth``
    or below ``min_growth`` (FR-37b). NULL growth values are ignored.
    """
    for name, value in growths.items():
        if value is None:
            continue
        if float(value) > max_growth:
            return f"{name} > {max_growth:g}"
        if float(value) < min_growth:
            return f"{name} < {min_growth:g}"
    return None


def index_momentum(sma_50: Decimal, sma_200: Decimal) -> Decimal | None:
    """``sma_50 / sma_200`` on index levels; NULL when ``sma_200`` is zero."""
    if sma_200 == 0:
        return None
    return sma_50 / sma_200


def _row(
    definition: IndexDefinition,
    trading_date: date,
    ticker_count: int,
    levels: IndexLevels,
) -> IndexRow:
    return IndexRow(
        ticker=definition.ticker,
        name=definition.name,
        country=definition.country,
        trading_date=trading_date,
        ticker_count=ticker_count,
        current_price=levels.current_price,
        sma_50=levels.sma_50,
        sma_200=levels.sma_200,
        momentum=index_momentum(levels.sma_50, levels.sma_200),
    )


def build_base_row(
    definition: IndexDefinition,
    *,
    trading_date: date | None,
    ticker_count: int,
    avg_sma_50_ratio: Decimal | None,
    avg_sma_200_ratio: Decimal | None,
) -> IndexRow | None:
    """First week of an index: price 100, SMA levels at 100 × mean(sma / price).

    Returns ``None`` when no stock has a positive price and both SMAs (FR-41).
    """
    if (
        ticker_count <= 0
        or trading_date is None
        or avg_sma_50_ratio is None
        or avg_sma_200_ratio is None
    ):
        return None
    levels = IndexLevels(
        current_price=BASE_INDEX_PRICE,
        sma_50=BASE_INDEX_PRICE * avg_sma_50_ratio,
        sma_200=BASE_INDEX_PRICE * avg_sma_200_ratio,
    )
    return _row(definition, trading_date, ticker_count, levels)


def build_chained_row(
    definition: IndexDefinition,
    previous: IndexLevels,
    *,
    trading_date: date | None,
    ticker_count: int,
    growth_price: Decimal | None,
    growth_sma_50: Decimal | None,
    growth_sma_200: Decimal | None,
) -> IndexRow | None:
    """Chain each level by the equal-weighted mean growth of its measure.

    Returns ``None`` when no stock contributes this week (FR-41).
    """
    if (
        ticker_count <= 0
        or trading_date is None
        or growth_price is None
        or growth_sma_50 is None
        or growth_sma_200 is None
    ):
        return None
    one = Decimal("1")
    levels = IndexLevels(
        current_price=previous.current_price * (one + growth_price),
        sma_50=previous.sma_50 * (one + growth_sma_50),
        sma_200=previous.sma_200 * (one + growth_sma_200),
    )
    return _row(definition, trading_date, ticker_count, levels)
