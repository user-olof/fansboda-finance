# Features — fansboda-finance

Feature overview derived from [PRD.md](./PRD.md). The PRD remains the authoritative specification for requirements and acceptance criteria.

## Summary

| Area | Description |
|------|-------------|
| Weekly SMA pipeline | Thursday job fetches prices, computes SMA-50/200, appends history |
| Normalized SMA ratios | Per-ticker `raw_50` / `raw_200` (SMA ÷ price) for cross-sectional comparison |
| Market aggregates | Per-`trading_date` mean and std of `raw_50` / `raw_200` across the watchlist |
| Historical backfill | Bootstrap of rolling weekly SMA snapshots (~2 years of data) |
| Watchlist seeding | Load symbols from file, resolve company metadata, upsert into Postgres |
| Rolling retention | Keeps ~1 year of `metrics` history; older rows purged after each weekly run |
| Centralized configuration | `DevConfig` / `ProdConfig` in `config.py`; selected via `APP_ENV` |
| Zero-cost ops | **One** GCP `e2-micro` (Always Free) + Neon Postgres free tier |
| CI/CD — production | `pytest` on PR to `main`; deploy to long-lived Production VM on push to `main` |
| CI/CD — dev backfill | Ephemeral `data-fetcher-dev` on push to `dev`; IAP SSH firewall + seed/backfill/verify pipeline (PRD §8.1, [RFC-011](./rfc/RFC-011-dev-backfill-ci.md)) |

---

## Users & use cases

- **Primary user:** project owner with a personal watchlist (Swedish `.ST` symbols and others).
- **Primary use case:** query `metrics` to compare `current_price`, `sma_50`, and `sma_200` — including trends over retained history (golden-cross / death-cross style signals). Use `raw_50`, `raw_200`, and the `market` table to rank tickers relative to the watchlist on each `trading_date` (cross-sectional normalization for heatmaps and sector views).
- **Watchlist management:** add or remove symbols via SQL on `tickers` or by running `seed_tickers.py`.

---

## Core data features

### SMA metrics history

- Stores **SMA-50**, **SMA-200**, and **current price** (adjusted close) per ticker.
- Stores **raw_50** and **raw_200** — SMA divided by `current_price` (`sma_50 / current_price`, `sma_200 / current_price`) for scale-free comparison across tickers.
- Stores **currency** from yfinance at fetch/backfill time. **Company** is copied from `tickers` into each snapshot.
- **Sector** and **industry** are watchlist-level fields on `tickers`, not duplicated per metric row.
- One row per `(ticker, trading_date)` — each weekly run appends a new snapshot.
- Idempotent inserts: `ON CONFLICT (ticker, trading_date) DO NOTHING`.

### Market aggregates

- **`market` table:** one row per `trading_date` with cross-sectional stats over the watchlist for that date.
- **`raw_mean_50` / `raw_mean_200`:** mean of all tickers' `raw_50` / `raw_200` on the date.
- **`raw_std_50` / `raw_std_200`:** standard deviation of all tickers' `raw_50` / `raw_200` on the date.
- Supports unbiased heatmap coloring (e.g. z-scores or percentile ranks vs the watchlist) without raw SMA-distance bias.

### Watchlist

- **`tickers` table:** `symbol` (primary key), `company`, `sector`, `industry`, `updated_at`.
- `sector` and `industry` come from yfinance (`sectorKey`, `industryKey`).
- Symbols include Swedish `.ST` listings and other markets.
- Deleting a ticker cascades to all its `metrics` rows.

### Data retention

- After each weekly run, `metrics` and `market` rows with `trading_date` older than **365 days** are deleted (`db/retention.py`).
- Retention purge runs even when all tickers are already fresh (nothing to fetch).
- Purge counts appear in the weekly job summary log.
- Cutoff uses UTC date via `metrics_retention_days` (configurable).

### Schema (`tickers` / `metrics` / `market`)

| Table | Key columns |
|-------|-------------|
| `tickers` | `symbol` (PK), `company`, `sector`, `industry`, `updated_at` |
| `metrics` | `id` (PK), `ticker` (FK → `tickers.symbol`), `company`, `trading_date`, `updated_at`, `currency`, `sma_50`, `sma_200`, `current_price`, `raw_50`, `raw_200` |
| `market` | `trading_date`, `updated_at`, `raw_mean_50`, `raw_mean_200`, `raw_std_50`, `raw_std_200` |

`company` on `metrics` is copied from `tickers` at fetch time. `currency` is the listing currency code captured per snapshot. `raw_50` and `raw_200` are `sma_50 / current_price` and `sma_200 / current_price`. Price and ratio columns use `NUMERIC(18, 6)`. Unique on `metrics (ticker, trading_date)`; one `market` row per `trading_date`.

DDL: `schema.sql` for new databases; `migrate_*.sql` for upgrades ([MIGRATIONS.md](./MIGRATIONS.md)).

---

## Pipeline jobs

### Weekly SMA fetch (`fetch_sma.py`)

Scheduled **Thursdays at 11:00 UTC** on the Production VM (FR-1 – FR-8).

| Capability | Detail |
|------------|--------|
| Load watchlist | Reads symbols and company names from `tickers`; fails clearly if empty |
| Skip fresh data | Skips tickers that already have a row at their latest `trading_date` |
| Batch download | ~300 days OHLCV via yfinance (default 40 symbols/batch) |
| Retry / backoff | Retries 429, rate limits, timeouts, connection errors, empty frames |
| Compute SMAs | Requires ≥200 valid daily closes; captures latest close and `trading_date` |
| Raw ratios | Computes `raw_50` and `raw_200` (`sma / current_price`) per ticker |
| Market stats | Aggregates mean and std of `raw_50` / `raw_200` into `market` for the snapshot date |
| yfinance metadata | Captures `currency` per snapshot; copies `company` from `tickers` |
| Append metrics | Inserts new rows without overwriting history |
| Retention purge | Deletes `metrics` and `market` rows older than configured retention (default 365 days) |
| Observability | Per-batch progress, per-ticker results, insert/purge counts, final summary |

### Watchlist seeding (`seed_tickers.py`)

Manual / ad-hoc script for initial and ongoing watchlist setup (FR-9 – FR-11).

| Capability | Detail |
|------------|--------|
| Load symbols | Reads symbol file (one per line; `#` comments ignored); uppercases |
| Resolve company | Fetches company name from yfinance (`longName`, fallback `shortName`) |
| Resolve sector / industry | Fetches `sectorKey` / `industryKey` from yfinance (same rate-limit pattern as company lookups) |
| Upsert | Insert or update `(symbol, company, sector, industry)` on conflict by `symbol`; sets `updated_at` |
| Rate limiting | Configurable delay between yfinance lookups (default 0.25s) |

### Watchlist metadata refresh (`refresh_tickers.py`)

Ad-hoc script to refresh watchlist metadata without a full re-seed (FR-12, RFC-010). **Not** cron-scheduled.

| Capability | Detail |
|------------|--------|
| Refresh existing | Re-resolve `company`, `sector`, and `industry` for symbols already in `tickers` |
| Add new | Include symbols from file not yet in `tickers` (same upsert as seed) |
| Symbol selection | Default: union of tickers file and DB; `--from-db` for all DB symbols; `--symbols AAPL,MSFT.ST` for a subset |
| Reuse | Same yfinance resolution and rate limiting as `seed_tickers.py` via `resolve_and_upsert_symbols` |

### Historical backfill (`backfill_sma.py`)

Bootstrap script for SMA history — **not** part of the weekly cron (FR-13 – FR-17). Used manually or via dev CI on push to `dev` (§8.1).

| Capability | Detail |
|------------|--------|
| Batch download | ~730 days daily OHLCV (default 25 symbols/batch) with retry and inter-batch delay |
| Rolling 52-week windows | Week 0 anchored at oldest bar; windows 0–51, 1–52, 2–53, … |
| SMA snapshots | One metric row per window at the last trading day in the window |
| Raw ratios | Populates `raw_50` and `raw_200` on each inserted metrics row |
| Market stats | Upserts cross-sectional `market` rows for all backfilled trading dates |
| Currency | Resolves listing `currency` per ticker (same rate-limit pattern as weekly fetch) |
| Skip existing | Skips `(ticker, trading_date)` pairs already in the database |
| Resume-safe | `ON CONFLICT DO NOTHING`; interrupted runs can continue without duplicates |

**Fresh database:** `schema.sql` → `seed_tickers.py` → `backfill_sma.py`

**Legacy database:** apply `migrate_*.sql` as needed; `migrate_metrics_history.sql` before backfill when upgrading from one-row-per-ticker layout.

---

## Configuration

All tunables live in **`config.py`** (PRD §5.5):

| Class | Environment |
|-------|-------------|
| `DevConfig` | Local development; loads git-ignored `.env` via `python-dotenv` |
| `ProdConfig` | Production VM; values from VM `.env` / environment |

`get_config()` selects by `APP_ENV` (`dev` default; `prod` / `production` → `ProdConfig`).

| Setting | Dev default | Prod default | Purpose |
|---------|-------------|--------------|---------|
| `database_url` | from `.env` (required) | from VM `.env` (required) | Neon connection string |
| `tickers_file` | `tickers.txt` | `tickers.txt` | Default seed file path |
| `yf_batch_size` | 40 | 40 | Weekly fetch batch size |
| `yf_batch_delay_seconds` | 2.0 | 2.0 | Delay between fetch batches |
| `yf_max_retries` | 3 | 3 | Max retries per batch |
| `yf_retry_base_seconds` | 5.0 | 5.0 | Exponential backoff base |
| `yf_name_delay_seconds` | 0.25 | 0.25 | Delay between name lookups |
| `metrics_retention_days` | 365 | 365 | Retention purge cutoff |
| `backfill_history_days` | 730 | 730 | Backfill download window |
| `backfill_window_weeks` | 52 | 52 | Rolling SMA window length |
| `backfill_batch_size` | 25 | 25 | Backfill batch size |
| `backfill_batch_delay_seconds` | 5.0 | 5.0 | Delay between backfill batches |

`DevConfig` and `ProdConfig` may override shared defaults per environment.

---

## Infrastructure & operations

### Architecture (PRD §4)

```
GCP e2-micro VM  ──cron Thu 11:00 UTC──▶  fetch_sma.py  ──▶  Neon Postgres
  (Debian 12)         yfinance batches        tickers + metrics + market
```

- **Compute:** one `e2-micro`, UTC, weekly on Thursdays.
- **Storage:** Neon Postgres (free tier).
- **Outbound only:** yfinance + Neon via `DATABASE_URL`; VM attached SA needs no GCP API roles.

### Production VM

- Linux user **`fansboda`** runs cron (not `root`).
- App path: `/opt/fansboda-finance`.
- Logs: `/var/log/fansboda-finance/fetch_sma.log`.
- Bootstrap: `scripts/bootstrap-vm.sh`.

PRD §10 cron:

```
0 11 * * 4 cd /opt/fansboda-finance && pipenv run python fetch_sma.py >> /var/log/fansboda-finance/fetch_sma.log 2>&1
```

Bootstrap installs an enhanced line that also sources `.env` and sets `PIPENV_VENV_IN_PROJECT=1` so `get_config()` receives `APP_ENV=production` and `DATABASE_URL`.

### CI/CD — production (PRD §8.2, implemented)

| Workflow | Trigger | Action |
|----------|---------|--------|
| `test.yml` | Push / PR to `main` | `pipenv run pytest` |
| `deploy.yml` | Push to `main` | SSH to Production VM, `git pull`, `pipenv install --deploy`, write `.env` |

- GitHub **`production`** environment.
- Branch protection on `main` should require tests (`scripts/configure-branch-protection.sh`).
- Deploy auth: **OIDC JWT + WIF** — no `GCP_SA_KEY`.
- VM `.env`: `DATABASE_URL`, `APP_ENV=production`; `chown fansboda:fansboda`, mode `600`.

**GitHub secrets:** `DATABASE_URL`, `GCP_PROJECT_ID`, `GCP_ZONE`, `GCP_INSTANCE_NAME`, `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_DEPLOY_SERVICE_ACCOUNT`.

### CI/CD — dev backfill (PRD §8.1)

On push to **`dev`**, `.github/workflows/dev-backfill.yml` runs a sequential pipeline:

| Step | Runs when | Action |
|------|-----------|--------|
| Spin up VM | Push to `dev` | Create ephemeral `data-fetcher-dev` in GCP (tag `dev-backfill`). Firewall must allow GitHub Actions SSH access — IAP ingress `tcp:22` from `35.235.240.0/20` scoped to that tag. Wait until SSH via `--tunnel-through-iap` succeeds. |
| Deploy | Spin up VM succeeds | SSH to dev VM; `git pull` dev branch, `pipenv install --deploy`; write `.env` with Neon **dev branch** URL |
| Data collection | Deploy succeeds | Run `seed_tickers.py` and `backfill_sma.py`; store results in the dev database |
| Verification | Data collection completes without error | Analyze log for missing data, failed downloads, etc.; run DB sanity checks (`scripts/verify_dev_backfill.py`) and print results |
| Delete VM | Always after pipeline jobs finish | Tear down `data-fetcher-dev` (including on failure) |

Uses GitHub **`DEV`** environment and `DATABASE_URL_DEV` secret. Deploy SA needs `roles/iap.tunnelResourceAccessor` (and `compute.osLogin` when OS Login is enabled) for IAP SSH. Ephemeral VM avoids paying for two 24/7 e2-micro instances. See [RFC-011](./rfc/RFC-011-dev-backfill-ci.md).

### Production first-time setup

1. Run `schema.sql` in Neon (prod); verify with `scripts/verify_schema.sql`.
2. Create **one** GCP `e2-micro` in a free-tier US region; attach instance SA.
3. Run `scripts/bootstrap-vm.sh` on the VM (sudo).
4. Configure GitHub secrets + WIF (PRD §8).
5. Push to `main` — deploy writes `.env` on VM.
6. `pipenv run python seed_tickers.py`.
7. Optionally `pipenv run python backfill_sma.py` once.
8. Enable branch protection.

### Operational runbook

| Task | Command |
|------|---------|
| Check last cron run | `tail -100 /var/log/fansboda-finance/fetch_sma.log` |
| Manual weekly run | `sudo -u fansboda bash -c 'cd /opt/fansboda-finance && set -a && . ./.env && set +a && PIPENV_VENV_IN_PROJECT=1 pipenv run python fetch_sma.py'` |
| Verify data | `SELECT * FROM metrics ORDER BY trading_date DESC, ticker LIMIT 10;` |
| Check retention | `SELECT MIN(trading_date), MAX(trading_date), COUNT(*) FROM metrics;` |
| Market snapshot | `SELECT * FROM market ORDER BY trading_date DESC LIMIT 10;` |

---

## Security

- **No credentials in the repo** — `.env` is git-ignored locally.
- Production `DATABASE_URL` in GitHub secrets; written to VM on deploy.
- **Deploy auth:** GitHub OIDC JWT + Workload Identity Federation — no long-lived JSON keys.
- **VM runtime:** Attached service account via metadata server; no key on disk.
- **SQL:** Parameterized queries in `db/` modules; job scripts contain no SQL strings.
- Single-owner system — infra-level access only (PRD §2).

Deploy SA IAM roles: `compute.instanceAdmin.v1`, `iam.serviceAccountUser`, `compute.osLogin`; `iap.tunnelResourceAccessor` when using IAP SSH (dev backfill). See PRD §8 for details.

---

## Non-functional characteristics

| Property | Behavior |
|----------|----------|
| Cost | ~$0/month — one Always Free `e2-micro` + Neon free tier |
| Reliability | Failed batches logged and counted; run continues with successful results |
| Idempotency | Re-running weekly job or backfill does not create duplicate rows |
| Maintainability | Pure logic separated from I/O; unit tests with mocks for DB and yfinance |

**Dependencies:** Python 3.11+; `yfinance`, `pandas`, `psycopg2-binary`, `python-dotenv` via Pipenv.

---

## Out of scope

Explicitly **not** part of fansboda-finance (PRD §2, §11):

- User-facing UI or read API
- Intraday or real-time quotes (weekly Thursday job only)
- Additional indicators (EMA, RSI, MACD) or signal/alerting layer
- Portfolio, order, or transaction tracking
- Application authentication / authorization
- Gap detection for missed weekly runs
- Dashboard for `metrics` data

See PRD §11 for future considerations that may be revisited later.
