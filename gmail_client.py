"""Keyless Gmail API delivery for the data-quality email (PRD FR-49 / RFC-017).

The VM's attached service account signs a domain-wide-delegation JWT through
the IAM Credentials API (its metadata-server token authorizes the signing) and
exchanges it for a Gmail token impersonating the Workspace sender. No key file,
refresh token, or SMTP password is stored anywhere.
"""

from __future__ import annotations

import base64
import logging
import time
from collections.abc import Callable
from email.message import EmailMessage
from typing import Any

import requests

from config import DEFAULT_YF_MAX_RETRIES, DEFAULT_YF_RETRY_BASE_SECONDS

logger = logging.getLogger(__name__)

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
TOKEN_URI = "https://oauth2.googleapis.com/token"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
REQUEST_TIMEOUT_SECONDS = 30


class GmailSendError(RuntimeError):
    """Gmail API rejected or could not deliver the message."""


def build_raw_message(*, sender: str, recipient: str, subject: str, body: str) -> str:
    """Return the base64url-encoded RFC 2822 message Gmail expects in ``raw``."""
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


def delegated_session(sender: str) -> Any:
    """Authorized session acting as ``sender`` via domain-wide delegation."""
    import google.auth
    from google.auth import iam
    from google.auth.transport.requests import AuthorizedSession, Request
    from google.oauth2 import service_account

    request = Request()
    source, _ = google.auth.default(scopes=[CLOUD_PLATFORM_SCOPE])
    source.refresh(request)
    service_account_email = source.service_account_email
    signer = iam.Signer(request, source, service_account_email)
    credentials = service_account.Credentials(
        signer,
        service_account_email,
        TOKEN_URI,
        scopes=[GMAIL_SEND_SCOPE],
        subject=sender,
    )
    return AuthorizedSession(credentials)


def send_email(
    *,
    sender: str,
    recipient: str,
    subject: str,
    body: str,
    max_retries: int = DEFAULT_YF_MAX_RETRIES,
    retry_base_seconds: float = DEFAULT_YF_RETRY_BASE_SECONDS,
    session_factory: Callable[[str], Any] = delegated_session,
) -> str | None:
    """Send one plain-text email; returns the Gmail message id.

    Retries 429 / 5xx and connection errors with exponential backoff; other
    HTTP errors (e.g. 400 / 401 / 403) raise ``GmailSendError`` immediately.
    """
    raw = build_raw_message(
        sender=sender, recipient=recipient, subject=subject, body=body
    )
    session = session_factory(sender)
    for attempt in range(max_retries + 1):
        try:
            response = session.post(
                GMAIL_SEND_URL, json={"raw": raw}, timeout=REQUEST_TIMEOUT_SECONDS
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            error: Exception = exc
        else:
            if response.status_code < 300:
                return response.json().get("id")
            error = GmailSendError(
                f"Gmail API returned HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )
            if response.status_code not in RETRYABLE_STATUS:
                raise error
        if attempt == max_retries:
            raise error
        wait = retry_base_seconds * (2**attempt)
        logger.warning(
            "Gmail send failed (attempt %d/%d): %s; retrying in %.1fs",
            attempt + 1,
            max_retries + 1,
            error,
            wait,
        )
        time.sleep(wait)
    return None
