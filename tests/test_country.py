"""Tests for db.country routing helpers (RFC-001 / RFC-002)."""

from db.country import CountrySet, country_set_for, infer_listing_market


def test_country_set_for_se_market() -> None:
    assert country_set_for(market="se_market", symbol="AAPL") is CountrySet.SWE


def test_country_set_for_st_suffix() -> None:
    assert country_set_for(symbol="VOLV-B.ST") is CountrySet.SWE
    assert country_set_for(market="us_market", symbol="ERIC-B.ST") is CountrySet.SWE


def test_country_set_for_us_default() -> None:
    assert country_set_for(market="us_market", symbol="AAPL") is CountrySet.US
    assert country_set_for(symbol="MSFT") is CountrySet.US


def test_infer_listing_market_keeps_explicit_market() -> None:
    assert infer_listing_market(market="us_market", symbol="FOO.ST") == "us_market"
    assert infer_listing_market(market="se_market", symbol="AAPL") == "se_market"


def test_infer_listing_market_from_symbol() -> None:
    assert infer_listing_market(symbol="VOLV-B.ST") == "se_market"
    assert infer_listing_market(symbol="AAPL") == "us_market"
