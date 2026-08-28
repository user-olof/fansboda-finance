"""Tests for dev backfill verification script (RFC-011)."""

from unittest.mock import patch

from scripts.verify_dev_backfill import analyze_log, format_report, parse_backfill_summary, verify_database


def test_parse_backfill_summary_extracts_last_line() -> None:
    log = (
        "noise\n"
        "Backfill summary: tickers=3 generated=10 inserted=8 "
        "skipped_existing=2 failed_batches=0\n"
        "Backfill summary: tickers=3 generated=12 inserted=12 "
        "skipped_existing=0 failed_batches=1\n"
    )
    summary = parse_backfill_summary(log)
    assert summary == {
        "tickers": 3,
        "generated": 12,
        "inserted": 12,
        "skipped_existing": 0,
        "failed_batches": 1,
    }


def test_analyze_log_flags_missing_summary() -> None:
    issues, fields = analyze_log("Seeded 2 ticker(s) from tickers.txt\n")
    assert any("Missing Backfill summary" in issue for issue in issues)
    assert fields["seed_count"] == 2


def test_analyze_log_passes_clean_run() -> None:
    log = (
        "Seeded 2 ticker(s) from tickers.txt\n"
        "Backfill summary: tickers=2 generated=20 inserted=20 "
        "skipped_existing=0 failed_batches=0\n"
    )
    issues, fields = analyze_log(log)
    assert issues == []
    assert fields["seed_count"] == 2
    assert fields["failed_batches"] == 0


def test_format_report_shows_pass_status() -> None:
    report = format_report(
        {"seed_count": 2, "generated": 20, "inserted": 20, "failed_batches": 0},
        {"ticker_count": 2, "metrics_ticker_count": 2, "metrics_row_count": 20},
        [],
    )
    assert "Status: PASS" in report
    assert "tickers=2" in report
    assert "market_rows" not in report


def test_verify_database_passes_without_market_rows() -> None:
    with patch("scripts.verify_dev_backfill.query_database") as mock_query:
        mock_query.return_value = {
            "ticker_count": 2,
            "metrics_ticker_count": 2,
            "metrics_row_count": 20,
        }
        issues, counts = verify_database("postgresql://example", expected_seed_count=2)

    assert issues == []
    assert "market_row_count" not in counts
