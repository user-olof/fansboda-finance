"""Tests for the outlier guard email (PRD FR-37b / §5.9, RFC-017)."""

import base64
import email
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
import requests

from config import BaseConfig
from db.country import CountrySet
from db.outliers import LOAD_OUTLIERS_SQL, load_outliers
from fetch_sma import _run_outlier_email
from gmail_client import (
    GMAIL_SEND_URL,
    GmailSendError,
    build_raw_message,
    send_email,
)
from models import OutlierRow
from outlier_email import build_outlier_email

W = date(2025, 12, 1)
NOW = datetime(2025, 12, 6, 11, 5, tzinfo=timezone.utc)


def _outlier(ticker: str = "WYLD.ST", *, is_new: bool = True) -> OutlierRow:
    return OutlierRow(
        country="swe",
        ticker=ticker,
        company="Wyld Networks",
        week_start=W,
        trading_date=date(2025, 12, 5),
        prev_close=Decimal("0.0041"),
        close=Decimal("1.95"),
        price_growth=Decimal("474.609756"),
        sma_50_growth=Decimal("4.9"),
        sma_200_growth=Decimal("0.2"),
        bound="price_growth > 4",
        is_new=is_new,
    )


def _config(**overrides: object) -> BaseConfig:
    values: dict[str, object] = {
        "database_url": "postgresql://user:secret@db/example",
        "yf_max_retries": 2,
        "yf_retry_base_seconds": 0.0,
    }
    values.update(overrides)
    return BaseConfig(**values)  # type: ignore[arg-type]


# --- db/outliers.py ---------------------------------------------------------


@pytest.mark.parametrize("country", list(CountrySet))
def test_load_outliers_sql_shape(country: CountrySet) -> None:
    sql = " ".join(LOAD_OUTLIERS_SQL[country].split())
    prefix = country.value
    assert f"FROM {prefix}_metrics cur JOIN {prefix}_tickers t" in sql
    assert f"LEFT JOIN {prefix}_metrics prev" in sql
    assert "prev.week_start = cur.week_start - 7" in sql
    assert "cur.week_start = ANY(%s)" in sql
    for growth in ("price_growth", "sma_50_growth", "sma_200_growth"):
        assert f"cur.{growth} NOT BETWEEN %s AND %s" in sql
        assert f"prev.{growth} NOT BETWEEN %s AND %s" in sql
    assert sql.count("%s") == 13


def _mock_conn(rows: list[tuple]) -> tuple[MagicMock, MagicMock]:
    cursor = MagicMock()
    cursor.fetchall.return_value = rows
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.cursor.return_value.__enter__.return_value = cursor
    return conn, cursor


def test_load_outliers_maps_rows_and_new_flag() -> None:
    db_rows = [
        (
            "WYLD.ST", "Wyld", W, date(2025, 12, 5), Decimal("0.0041"),
            Decimal("1.95"), Decimal("474.6"), Decimal("0.1"), Decimal("0.01"), False,
        ),
        (
            "OLD.ST", "Old", W, date(2025, 12, 5), Decimal("1"),
            Decimal("1"), Decimal("0"), Decimal("6"), Decimal("0.01"), True,
        ),
    ]
    conn, cursor = _mock_conn(db_rows)
    with patch("db.outliers.psycopg2.connect", return_value=conn):
        rows = load_outliers(
            "postgresql://example",
            [W, W],
            country=CountrySet.SWE,
            max_growth=4.0,
            min_growth=-0.8,
        )

    bounds = (Decimal("-0.8"), Decimal("4.0")) * 3
    cursor.execute.assert_called_once_with(
        LOAD_OUTLIERS_SQL[CountrySet.SWE], (*bounds, [W], *bounds)
    )
    assert [(r.ticker, r.bound, r.is_new, r.country) for r in rows] == [
        ("WYLD.ST", "price_growth > 4", True, "swe"),
        ("OLD.ST", "sma_50_growth > 4", False, "swe"),
    ]


def test_load_outliers_no_weeks_skips_db() -> None:
    with patch("db.outliers.psycopg2.connect") as mock_connect:
        assert load_outliers(
            "postgresql://example",
            [],
            country=CountrySet.US,
            max_growth=4.0,
            min_growth=-0.8,
        ) == []
    mock_connect.assert_not_called()


# --- outlier_email.py -------------------------------------------------------


def test_build_outlier_email_none_without_new_outliers() -> None:
    assert build_outlier_email([], max_growth=4.0, min_growth=-0.8, now=NOW) is None
    assert (
        build_outlier_email(
            [_outlier(is_new=False)], max_growth=4.0, min_growth=-0.8, now=NOW
        )
        is None
    )


def test_build_outlier_email_content() -> None:
    message = build_outlier_email(
        [_outlier(), _outlier("OLD.ST", is_new=False)],
        max_growth=4.0,
        min_growth=-0.8,
        now=NOW,
    )
    assert message is not None
    subject, body = message
    assert subject == (
        "fansboda-finance: 1 implausible weekly move, week of 2025-12-01"
    )
    for expected in (
        "SWE  WYLD.ST  Wyld Networks",
        "trading_date:      2025-12-05",
        "prev week close:   0.0041 (stored)",
        "close:             1.9500",
        "price_growth:      +47461.0%",
        "sma_50_growth:     +490.0%",
        "bound crossed:     price_growth > 4",
        "excluded from that week's index",
        "1 continuing outlier(s)",
        "Thresholds: growth above 4 (x5) or below -0.8 (x0.2).",
        "Generated 2025-12-06 11:05:00 UTC",
    ):
        assert expected in body, expected
    assert "OLD.ST" not in body


# --- gmail_client.py --------------------------------------------------------


def test_build_raw_message_is_base64url_mime() -> None:
    raw = build_raw_message(
        sender="noreply@example.com",
        recipient="owner@example.com",
        subject="Hi",
        body="Body\n",
    )
    parsed = email.message_from_bytes(base64.urlsafe_b64decode(raw))
    assert parsed["From"] == "noreply@example.com"
    assert parsed["To"] == "owner@example.com"
    assert parsed["Subject"] == "Hi"
    assert parsed.get_payload().strip() == "Body"


def _response(status: int, payload: dict | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.json.return_value = payload or {}
    response.text = "error text"
    return response


def test_send_email_posts_raw_message_as_sender() -> None:
    session = MagicMock()
    session.post.return_value = _response(200, {"id": "msg-1"})
    factory = MagicMock(return_value=session)

    message_id = send_email(
        sender="noreply@example.com",
        recipient="owner@example.com",
        subject="S",
        body="B",
        session_factory=factory,
    )

    assert message_id == "msg-1"
    factory.assert_called_once_with("noreply@example.com")
    url = session.post.call_args.args[0]
    assert url == GMAIL_SEND_URL
    assert "raw" in session.post.call_args.kwargs["json"]


def test_send_email_retries_rate_limit_then_succeeds() -> None:
    session = MagicMock()
    session.post.side_effect = [
        _response(429),
        requests.ConnectionError("reset"),
        _response(200, {"id": "msg-2"}),
    ]
    with patch("gmail_client.time.sleep") as mock_sleep:
        assert send_email(
            sender="a@example.com",
            recipient="b@example.com",
            subject="S",
            body="B",
            max_retries=3,
            retry_base_seconds=1.0,
            session_factory=lambda _sender: session,
        ) == "msg-2"
    assert [c.args[0] for c in mock_sleep.call_args_list] == [1.0, 2.0]


def test_send_email_does_not_retry_forbidden() -> None:
    session = MagicMock()
    session.post.return_value = _response(403)
    with patch("gmail_client.time.sleep") as mock_sleep:
        with pytest.raises(GmailSendError, match="HTTP 403"):
            send_email(
                sender="a@example.com",
                recipient="b@example.com",
                subject="S",
                body="B",
                session_factory=lambda _sender: session,
            )
    assert session.post.call_count == 1
    mock_sleep.assert_not_called()


def test_send_email_gives_up_after_max_retries() -> None:
    session = MagicMock()
    session.post.return_value = _response(503)
    with patch("gmail_client.time.sleep"):
        with pytest.raises(GmailSendError, match="HTTP 503"):
            send_email(
                sender="a@example.com",
                recipient="b@example.com",
                subject="S",
                body="B",
                max_retries=2,
                retry_base_seconds=0.0,
                session_factory=lambda _sender: session,
            )
    assert session.post.call_count == 3


# --- fetch_sma._run_outlier_email -------------------------------------------


def test_run_outlier_email_disabled_logs_instead_of_sending(caplog) -> None:
    with patch("fetch_sma.load_outliers", return_value=[_outlier()]) as mock_load:
        with patch("fetch_sma.send_email") as mock_send:
            with caplog.at_level("INFO", logger="fetch_sma"):
                assert _run_outlier_email(_config(), {W}) == (3, 0)

    assert mock_load.call_count == len(CountrySet)
    mock_send.assert_not_called()
    assert "would send" in caplog.text
    assert "WYLD.ST" in caplog.text
    assert "secret" not in caplog.text


def test_run_outlier_email_sends_when_enabled() -> None:
    config = _config(
        alert_email_enabled=True,
        alert_email_from="noreply@example.com",
        alert_email_to="owner@example.com",
    )
    with patch(
        "fetch_sma.load_outliers",
        side_effect=[[_outlier()], [], [_outlier("OLD.L", is_new=False)]],
    ):
        with patch("fetch_sma.send_email", return_value="msg-1") as mock_send:
            assert _run_outlier_email(config, {W}) == (1, 1)

    kwargs = mock_send.call_args.kwargs
    assert kwargs["sender"] == "noreply@example.com"
    assert kwargs["recipient"] == "owner@example.com"
    assert kwargs["subject"].startswith("fansboda-finance: 1 implausible")
    assert kwargs["max_retries"] == 2


def test_run_outlier_email_nothing_new_sends_nothing() -> None:
    config = _config(
        alert_email_enabled=True,
        alert_email_from="noreply@example.com",
        alert_email_to="owner@example.com",
    )
    with patch("fetch_sma.load_outliers", return_value=[_outlier(is_new=False)]):
        with patch("fetch_sma.send_email") as mock_send:
            assert _run_outlier_email(config, {W}) == (0, 3)
    mock_send.assert_not_called()


def test_run_outlier_email_send_failure_is_logged_not_raised(caplog) -> None:
    config = _config(
        alert_email_enabled=True,
        alert_email_from="noreply@example.com",
        alert_email_to="owner@example.com",
    )
    with patch("fetch_sma.load_outliers", side_effect=[[_outlier()], [], []]):
        with patch("fetch_sma.send_email", side_effect=GmailSendError("HTTP 403")):
            assert _run_outlier_email(config, {W}) == (1, 0)
    assert "Failed to send outlier email" in caplog.text
    assert "WYLD.ST" in caplog.text


def test_run_outlier_email_missing_addresses_logs_error(caplog) -> None:
    with patch("fetch_sma.load_outliers", side_effect=[[_outlier()], [], []]):
        with patch("fetch_sma.send_email") as mock_send:
            _run_outlier_email(_config(alert_email_enabled=True), {W})
    mock_send.assert_not_called()
    assert "ALERT_EMAIL_FROM / ALERT_EMAIL_TO missing" in caplog.text


def test_run_outlier_email_db_failure_is_swallowed(caplog) -> None:
    with patch("fetch_sma.load_outliers", side_effect=RuntimeError("down")):
        assert _run_outlier_email(_config(), {W}) == (0, 0)
    assert "Failed to load outliers" in caplog.text
