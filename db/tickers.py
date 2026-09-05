"""Database access for the country tickers watchlist tables (RFC-001)."""

from __future__ import annotations

from collections import defaultdict

import psycopg2
from psycopg2.extras import execute_values

from db.country import CountrySet, country_set_for
from models import TickerEntry

LOAD_TICKERS_SQL = """
SELECT symbol, company, sector, industry, market, exchange_name FROM us_tickers
UNION ALL
SELECT symbol, company, sector, industry, market, exchange_name FROM swe_tickers
UNION ALL
SELECT symbol, company, sector, industry, market, exchange_name FROM uk_tickers
ORDER BY symbol
"""

UPSERT_TICKER_SQL = {
    CountrySet.US: """
INSERT INTO us_tickers (symbol, company, sector, industry, market, exchange_name)
VALUES %s
ON CONFLICT (symbol) DO UPDATE SET
    company = EXCLUDED.company,
    sector = EXCLUDED.sector,
    industry = EXCLUDED.industry,
    market = EXCLUDED.market,
    exchange_name = EXCLUDED.exchange_name,
    updated_at = NOW();
""",
    CountrySet.SWE: """
INSERT INTO swe_tickers (symbol, company, sector, industry, market, exchange_name)
VALUES %s
ON CONFLICT (symbol) DO UPDATE SET
    company = EXCLUDED.company,
    sector = EXCLUDED.sector,
    industry = EXCLUDED.industry,
    market = EXCLUDED.market,
    exchange_name = EXCLUDED.exchange_name,
    updated_at = NOW();
""",
    CountrySet.UK: """
INSERT INTO uk_tickers (symbol, company, sector, industry, market, exchange_name)
VALUES %s
ON CONFLICT (symbol) DO UPDATE SET
    company = EXCLUDED.company,
    sector = EXCLUDED.sector,
    industry = EXCLUDED.industry,
    market = EXCLUDED.market,
    exchange_name = EXCLUDED.exchange_name,
    updated_at = NOW();
""",
}

TickerUpsertRow = tuple[
    str, str | None, str | None, str | None, str | None, str | None
]


def load_tickers_from_db(database_url: str) -> list[TickerEntry]:
    """Load the watchlist from us_tickers, swe_tickers, and uk_tickers."""
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(LOAD_TICKERS_SQL)
            rows = cur.fetchall()

    if not rows:
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
