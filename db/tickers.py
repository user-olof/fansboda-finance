"""Database access for the country tickers watchlist tables (RFC-001)."""

from __future__ import annotations

from collections import defaultdict

import psycopg2
from psycopg2.extras import execute_values

from db.country import (
    TICKERS_TABLE,
    CountrySet,
    country_set_for,
    sql_for_countries,
    union_all_sql,
)
from models import TickerEntry

LOAD_TICKERS_SQL = (
    union_all_sql(
        "SELECT symbol, company, sector, industry, market, exchange_name "
        "FROM {tickers}"
    )
    + "\nORDER BY symbol"
)

LOAD_TICKERS_SQL_BY_COUNTRY = sql_for_countries(
    """
SELECT symbol, company, sector, industry, market, exchange_name
FROM {tickers}
ORDER BY symbol
"""
)

UPSERT_TICKER_SQL = sql_for_countries(
    """
INSERT INTO {tickers} (symbol, company, sector, industry, market, exchange_name)
VALUES %s
ON CONFLICT (symbol) DO UPDATE SET
    company = EXCLUDED.company,
    sector = EXCLUDED.sector,
    industry = EXCLUDED.industry,
    market = EXCLUDED.market,
    exchange_name = EXCLUDED.exchange_name,
    updated_at = NOW();
"""
)

TickerUpsertRow = tuple[
    str, str | None, str | None, str | None, str | None, str | None
]


def load_tickers_from_db(
    database_url: str,
    *,
    country: CountrySet | None = None,
) -> list[TickerEntry]:
    """Load the watchlist from country tickers tables.

    When ``country`` is set, load only that set's ``*_tickers`` table (FR-18).
    """
    sql = (
        LOAD_TICKERS_SQL_BY_COUNTRY[country]
        if country is not None
        else LOAD_TICKERS_SQL
    )
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()

    if not rows:
        if country is not None:
            raise ValueError(f"No tickers found in {TICKERS_TABLE[country]}")
        raise ValueError("No tickers found in us_tickers, swe_tickers, or uk_tickers")

    return [
        TickerEntry(
            symbol=row[0],
            company=row[1],
            sector=row[2],
            industry=row[3],
            market=row[4],
            exchange_name=row[5],
        )
        for row in rows
    ]


def upsert_tickers(database_url: str, rows: list[TickerUpsertRow]) -> int:
    """Upsert ticker symbols into country tickers tables. Returns rows affected."""
    if not rows:
        return 0

    by_country: dict[CountrySet, list[TickerUpsertRow]] = defaultdict(list)
    for row in rows:
        symbol, _company, _sector, _industry, market, _exchange_name = row
        country = country_set_for(market=market, symbol=symbol)
        by_country[country].append(row)

    affected = 0
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            for country, country_rows in by_country.items():
                execute_values(cur, UPSERT_TICKER_SQL[country], country_rows)
                affected += cur.rowcount
        conn.commit()

    return affected
