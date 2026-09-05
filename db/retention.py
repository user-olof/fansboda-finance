"""Rolling data retention for country metrics and market_metrics tables (RFC-004)."""

from __future__ import annotations

from db.market import purge_stale_market
from db.metrics import purge_stale_metrics, retention_cutoff

__all__ = [
    "purge_stale_data",
    "purge_stale_market",
    "purge_stale_metrics",
    "retention_cutoff",
]


def purge_stale_data(database_url: str, retention_days: int) -> tuple[int, int]:
    """Delete stale rows from all country history and aggregate tables.

    Purges ``us_metrics``, ``swe_metrics``, ``uk_metrics``, ``us_market_metrics``,
    ``swe_market_metrics``, and ``uk_market_metrics`` where ``trading_date`` is
    older than the retention window (UTC cutoff).

    Returns ``(metrics_deleted, market_metrics_deleted)``.
    """
    metrics_purged = purge_stale_metrics(database_url, retention_days)
    market_metrics_purged = purge_stale_market(database_url, retention_days)
    return metrics_purged, market_metrics_purged
