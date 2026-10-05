#!/usr/bin/env python3
"""Send one test message with the active config (PRD §8.2 / RFC-017).

The only supported way to verify Gmail delivery; never run ``fetch_sma.py``
just to test email. Run on the VM as ``fansboda`` after the one-time Gmail /
domain-wide delegation setup:

    pipenv run python scripts/send_test_email.py
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import get_config  # noqa: E402
from gmail_client import send_email  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> int:
    try:
        config = get_config()
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    if not config.alert_email_from or not config.alert_email_to:
        logger.error("ALERT_EMAIL_FROM and ALERT_EMAIL_TO must both be set")
        return 1

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    try:
        message_id = send_email(
            sender=config.alert_email_from,
            recipient=config.alert_email_to,
            subject="fansboda-finance: test email",
            body=(
                "Test message from scripts/send_test_email.py.\n"
                "Gmail API delivery via domain-wide delegation works.\n"
                f"Sent {now}.\n"
            ),
            max_retries=config.yf_max_retries,
            retry_base_seconds=config.yf_retry_base_seconds,
        )
    except Exception:
        logger.exception("Test email failed")
        return 1

    logger.info(
        "Test email sent from %s to %s (message id %s)",
        config.alert_email_from,
        config.alert_email_to,
        message_id,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
