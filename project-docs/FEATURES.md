# Features — fansboda-finance

Feature overview derived from [PRD.md](./PRD.md). The PRD remains the authoritative specification for requirements and acceptance criteria.

## Summary

| Area | Description |
|------|-------------|
| Weekly SMA pipeline | Saturday job fetches prices, computes SMA-50/200, stores one snapshot per ticker per week |
| Normalized momentum | Per-ticker `momentum` (`sma_50 / sma_200`) and cross-sectional `z_score` |
| Market aggregates | Per-`(market, week_start)` `momentum_mean` / `momentum_std` in `us_market_metrics` / `swe_market_metrics` / `uk_market_metrics` |
| Historical backfill | Bootstrap of rolling weekly SMA snapshots (~2 years), **scoped per country set** (`--country us|swe|uk`) so adding a market later does not re-process others |
| Watchlist seeding | Load symbols from file, resolve company metadata, upsert into Postgres (optional `--country`) |
| Rolling retention | Keeps ~1 year of `*_metrics` and `*_market_metrics` history; older rows purged after each weekly run |
| Sector trends | Equal-weighted weekly trend per sector in `us_by_sector` / `swe_by_sector` / `uk_by_sector` (PRD §5.7) |
| Equity indices | Equal-weighted weekly price index per country in `indices`: `US-IDX`, `SWE-IDX`, `UK-IDX` (PRD §5.8) |
| Centralized configuration | `DevConfig` / `ProdConfig` in `config.py`; selected via `APP_ENV` |
| Zero-cost ops | **One** GCP `e2-micro` (Always Free) + Neon Postgres free tier |
| CI/CD — production | `pytest` on PR to `main`; deploy to long-lived Production VM on push to `main` |
| CI/CD — dev backfill | Ephemeral `data-fetcher-dev` via **manual** `workflow_dispatch` with required `country` input; IAP SSH + scoped seed/backfill/verify (PRD §8.1, [RFC-011](./rfc/RFC-011-dev-backfill-ci.md)) |

---

## Users & use cases

- **Primary user:** project owner with personal watchlists of US, Swedish (`.ST`), and UK (`.L`) symbols; may also query country metrics tables to see which stocks are above/below their long-term moving averages.
- **Primary use case — trend data for downstream analysis:** weekly `sma_50` / `sma_200` history consumed by the `fansboda` repo for Golden / Death Cross detection (PRD §5.6). Use **`momentum`**, **`z_score`**, and `*_market_metrics` (`momentum_mean` / `momentum_std`) to rank tickers relative to peers in the same country set in each week (cross-sectional normalization for heatmaps; sector views via `*_tickers.sector`).
- **Watchlist management:** add or remove symbols via SQL on `us_tickers` / `swe_tickers` / `uk_tickers`, or by running `seed_tickers.py` (optionally `--country us|swe|uk` to touch only one set).

---

## Core data features

### SMA metrics history

- Stored in **`us_metrics`** (US), **`swe_metrics`** (Swedish), and **`uk_metrics`** (UK).
- Stores **SMA-50**, **SMA-200**, and **current price** (adjusted close) per ticker.
- Stores **momentum** — `sma_50 / sma_200` — and **z_score** —
  `(momentum - momentum_mean) / momentum_std` using that date's matching
  `*_market_metrics` aggregates — for cross-sectional comparison across tickers.
- Stores **currency** from yfinance at fetch/backfill time. **Company** is copied from the matching `*_tickers` table into each snapshot.
- **Sector**, **industry**, listing **market**, and **exchange_name** are watchlist-level fields on `*_tickers`, not duplicated per metric row.
- One row per ticker per calendar week (`week_start` = Monday) within each country set; `trading_date` is the bar the row holds.
- Idempotent week upserts: `ON CONFLICT (ticker, week_start) DO UPDATE … WHERE EXCLUDED.trading_date > existing` — a newer bar in the same week replaces the row.

### Market aggregates

- **`us_market_metrics` / `swe_market_metrics` / `uk_market_metrics`:** one row per `(market, week_start)` with cross-sectional stats over tickers in that listing-market bucket in that week (PRD §6).
- Aggregates **`momentum`** from the matching country `*_metrics` rows on that date.
- **`momentum_mean`:** mean of tickers' `momentum` in the bucket on the date.
- **`momentum_std`:** standard deviation of tickers' `momentum` in the bucket on the date.
- Supports unbiased heatmap coloring via stored `z_score` on each metrics row.

**Status:** Implemented — see [RFC-012](./rfc/RFC-012-normalized-ratios-market.md).

### Watchlist

- **`us_tickers` / `swe_tickers` / `uk_tickers`:** `symbol` (primary key), `company`, `sector`, `industry`, `market`, `exchange_name`, `business_summary`, `updated_at`.
- `sector`, `industry`, and `market` come from yfinance (`sectorKey`, `industryKey`, and listing `market`).
- `exchange_name` comes from yfinance `fullExchangeName`; `business_summary` from `longBusinessSummary` (fill existing rows once with `seed_tickers.py --update-business-summary`).
- US symbols live in `us_tickers`; Swedish `.ST` listings in `swe_tickers`; UK `.L` listings in `uk_tickers`.
- Deleting a row from a country tickers table cascades to all of its rows in the matching metrics table.

### Data retention

- After each weekly run, `us_metrics` / `swe_metrics` / `uk_metrics` and matching `*_market_metrics` rows with `trading_date` / `week_start` older than **365 days** are deleted (`db/retention.py`).
- Retention purge runs even when all tickers are already fresh (nothing to fetch).
- Purge counts appear in the weekly job summary log.
- `*_by_sector` weeks no longer present in `*_metrics` are pruned by the sector refresh.
- `indices` rows with `week_start` older than 365 days are purged with the same window (RFC-015).
- Cutoff uses UTC date via `metrics_retention_days` (configurable).

### Schema (US, Swedish, and UK table sets)

| Set | Watchlist | SMA history | Cross-sectional aggregates |
|-----|-----------|-------------|----------------------------|
| US stocks | `us_tickers` | `us_metrics` | `us_market_metrics` |
| Swedish stocks | `swe_tickers` | `swe_metrics` | `swe_market_metrics` |
| UK stocks | `uk_tickers` | `uk_metrics` | `uk_market_metrics` |

**Country routing:**

| Set | Typical symbol suffix | Typical yfinance `market` |
|-----|----------------------|---------------------------|
| US | (none / other) | `us_market` |
| Swedish | `.ST` | `se_market` |
| UK | `.L` | `uk_market` |

| Table role | Key columns |
|------------|-------------|
| `*_tickers` | `symbol` (PK), `company`, `sector`, `industry`, `market`, `exchange_name`, `business_summary`, `updated_at` |
| `*_metrics` | `id` (PK), `ticker` (FK → matching `*_tickers.symbol`), `company`, `week_start`, `trading_date`, `updated_at`, `currency`, `sma_50`, `sma_200`, `current_price`, `momentum`, `z_score` |
| `*_market_metrics` | `market`, `week_start`, `updated_at`, `momentum_mean`, `momentum_std` |
| `*_by_sector` | `sector`, `week_start` (PK together), `updated_at`, `ticker_count`, `momentum_mean`, `momentum_median`, `z_score_mean`, `pct_uptrend` |
| `indices` (one shared table) | `ticker`, `week_start` (PK together), `name`, `country`, `updated_at`, `ticker_count`, `avg_return`, `index_price` |

`company` on each metrics row is copied from the matching tickers table at fetch time. `currency` is the listing currency code captured per snapshot. Listing `market` lives on the tickers tables and is also stored on `*_market_metrics`. `exchange_name` is the human-readable exchange from yfinance `fullExchangeName`. **`momentum`** is `sma_50 / sma_200`; **`z_score`** is `(momentum - momentum_mean) / momentum_std` using that week's market aggregates. Price and derived columns use `NUMERIC(18, 6)`. Unique on `*_metrics (week_start, ticker)` and `*_market_metrics (market, week_start)`.

DDL: `schema.sql` for new databases; `migrate_*.sql` for upgrades ([MIGRATIONS.md](./MIGRATIONS.md)).

---

## Pipeline jobs

### Weekly SMA fetch (`fetch_sma.py`)

Scheduled **Saturdays at 11:00 UTC** on the Production VM (after every market's Friday close) (FR-1 – FR-8).

| Capability | Detail |
|------------|--------|
| Load watchlist | Reads symbols and company names from `us_tickers`, `swe_tickers`, and `uk_tickers`; fails clearly if all three are empty |
| Skip fresh data | Skips tickers whose current-week row already holds the newest expected bar (Friday on weekends, otherwise today) |
| Batch download | ~300 days OHLCV via yfinance (default 40 symbols/batch) |
| Retry / backoff | Retries 429, rate limits, timeouts, connection errors, empty frames |
| Compute SMAs | Requires ≥200 valid daily closes; captures latest close and `trading_date` |
| Momentum | Computes `momentum` = `sma_50 / sma_200` per ticker |
| Market stats | Aggregates `momentum_mean` / `momentum_std` into `us_market_metrics` / `swe_market_metrics` / `uk_market_metrics` per `(market, week_start)` |
| Z-score | Sets `z_score` = `(momentum - momentum_mean) / momentum_std` using that date's market aggregates |
| yfinance metadata | Captures `currency` per snapshot; copies `company` from the matching `*_tickers` table |
| Append metrics | Inserts new rows into `us_metrics` / `swe_metrics` / `uk_metrics` without overwriting history |
| Retention purge | Deletes `*_metrics` and `*_market_metrics` rows older than configured retention (default 365 days) |
| Observability | Per-batch progress, per-ticker results, insert/purge counts, final summary |

### Watchlist seeding (`seed_tickers.py`)

Manual / ad-hoc script for initial and ongoing watchlist setup (FR-9 – FR-11).

| Capability | Detail |
|------------|--------|
| Load symbols | Reads symbol file (one per line; `#` comments ignored); uppercases |
| Resolve company | Fetches company name from yfinance (`longName`, fallback `shortName`) |
| Resolve sector / industry / market | Fetches `sectorKey`, `industryKey`, and listing `market` from yfinance (same rate-limit pattern as company lookups) |
| Resolve exchange name | Fetches `fullExchangeName` from yfinance into `exchange_name` |
| Upsert | Insert or update `(symbol, company, sector, industry, market, exchange_name)` into `us_tickers`, `swe_tickers`, or `uk_tickers` on conflict by `symbol`; sets `updated_at` |
| Country scope | Optional `--country us|swe|uk` — only resolve/upsert symbols that route to that set (PRD FR-11; used by per-country `dev-backfill`) |
| Rate limiting | Configurable delay between yfinance lookups (default 0.25s) |

```bash
pipenv run python seed_tickers.py --country us
```

**Status:** Shipped — US/SWE/UK upsert routing, `exchange_name`, and optional `--country` filter ([RFC-002](./rfc/RFC-002-watchlist-seeding.md)).

### Watchlist metadata refresh (`refresh_tickers.py`)

Ad-hoc script to refresh watchlist metadata without a full re-seed (FR-12, RFC-010). **Not** cron-scheduled.

| Capability | Detail |
|------------|--------|
| Refresh existing | Re-resolve `company`, `sector`, `industry`, `market`, and `exchange_name` for symbols already in `us_tickers` / `swe_tickers` / `uk_tickers` |
| Add new | Include symbols from file not yet in any tickers table (same upsert as seed) |
| Symbol selection | Default: union of tickers file and DB; `--from-db` for all DB symbols; `--symbols AAPL,MSFT.ST,VOD.L` for a subset |
| Reuse | Same yfinance resolution and rate limiting as `seed_tickers.py` via `resolve_and_upsert_symbols` |

```bash
pipenv run python refresh_tickers.py --from-db
pipenv run python refresh_tickers.py --symbols AAPL,MSFT.ST,VOD.L
```

**Status:** Shipped — US/SWE/UK load/upsert, `exchange_name` from `fullExchangeName`, `--from-db` / `--symbols` ([RFC-010](./rfc/RFC-010-metadata-refresh.md)). No `--country` on refresh (optional in RFC-010; not required by FR-12).

### Historical backfill (`backfill_sma.py`)

Bootstrap script for SMA history — **not** part of the weekly cron (FR-13 – FR-18). Used manually or via the manual per-country `dev-backfill` workflow (PRD §8.1).

| Capability | Detail |
|------------|--------|
| Batch download | ~730 days daily OHLCV (default 25 symbols/batch) with retry and inter-batch delay |
| Weekly snapshots | One SMA snapshot per calendar week at the week's last bar (normally Friday), using closes up to that bar — aligned with the Saturday job regardless of run day |
| SMA snapshots | One metric row per window at the last trading day in the window |
| Momentum / z-score | Populates `momentum` and `z_score` on each inserted country `*_metrics` row |
| Market stats | Upserts matching `*_market_metrics` with `momentum_mean` / `momentum_std` for backfilled weeks |
| Currency | Resolves listing `currency` per ticker (same rate-limit pattern as weekly fetch) |
| Skip existing | Skips `(ticker, trading_date)` pairs already in the matching country metrics table |
| Resume-safe | Week upsert; interrupted runs can continue without duplicates |
| Country scope | **Required** `--country us|swe|uk` — only that set's tickers are loaded and only that set's tables are written (FR-18). Adding UK later must not re-download or re-touch US/SWE. |
| Exchange scope | Optional, repeatable `--exchange NAME` (e.g. `NasdaqGS`, `NYSE`) limits the run to tickers with that `exchange_name` (FR-18a) |

```bash
pipenv run python backfill_sma.py --country us
```

**Fresh database:** `schema.sql` → `seed_tickers.py --country us` → `backfill_sma.py --country us` (repeat for `swe` / `uk` when those watchlists are ready). Prefer separate per-country runs over one all-country backfill.

**Legacy database:** apply `migrate_*.sql` as needed; `migrate_metrics_history.sql` before backfill when upgrading from one-row-per-ticker layout.

**Status:** Shipped — required `--country us|swe|uk` scopes watchlist load and writes ([RFC-005](./rfc/RFC-005-historical-backfill.md)).

### Golden Cross & Death Cross detection

Not part of this repo — owned by **`fansboda`**, which reads the `*_metrics`
SMA history produced here (PRD §5.6).

### Sector trend averages

Equal-weighted weekly trend per sector (PRD §5.7, FR-27 – FR-33).

| Capability | Detail |
|------------|--------|
| Status | **Shipped** — [RFC-014](./rfc/RFC-014-sector-trends.md) |
| Tables | `us_by_sector` / `swe_by_sector` / `uk_by_sector`, one row per `(sector, week_start)` |
| Grouping | `*_tickers.sector`, normalized to `sectorKey` form (`Financial Services` → `financial-services`) |
| Measures | `ticker_count`, `momentum_mean`, `momentum_median`, `z_score_mean`, `pct_uptrend` (% with SMA-50 > SMA-200); every company weighted equally |
| Weekly job | `fetch_sma.py` refreshes the weeks it wrote after the retention purge |
| Standalone | `compute_sector_trends.py [--country us|swe|uk] [--week YYYY-MM-DD]` — default: all stored weeks, all sets; no yfinance |
| Retention | Weeks no longer present in `*_metrics` are pruned each run |

---

### Equity indices

Equal-weighted weekly price index per country set (PRD §5.8, FR-34 – FR-43).

| Capability | Detail |
|------------|--------|
| Status | **Shipped** — [RFC-015](./rfc/RFC-015-equity-indices.md) |
| Indices | `US-IDX` US Equity Index, `SWE-IDX` OMX Equity Index, `UK-IDX` FTSE Equity Index |
| Table | `indices` — one shared table, one row per `(ticker, week_start)` |
| Calculation | Each stock's weekly return = `current_price` this week / previous stored week − 1; index growth = plain average of those returns (equal weight); `index_price = previous × (1 + avg_return)`, base week = 100 |
| Inclusion | Only stocks with a price in both weeks; weeks with no contributing stocks are skipped |
| Weekly job | `fetch_sma.py` computes the weeks it wrote, after sector trends (FR-7b) |
| Standalone | `compute_indices.py [--country us|swe|uk]` — full rebuild over all retained metrics weeks; no yfinance |
| Retention | Rows with `week_start` older than `METRICS_RETENTION_DAYS` are purged weekly (same window as metrics) |

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
| `metrics_retention_days` | 365 | 365 | Retention purge cutoff for `us_metrics` / `swe_metrics` / `uk_metrics` / `*_market_metrics` and `indices` |
| `backfill_history_days` | 730 | 730 | Backfill download window |
| `backfill_batch_size` | 25 | 25 | Backfill batch size |
| `backfill_batch_delay_seconds` | 5.0 | 5.0 | Delay between backfill batches |

`DevConfig` and `ProdConfig` may override shared defaults per environment.

---

## Infrastructure & operations

### Architecture (PRD §4)

```
GCP e2-micro VM  ──cron Thu 11:00 UTC──▶  fetch_sma.py  ──▶  Neon Postgres
  (Debian 12)         yfinance batches        us_* / swe_* / uk_* tickers,
                                              metrics, market_metrics
```

- **Compute:** one `e2-micro`, UTC, weekly on Saturdays.
- **Storage:** Neon Postgres (free tier).
- **Outbound only:** yfinance + Neon via `DATABASE_URL`; VM attached SA needs no GCP API roles.

### Production VM

- Linux user **`fansboda`** runs cron (not `root`).
- App path: `/opt/fansboda-finance`.
- Logs: `/var/log/fansboda-finance/fetch_sma.log`.
- Bootstrap: `scripts/bootstrap-vm.sh`.

PRD §10 cron:

```
0 11 * * 6 cd /opt/fansboda-finance && pipenv run python fetch_sma.py >> /var/log/fansboda-finance/fetch_sma.log 2>&1
```

Bootstrap installs an enhanced line that also sources `.env` and sets `PIPENV_VENV_IN_PROJECT=1` so `get_config()` receives `DATABASE_URL` and `APP_ENV` from the VM `.env`.

### CI/CD — production (PRD §8.2, implemented)

| Workflow | Trigger | Action |
|----------|---------|--------|
| `test.yml` | Push / PR to `main` | `pipenv run pytest` (covers `us_*` / `swe_*` / `uk_*` schema and routing) |
| `deploy.yml` | After `test.yml` succeeds on a push to `main` | SCP tarball to Production VM, `pipenv install --deploy`, write `.env` (temporary `APP_ENV=dev` while validating) |

- GitHub **`PROD`** environment.
- Branch protection on `main` should require tests (`scripts/configure-branch-protection.sh`).
- Deploy auth: **OIDC JWT + WIF** — no `GCP_SA_KEY`.
- VM `.env`: `DATABASE_URL`, temporary `APP_ENV=dev` while validating (cut over to `APP_ENV=production` later); `chown fansboda:fansboda`, mode `600`.
- Schema upgrades (three country sets; [MIGRATIONS.md](./MIGRATIONS.md) through steps 12–13) are applied **manually** — not by `deploy.yml`.

**GitHub secrets:** `DATABASE_URL`, `GCP_PROJECT_ID`, `GCP_ZONE`, `GCP_INSTANCE_NAME`, `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_DEPLOY_SERVICE_ACCOUNT`.

### CI/CD — dev backfill (PRD §8.1, implemented)

On **manual `workflow_dispatch`** (not on push to `dev`), `.github/workflows/dev-backfill.yml` runs a sequential pipeline for **one country set** per dispatch:

| Step | Runs when | Action |
|------|-----------|--------|
| Spin up VM | Manual `workflow_dispatch` with required `country` (`us` \| `swe` \| `uk`) | Create ephemeral `data-fetcher-dev` in GCP (tag `dev-backfill`). Firewall must allow GitHub Actions SSH access — IAP ingress `tcp:22` from `35.235.240.0/20` scoped to that tag. Wait until SSH via `--tunnel-through-iap` succeeds. |
| Deploy | Spin up VM succeeds | SCP tarball to dev VM, ensure `pipenv`, `pipenv install --deploy`; write `.env` with Neon **dev branch** URL; run `scripts/apply_migrations.sh` (full schema; data collection remains scoped) |
| Data collection | Deploy succeeds | Run `seed_tickers.py --country <country>` and `backfill_sma.py --country <country>` only for that set |
| Verification | Data collection completes without error | Analyze log for missing data, failed downloads, etc.; run DB sanity checks for the **selected** country set (`scripts/verify_dev_backfill.py`) and print results |
| Delete VM | Always after pipeline jobs finish | Tear down `data-fetcher-dev` (including on failure) |

Uses GitHub **`DEV`** environment and `DATABASE_URL` secret (dev branch). Deploy SA needs `roles/iap.tunnelResourceAccessor` (and `compute.osLogin` when OS Login is enabled) for IAP SSH. Ephemeral VM avoids paying for two 24/7 e2-micro instances. See [RFC-011](./rfc/RFC-011-dev-backfill-ci.md).

**Why scoped:** Adding UK (or SWE) later must not re-seed/re-backfill an already-complete US set in the shared Neon database — avoids re-touching production/dev history and wasting yfinance quota.

**Status:** Shipped — required `country` input; scoped seed/backfill/verify ([RFC-011](./rfc/RFC-011-dev-backfill-ci.md)).

### Production first-time setup

1. Run `schema.sql` in Neon (prod); verify with `scripts/verify_schema.sql`. For upgrades, apply `migrate_*.sql` through the latest step in [MIGRATIONS.md](./MIGRATIONS.md).
2. Create **one** GCP `e2-micro` in a free-tier US region; attach instance SA.
3. Run `scripts/bootstrap-vm.sh` on the VM (sudo) — user, UTC, logs, cron (code via deploy).
4. Configure GitHub secrets + WIF (PRD §8).
5. Push to `main` — once tests pass, deploy unpacks tarball, installs deps, writes `.env` on VM.
6. `pipenv run python seed_tickers.py --country us` (and `--country swe` / `--country uk` when those watchlists are ready).
7. Optionally `pipenv run python backfill_sma.py --country us` (repeat per country set; do not re-run an already-complete set when adding another).
8. Enable branch protection.

### Operational runbook

| Task | Command |
|------|---------|
| Check last cron run | `tail -100 /var/log/fansboda-finance/fetch_sma.log` |
| Manual weekly run | `sudo -u fansboda bash -c 'cd /opt/fansboda-finance && set -a && . ./.env && set +a && PIPENV_VENV_IN_PROJECT=1 pipenv run python fetch_sma.py'` |
| Seed one country set | `pipenv run python seed_tickers.py --country us` (or `swe` / `uk`) |
| Backfill one country set | `pipenv run python backfill_sma.py --country us` (or `swe` / `uk`; do not re-run a completed set when adding another) |
| Dev backfill CI | Manual `workflow_dispatch` on `dev-backfill.yml` with `country=us\|swe\|uk` |
| Verify data | `SELECT * FROM us_metrics ORDER BY trading_date DESC, ticker LIMIT 10;` (same for `swe_metrics` / `uk_metrics`) |
| Check retention | `SELECT MIN(trading_date), MAX(trading_date), COUNT(*) FROM us_metrics;` (same for `swe_metrics` / `uk_metrics`) |
| Market snapshot | `SELECT * FROM us_market_metrics ORDER BY week_start DESC, market LIMIT 10;` (same for `swe_market_metrics` / `uk_market_metrics`) |

---

## Security

- **No credentials in the repo** — `.env` is git-ignored locally.
- Production `DATABASE_URL` in GitHub secrets; written to VM on deploy.
- **Deploy auth:** GitHub OIDC JWT + Workload Identity Federation — no long-lived JSON keys.
- **SSH/SCP:** `--tunnel-through-iap` for production deploy and dev backfill (no public IP).
- **VM runtime:** Attached service account via metadata server; no key on disk.
- **SQL:** Parameterized queries in `db/` modules; job scripts contain no SQL strings; live paths use `us_*` / `swe_*` / `uk_*` only.
- Single-owner system — infra-level access only (PRD §2).

Deploy SA IAM roles: `compute.instanceAdmin.v1`, `iam.serviceAccountUser`, `compute.osLogin`, `iap.tunnelResourceAccessor`. See PRD §8 / [RFC-009](./rfc/RFC-009-security-deploy-auth.md).

---

## Non-functional characteristics

| Property | Behavior |
|----------|----------|
| Cost | ~$0/month — one Always Free `e2-micro` + Neon free tier |
| Reliability | Failed batches logged and counted; run continues with successful results |
| Idempotency | Re-running weekly job or a **scoped** backfill does not create duplicate rows; per-country runs avoid re-touching other sets |
| Maintainability | Pure logic separated from I/O; unit tests with mocks for DB and yfinance |

**Dependencies:** Python 3.11+; `yfinance`, `pandas`, `psycopg2-binary`, `python-dotenv` via Pipenv.

---

## Out of scope

Explicitly **not** part of fansboda-finance (PRD §2, §11), except where noted:

- User-facing UI or read API
- Intraday or real-time quotes (weekly Saturday job only)
- Additional indicators (EMA, RSI, MACD) or alternate moving-average windows beyond the SMA-50 / SMA-200 pair
- Golden / Death Cross detection, signals, or alerting — owned by the `fansboda` repo (PRD §5.6)
- Portfolio, order, or transaction tracking
- Application authentication / authorization
- Gap detection for missed weekly runs
- Dashboard for `us_metrics` / `swe_metrics` / `uk_metrics` data

See PRD §11 for future considerations that may be revisited later.
