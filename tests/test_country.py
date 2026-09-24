"""Tests for db.country routing helpers (RFC-001 / RFC-002)."""

from db.country import (
    CountrySet,
    country_set_for,
    infer_listing_market,
    sql_for_countries,
    union_all_sql,
)


def test_country_set_for_se_market() -> None:
    assert country_set_for(market="se_market", symbol="AAPL") is CountrySet.SWE


def test_country_set_for_st_suffix() -> None:
    assert country_set_for(symbol="VOLV-B.ST") is CountrySet.SWE
    assert country_set_for(market="us_market", symbol="ERIC-B.ST") is CountrySet.SWE


def test_country_set_for_uk_market() -> None:
    assert country_set_for(market="uk_market", symbol="AAPL") is CountrySet.UK


def test_country_set_for_l_suffix() -> None:
    assert country_set_for(symbol="VOD.L") is CountrySet.UK
    assert country_set_for(market="us_market", symbol="BP.L") is CountrySet.UK


def test_country_set_for_us_default() -> None:
    assert country_set_for(market="us_market", symbol="AAPL") is CountrySet.US
    assert country_set_for(symbol="MSFT") is CountrySet.US


def test_infer_listing_market_keeps_explicit_market() -> None:
    assert infer_listing_market(market="us_market", symbol="FOO.ST") == "us_market"
    assert infer_listing_market(market="se_market", symbol="AAPL") == "se_market"
    assert infer_listing_market(market="uk_market", symbol="AAPL") == "uk_market"


def test_infer_listing_market_from_symbol() -> None:
    assert infer_listing_market(symbol="VOLV-B.ST") == "se_market"
    assert infer_listing_market(symbol="VOD.L") == "uk_market"
    assert infer_listing_market(symbol="AAPL") == "us_market"


def test_sql_for_countries_formats_allowlisted_tables() -> None:
    sql = sql_for_countries("SELECT 1 FROM {metrics} JOIN {tickers}")
    assert "FROM us_metrics JOIN us_tickers" in sql[CountrySet.US]
    assert "FROM swe_metrics JOIN swe_tickers" in sql[CountrySet.SWE]
    assert "FROM uk_metrics JOIN uk_tickers" in sql[CountrySet.UK]


def test_union_all_sql_joins_country_fragments() -> None:
    sql = union_all_sql("SELECT trading_date FROM {metrics}")
    assert "UNION ALL" in sql
    assert "FROM us_metrics" in sql
    assert "FROM swe_metrics" in sql
    assert "FROM uk_market_metrics" not in sql
