"""Plain-text data-quality email for implausible weekly moves (PRD §5.9). No I/O."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from models import OutlierRow


def _pct(value: Decimal | None) -> str:
    return "n/a" if value is None else f"{float(value) * 100:+.1f}%"


def _price(value: Decimal | None) -> str:
    return "n/a" if value is None else f"{float(value):.4f}"


def build_outlier_email(
    outliers: list[OutlierRow],
    *,
    max_growth: float,
    min_growth: float,
    now: datetime,
) -> tuple[str, str] | None:
    """Return ``(subject, body)`` for new outliers, or None when there are none.

    Continuing outliers (also flagged the previous week) are only counted so a
    persistent problem is reported once (FR-47).
    """
    new = [row for row in outliers if row.is_new]
    if not new:
        return None
    continuing = len(outliers) - len(new)

    latest_week = max(row.week_start for row in new)
    count = len(new)
    subject = (
        f"fansboda-finance: {count} implausible weekly "
        f"move{'s' if count != 1 else ''}, week of {latest_week.isoformat()}"
    )

    lines = [
        f"{count} stock-week(s) moved implausibly and were excluded from that "
        "week's equity index:",
        "",
    ]
    for row in sorted(new, key=lambda r: (r.week_start, r.country, r.ticker)):
        lines.extend(
            [
                f"{row.country.upper()}  {row.ticker}  {row.company or ''}".rstrip(),
                f"  trading_date:      {row.trading_date.isoformat()}",
                f"  prev week close:   {_price(row.prev_close)} (stored)",
                f"  close:             {_price(row.close)}",
                f"  price_growth:      {_pct(row.price_growth)}",
                f"  sma_50_growth:     {_pct(row.sma_50_growth)}",
                f"  sma_200_growth:    {_pct(row.sma_200_growth)}",
                f"  bound crossed:     {row.bound}",
                "  excluded from that week's index",
                "",
            ]
        )
    if continuing:
        lines.extend(
            [
                f"{continuing} continuing outlier(s) already reported in an "
                "earlier week are not listed.",
                "",
            ]
        )
    lines.extend(
        [
            "--",
            f"Thresholds: growth above {max_growth:g} (x{1 + max_growth:g}) or "
            f"below {min_growth:g} (x{1 + min_growth:g}).",
            f"Generated {now.strftime('%Y-%m-%d %H:%M:%S UTC')} by the weekly job.",
        ]
    )
    return subject, "\n".join(lines) + "\n"
