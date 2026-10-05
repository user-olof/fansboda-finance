"""Implausible weekly moves from stored growth columns (PRD FR-37b / §5.9).

Outliers are derived from ``*_metrics`` and the configured bounds; there is no
outlier table.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import psycopg2

from db.country import CountrySet, sql_for_countries
from equity_index import is_outlier
from models import OutlierRow

# Bounds: 6 params for the previous week's flag, then the week list, then 6
# params for this week's flag. NULL growth never counts as an outlier.
LOAD_OUTLIERS_SQL = sql_for_countries(
    """
SELECT
    cur.ticker,
    t.company,
    cur.week_start,
    cur.trading_date,
    prev.current_price,
    cur.current_price,
    cur.price_growth,
    cur.sma_50_growth,
    cur.sma_200_growth,
    COALESCE(
        prev.price_growth NOT BETWEEN %s AND %s
        OR prev.sma_50_growth NOT BETWEEN %s AND %s
        OR prev.sma_200_growth NOT BETWEEN %s AND %s,
        FALSE
    ) AS was_outlier
FROM {metrics} cur
JOIN {tickers} t ON t.symbol = cur.ticker
LEFT JOIN {metrics} prev
  ON prev.ticker = cur.ticker
 AND prev.week_start = cur.week_start - 7
WHERE cur.week_start = ANY(%s)
  AND (
      cur.price_growth NOT BETWEEN %s AND %s
      OR cur.sma_50_growth NOT BETWEEN %s AND %s
      OR cur.sma_200_growth NOT BETWEEN %s AND %s
  )
ORDER BY cur.week_start, cur.ticker
"""
)


def load_outliers(
    database_url: str,
    week_starts: list[date],
    *,
    country: CountrySet,
    max_growth: float,
    min_growth: float,
) -> list[OutlierRow]:
    """Return outlier stock-weeks for ``week_starts`` in one country set.

    ``is_new`` is False when the same stock was also an outlier in the
    previous calendar week (FR-47).
    """
    if not week_starts:
        return []

    bounds = (Decimal(str(min_growth)), Decimal(str(max_growth))) * 3
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                LOAD_OUTLIERS_SQL[country],
                (*bounds, sorted(set(week_starts)), *bounds),
            )
            rows = cur.fetchall()

    outliers: list[OutlierRow] = []
    for (
        ticker,
        company,
        week_start,
        trading_date,
        prev_close,
        close,
        price_growth,
        sma_50_growth,
        sma_200_growth,
        was_outlier,
    ) in rows:
        bound = is_outlier(
            {
                "price_growth": price_growth,
                "sma_50_growth": sma_50_growth,
                "sma_200_growth": sma_200_growth,
            },
            max_growth=max_growth,
            min_growth=min_growth,
        )
        if bound is None:
            continue
        outliers.append(
            OutlierRow(
                country=country.value,
                ticker=ticker,
                company=company,
                week_start=week_start,
                trading_date=trading_date,
                prev_close=prev_close,
                close=close,
                price_growth=price_growth,
                sma_50_growth=sma_50_growth,
                sma_200_growth=sma_200_growth,
                bound=bound,
                is_new=not was_outlier,
            )
        )
    return outliers
