"""Rolling data retention for metrics and market tables (RFC-004)."""

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
    """Delete stale metrics and market rows. Returns (metrics_deleted, market_deleted)."""
    metrics_purged = purge_stale_metrics(database_url, retention_days)
    market_purged = purge_stale_market(database_url, retention_days)
    return metrics_purged, market_purged
