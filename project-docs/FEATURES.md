# Features — fansboda-finance

Feature overview derived from [PRD.md](./PRD.md). The PRD remains the authoritative specification for requirements and acceptance criteria.

## Summary

| Area | Description |
|------|-------------|
| Weekly SMA pipeline | Thursday job fetches prices, computes SMA-50/200, appends history |
| Normalized SMA ratios | Per-ticker `raw_50` / `raw_200` (SMA ÷ price) for cross-sectional comparison |
| Market aggregates | Per-`trading_date` mean and std of `raw_50` / `raw_200` in `us_market_metrics` / `swe_market_metrics` |
| Historical backfill | Bootstrap of rolling weekly SMA snapshots (~2 years of data) |
| Watchlist seeding | Load symbols from file, resolve company metadata, upsert into Postgres |
| Rolling retention | Keeps ~1 year of `*_metrics` and `*_market_metrics` history; older rows purged after each weekly run |
| Centralized configuration | `DevConfig` / `ProdConfig` in `config.py`; selected via `APP_ENV` |
| Zero-cost ops | **One** GCP `e2-micro` (Always Free) + Neon Postgres free tier |
| CI/CD — production | `pytest` on PR to `main`; deploy to long-lived Production VM on push to `main` |
| CI/CD — dev backfill | Ephemeral `data-fetcher-dev` on push to `dev`; IAP SSH firewall + seed/backfill/verify pipeline (PRD §8.1, [RFC-011](./rfc/RFC-011-dev-backfill-ci.md)) |

---

## Users & use cases

- **Primary user:** project owner with personal watchlists of US and Swedish (`.ST`) symbols.
- **Primary use case:** query `us_metrics` / `swe_metrics` to compare `current_price`, `sma_50`, and `sma_200` — including trends over retained history (golden-cross / death-cross style signals). Use `raw_50`, `raw_200`, and `us_market_metrics` / `swe_market_metrics` to rank tickers relative to peers in the same country set on each `trading_date` (cross-sectional normalization for heatmaps; sector views via `us_tickers.sector` / `swe_tickers.sector`).
- **Watchlist management:** add or remove symbols via SQL on `us_tickers` / `swe_tickers` or by running `seed_tickers.py`.

---

## Core data features

### SMA metrics history

- Stored in **`us_metrics`** (US stocks) and **`swe_metrics`** (Swedish stocks).
- Stores **SMA-50**, **SMA-200**, and **current price** (adjusted close) per ticker.
- Stores **raw_50** and **raw_200** — SMA divided by `current_price` (`sma_50 / current_price`, `sma_200 / current_price`) for scale-free comparison across tickers.
- Stores **currency** from yfinance at fetch/backfill time. **Company** is copied from the matching `*_tickers` table into each snapshot.
- **Sector** and **industry** are watchlist-level fields on `us_tickers` / `swe_tickers`, not duplicated per metric row.
- One row per `(ticker, trading_date)` within each country set — each weekly run appends a new snapshot.
- Idempotent inserts: `ON CONFLICT (ticker, trading_date) DO NOTHING`.

### Market aggregates

- **`us_market_metrics` / `swe_market_metrics`:** one row per `trading_date` with cross-sectional stats over tickers in that country set on that date (PRD §6).
- Aggregates `raw_50` / `raw_200` from the matching `us_metrics` / `swe_metrics` rows on that date.
- **`raw_mean_50` / `raw_mean_200`:** mean of tickers' `raw_50` / `raw_200` in the set on the date.
- **`raw_std_50` / `raw_std_200`:** standard deviation of tickers' `raw_50` / `raw_200` in the set on the date.
- Supports unbiased heatmap coloring (e.g. z-scores or percentile ranks vs peers in the same country set) without raw SMA-distance bias.

### Watchlist

- **`us_tickers` / `swe_tickers`:** `symbol` (primary key), `company`, `sector`, `industry`, `market`, `updated_at`.
- `sector`, `industry`, and `market` come from yfinance (`sectorKey`, `industryKey`, and listing `market`).
- US symbols live in `us_tickers`; Swedish `.ST` listings live in `swe_tickers`.
- Deleting a row from `us_tickers` or `swe_tickers` cascades to all of its rows in the matching metrics table.

### Data retention

- After each weekly run, `us_metrics` / `swe_metrics` and `us_market_metrics` / `swe_market_metrics` rows with `trading_date` older than **365 days** are deleted (`db/retention.py`).
- Retention purge runs even when all tickers are already fresh (nothing to fetch).
- Purge counts appear in the weekly job summary log.
- Cutoff uses UTC date via `metrics_retention_days` (configurable).

### Schema (US and Swedish table sets)

| Set | Watchlist | SMA history | Cross-sectional aggregates |
|-----|-----------|-------------|----------------------------|
| US stocks | `us_tickers` | `us_metrics` | `us_market_metrics` |
| Swedish stocks | `swe_tickers` | `swe_metrics` | `swe_market_metrics` |

| Table role | Key columns |
|------------|-------------|
| `*_tickers` | `symbol` (PK), `company`, `sector`, `industry`, `market`, `updated_at` |
| `*_metrics` | `id` (PK), `ticker` (FK → matching `*_tickers.symbol`), `company`, `trading_date`, `updated_at`, `currency`, `sma_50`, `sma_200`, `current_price`, `raw_50`, `raw_200` |
| `*_market_metrics` | `market`, `trading_date`, `updated_at`, `raw_mean_50`, `raw_mean_200`, `raw_std_50`, `raw_std_200` |

`company` on each metrics row is copied from the matching tickers table at fetch time. `currency` is the listing currency code captured per snapshot. Listing `market` lives on the tickers tables and is also stored on `*_market_metrics`. `raw_50` and `raw_200` are `sma_50 / current_price` and `sma_200 / current_price`. Price and ratio columns use `NUMERIC(18, 6)`. Unique on `*_metrics (ticker, trading_date)` and `*_market_metrics (market, trading_date)`.

DDL: `schema.sql` for new databases; `migrate_*.sql` for upgrades ([MIGRATIONS.md](./MIGRATIONS.md)).

---

## Pipeline jobs

### Weekly SMA fetch (`fetch_sma.py`)

Scheduled **Thursdays at 11:00 UTC** on the Production VM (FR-1 – FR-8).

| Capability | Detail |
|------------|--------|
| Load watchlist | Reads symbols and company names from `us_tickers` and `swe_tickers`; fails clearly if both are empty |
| Skip fresh data | Skips tickers that already have a row in the matching `*_metrics` table at their latest `trading_date` |
| Batch download | ~300 days OHLCV via yfinance (default 40 symbols/batch) |
| Retry / backoff | Retries 429, rate limits, timeouts, connection errors, empty frames |
| Compute SMAs | Requires ≥200 valid daily closes; captures latest close and `trading_date` |
| Raw ratios | Computes `raw_50` and `raw_200` (`sma / current_price`) per ticker |
| Market stats | Aggregates mean and std of `raw_50` / `raw_200` into `us_market_metrics` / `swe_market_metrics` per `trading_date` |
| yfinance metadata | Captures `currency` per snapshot; copies `company` from the matching `*_tickers` table |
| Append metrics | Inserts new rows into `us_metrics` / `swe_metrics` without overwriting history |
| Retention purge | Deletes `*_metrics` and `*_market_metrics` rows older than configured retention (default 365 days) |
| Observability | Per-batch progress, per-ticker results, insert/purge counts, final summary |

### Watchlist seeding (`seed_tickers.py`)

Manual / ad-hoc script for initial and ongoing watchlist setup (FR-9 – FR-11).

| Capability | Detail |
|------------|--------|
| Load symbols | Reads symbol file (one per line; `#` comments ignored); uppercases |
| Resolve company | Fetches company name from yfinance (`longName`, fallback `shortName`) |
| Resolve sector / industry / market | Fetches `sectorKey`, `industryKey`, and listing `market` from yfinance (same rate-limit pattern as company lookups) |
| Upsert | Insert or update `(symbol, company, sector, industry, market)` into `us_tickers` or `swe_tickers` on conflict by `symbol`; sets `updated_at` |
| Rate limiting | Configurable delay between yfinance lookups (default 0.25s) |

### Watchlist metadata refresh (`refresh_tickers.py`)

Ad-hoc script to refresh watchlist metadata without a full re-seed (FR-12, RFC-010). **Not** cron-scheduled.

| Capability | Detail |
|------------|--------|
| Refresh existing | Re-resolve `company`, `sector`, `industry`, and `market` for symbols already in `us_tickers` / `swe_tickers` |
| Add new | Include symbols from file not yet in either tickers table (same upsert as seed) |
| Symbol selection | Default: union of tickers file and DB; `--from-db` for all DB symbols; `--symbols AAPL,MSFT.ST` for a subset |
| Reuse | Same yfinance resolution and rate limiting as `seed_tickers.py` via `resolve_and_upsert_symbols` |

### Historical backfill (`backfill_sma.py`)

Bootstrap script for SMA history — **not** part of the weekly cron (FR-13 – FR-17). Used manually or via dev CI on push to `dev` (§8.1).

| Capability | Detail |
|------------|--------|
| Batch download | ~730 days daily OHLCV (default 25 symbols/batch) with retry and inter-batch delay |
| Rolling 52-week windows | Week 0 anchored at oldest bar; windows 0–51, 1–52, 2–53, … |
| SMA snapshots | One metric row per window at the last trading day in the window |
| Raw ratios | Populates `raw_50` and `raw_200` on each inserted `us_metrics` / `swe_metrics` row |
| Market stats | Upserts `us_market_metrics` / `swe_market_metrics` rows for all backfilled `trading_date` values |
| Currency | Resolves listing `currency` per ticker (same rate-limit pattern as weekly fetch) |
| Skip existing | Skips `(ticker, trading_date)` pairs already in the matching country metrics table |
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
| `metrics_retention_days` | 365 | 365 | Retention purge cutoff for `us_metrics` / `swe_metrics` / `*_market_metrics` |
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
  (Debian 12)         yfinance batches        us_* / swe_* tickers, metrics,
                                              market_metrics
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

Bootstrap installs an enhanced line that also sources `.env` and sets `PIPENV_VENV_IN_PROJECT=1` so `get_config()` receives `DATABASE_URL` and `APP_ENV` from the VM `.env`.

### CI/CD — production (PRD §8.2, implemented)

| Workflow | Trigger | Action |
|----------|---------|--------|
| `test.yml` | Push / PR to `main` | `pipenv run pytest` |
| `deploy.yml` | Push to `main` | SCP tarball to Production VM, `pipenv install --deploy`, write `.env` (temporary `APP_ENV=dev` while validating) |

- GitHub **`production`** environment.
- Branch protection on `main` should require tests (`scripts/configure-branch-protection.sh`).
- Deploy auth: **OIDC JWT + WIF** — no `GCP_SA_KEY`.
- VM `.env`: `DATABASE_URL`, temporary `APP_ENV=dev` while validating (cut over to `APP_ENV=production` later); `chown fansboda:fansboda`, mode `600`.

**GitHub secrets:** `DATABASE_URL`, `GCP_PROJECT_ID`, `GCP_ZONE`, `GCP_INSTANCE_NAME`, `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_DEPLOY_SERVICE_ACCOUNT`.

### CI/CD — dev backfill (PRD §8.1)

On push to **`dev`**, `.github/workflows/dev-backfill.yml` runs a sequential pipeline:

| Step | Runs when | Action |
|------|-----------|--------|
| Spin up VM | Push to `dev` | Create ephemeral `data-fetcher-dev` in GCP (tag `dev-backfill`). Firewall must allow GitHub Actions SSH access — IAP ingress `tcp:22` from `35.235.240.0/20` scoped to that tag. Wait until SSH via `--tunnel-through-iap` succeeds. |
| Deploy | Spin up VM succeeds | SCP tarball to dev VM, ensure `pipenv`, `pipenv install --deploy`; write `.env` with Neon **dev branch** URL; run `scripts/apply_migrations.sh` (`schema.sql` + step 11) |
| Data collection | Deploy succeeds | Run `seed_tickers.py` and `backfill_sma.py`; store results in the country-set tables on the dev database |
| Verification | Data collection completes without error | Analyze log for missing data, failed downloads, etc.; run DB sanity checks on `us_*` / `swe_*` (`scripts/verify_dev_backfill.py`) and print results |
| Delete VM | Always after pipeline jobs finish | Tear down `data-fetcher-dev` (including on failure) |

Uses GitHub **`DEV`** environment and `DATABASE_URL` secret (dev branch). Deploy SA needs `roles/iap.tunnelResourceAccessor` (and `compute.osLogin` when OS Login is enabled) for IAP SSH. Ephemeral VM avoids paying for two 24/7 e2-micro instances. See [RFC-011](./rfc/RFC-011-dev-backfill-ci.md).

### Production first-time setup

1. Run `schema.sql` in Neon (prod); verify with `scripts/verify_schema.sql`. For upgrades, apply `migrate_*.sql` through step 11.
2. Create **one** GCP `e2-micro` in a free-tier US region; attach instance SA.
3. Run `scripts/bootstrap-vm.sh` on the VM (sudo) — user, UTC, logs, cron (code via deploy).
4. Configure GitHub secrets + WIF (PRD §8).
5. Push to `main` — deploy unpacks tarball, installs deps, writes `.env` on VM.
6. `pipenv run python seed_tickers.py`.
7. Optionally `pipenv run python backfill_sma.py` once.
8. Enable branch protection.

### Operational runbook

| Task | Command |
|------|---------|
| Check last cron run | `tail -100 /var/log/fansboda-finance/fetch_sma.log` |
| Manual weekly run | `sudo -u fansboda bash -c 'cd /opt/fansboda-finance && set -a && . ./.env && set +a && PIPENV_VENV_IN_PROJECT=1 pipenv run python fetch_sma.py'` |
| Verify data | `SELECT * FROM us_metrics ORDER BY trading_date DESC, ticker LIMIT 10;` (same for `swe_metrics`) |
| Check retention | `SELECT MIN(trading_date), MAX(trading_date), COUNT(*) FROM us_metrics;` (same for `swe_metrics`) |
| Market snapshot | `SELECT * FROM us_market_metrics ORDER BY trading_date DESC, market LIMIT 10;` (same for `swe_market_metrics`) |

---

## Security

- **No credentials in the repo** — `.env` is git-ignored locally.
- Production `DATABASE_URL` in GitHub secrets; written to VM on deploy.
- **Deploy auth:** GitHub OIDC JWT + Workload Identity Federation — no long-lived JSON keys.
- **SSH/SCP:** `--tunnel-through-iap` for production deploy and dev backfill (no public IP).
- **VM runtime:** Attached service account via metadata server; no key on disk.
- **SQL:** Parameterized queries in `db/` modules; job scripts contain no SQL strings; live paths use `us_*` / `swe_*` only.
- Single-owner system — infra-level access only (PRD §2).

Deploy SA IAM roles: `compute.instanceAdmin.v1`, `iam.serviceAccountUser`, `compute.osLogin`, `iap.tunnelResourceAccessor`. See PRD §8 / [RFC-009](./rfc/RFC-009-security-deploy-auth.md).

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
- Dashboard for `us_metrics` / `swe_metrics` data

See PRD §11 for future considerations that may be revisited later.
