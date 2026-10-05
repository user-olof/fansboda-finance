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
- Run fully unattended on a weekly schedule (Saturdays).
- Keep monthly operating cost at ~$0 within GCP Always Free and Neon free tiers.
- Be resilient to transient data-provider failures (rate limits, timeouts).
- Avoid redundant work by skipping symbols that already have a row for the
  latest `trading_date`.

### Non-Goals

- No user-facing UI or API — data is consumed directly from Postgres.
- No intraday / real-time quotes; the weekly job runs once weekly (Saturday).
- No additional technical indicators beyond SMA-50, SMA-200, current price,
  and the derived `momentum` / `z_score` fields in §6 — including no EMA, RSI,
  MACD, and no alternate moving-average windows in v1.
- No Golden / Death Cross detection, signals, or alerting — owned by the
  `fansboda` repo (§5.6). The only notification this repo sends is the
  data-quality email for implausible price moves (§5.9).
- No portfolio, order, or transaction tracking.
- No authentication/authorization layer (single-owner, infra-level access only).

## 3. Users & Use Cases

- **Primary user:** the project owner, who maintains personal watchlists of
  US, Swedish (`.ST`), and UK (`.L`) symbols and queries the country metrics
  tables (`us_metrics` / `swe_metrics` / `uk_metrics`) to see which stocks are
  above/below their long-term moving averages.
- **Primary use case — trend data for downstream analysis:** provide the
  weekly `sma_50` / `sma_200` history that the `fansboda` repo uses for
  Golden / Death Cross detection (§5.6). Use **`momentum`** and **`z_score`**
  (vs peers in the same country set / listing `market` on that date via
  `*_market_metrics`) to rank relative strength for heatmaps; market and
  sector views via the market and sector index rows in `indices` (§5.8).
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
                                              |   + indices (one table: market   |
                                              |     + sector indices)            |
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
- **FR-5a Weekly growth from one adjusted series:** From the same downloaded
  (split- and dividend-adjusted) series, find the ticker's last bar of the
  **previous calendar week** (`week_start − 7 days`) and compute, using only
  closes up to each bar:
  - `price_growth = close(this bar) / close(previous-week bar) − 1`
  - `sma_50_growth = sma_50(this bar) / sma_50(previous-week bar) − 1`
  - `sma_200_growth = sma_200(this bar) / sma_200(previous-week bar) − 1`

  Each is NULL when the previous week has no bar, the earlier value is
  missing or zero, or there are too few closes for that SMA at the
  previous-week bar. Because both sides come from one consistently adjusted
  download, a split or dividend between two weekly fetches cannot create a
  fake jump — unlike dividing this week's stored row by last week's stored
  row, which were adjusted on different days. No extra yfinance calls.
- **FR-6 Insert:** Write one row per ticker per calendar week into
  `us_metrics`, `swe_metrics`, or `uk_metrics` (`insert_metrics`), keyed by
  `week_start` (Monday of `trading_date`), including `momentum`, `z_score`,
  and the FR-5a growth columns.
  Use `ON CONFLICT (ticker, week_start) DO UPDATE … WHERE EXCLUDED.trading_date
  > existing trading_date`: a newer bar in the same week replaces the row, an
  equal or older bar is ignored, so re-runs are idempotent.
- **FR-7 Retention purge:** After inserts, delete rows from `us_metrics` /
  `swe_metrics` / `uk_metrics` (and the matching `*_market_metrics` tables,
  plus `indices`) where `trading_date` (`week_start` for `*_market_metrics`)
  is older than one year (`purge_stale_metrics`).
- **FR-7a Sector trends:** Retired — sector trends are the sector index rows
  written by FR-7b (§5.7).
- **FR-7b Equity indices:** After the retention purge, compute the `indices`
  rows — each country's market index and all of its sector indices — for
  every week written in this run (§5.8). A failure here is logged and exits
  non-zero.
- **FR-7c Outlier email:** After the indices, email newly detected
  implausible weekly moves in the weeks written this run (§5.9).
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
- **FR-15a Weekly growth:** Compute `price_growth`, `sma_50_growth`, and
  `sma_200_growth` for every snapshot exactly as FR-5a, from the same
  downloaded series (each snapshot vs the last bar of the previous calendar
  week).
- **FR-16 Skip existing:** Before insert, skip `(ticker, trading_date)` pairs
  already present in the matching country metrics table — except that rows
  whose growth columns are NULL get those three columns filled from the
  backfill's computed values (no other column changes). Re-running
  `backfill_sma.py --country …` therefore populates growth on history stored
  before FR-5a existed.
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
| `outlier_max_growth` | 4.0 | 4.0 | Weekly growth above this (more than ×5) is an outlier (FR-37b) |
| `outlier_min_growth` | −0.8 | −0.8 | Weekly growth below this (below ÷5) is an outlier (FR-37b) |
| `alert_email_enabled` | `false` | `true` | Send the outlier email (FR-51); when off, log it instead |
| `alert_email_from` | from `.env` (optional) | from VM `.env` (required when enabled) | Workspace mailbox the service account sends as (FR-49) |
| `alert_email_to` | from `.env` (optional) | from VM `.env` (required when enabled) | Owner's work email address (FR-49) |

`DevConfig` and `ProdConfig` may override any of the shared defaults where
environments differ (e.g. more conservative batch delays in production).

### 5.6 Golden Cross & Death Cross detection — moved to `fansboda`

Golden / Death Cross detection is owned by the separate **`fansboda`** repo,
which reads the `us_metrics` / `swe_metrics` / `uk_metrics` SMA history this
pipeline produces. This repo has no detection code; FR-19 – FR-26 are retired
here (numbers are not reused).

### 5.7 Sector trend averages (retired)

Superseded by the sector indices in §5.8: each sector's equal-weighted trend
is now a sector index row in `indices` (levels, momentum, `pct_uptrend`,
`z_score`). FR-27–FR-33, `compute_sector_trends.py`, and the
`us_by_sector` / `swe_by_sector` / `uk_by_sector` tables are removed (the
tables are dropped by a migration). The old `momentum_median` and
`z_score_mean` measures have no replacement.

### 5.8 Equal-weighted equity indices (`compute_indices.py`, `indices` table)

Synthetic equal-weighted indices built from the stocks in each country set's
watchlist: one **market index** per country set, plus one **sector index**
per sector within that set. All are stored in the single `indices` table in
the same shape: an index **price**, its **SMA-50** and **SMA-200** levels,
**momentum**, **`z_score`**, **`pct_uptrend`**, the contributing
**`ticker_count`**, and the set's **currency**. Every stock has equal weight.
Derived entirely from the stored `*_metrics` growth columns (FR-5a) and
`*_tickers.sector` — no yfinance calls.

- **FR-34 Index definitions:** Per country set, one market index over all
  of the set's stocks:

  | Country set | Index name | Ticker | Currency | Source tables |
  |-------------|------------|--------|----------|---------------|
  | US | US Equity Index | `US-IDX` | `USD` | `us_metrics` ⋈ `us_tickers` |
  | Swedish | OMX Equity Index | `SWE-IDX` | `SEK` | `swe_metrics` ⋈ `swe_tickers` |
  | UK | FTSE Equity Index | `UK-IDX` | `GBP` | `uk_metrics` ⋈ `uk_tickers` |

  plus one sector index per sector key `<s>` present in the set's tickers
  table: ticker `<market ticker>-<S>` (sector key upper-cased, e.g.
  `US-IDX-TECHNOLOGY`, `SWE-IDX-FINANCIAL-SERVICES`), name
  `<index name> – <Sector>` (sector key title-cased with spaces, e.g.
  `US Equity Index – Financial Services`), `sector = <s>`, same currency.
  Market index rows have `sector = NULL`.
- **FR-34a Sector membership:** A stock belongs to the sector index of its
  current `*_tickers.sector`, normalized to the yfinance `sectorKey` form
  (`lower`, trimmed, spaces → `-`) so a display-name fallback such as
  "Financial Services" merges with `financial-services`. Stocks with a blank
  or NULL sector count only towards the market index. Every sector gets an
  index regardless of size; consumers filter on `ticker_count` when they need
  a minimum sample.
- **FR-35 One row per index per week:** Store one `indices` row per index
  ticker per calendar week. The row's `trading_date` is the latest
  `trading_date` among that index's contributing stocks' metrics rows for that
  week. Key `(ticker, trading_date)`; at most one row per ticker per calendar
  week — when a later bar in the same week is computed (e.g. a mid-week manual
  run followed by the Saturday job), it replaces that week's row, mirroring
  FR-6.
- **FR-36 Contributing stocks:** A stock contributes to an index's week `w`
  when it is a member of that index (the whole set, or the sector per
  FR-34a) and its week-`w` metrics row has positive `current_price`,
  `sma_50`, and `sma_200` and non-NULL `price_growth`, `sma_50_growth`, and
  `sma_200_growth` (FR-5a). The same set of `N` stocks drives all three
  levels and `pct_uptrend`, so they stay comparable. New listings,
  incomplete SMAs, and stocks without a previous-week bar do not contribute
  that week.
- **FR-37 Equal-weighted growth per level:** For each measure, the index's
  weekly growth is the plain average of the contributing stocks' stored
  growth: `g_price(w) = (1 / N) × Σ price_growth_i(w)`, and likewise
  `g_sma_50` from `sma_50_growth` and `g_sma_200` from `sma_200_growth`.
  Every stock counts once regardless of market cap or price level (weights
  reset every week). Using the stored growth (not a ratio of two stored rows)
  keeps splits and dividends between weekly fetches from distorting the
  index.
- **FR-37a Gap weeks:** The growth columns cover one calendar week. If the
  index's previous stored week `p` is not the previous calendar week (a week
  in between had no contributing stocks), that week instead uses the ratio of
  stored rows between `p` and `w`
  (`g_x = (1 / N) × Σ (x_i(w) / x_i(p) − 1)`, over member stocks with
  positive values in both weeks).
- **FR-37b Outlier guard:** A stock-week is an **outlier** when any of its
  three weekly growth values (FR-5a, or the FR-37a ratio in a gap week) is
  above `outlier_max_growth` (default `4.0`, i.e. more than ×5) or below
  `outlier_min_growth` (default `−0.8`, i.e. below ÷5). Outliers are excluded
  from that week's contributing set — for the market index and its sector
  index alike — for all three levels, `pct_uptrend`, and `N`, so one broken
  series — typically a split Yahoo failed to adjust, e.g. `WYLD.ST` 1:500 on
  2025-12-05 — cannot move an index. The exclusion is per week: the stock
  contributes again in later weeks whose growth is within the bounds. A
  genuine ×5 move is also excluded; with equal weights that bias is small for
  the market index, but larger for sector indices with few stocks. Smaller
  residual SMA drift after an unadjusted split (SMA growth below ×5 in the
  following weeks) is not caught; fixing the series itself is §11 future
  work. Base weeks (FR-39) have no growth and are not guarded.
- **FR-38 Index levels:** Chain-link each level onto its previous value:
  `level_x(w) = level_x(p) × (1 + g_x(w))`, stored as the row's
  `current_price`, `sma_50`, and `sma_200`.
- **FR-39 Base week:** The first week for an index (no earlier stored row for
  that ticker — for a sector index, possibly later than its market index's
  base week) uses every member stock with positive `current_price`,
  `sma_50`, and `sma_200` that week:
  - `current_price = 100`
  - `sma_50 = 100 × (1 / N) × Σ (sma_50_i / current_price_i)`
  - `sma_200 = 100 × (1 / N) × Σ (sma_200_i / current_price_i)`

  Anchoring both SMA levels to the stocks' average SMA-to-price ratio makes
  index momentum reflect the stocks' real trend from the first week, instead
  of starting at exactly 1.0. Because every ratio and growth rate is
  unit-free, mixed price units within a set (e.g. GBp vs GBP) do not distort
  the index as long as each stock's own units are consistent over time.
- **FR-40 Momentum:** `momentum = sma_50 / sma_200` on the index levels (NULL
  if `sma_200` is zero), the same definition as for stocks (FR-5).
- **FR-40a Uptrend share:** `pct_uptrend` = percentage (0–100) of the week's
  `N` contributing stocks with `sma_50 > sma_200`.
- **FR-40b Z-score (sector vs sectors):** For each country set and week, over
  that set's sector index rows with non-NULL `momentum`:
  `z_score = (momentum − mean) / std`, where `mean` and `std` are the
  equal-weighted mean and population standard deviation of those sector
  indices' momentum (the same population std as the stock-level `z_score`,
  FR-5). NULL when fewer than two sector indices have momentum that week or
  `std` is zero. Market index rows always have `z_score = NULL` (the market
  is the whole country, not a peer of its sectors). Z-scores are recomputed
  for every week whose sector rows are written.
- **FR-40c Currency:** `currency` is the country set's currency (FR-34).
  Index levels are unit-free (base 100); the column records which currency
  the underlying stocks trade in.
- **FR-41 Insufficient data:** If no stock contributes to an index in a week
  (`N = 0`), do not write a row for that index and week; the next week chains
  from that index's last stored row.
- **FR-42 Idempotent writes:** Recomputing a week overwrites that week's rows;
  weeks are computed in ascending order so each week chains from the
  already-stored previous week. A sector that no longer has any member stocks
  keeps its stored history until retention purges it.
- **FR-43 Invocation:** Runs as part of the weekly job (FR-7b) for the weeks
  just written (recomputing any later stored weeks so the chain stays
  consistent), and standalone for a full rebuild of all market and sector
  indices via `pipenv run python compute_indices.py [--country us|swe|uk]`.
  A full rebuild starts at the earliest week still in the metrics table, so
  the base week (and therefore index levels, but not weekly growth) moves
  forward as retention purges old metrics. Run it after `backfill_sma.py`,
  `refresh_tickers.py` (sector changes), or filling the growth columns.
- **FR-44 Retention:** Purge `indices` rows with the same window as the
  metrics tables (FR-7): delete rows whose `trading_date` is older than
  `METRICS_RETENTION_DAYS`. The weekly calculation only needs the previous
  stored week, so purging old rows does not break the chain.
- **FR-45 Observability:** Log per country set the market index's
  `trading_date`, `ticker_count`, the three levels, `momentum`, and
  `pct_uptrend`, plus the number of sector indices written; summary line with
  rows written per country. Log one `WARNING` per excluded outlier (country,
  ticker, `trading_date`, the three growth values) and the outlier count per
  country set. Exit non-zero on DB failure.

### 5.9 Data-quality email (implausible price moves)

The owner is told by email when a stock makes an implausible weekly move, so
broken Yahoo series are noticed without reading logs or spotting odd index
levels. Outliers are derived from stored `*_metrics` rows with the FR-37b
thresholds — no extra table and no extra yfinance calls.

- **FR-46 Trigger:** Only the weekly job sends email (FR-7c), once per run,
  after the indices step. Standalone `compute_indices.py`, `backfill_sma.py`,
  and `backfill_market.py` only log outliers (FR-45) and never email.
- **FR-47 Scope — new outliers only:** The email lists outlier stock-weeks
  (FR-37b) in the weeks written this run whose same stock was **not** an
  outlier in the previous calendar week, so a persistent problem is reported
  once rather than every Saturday. No outliers → no email (no "all clear"
  message). The email also states how many continuing outliers were left
  out.
- **FR-48 Content:** Plain text. Subject:
  `fansboda-finance: <n> implausible weekly move(s), week of <week_start>`.
  Per outlier: country set, ticker, company, `trading_date`, previous-week
  and current close, `price_growth`, `sma_50_growth`, `sma_200_growth`, which
  bound was crossed, and a note that the stock was excluded from that week's
  index. Footer: the active thresholds and the run's UTC timestamp. No
  credentials or connection strings in the body.
- **FR-49 Delivery — Gmail API via Workspace domain-wide delegation:**
  Send with the Gmail API (`users.messages.send`, scope
  `https://www.googleapis.com/auth/gmail.send`) **from** a Google Workspace
  mailbox (`alert_email_from`) **to** the owner's work address
  (`alert_email_to`). The VM's attached service account authenticates
  keylessly: it signs its delegation JWT through the IAM Credentials
  API (`signBlob`) using its metadata-server token, with `subject` =
  `alert_email_from`. No JSON key, OAuth refresh token, or SMTP password is
  stored anywhere. One-time setup is in §8.2.
- **FR-50 Failure handling:** A send failure (auth, quota, network) is logged
  as `ERROR` with the outlier list in the log, and does not fail the run or
  roll back data. Sending is retried with the same exponential backoff as
  yfinance (FR-4) for transient errors.
- **FR-51 Environments:** Sending is controlled by `alert_email_enabled`
  (dev default off, prod default on). When disabled, the job logs the email
  subject and body instead of sending.

## 6. Data Model

Data is partitioned by listing country into three parallel table sets with the
same column layouts.

| Set | Watchlist | SMA history | Cross-sectional aggregates |
|-----|-----------|-------------|----------------------------|
| US stocks | `us_tickers` | `us_metrics` | `us_market_metrics` |
| Swedish stocks | `swe_tickers` | `swe_metrics` | `swe_market_metrics` |
| UK stocks | `uk_tickers` | `uk_metrics` | `uk_market_metrics` |

Market and sector indices for all three sets share one `indices` table.

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
| `price_growth` | NUMERIC(18,6) | Close growth vs the last bar of the previous calendar week, from one adjusted series (FR-5a) |
| `sma_50_growth` | NUMERIC(18,6) | SMA-50 growth over the same period (FR-5a) |
| `sma_200_growth` | NUMERIC(18,6) | SMA-200 growth over the same period (FR-5a) |

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

### Index table (`indices`)

A single table shared by all country sets (§5.8): each set's market index and
all of its sector indices, one row per index ticker per calendar week.

| Column | Type | Notes |
|--------|------|-------|
| `ticker` | TEXT | Market index `US-IDX` / `SWE-IDX` / `UK-IDX`, or sector index `<market ticker>-<SECTOR>` (e.g. `US-IDX-TECHNOLOGY`) |
| `name` | TEXT | e.g. `US Equity Index`, `US Equity Index – Technology` |
| `country` | TEXT | Country set: `us`, `swe`, or `uk` |
| `sector` | TEXT | Sector key (`sectorKey` form, e.g. `technology`); NULL for market indices |
| `currency` | TEXT | Country set currency: `USD`, `SEK`, or `GBP` |
| `trading_date` | DATE | Latest `trading_date` among the contributing stocks that week |
| `updated_at` | TIMESTAMPTZ | When the row was written |
| `ticker_count` | INTEGER | Stocks contributing this week (`N`), after excluding outliers (FR-37b) |
| `current_price` | NUMERIC(18,6) | Equal-weighted price index level, chained from `price_growth` (base week = 100) |
| `sma_50` | NUMERIC(18,6) | Equal-weighted SMA-50 index level, chained from `sma_50_growth` (base = 100 × average `sma_50 / current_price`) |
| `sma_200` | NUMERIC(18,6) | Equal-weighted SMA-200 index level, chained from `sma_200_growth` (base = 100 × average `sma_200 / current_price`) |
| `pct_uptrend` | NUMERIC(18,6) | % of contributing stocks with `sma_50 > sma_200` (0–100) |
| `momentum` | NUMERIC(18,6) | `sma_50 / sma_200` |
| `z_score` | NUMERIC(18,6) | Sector index momentum vs the set's sector indices that week (FR-40b); NULL for market indices |

Primary key on `(ticker, trading_date)`, with at most one row per ticker per
calendar week (FR-35). Rows with `trading_date` older than one year are
deleted on each weekly run (FR-44, same retention as the metrics tables).
Upgrading an existing database: a migration adds `sector`, `currency`,
`pct_uptrend`, and `z_score` and drops `us_by_sector` / `swe_by_sector` /
`uk_by_sector`; then rebuild with `compute_indices.py`.

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
  `DATABASE_URL`, `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_DEPLOY_SERVICE_ACCOUNT`,
  `ALERT_EMAIL_FROM`, `ALERT_EMAIL_TO` (the last two in the **`production`**
  environment; written to the VM `.env` on deploy, never committed).

### Outlier email setup (Gmail API, one-time)

Keyless delivery for FR-49, done outside the repo:

1. **GCP project:** enable the **Gmail API** and the **IAM Service Account
   Credentials API**.
2. **VM service account:** grant it `roles/iam.serviceAccountTokenCreator`
   **on itself** (so it can sign with the IAM Credentials API as its own identity). The VM's
   access scopes must allow IAM calls (`cloud-platform`).
3. **Google Workspace admin:** under *Security → API controls → Domain-wide
   delegation*, add the VM service account's **client ID** with exactly the
   scope `https://www.googleapis.com/auth/gmail.send`.
4. **Sender mailbox:** use a Workspace user (e.g. a dedicated
   `noreply@` account, or the owner's own work account) as
   `ALERT_EMAIL_FROM`; set `ALERT_EMAIL_TO` to the owner's work address.
5. **Verify:** after deploy, a manual dry run on the VM with
   `alert_email_enabled` on sends a test message (implementation provides a
   test entrypoint; never trigger the full weekly job just to test email).

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
  for data collection, since `fetch_sma.py` only makes outbound calls
  (yfinance, Neon) using `DATABASE_URL` from `.env`. For the outlier email
  it needs only `roles/iam.serviceAccountTokenCreator` on itself plus the
  Workspace domain-wide delegation grant above — still no key file.
- Do not create or store JSON keys for the deploy service account; OIDC JWT via
  WIF is the only supported deploy auth path.

## 9. Dependencies

Python 3.11+. Key libraries: `yfinance`, `pandas`, `psycopg2-binary`,
`python-dotenv`, `google-auth` (+ `requests`) for keyless Gmail API delivery
(§5.9). Dependencies are pinned via `Pipfile`/`Pipfile.lock`
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
- Market and sector indices (after the indices migration, rebuild history
  once with `pipenv run python compute_indices.py`):
  `SELECT ticker, trading_date, current_price, sma_50, sma_200, momentum, ticker_count FROM indices WHERE sector IS NULL ORDER BY ticker, trading_date DESC;`
- Sector ranking for the latest week:
  `SELECT ticker, ticker_count, momentum, z_score, pct_uptrend FROM indices WHERE country = 'us' AND sector IS NOT NULL AND date_trunc('week', trading_date) = (SELECT date_trunc('week', MAX(trading_date)) FROM indices WHERE country = 'us') ORDER BY z_score DESC;`

## 11. Future Considerations (Out of Current Scope)

- Golden / Death Cross detection — lives in the `fansboda` repo (§5.6), not
  here.
- Additional indicators (EMA, RSI, MACD) or alternate moving-average windows
  beyond the SMA-50 / SMA-200 pair.
- A read API or dashboard for the `us_metrics` / `swe_metrics` / `uk_metrics`
  data.
- Gap detection for missed weekly runs.
- Further corporate-action handling beyond FR-5a and the FR-37b outlier
  guard: recording splits from yfinance (`actions=True`) in a
  corporate-actions table, and correcting series Yahoo failed to
  split-adjust (e.g. `WYLD.ST`, 1:500 on 2025-12-05) before computing SMAs,
  `momentum`, `z_score`, and the indices.
