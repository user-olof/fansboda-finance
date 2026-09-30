# Product Requirements Document — fansboda-finance

## 1. Overview

`fansboda-finance` is a lightweight, scheduled data pipeline that tracks a
watchlist of stock tickers and maintains their key moving-average indicators in
a managed Postgres database. Once a week (Saturday, after the Friday close) it fetches recent price history from
[yfinance](https://github.com/ranaroussi/yfinance), computes the 50-day and
200-day simple moving averages (SMAs), records the latest close, and inserts a
new row per ticker per `trading_date` into a [Neon](https://neon.tech) Postgres
database. Rows older than one year are deleted after each run.

The system is designed to run at near-zero cost: a single GCP `e2-micro`
Always-Free VM executes the job via cron, and Neon's free tier stores the data.

## 2. Goals & Non-Goals

### Goals

- Maintain a rolling one-year history of SMA-50, SMA-200, current price,
  **momentum** (`sma_50 / sma_200`), and cross-sectional **`z_score`** for a
  user-managed watchlist of symbols (one row per ticker per `trading_date`).
- Detect **Golden Cross** and **Death Cross** processes on that retained weekly
  SMA history for the US, Swedish, and UK watchlists (see §5.6).
- Run fully unattended on a weekly schedule (Saturdays).
- Keep monthly operating cost at ~$0 within GCP Always Free and Neon free tiers.
- Be resilient to transient data-provider failures (rate limits, timeouts).
- Avoid redundant work by skipping symbols that already have a row for the
  latest `trading_date`.

### Non-Goals

- No user-facing UI or API — data is consumed directly from Postgres (and from
  ad-hoc detection output in §5.6).
- No intraday / real-time quotes; the weekly job runs once weekly (Saturday).
- No additional technical indicators beyond SMA-50, SMA-200, current price,
  and the derived `momentum` / `z_score` fields in §6 — including no EMA, RSI,
  MACD, and no alternate moving-average windows in v1.
- No push notifications, alerting, or watchers for cross detections (or other
  signals).
- No dedicated detections table or persisted detection history in this product
  pass — detection is computed on demand from retained `*_metrics` rows.
- No portfolio, order, or transaction tracking.
- No authentication/authorization layer (single-owner, infra-level access only).

## 3. Users & Use Cases

- **Primary user:** the project owner, who maintains personal watchlists of
  US, Swedish (`.ST`), and UK (`.L`) symbols and queries the country metrics
  tables (`us_metrics` / `swe_metrics` / `uk_metrics`) to see which stocks are
  above/below their long-term moving averages.
- **Primary use case — Golden / Death Cross detection:** detect completed
  **Golden Cross** and **Death Cross** processes from stored weekly
  `sma_50` / `sma_200` history (no yfinance at detection time). Each pattern
  is a three-stage process that may span multiple weekly snapshots:

  - **Golden Cross:** (1) downtrend or consolidation — SMA-50 below SMA-200;
    (2) convergence — the gap narrows as recent prices strengthen; (3)
    crossover — SMA-50 crosses **above** SMA-200.
  - **Death Cross:** (1) uptrend or consolidation — SMA-50 above SMA-200;
    (2) convergence — the gap narrows as recent prices weaken vs the longer
    trend; (3) crossover — SMA-50 crosses **below** SMA-200.

  Use **`momentum`** and **`z_score`** (vs peers in the same country set /
  listing `market` on that date via `*_market_metrics`) to rank relative
  strength for heatmaps; sector views via `*_tickers.sector`.
- **Watchlist management:** add or remove symbols by editing `us_tickers`,
  `swe_tickers`, or `uk_tickers` (directly via SQL or by running the seeding
  script).

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
                                              |   US: us_tickers, us_metrics,    |
                                              |       us_market_metrics          |
                                              |   SE: swe_tickers, swe_metrics,  |
                                              |       swe_market_metrics         |
                                              |   UK: uk_tickers, uk_metrics,    |
                                              |       uk_market_metrics          |
                                              |   + us_/swe_/uk_by_sector        |
                                              +----------------------------------+
```

- **Compute:** GCP `e2-micro` VM, timezone UTC, cron-scheduled weekly on Saturdays.
- **Data source:** yfinance (Yahoo Finance), batched downloads with retry.
- **Storage:** Neon Postgres (serverless free tier).
- **CI/CD:** GitHub Actions for test (pytest) and deploy to the Production VM
  (see §8).

## 5. Functional Requirements

### 5.1 Weekly SMA fetch (`fetch_sma.py`)

- **FR-1 Load watchlist:** Read all symbols and names from `us_tickers`,
  `swe_tickers`, and `uk_tickers` (`load_tickers_from_db`). Fail clearly if all
  three are empty.
- **FR-2 Skip fresh data:** For each ticker, skip fetching if the matching
  country metrics table (`us_metrics` / `swe_metrics` / `uk_metrics`) already
  has its row for the current UTC week (`week_start` = Monday) and that row's
  `trading_date` is on or after the newest bar the run can expect — Friday on
  Saturday/Sunday, otherwise today (`filter_stale_tickers`). Re-runs after
  the Saturday job are cheap, a mid-week manual run never blocks the Saturday
  job from storing the full Friday close, and every ticker is re-fetched each
  new week — freshness is never judged only against the newest date already
  stored.
- **FR-3 Batch download:** Fetch ~300 days of OHLCV history in configurable
  batches (default 40 symbols/batch) with a delay between batches.
- **FR-4 Retry/backoff:** Retry retryable failures (HTTP 429, rate, timeout,
  connection, empty frames) with exponential backoff (`download_batch`).
- **FR-5 Compute metrics:** From daily closes compute SMA-50 and SMA-200; skip
  symbols with fewer than 200 valid closes. Capture the latest close as
  `current_price` and the latest bar's date as `trading_date`. Compute
  **`momentum`** = `sma_50 / sma_200` (NULL when either SMA is NULL or
  `sma_200` is zero). After per-ticker values for a week are known,
  upsert cross-sectional **`momentum_mean`** / **`momentum_std`** into the
  matching `*_market_metrics` row, then set each ticker's **`z_score`** =
  `(momentum - momentum_mean) / momentum_std` (NULL when `momentum` or
  aggregates are missing, or `momentum_std` is zero).
- **FR-6 Insert:** Write one row per ticker per calendar week into
  `us_metrics`, `swe_metrics`, or `uk_metrics` (`insert_metrics`), keyed by
  `week_start` (Monday of `trading_date`), including `momentum` and `z_score`.
  Use `ON CONFLICT (ticker, week_start) DO UPDATE … WHERE EXCLUDED.trading_date
  > existing trading_date`: a newer bar in the same week replaces the row, an
  equal or older bar is ignored, so re-runs are idempotent.
- **FR-7 Retention purge:** After inserts, delete rows from `us_metrics` /
  `swe_metrics` / `uk_metrics` (and the matching `*_market_metrics` tables)
  where `trading_date` (`week_start` for `*_market_metrics`) is older than
  one year (`purge_stale_metrics`).
- **FR-7a Sector trends:** After the retention purge, recompute the
  `*_by_sector` rows for every week written in this run and prune sector weeks
  that no longer exist in the metrics tables (§5.7, `refresh_sector_trends`).
  A failure here is logged and exits non-zero.
- **FR-8 Observability:** Log per-batch progress, per-ticker results, insert
  and purge counts, and a final summary (total / skipped / fetched / failed
  batches). Exit non-zero on fatal errors (missing `DATABASE_URL`, no metrics
  collected, DB failure).

### 5.2 Watchlist seeding (`seed_tickers.py`)

- **FR-9 Load symbols:** Read symbols from a text file (one per line, `#`
  comments and blanks ignored), uppercased.
- **FR-10 Resolve names:** Fetch each company's name from yfinance metadata
  (`longName`, falling back to `shortName`), with a small rate-limit delay.
- **FR-11 Upsert tickers:** Insert/update
  `(symbol, company, sector, industry, market, exchange_name, business_summary)`
  rows into `us_tickers`, `swe_tickers`, or `uk_tickers` on conflict by
  `symbol` (country chosen by listing market / symbol suffix — see §6). Resolve
  `exchange_name` from yfinance `fullExchangeName` and `business_summary` from
  `longBusinessSummary`. Support an optional
  `--country us|swe|uk` filter so only symbols that route to that country set
  are resolved and upserted (required for per-country `dev-backfill` — §8.1).
- **FR-11a One-off business summary fill:** `seed_tickers.py
  --update-business-summary [--country us|swe|uk]` resolves
  `business_summary` for every ticker already in the tickers tables and
  updates only that column (and `updated_at`); the symbol file is ignored and
  tickers whose yfinance lookup fails are left unchanged.
- **FR-12 Ad-hoc metadata refresh:** `refresh_tickers.py` updates watchlist
  metadata on an ad-hoc basis — re-resolve `company`, `sector`, `industry`,
  listing `market`, `exchange_name` (`fullExchangeName`), and
  `business_summary` (`longBusinessSummary`) from yfinance and
  upsert them into `us_tickers` / `swe_tickers` / `uk_tickers`. It operates on
  both:
  - **Existing symbols** already present in a country tickers table (refresh
    their metadata in place), and
  - **New symbols** found in the symbol file that are not yet in any tickers
    table (resolve their metadata and add them as new rows).

  It applies the same rate-limiting and upsert-on-conflict behavior as
  seeding. CLI: default file ∪ DB merge; `--from-db`; optional `--symbols` subset.

### 5.4 Historical backfill (`backfill_sma.py`)

One-off manual script to bootstrap SMA history. **Not** part of the recurring
Saturday schedule.

- **FR-13 Batch download:** Fetch two years (~730 days) of daily OHLCV per
  ticker batch (default 25 symbols/batch) with retry/backoff and a delay between
  batches.
- **FR-14 Weekly snapshots:** Bucket each ticker's bars by calendar week
  (Monday-based `week_start`). For every week, compute one SMA snapshot at the
  week's last bar (normally Friday) using only closes up to and including that
  bar; skip weeks with fewer than 200 closes so far. Snapshots therefore align
  with what the Saturday job stores, regardless of the day the backfill runs.
- **FR-15 Insert history:** Write rows to `us_metrics` / `swe_metrics` /
  `uk_metrics` with the same week upsert as FR-6, so interrupted runs can
  resume without duplicates and a week holding an older (mid-week) bar is
  upgraded to the week's last bar.
- **FR-16 Skip existing:** Before insert, skip `(ticker, trading_date)` pairs
  already present in the matching country metrics table.
- **FR-17 Observability:** Log per-batch generated, new, inserted, and
  skipped-existing counts plus a final summary.
- **FR-18 Country-set scope:** Backfill must accept a required country-set
  filter (`us` | `swe` | `uk`) so a run only loads tickers from that set's
  `*_tickers` table and only writes that set's `*_metrics` /
  `*_market_metrics`. Adding a new country later (e.g. UK) must not re-download
  or re-touch an already-backfilled set (e.g. US) — even though inserts are
  idempotent, a full multi-set run would still hit yfinance and upsert market
  aggregates for the other sets.
- **FR-18a Exchange scope (optional):** `--exchange NAME` further limits the
  run to tickers whose `exchange_name` matches `NAME` (case-insensitive exact
  match on yfinance `fullExchangeName`, e.g. `NasdaqGS`, `NYSE`, `Stockholm`,
  `LSE`); repeat the flag to include several exchanges. If no ticker matches,
  the run fails and logs the exchange names present in that set. Market
  aggregates and z_scores for the touched weeks are still recomputed from
  every ticker stored for that country set and week.

Default CLI (scoped examples):

`pipenv run python backfill_sma.py --country us`

`pipenv run python backfill_sma.py --country us --exchange NasdaqGS --exchange NYSE`

Run once per country set after seeding that set's tickers (and applying
`migrate_metrics_history.sql` when upgrading a legacy DB). Prefer separate
runs over one all-country backfill so production/dev history for an existing
set is not re-processed when another set is added.

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
| `metrics_retention_days` | 365 | 365 | Delete `us_metrics` / `swe_metrics` / `uk_metrics` rows with `trading_date` (and matching `*_market_metrics` rows with `week_start`) older than this |
| `backfill_history_days` | 730 | 730 | Days of OHLCV history per backfill batch download |
| `backfill_batch_size` | 25 | 25 | Symbols per yfinance batch during backfill |
| `backfill_batch_delay_seconds` | 5.0 | 5.0 | Delay between backfill batches |

`DevConfig` and `ProdConfig` may override any of the shared defaults where
environments differ (e.g. more conservative batch delays in production).

### 5.6 Golden Cross & Death Cross detection

Detection-only feature over retained weekly SMA history. Does **not** call
yfinance; does **not** run on the Saturday cron schedule in v1.

- **FR-19 Source of truth:** Read only from the country metrics tables
  (`us_metrics` / `swe_metrics` / `uk_metrics`), using `sma_50`, `sma_200`, and
  `trading_date` (ordered per ticker). Do not fetch prices at detection time.
- **FR-20 MA pair:** Treat SMA-50 as the shorter moving average and SMA-200 as
  the longer moving average for all stage checks.
- **FR-21 Golden Cross stages:** A Golden Cross event is emitted only when a
  ticker completes all three stages in order over retained weekly snapshots
  (a full process may take multiple weeks):

  1. **Downtrend or consolidation** — shorter MA (SMA-50) sits below longer MA
     (SMA-200).
  2. **Convergence** — the gap between them narrows as recent prices
     strengthen.
  3. **Crossover** — shorter MA crosses **above** the longer MA.

- **FR-22 Death Cross stages:** A Death Cross event is emitted only when a
  ticker completes all three stages in order (mirror of Golden Cross):

  1. **Uptrend or consolidation** — shorter MA sits above longer MA.
  2. **Convergence** — the gap narrows as recent prices weaken vs the longer
     trend.
  3. **Crossover** — shorter MA crosses **below** the longer MA.

- **FR-23 Scope:** Support all three country sets. Allow filtering to one
  country and/or a symbol subset for an ad-hoc run.
- **FR-24 Consumption:** Provide an ad-hoc runnable entrypoint (CLI or
  equivalent) that prints human-readable and machine-readable output of
  completed Golden Cross and Death Cross detections. Do not schedule this on
  cron in v1.
- **FR-25 Gaps & incomplete sequences:** Skip rows where `sma_50` or `sma_200`
  is NULL. Incomplete stage sequences (stages 1–2 without a completed stage 3,
  or out-of-order history) must not emit an event.
- **FR-26 Stage config:** Stage windows and numeric thresholds are
  configurable. Exact default values are **not** frozen in this PRD — they
  belong in application config and a later design RFC.

### 5.7 Sector trend averages (`compute_sector_trends.py`)

Equal-weighted weekly trend summary per sector, from an investor's
perspective: every company counts once regardless of market cap. Derived
entirely from stored data — no yfinance calls.

- **FR-27 Source:** Join each country metrics table to its tickers table
  (`us_metrics` ⋈ `us_tickers`, etc.) and group by `tickers.sector` and
  `week_start`. Only rows with non-NULL `momentum` and a non-blank `sector`
  contribute.
- **FR-28 Sector key:** Normalize `sector` to the yfinance `sectorKey` form
  (`lower`, trimmed, spaces → `-`) so a display-name fallback such as
  "Financial Services" merges with `financial-services`.
- **FR-29 Measures:** Per sector and week store `ticker_count`,
  `momentum_mean` (average `sma_50 / sma_200`), `momentum_median`,
  `z_score_mean` (average cross-sectional `z_score`), and `pct_uptrend`
  (percentage 0–100 of companies with `sma_50 > sma_200`). All averages are
  equal-weighted. Every sector is stored regardless of size; consumers filter
  on `ticker_count` when they need a minimum sample.
- **FR-30 Write semantics:** Each `(country, week)` is replaced atomically
  (delete the week's rows, insert fresh aggregates, one transaction), so
  re-runs are idempotent and sectors that lose all tickers disappear.
- **FR-31 Retention:** Each run deletes `*_by_sector` weeks with no remaining
  rows in the matching metrics table, so sector history follows the metrics
  retention window (FR-7) without its own cutoff.
- **FR-32 Invocation:** Runs as part of the weekly job (FR-7a) for the weeks
  just written, and standalone via
  `pipenv run python compute_sector_trends.py [--country us|swe|uk] [--week YYYY-MM-DD]`
  — default recomputes every stored week for all three country sets; `--week`
  is normalized to that week's Monday. Run it standalone after
  `backfill_sma.py` / `backfill_market.py`, which do not refresh sector rows.
- **FR-33 Observability:** Log scope and a summary line with rows written and
  rows pruned. Exit non-zero on DB failure.

## 6. Data Model

Data is partitioned by listing country into three parallel table sets with the
same column layouts.

| Set | Watchlist | SMA history | Cross-sectional aggregates | Sector trends |
|-----|-----------|-------------|----------------------------|---------------|
| US stocks | `us_tickers` | `us_metrics` | `us_market_metrics` | `us_by_sector` |
| Swedish stocks | `swe_tickers` | `swe_metrics` | `swe_market_metrics` | `swe_by_sector` |
| UK stocks | `uk_tickers` | `uk_metrics` | `uk_market_metrics` | `uk_by_sector` |

**Country routing (seed / refresh / insert):**

| Set | Typical symbol suffix | Typical yfinance `market` |
|-----|----------------------|---------------------------|
| US | (none / other) | `us_market` |
| Swedish | `.ST` | `se_market` |
| UK | `.L` | `uk_market` |

### Watchlist tables (`us_tickers` / `swe_tickers` / `uk_tickers`)

| Column | Type | Notes |
|--------|------|-------|
| `symbol` | TEXT | Primary key |
| `company` | TEXT | Company name |
| `sector` | TEXT | Sector from yfinance (using `sectorKey`) |
| `industry` | TEXT | Industry from yfinance (using `industryKey`) |
| `market` | TEXT | Listing market from yfinance (e.g. `us_market`, `se_market`, `uk_market`) |
| `exchange_name` | TEXT | Exchange display name from yfinance `fullExchangeName` |
| `business_summary` | TEXT | Company description from yfinance `longBusinessSummary` |
| `updated_at` | TIMESTAMPTZ | When the row was written |

### Metrics tables (`us_metrics` / `swe_metrics` / `uk_metrics`)

One row per ticker per calendar week (`week_start`) within that country set.

| Column | Type | Notes |
|--------|------|-------|
| `id` | BIGSERIAL | Primary key |
| `ticker` | TEXT | FK → matching `*_tickers.symbol` `ON DELETE CASCADE` |
| `company` | TEXT | Copied from the matching tickers table at fetch time |
| `week_start` | DATE | Monday of the calendar week containing `trading_date` |
| `trading_date` | DATE | Market session used for this snapshot (the latest bar stored for the week) |
| `updated_at` | TIMESTAMPTZ | When the row was written |
| `currency` | TEXT | Currency code |
| `sma_50` | NUMERIC(18,6) | 50-day SMA of closes |
| `sma_200` | NUMERIC(18,6) | 200-day SMA of closes |
| `current_price` | NUMERIC(18,6) | Adjusted close on `trading_date` |
| `momentum` | NUMERIC(18,6) | `sma_50 / sma_200` |
| `z_score` | NUMERIC(18,6) | `(momentum - momentum_mean) / momentum_std` using that week's matching `*_market_metrics` aggregates |

Unique constraint on `(week_start, ticker)`. Each week adds one row per
ticker; a later bar in the same week replaces it (FR-6). Rows with
`trading_date` older than one year are deleted on each run.

### Market metrics tables (`us_market_metrics` / `swe_market_metrics` / `uk_market_metrics`)

Cross-sectional momentum stats for one country set; one row per
`(market, week_start)`. Aggregates `momentum` from that set's metrics rows
in that week, so every ticker's weekly snapshot contributes even when their
bar dates differ (holidays, exchange calendars).

| Column | Type | Notes |
|--------|------|-------|
| `market` | TEXT | Listing market bucket (e.g. `us_market`, `se_market`, `uk_market`); matches the set's tickers `market` values |
| `week_start` | DATE | Monday of the snapshot week |
| `updated_at` | TIMESTAMPTZ | When the row was written |
| `momentum_mean` | NUMERIC(18,6) | Mean of tickers' `momentum` in this set in this week |
| `momentum_std` | NUMERIC(18,6) | St. dev. of tickers' `momentum` in this set in this week |

Primary key on `(market, week_start)`. Rows with `week_start` older
than one year are deleted on each weekly run (same retention as the metrics
tables).

### Sector trend tables (`us_by_sector` / `swe_by_sector` / `uk_by_sector`)

Equal-weighted weekly trend averages per sector (§5.7); one row per
`(sector, week_start)`.

| Column | Type | Notes |
|--------|------|-------|
| `sector` | TEXT | Normalized `tickers.sector` (`sectorKey` form, e.g. `technology`) |
| `week_start` | DATE | Monday of the snapshot week |
| `updated_at` | TIMESTAMPTZ | When the row was written |
| `ticker_count` | INTEGER | Companies contributing (non-NULL `momentum`) |
| `momentum_mean` | NUMERIC(18,6) | Average `momentum` |
| `momentum_median` | NUMERIC(18,6) | Median `momentum` |
| `z_score_mean` | NUMERIC(18,6) | Average `z_score` (NULL z-scores ignored) |
| `pct_uptrend` | NUMERIC(18,6) | % of companies with `sma_50 > sma_200` (0–100) |

Primary key on `(sector, week_start)`. Weeks absent from the matching metrics
table are pruned on each run (FR-31).

Deleting a row from `us_tickers`, `swe_tickers`, or `uk_tickers` cascades to all
of its rows in the matching metrics table.

## 7. Non-Functional Requirements

- **Cost:** ~$0/month within GCP Always Free (`e2-micro`) and Neon free tier.
- **Reliability:** Transient provider errors must not abort the whole run; a
  failed batch is logged and counted, and the job still inserts what it has.
- **Idempotency:** Re-running in the same week is a no-op for tickers whose
  week row already holds the newest expected bar; inserts upsert per
  `(ticker, week_start)` and only replace a row with a newer bar.
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

### 8.1 Backfill (`.github/workflows/dev-backfill.yml`)

Triggered **only by manual `workflow_dispatch`** — not on push to `dev` (or any
other branch).

Each dispatch must target **exactly one** country set so markets can be
bootstrapped independently (US today, UK later, etc.) without re-running
backfill for sets that already have history.

- **Inputs:** required `country` = `us` | `swe` | `uk` (maps to the matching
  `*_tickers` / `*_metrics` / `*_market_metrics` set in §6).
- **Spin up a VM:** Create ephemeral `data-fetcher-dev` in GCP; firewall must
  allow GitHub Actions SSH via IAP.
- **Deploy:** On spin-up success, deploy code and write `.env` on the Dev VM;
  apply schema / migrations against the Neon **dev** branch (full schema still;
  data collection is scoped).
- **Data collection:** On deploy success, seed and backfill **only** the
  selected country set (e.g. `seed_tickers.py --country uk` then
  `backfill_sma.py --country uk`). Do not process other country sets in that
  run.
- **Verification:** On data collection success without a fatal error; analyze
  missing data, failed downloads, etc., for the selected country set, and print
  the result.
- **Delete VM:** Always tear down `data-fetcher-dev` (including on failure).

**Rationale:** Country tables are isolated, but an unscoped seed/backfill still
re-resolves and re-downloads every symbol in the tickers file. Scoping keeps a
later UK (or SWE) bootstrap from polluting or re-touching production/dev US
history and from burning yfinance quota on sets that are already complete.

### 8.2 Production  

- **Test (`.github/workflows/test.yml`):** Runs `pytest` on push/PR to `main`.
- **Deploy (`.github/workflows/deploy.yml`):** Runs if and only if the test
  workflow succeeds for a push to `main` (`workflow_run`), and deploys exactly
  the tested commit to the Production VM. Failed tests or PR runs never deploy.
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
- Cron entry on the VM (`crontab -u fansboda -e`) — **Saturdays at 11:00 UTC** (every market has closed for the week, so each row holds a full Friday close):
  `0 11 * * 6 cd /opt/fansboda-finance && pipenv run python fetch_sma.py >> /var/log/fansboda-finance/fetch_sma.log 2>&1`
- First-time setup: run `schema.sql` in Neon, then `scripts/bootstrap-vm.sh` on
  the VM (as root/sudo). Existing databases upgrade via the `migrate_*.sql`
  scripts. Seed **per country set** as needed (e.g.
  `pipenv run python seed_tickers.py --country us`, and separately for `swe` /
  `uk` when ready). For historical SMA data, run `migrate_metrics_history.sql`
  in Neon when upgrading a legacy DB, then backfill **per country set** (manual,
  not cron), e.g. `pipenv run python backfill_sma.py --country us` (and
  separately for `swe` / `uk` when those watchlists are ready). Use the same
  `--country` scope on the manual `dev-backfill` workflow (§8.1).
- Verify data:
  `SELECT * FROM us_metrics ORDER BY trading_date DESC, ticker LIMIT 10;`
  (and the same against `swe_metrics` / `uk_metrics`)
- Check retention:
  `SELECT MIN(trading_date), MAX(trading_date), COUNT(*) FROM us_metrics;`
  (and the same against `swe_metrics` / `uk_metrics`)
- Market snapshot:
  `SELECT * FROM us_market_metrics ORDER BY trading_date DESC, market LIMIT 10;`
  (and the same against `swe_market_metrics` / `uk_market_metrics`)
- Sector trends (after migration step 17, fill history once with
  `pipenv run python compute_sector_trends.py`):
  `SELECT * FROM us_by_sector WHERE week_start = (SELECT MAX(week_start) FROM us_by_sector) ORDER BY z_score_mean DESC;`

## 11. Future Considerations (Out of Current Scope)

- **Golden Cross / Death Cross detection** (stage semantics, ad-hoc
  consumption, config knobs) is **in scope** via §5.6 — not a future idea.
  Still out of current scope for that feature:
  - Push notifications, alerting, or watchers when a cross completes.
  - Persisting detections in a dedicated table / detection history store.
  - Exact numeric stage windows and thresholds (defer to a design RFC /
    config defaults; see FR-26).
- Additional indicators (EMA, RSI, MACD) or alternate moving-average windows
  beyond the SMA-50 / SMA-200 pair used by §5.6.
- A read API or dashboard for the `us_metrics` / `swe_metrics` / `uk_metrics`
  data.
- Gap detection for missed weekly runs.
