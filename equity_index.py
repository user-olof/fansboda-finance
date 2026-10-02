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
class IndexRow:
    ticker: str
    name: str
    country: CountrySet
    week_start: date
    ticker_count: int
    avg_return: Decimal | None
    index_price: Decimal


def build_index_row(
    definition: IndexDefinition,
    week_start: date,
    *,
    prev_price: Decimal | None,
    ticker_count: int,
    avg_return: Decimal | None,
) -> IndexRow | None:
    """Chain one week onto the previous stored index level.

    ``prev_price=None`` marks the base week (level ``BASE_INDEX_PRICE``,
    ``avg_return`` NULL); ``ticker_count`` is then the number of priced
    stocks. Otherwise ``avg_return`` is the equal-weighted mean of stock
    returns since the previous stored week. Returns ``None`` when no stock
    contributes (FR-39).
    """
    if ticker_count <= 0:
        return None
    if prev_price is None:
        return IndexRow(
            ticker=definition.ticker,
            name=definition.name,
            country=definition.country,
            week_start=week_start,
            ticker_count=ticker_count,
            avg_return=None,
            index_price=BASE_INDEX_PRICE,
        )
    if avg_return is None:
        return None
    return IndexRow(
        ticker=definition.ticker,
        name=definition.name,
        country=definition.country,
        week_start=week_start,
        ticker_count=ticker_count,
        avg_return=avg_return,
        index_price=prev_price * (Decimal("1") + avg_return),
    )
