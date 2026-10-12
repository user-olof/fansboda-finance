"""Rolling data retention for country metrics, market_metrics, and indices (RFC-004)."""

from __future__ import annotations

from db.indices import purge_stale_indices
from db.market import purge_stale_market
from db.metrics import purge_stale_metrics, retention_cutoff

__all__ = [
    "purge_stale_data",
    "purge_stale_indices",
    "purge_stale_market",
    "purge_stale_metrics",
    "retention_cutoff",
]


def purge_stale_data(
    database_url: str, retention_days: int
) -> tuple[int, int, int]:
    """Delete stale rows from all country history and aggregate tables.

    Purges ``us_metrics``, ``swe_metrics``, and ``uk_metrics`` where
    ``trading_date`` is older than the retention window (UTC cutoff), and
    ``us_market_metrics``, ``swe_market_metrics``, and ``uk_market_metrics``
    and ``indices`` where ``week_start`` is older than it.

    Returns ``(metrics_deleted, market_metrics_deleted, indices_deleted)``.
    """
    metrics_purged = purge_stale_metrics(database_url, retention_days)
    market_metrics_purged = purge_stale_market(database_url, retention_days)
    indices_purged = purge_stale_indices(database_url, retention_days)
    return metrics_purged, market_metrics_purged, indices_purged
