# Product Requirements Document — fansboda-finance

## 1. Overview

`fansboda-finance` is a lightweight, scheduled data pipeline that tracks a
watchlist of stock tickers and maintains their key moving-average indicators in
a managed Postgres database. Once a week (Thursday) it fetches recent price history from
[yfinance](https://github.com/ranaroussi/yfinance), computes the 50-day and
200-day simple moving averages (SMAs), records the latest close, and inserts a
new row per ticker per `trading_date` into a [Neon](https://neon.tech) Postgres
database. Rows older than one year are deleted after each run.

The system is designed to run at near-zero cost: a single GCP `e2-micro`
Always-Free VM executes the job via cron, and Neon's free tier stores the data.

## 2. Goals & Non-Goals

### Goals

- Maintain a rolling one-year history of SMA-50, SMA-200, and current price for
  a user-managed watchlist of symbols (one row per ticker per `trading_date`).
- Run fully unattended on a weekly schedule (Thursdays).
- Keep monthly operating cost at ~$0 within GCP Always Free and Neon free tiers.
- Be resilient to transient data-provider failures (rate limits, timeouts).
- Avoid redundant work by skipping symbols that already have a row for the
  latest `trading_date`.

### Non-Goals

- No user-facing UI or API — data is consumed directly from Postgres.
- No intraday / real-time quotes; the job runs once weekly (Thursday).
- No additional technical indicators beyond SMA-50, SMA-200, and current price.
- No portfolio, order, or transaction tracking.
- No authentication/authorization layer (single-owner, infra-level access only).

## 3. Users & Use Cases

- **Primary user:** the project owner, who maintains a personal watchlist
  (Swedish `.ST` symbols and others) and queries the `metrics` table to see
  which stocks are above/below their long-term moving averages.
- **Primary use case:** identify golden-cross / death-cross style signals by
  comparing `current_price`, `sma_50`, and `sma_200` for each watched symbol,
  including trends over the retained history.
- **Watchlist management:** add or remove symbols by editing the `tickers`
  table (directly via SQL or by running the seeding script).

## 4. System Architecture

```
+-------------------+   cron Thu @ 11:00 UTC   +---------------------+
|  GCP e2-micro VM  |  ─────────────────────▶  |  fetch_sma.py       |
|  (Debian 12)      |                            |  (weekly job)       |
+-------------------+                                 +----------+----------+
                                                                 │
                          yfinance batch download                │ insert
                                                                 ▼
                                              +----------------------------------+
                                              |  Neon Postgres                   |
                                              |   - tickers  (watchlist)         |
                                              |   - metrics  (SMA history)       |
                                              +----------------------------------+
```

- **Compute:** GCP `e2-micro` VM, timezone UTC, cron-scheduled weekly on Thursdays.
- **Data source:** yfinance (Yahoo Finance), batched downloads with retry.
- **Storage:** Neon Postgres (serverless free tier).
- **CI/CD:** GitHub Actions for test (pytest) and deploy to the Production VM
  (see §8).

## 5. Functional Requirements

### 5.1 Weekly SMA fetch (`fetch_sma.py`)

- **FR-1 Load watchlist:** Read all symbols and names from the `tickers` table
  (`load_tickers_from_db`). Fail clearly if the table is empty.
- **FR-2 Skip fresh data:** For each ticker, skip fetching if a `metrics` row
  already exists for that ticker's latest `trading_date` (`filter_stale_tickers`),
  reducing API load.
- **FR-3 Batch download:** Fetch ~300 days of OHLCV history in configurable
  batches (default 40 symbols/batch) with a delay between batches.
- **FR-4 Retry/backoff:** Retry retryable failures (HTTP 429, rate, timeout,
  connection, empty frames) with exponential backoff (`download_batch`).
- **FR-5 Compute metrics:** From daily closes compute SMA-50 and SMA-200; skip
  symbols with fewer than 200 valid closes. Capture the latest close as
  `current_price` and the latest bar's date as `trading_date`.
- **FR-6 Insert:** Append one new row per ticker into `metrics` for the
  computed `trading_date` (`insert_metrics`). Do not overwrite prior rows; use
  `ON CONFLICT (ticker, trading_date) DO NOTHING` so re-runs are idempotent.
- **FR-7 Retention purge:** After inserts, delete `metrics` rows where
  `trading_date` is older than one year (`purge_stale_metrics`).
- **FR-8 Observability:** Log per-batch progress, per-ticker results, insert
  and purge counts, and a final summary (total / skipped / fetched / failed
  batches). Exit non-zero on fatal errors (missing `DATABASE_URL`, no metrics
  collected, DB failure).

### 5.2 Watchlist seeding (`seed_tickers.py`)

- **FR-9 Load symbols:** Read symbols from a text file (one per line, `#`
  comments and blanks ignored), uppercased.
- **FR-10 Resolve names:** Fetch each company's name from yfinance metadata
  (`longName`, falling back to `shortName`), with a small rate-limit delay.
- **FR-11 Upsert tickers:** Insert/update `(symbol, name)` rows into the
  `tickers` table on conflict by `symbol`.
- **FR-12 Ad-hoc metadata refresh:** `refresh_tickers.py` updates watchlist
  metadata on an ad-hoc basis — re-resolve `company`, `sector`, and `industry`
  from yfinance and upsert them into `tickers`. It operates on both:
  - **Existing symbols** already present in the `tickers` table (refresh their
    metadata in place), and
  - **New symbols** found in the symbol file that are not yet in `tickers`
    (resolve their metadata and add them as new rows).

  It applies the same rate-limiting and upsert-on-conflict behavior as
  seeding. CLI: default file ∪ DB merge; `--from-db`; optional `--symbols` subset.

### 5.4 Historical backfill (`backfill_sma.py`)

One-off manual script to bootstrap SMA history. **Not** part of the recurring
Thursday schedule.

- **FR-13 Batch download:** Fetch two years (~730 days) of daily OHLCV per
  ticker batch (default 25 symbols/batch) with retry/backoff and a delay between
  batches.
- **FR-14 Rolling week windows:** From each ticker's oldest bar, assign week
  index 0, 1, 2, … counting forward in 7-day steps. Build rolling **52-week**
  windows (weeks 0–51, then 1–52, then 2–53, and so on). Each window produces
  one SMA snapshot at the last trading day in the window.
- **FR-15 Insert history:** Append rows to `metrics` with
  `ON CONFLICT (ticker, trading_date) DO NOTHING` so interrupted runs can
  resume without duplicates.
- **FR-16 Skip existing:** Before insert, skip `(ticker, trading_date)` pairs
  already present in the database.
- **FR-17 Observability:** Log per-batch generated, new, inserted, and
  skipped-existing counts plus a final summary.

Run once after seeding `tickers` and applying `migrate_metrics_history.sql`:

`pipenv run python backfill_sma.py`

### 5.5 Configuration

All configuration is centralized in a single configuration module (e.g.
`config.py`) with two classes:

- **`DevConfig`** — used for local development (loads secrets such as
  `DATABASE_URL` from a git-ignored `.env` via `python-dotenv`).
- **`ProdConfig`** — used on the Production VM (values supplied by the
  deploy workflow / VM environment).

Scripts select the active config at startup (e.g. via an `APP_ENV` environment
variable or equivalent). Application code reads tunables from the chosen config
object instead of calling `os.getenv` directly.

| Setting | Dev default | Prod default | Purpose |
|---------|-------------|--------------|---------|
| `database_url` | from `.env` (required) | from VM `.env` (required) | Neon Postgres connection string |
| `tickers_file` | `tickers.txt` | `tickers.txt` | Seed file path for `seed_tickers.py` |
| `yf_batch_size` | 40 | 40 | Symbols per yfinance batch |
| `yf_batch_delay_seconds` | 2.0 | 2.0 | Delay between batches |
| `yf_max_retries` | 3 | 3 | Max retries per batch |
| `yf_retry_base_seconds` | 5.0 | 5.0 | Backoff base (doubles per attempt) |
| `yf_name_delay_seconds` | 0.25 | 0.25 | Delay between name lookups when seeding |
| `metrics_retention_days` | 365 | 365 | Delete `metrics` rows with `trading_date` older than this |
| `backfill_history_days` | 730 | 730 | Days of OHLCV history per backfill batch download |
| `backfill_window_weeks` | 52 | 52 | Rolling window length (weeks 0–51, then 1–52, …) |
| `backfill_batch_size` | 25 | 25 | Symbols per yfinance batch during backfill |
| `backfill_batch_delay_seconds` | 5.0 | 5.0 | Delay between backfill batches |

`DevConfig` and `ProdConfig` may override any of the shared defaults where
environments differ (e.g. more conservative batch delays in production).

## 6. Data Model

### Table `tickers` (watchlist)

| Column | Type | Notes |
|--------|------|-------|
| `symbol` | TEXT | Primary key |
| `company` | TEXT | Company name |
| `sector` | TEXT | Sector from yfinance (using sectorKey) |
| `industry` | TEXT | Industry from yfinance (using industryKey) |
| `updated_at` | TIMESTAMPTZ | When the row was written |

### Table `metrics` (SMA history, one row per ticker per `trading_date`)

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGSERIAL | Primary key |
| `ticker` | TEXT | FK → `tickers.symbol` `ON DELETE CASCADE` |
| `company` | TEXT | Copied from `tickers` at fetch time |
| `trading_date` | DATE | Market session used for this snapshot |
| `updated_at` | TIMESTAMPTZ | When the row was written |
| `currency` | TEXT | Currency code |
| `sma_50` | NUMERIC(18,6) | 50-day SMA of closes |
| `sma_200` | NUMERIC(18,6) | 200-day SMA of closes |
| `current_price` | NUMERIC(18,6) | Adjusted close on `trading_date` |

Unique constraint on `(ticker, trading_date)`. Multiple rows per ticker are
expected; each weekly run appends a new snapshot. Rows with `trading_date`
older than one year are deleted on each run.

Deleting a row from `tickers` cascades to all of its `metrics` rows.

## 7. Non-Functional Requirements

- **Cost:** ~$0/month within GCP Always Free (`e2-micro`) and Neon free tier.
- **Reliability:** Transient provider errors must not abort the whole run; a
  failed batch is logged and counted, and the job still inserts what it has.
- **Idempotency:** Re-running in the same week is a no-op for tickers that
  already have a row for that `trading_date`; inserts use conflict-safe append.
  Retention purge is safe to repeat.
- **Security:** No credentials in the repo. `.env` is git-ignored and local
  only; production `DATABASE_URL` lives in GitHub secrets and is written to the
  VM on deploy. The Production VM uses a service account attached at the instance
  level. GitHub Actions authenticates to GCP via a short-lived **OIDC JWT** and
  Workload Identity Federation — no long-lived service account keys (`GCP_SA_KEY`).
- **Maintainability:** Pure, testable functions (parsing/compute separated from
  I/O); unit tests cover parsing, SMA math, batching, and DB-interaction logic
  via mocks.

## 8. CI/CD

### 8.1 Backfill

- **Spin up a VM:** On push to `dev`, spins up a new VM (`data-fetcher-dev`) in GCP and create a firewall rule allowing GitHub Actions to access the VM via SSH 
- **Deploy:** On `Spin up a VM` being successfully completed, deploys to the new Dev VM
- **Data collection:** On `Deploy` being successfully completed; requests, retrieves and stores the data in the Neon database (dev branch)
- **Verification:** On `Data collection` being completed without an interrupting error; analyze if there were any missing data, failed downloads etc and print the result 
- **Delete VM:** Delete VM 

### 8.2 Production  

- **Test (`.github/workflows/test.yml`):** Runs `pytest` on push/PR to `main`.
- **Deploy (`.github/workflows/deploy.yml`):** On push to `main`, deploys to the
  Production VM.
- Branch protection on `main` should require the test workflow to pass.

### Production pipeline

- The Production VM has a **service account attached** at the instance level.
  Code and agents on the VM authenticate as that identity through the metadata
  server — no key file on disk.
- The deploy workflow pulls the repo on the VM, installs deps
  (`pipenv install --deploy`), and writes the VM `.env` from the `DATABASE_URL`
  secret via `gcloud compute scp`.
- Required GitHub secrets: `GCP_PROJECT_ID`, `GCP_ZONE`, `GCP_INSTANCE_NAME`,
  `DATABASE_URL`, `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_DEPLOY_SERVICE_ACCOUNT`.

### Deploy authentication (GitHub OIDC JWT)

The **deploy service account** is a dedicated GCP identity used only by
GitHub Actions to SSH/SCP into the VM. It must **not** use a downloaded JSON key.
Instead, the deploy workflow authenticates with **Workload Identity Federation**
(WIF):

1. GitHub Actions requests a short-lived **OIDC JWT** for the workflow run
   (`permissions: id-token: write`).
2. `google-github-actions/auth` exchanges that JWT with Google for a short-lived
   GCP access token on behalf of the deploy service account.
3. `gcloud compute ssh` / `scp` use that token; no `GCP_SA_KEY` secret.

One-time GCP setup (outside the repo):

- Create a Workload Identity Pool and a GitHub OIDC provider (issuer
  `https://token.actions.githubusercontent.com`).
- Create a deploy service account and grant it the IAM roles in the table below.
- Bind the pool to the deploy SA (`roles/iam.workloadIdentityUser`), restricted
  to this repository (and optionally the `main` branch / `production` environment).

In `deploy.yml`, authenticate with:

```yaml
permissions:
  contents: read
  id-token: write

# ...
- uses: google-github-actions/auth@v2
  with:
    workload_identity_provider: ${{ secrets.GCP_WORKLOAD_IDENTITY_PROVIDER }}
    service_account: ${{ secrets.GCP_DEPLOY_SERVICE_ACCOUNT }}
```

### Service account permissions (GCP)

The **deploy service account** (authenticated via GitHub OIDC JWT) needs the
following IAM roles:

| Role | Granted on | Why |
|------|-----------|-----|
| `roles/compute.instanceAdmin.v1` | Project (or the VM instance) | Read instance details and manage SSH key metadata for `gcloud compute ssh`/`scp` |
| `roles/iam.serviceAccountUser` | The VM's attached service account | Required to SSH/SCP into an instance that runs as a service account |
| `roles/compute.osLogin` | Project (or the VM instance) | Log in to the VM when **OS Login** is enabled (use `roles/compute.osAdminLogin` if sudo is needed) |
| `roles/iap.tunnelResourceAccessor` | Project (or the VM instance) | Only if connecting via IAP TCP tunneling (`--tunnel-through-iap`) instead of a public IP |

Notes:

- **OS Login must be enabled** on the project or VM for the `compute.osLogin`
  role to apply; otherwise SSH falls back to metadata-based keys covered by
  `compute.instanceAdmin.v1`.
- Grant on the specific instance rather than the whole project where possible,
  following least-privilege.
- The VM's **attached** service account (separate from the deploy SA) is the
  runtime identity for workloads on that instance. It needs no special GCP roles
  for the weekly job itself, since `fetch_sma.py` only makes outbound calls
  (yfinance, Neon) using `DATABASE_URL` from `.env`.
- Do not create or store JSON keys for the deploy service account; OIDC JWT via
  WIF is the only supported deploy auth path.

## 9. Dependencies

Python 3.11+. Key libraries: `yfinance`, `pandas`, `psycopg2-binary`,
`python-dotenv`. Dependencies are pinned via `Pipfile`/`Pipfile.lock`
(`requirements.txt` provided as an export).

## 10. Operational Notes

- **Cron user:** The weekly job runs as a dedicated Linux user `fansboda`
  (`crontab -u fansboda`). That user owns `/opt/fansboda-finance`, the Pipenv
  venv, `.env`, and the job log — not `root`. After deploy, `.env` must remain
  readable by `fansboda` (see deploy workflow `chown`).
- Cron entry on the VM (`crontab -u fansboda -e`) — **Thursdays at 11:00 UTC**:
  `0 11 * * 4 cd /opt/fansboda-finance && pipenv run python fetch_sma.py >> /var/log/fansboda-finance/fetch_sma.log 2>&1`
- First-time setup: run `schema.sql` in Neon, then `scripts/bootstrap-vm.sh` on
  the VM (as root/sudo). Existing databases upgrade via the `migrate_*.sql`
  scripts. For historical SMA data, run `migrate_metrics_history.sql` in Neon,
  then `pipenv run python backfill_sma.py` once (manual, not cron).
- Verify data: `SELECT * FROM metrics ORDER BY trading_date DESC, ticker LIMIT 10;`
- Check retention: `SELECT MIN(trading_date), MAX(trading_date), COUNT(*) FROM metrics;`

## 11. Future Considerations (Out of Current Scope)

- Additional indicators (EMA, RSI, MACD) or signal/alerting layer.
- A read API or dashboard for the `metrics` data.
- Gap detection for missed weekly runs.
