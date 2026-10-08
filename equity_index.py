"""Pure equal-weighted market and sector index logic (PRD §5.8 / RFC-015 / RFC-018). No I/O."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from db.country import CountrySet

BASE_INDEX_PRICE = Decimal("100")


COUNTRY_CURRENCY: dict[CountrySet, str] = {
    CountrySet.US: "USD",
    CountrySet.SWE: "SEK",
    CountrySet.UK: "GBP",
}


@dataclass(frozen=True)
class IndexDefinition:
    ticker: str
    name: str
    country: CountrySet
    sector_key: str | None = None

    @property
    def currency(self) -> str:
        return COUNTRY_CURRENCY[self.country]


INDEX_DEFINITIONS: dict[CountrySet, IndexDefinition] = {
    CountrySet.US: IndexDefinition("US-IDX", "NYSE & Nasdaq", CountrySet.US),
    CountrySet.SWE: IndexDefinition("SWE-IDX", "OMX Stockholm", CountrySet.SWE),
    CountrySet.UK: IndexDefinition("UK-IDX", "FTSE London", CountrySet.UK),
}


def sector_index_definition(country: CountrySet, sector: str) -> IndexDefinition:
    """Sector index for a ``sectorKey`` (e.g. ``financial-services``) in a set.

    Ticker ``<market ticker>-<SECTOR>`` (``US-IDX-FINANCIAL-SERVICES``), name =
    the sector label alone (``Financial Services``). Labels repeat across
    countries but are unique within one, since sector keys are.
    """
    market = INDEX_DEFINITIONS[country]
    return IndexDefinition(
        ticker=f"{market.ticker}-{sector.upper()}",
        name=sector.replace("-", " ").title(),
        country=country,
        sector_key=sector,
    )


@dataclass(frozen=True)
class IndexLevels:
    current_price: Decimal
    sma_50: Decimal
    sma_200: Decimal


@dataclass(frozen=True)
class WeekLevels:
    """An index's levels for one week, read from its daily series."""

    trading_date: date
    levels: IndexLevels
    days_used: int


@dataclass(frozen=True)
class IndexRow:
    """One ``indices`` row. ``sector`` is the stored label (market rows: the index
    name, ``NYSE & Nasdaq``; sector rows: the sector, ``Technology``); ``sector_key`` is the ``sectorKey`` used to
    group sector rows (None on market rows) and is not stored."""

    ticker: str
    sector: str
    country: CountrySet
    trading_date: date
    ticker_count: int
    current_price: Decimal
    sma_50: Decimal
    sma_200: Decimal
    momentum: Decimal | None
    sector_key: str | None = None
    currency: str | None = None
    pct_uptrend: Decimal | None = None
    z_score: Decimal | None = None

    @property
    def levels(self) -> IndexLevels:
        return IndexLevels(self.current_price, self.sma_50, self.sma_200)


def is_outlier(
    growths: dict[str, Decimal | None],
    *,
    max_growth: float,
    min_growth: float,
) -> str | None:
    """Return the first crossed bound (e.g. ``"price_growth > 9"``), else None.

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
    pct_uptrend: Decimal | None,
) -> IndexRow:
    return IndexRow(
        ticker=definition.ticker,
        sector=definition.name,
        country=definition.country,
        trading_date=trading_date,
        ticker_count=ticker_count,
        current_price=levels.current_price,
        sma_50=levels.sma_50,
        sma_200=levels.sma_200,
        momentum=index_momentum(levels.sma_50, levels.sma_200),
        sector_key=definition.sector_key,
        currency=definition.currency,
        pct_uptrend=pct_uptrend,
    )


def build_index_row(
    definition: IndexDefinition,
    *,
    trading_date: date | None,
    ticker_count: int,
    levels: IndexLevels,
    pct_uptrend: Decimal | None = None,
) -> IndexRow | None:
    """One week of an index from its daily series levels (specs/002-index-true-sma).

    Returns ``None`` when no stock has a positive price and both SMAs (FR-41).
    """
    if ticker_count <= 0 or trading_date is None:
        return None
    return _row(definition, trading_date, ticker_count, levels, pct_uptrend)


def with_sector_z_scores(rows: list[IndexRow]) -> list[IndexRow]:
    """Set ``z_score`` on one country-week's sector rows (FR-40b).

    ``(momentum − mean) / std`` over the sector rows with momentum, using the
    population std (like the stock-level ``z_score``). NULL with fewer than two
    such sectors or zero std; market rows (``sector_key is None``) stay NULL.
    """
    momenta = [
        row.momentum
        for row in rows
        if row.sector_key is not None and row.momentum is not None
    ]
    mean = std = None
    if len(momenta) >= 2:
        mean = sum(momenta, Decimal(0)) / len(momenta)
        std = (sum(((m - mean) ** 2 for m in momenta), Decimal(0)) / len(momenta)).sqrt()
    result: list[IndexRow] = []
    for row in rows:
        z_score = None
        if row.sector_key is not None and row.momentum is not None and std:
            z_score = (row.momentum - mean) / std
        result.append(replace(row, z_score=z_score))
    return result
