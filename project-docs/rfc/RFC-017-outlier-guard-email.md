# RFC-017: Outlier Guard & Data-Quality Email

| Field | Value |
|-------|-------|
| **Priority** | P3 |
| **Status** | **Proposed** |
| **Depends on** | RFC-006, RFC-007, RFC-009, RFC-015, RFC-016 |
| **PRD** | §2, §5.1 (FR-7c), §5.5, §5.8 (FR-37b, FR-45), §5.9 (FR-46–FR-51), §8.2, §9 |
| **Feature** | [Equity indices](../FEATURES.md#equity-indices), [Data-quality email](../FEATURES.md#data-quality-email) |

## Summary

Corporate-action handling layer 3. A stock-week whose weekly growth is
implausible (more than ×5 up or below ÷5 down, configurable) is excluded from
that week's equity index (RFC-015), and the weekly job emails the owner's
work address about **newly** detected outliers via the Gmail API, sent from a
Google Workspace mailbox using the VM's attached service account and
domain-wide delegation — no stored key, token, or password.

Outliers are derived from stored `*_metrics` growth columns (RFC-016) and the
thresholds; no extra table, no schema migration, no extra yfinance calls.

## Requirements

| ID | Requirement |
|----|-------------|
| FR-37b | Outlier = any of `price_growth` / `sma_50_growth` / `sma_200_growth` (or the FR-37a gap-week ratio) `> outlier_max_growth` (4.0) or `< outlier_min_growth` (−0.8). Excluded from all three levels and `N` that week; base weeks not guarded |
| FR-45 | `WARNING` log per excluded outlier + outlier count per index |
| FR-7c / FR-46 | Only the weekly job emails, once per run, after indices; standalone `compute_indices.py` / backfills only log |
| FR-47 | Email only outliers whose stock was **not** an outlier in the previous calendar week; no outliers → no email; report count of continuing outliers |
| FR-48 | Plain-text subject/body as in PRD (country, ticker, company, `trading_date`, previous / current close, three growth values, bound crossed, "excluded from index"; thresholds + UTC timestamp footer); no secrets |
| FR-49 | Gmail API `users.messages.send`, scope `gmail.send`, from `alert_email_from` to `alert_email_to`; VM SA signs its delegation JWT via IAM Credentials `signJwt`, `subject = alert_email_from` |
| FR-50 | Send failure → `ERROR` log with outlier list; run does not fail; transient errors retried with FR-4 backoff |
| FR-51 | `alert_email_enabled` (dev off / prod on); when off, log subject + body |

## Design

### Configuration (`config.py`, RFC-006)

| Setting | Env var | Dev | Prod |
|---------|---------|-----|------|
| `outlier_max_growth` | `OUTLIER_MAX_GROWTH` | 4.0 | 4.0 |
| `outlier_min_growth` | `OUTLIER_MIN_GROWTH` | −0.8 | −0.8 |
| `alert_email_enabled` | `ALERT_EMAIL_ENABLED` | `false` | `true` |
| `alert_email_from` | `ALERT_EMAIL_FROM` | optional | required when enabled |
| `alert_email_to` | `ALERT_EMAIL_TO` | optional | required when enabled |

`ProdConfig` validation: enabled without both addresses → log an `ERROR` at
email time and skip sending (data collection must not depend on email).

### Modules

| Path | Change |
|------|--------|
| `equity_index.py` | Pure `is_outlier(growths, *, max_growth, min_growth) -> str | None` (returns the crossed bound, e.g. `"price_growth > 4.0"`) |
| `db/indices.py` | Chained / gap-week stats SQL add `AND x_growth BETWEEN %s AND %s` for all three measures (bounds as parameters); `write_index_weeks` takes the bounds and logs outliers via the loader below |
| `db/outliers.py` | `load_outliers(database_url, week_starts, *, country, max_growth, min_growth) -> list[OutlierRow]` — parameterized SQL over `{metrics}` ⋈ `{tickers}` for the given weeks, with a `LEFT JOIN` on the same ticker's previous-calendar-week row to set `is_new` (FR-47); returns previous close via that join |
| `models.py` | `OutlierRow(country, ticker, company, week_start, trading_date, prev_close, close, price_growth, sma_50_growth, sma_200_growth, bound, is_new)` |
| `outlier_email.py` | Pure `build_outlier_email(outliers, *, max_growth, min_growth, now) -> (subject, body) | None` (None when no new outliers) |
| `gmail_client.py` | `send_email(*, sender, recipient, subject, body)` — keyless auth (below), retry with `yf_max_retries` / `yf_retry_base_seconds` backoff on 429 / 5xx / connection errors |
| `fetch_sma.py` | `_run_outlier_email(config, week_starts_by_country)` after `_run_indices`; catches and logs all email errors (FR-50); summary line gains `outliers_new` / `outliers_continuing` |
| `scripts/send_test_email.py` | Sends one fixed test message with the active config — the only way to test delivery (never run `fetch_sma.py` to test email) |
| `Pipfile` / `Pipfile.lock` | Add `google-auth` and `requests` |

### Keyless Gmail auth (`gmail_client.py`)

```python
from google.auth import default, iam
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2 import service_account

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.send"
TOKEN_URI = "https://oauth2.googleapis.com/token"

source, _ = default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
source.refresh(Request())
sa_email = source.service_account_email
signer = iam.Signer(Request(), source, sa_email)
creds = service_account.Credentials(
    signer, sa_email, TOKEN_URI, scopes=[GMAIL_SCOPE], subject=sender,
)
AuthorizedSession(creds).post(
    "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
    json={"raw": base64url(mime_message)},
)
```

The metadata-server token authorizes `signJwt`; the signed JWT is exchanged
for a Gmail token impersonating `alert_email_from`. Nothing secret lives on
disk; addresses are not secrets but are kept out of the repo in the VM
`.env`.

### Deploy (RFC-007)

`deploy.yml` adds `ALERT_EMAIL_FROM` / `ALERT_EMAIL_TO` (GitHub `production`
environment secrets) to the VM `.env`, same `install -o fansboda -g fansboda
-m 600` path. `ALERT_EMAIL_ENABLED` follows `APP_ENV` defaults unless set.

### One-time setup (outside the repo, PRD §8.2)

1. Enable the **Gmail API** and **IAM Service Account Credentials API**.
2. Grant the VM SA `roles/iam.serviceAccountTokenCreator` on itself; VM
   access scopes include `cloud-platform`.
3. Workspace admin: Domain-wide delegation → VM SA client ID → scope
   `https://www.googleapis.com/auth/gmail.send` only.
4. Choose the sender Workspace user (`ALERT_EMAIL_FROM`) and set
   `ALERT_EMAIL_TO`; add both as `production` secrets.
5. After deploy: `pipenv run python scripts/send_test_email.py` on the VM as
   `fansboda`.

## Tests

- `is_outlier`: each measure above / below bounds, boundaries, NULLs.
- Index SQL: bound parameters present on all three growth columns in chained
  and gap-week queries; an outlier stock does not move levels or `N`.
- `load_outliers` SQL parameterized; `is_new` false when the previous week
  was also an outlier.
- `build_outlier_email`: none / only continuing → `None`; subject count and
  body fields; no `DATABASE_URL` in output.
- `gmail_client` with mocked `google.auth` and session: payload is base64url
  MIME with the right From / To; retries on 429; no retry on 400/403.
- `fetch_sma`: email failure is logged and exit code unchanged; disabled
  config logs instead of sending.
- `test_sql_security.py`: no SQL in `outlier_email.py` / `gmail_client.py`.

## Rollout

1. RFC-016 rolled out (growth columns filled, indices rebuilt).
2. Complete the one-time setup.
3. Deploy; run `scripts/send_test_email.py`.
4. Rebuild indices so history excludes outliers:
   `pipenv run python compute_indices.py`.

## Open questions

- None. The Workspace admin must allow domain-wide delegation; if the
  organisation forbids it, revisit FR-49 (e.g. OAuth refresh token for a
  dedicated mailbox) before implementing.
