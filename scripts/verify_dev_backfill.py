#!/usr/bin/env python3
"""Verify dev backfill CI results from job logs and Neon dev branch (RFC-011)."""

from __future__ import annotations

import argparse
import os
import re
import sys

import psycopg2

BACKFILL_SUMMARY_RE = re.compile(
    r"Backfill summary: tickers=(\d+) generated=(\d+) inserted=(\d+) "
    r"skipped_existing=(\d+) market_trading_dates=(\d+) failed_batches=(\d+)"
)
SEED_SUMMARY_RE = re.compile(r"Seeded (\d+) ticker\(s\) from ")


def parse_backfill_summary(log_text: str) -> dict[str, int] | None:
    """Return the last Backfill summary line parsed as integers."""
    matches = BACKFILL_SUMMARY_RE.findall(log_text)
    if not matches:
        return None
    tickers, generated, inserted, skipped, market_trading_dates, failed = matches[-1]
    return {
        "tickers": int(tickers),
        "generated": int(generated),
        "inserted": int(inserted),
        "skipped_existing": int(skipped),
        "market_trading_dates": int(market_trading_dates),
        "failed_batches": int(failed),
    }


def parse_seed_count(log_text: str) -> int | None:
    """Return seeded ticker count from the last matching log line."""
    matches = SEED_SUMMARY_RE.findall(log_text)
    if not matches:
        return None
    return int(matches[-1])


def analyze_log(log_text: str) -> tuple[list[str], dict[str, int | None]]:
    """Return verification issues and parsed summary fields from the job log."""
    issues: list[str] = []
    seed_count = parse_seed_count(log_text)
    summary = parse_backfill_summary(log_text)

    if seed_count is None:
        issues.append("Missing seed summary line in collect-data log")
    elif seed_count == 0:
        issues.append("No tickers seeded")

    if summary is None:
        issues.append("Missing Backfill summary line in collect-data log")
    else:
        if summary["failed_batches"] > 0:
            issues.append(
                f"Backfill reported {summary['failed_batches']} failed batch(es)"
            )
        if summary["generated"] == 0 and summary["skipped_existing"] == 0:
            issues.append("No metrics generated during backfill")

    if "Failed backfill batch" in log_text:
        issues.append("Log contains failed backfill batch exceptions")

    fields: dict[str, int | None] = {
        "seed_count": seed_count,
        **(summary or {}),
    }
    return issues, fields


def query_database(database_url: str) -> dict[str, int]:
    """Return ticker and metrics counts from the dev database."""
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM tickers")
            ticker_count = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(DISTINCT ticker) FROM metrics")
            metrics_ticker_count = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM metrics")
            metrics_row_count = int(cur.fetchone()[0])

    return {
        "ticker_count": ticker_count,
        "metrics_ticker_count": metrics_ticker_count,
        "metrics_row_count": metrics_row_count,
    }


def verify_database(
    database_url: str, *, expected_seed_count: int | None
) -> tuple[list[str], dict[str, int]]:
    """Check dev branch has tickers and metrics after backfill."""
    issues: list[str] = []
    counts = query_database(database_url)

    if counts["ticker_count"] == 0:
        issues.append("Database has no tickers")
    if counts["metrics_row_count"] == 0:
        issues.append("Database has no metrics rows")
    if (
        counts["ticker_count"] > 0
        and counts["metrics_ticker_count"] < counts["ticker_count"]
    ):
        missing = counts["ticker_count"] - counts["metrics_ticker_count"]
        issues.append(f"{missing} ticker(s) have no metrics rows")

    if expected_seed_count is not None and counts["ticker_count"] < expected_seed_count:
        issues.append(
            f"Database ticker count ({counts['ticker_count']}) "
            f"below seeded count ({expected_seed_count})"
        )

    return issues, counts


def format_report(
    log_fields: dict[str, int | None],
    db_counts: dict[str, int] | None,
    issues: list[str],
) -> str:
    """Build a human-readable verification summary for Actions logs."""
    lines = ["Dev backfill verification summary", "--------------------------------"]
    if log_fields.get("seed_count") is not None:
        lines.append(f"Seeded tickers (log): {log_fields['seed_count']}")
    if "generated" in log_fields and log_fields["generated"] is not None:
        lines.append(
            "Backfill (log): "
            f"generated={log_fields['generated']} "
            f"inserted={log_fields.get('inserted')} "
            f"skipped_existing={log_fields.get('skipped_existing')} "
            f"market_trading_dates={log_fields.get('market_trading_dates')} "
            f"failed_batches={log_fields.get('failed_batches')}"
        )
    if db_counts:
        lines.append(
            "Database: "
            f"tickers={db_counts['ticker_count']} "
            f"metrics_tickers={db_counts['metrics_ticker_count']} "
            f"metrics_rows={db_counts['metrics_row_count']}"
        )
    if issues:
        lines.append("Status: FAIL")
        for issue in issues:
            lines.append(f"  - {issue}")
    else:
        lines.append("Status: PASS")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify dev backfill CI run")
    parser.add_argument(
        "log_file",
        help="Collect-data job log captured from SSH output",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Neon dev branch URL (defaults to DATABASE_URL env)",
    )
    args = parser.parse_args(argv)

    log_text = open(args.log_file, encoding="utf-8").read()
    log_issues, log_fields = analyze_log(log_text)
    issues = list(log_issues)
    db_counts: dict[str, int] | None = None

    database_url = args.database_url or os.environ.get("DATABASE_URL")
    if database_url:
        db_issues, db_counts = verify_database(
            database_url, expected_seed_count=log_fields.get("seed_count")
        )
        issues.extend(db_issues)

    report = format_report(log_fields, db_counts, issues)
    print(report)

    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
