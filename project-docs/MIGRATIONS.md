# Database migrations

Schema specification: [RFC-001](./rfc/RFC-001-data-model.md). Target layout: [PRD §6](./PRD.md) / [FEATURES.md](./FEATURES.md).

## Target schema (PRD §6)

Data is partitioned by listing country into three parallel table sets:

| Set | Watchlist | SMA history | Cross-sectional aggregates |
|-----|-----------|-------------|----------------------------|
| US stocks | `us_tickers` | `us_metrics` | `us_market_metrics` |
| Swedish stocks | `swe_tickers` | `swe_metrics` | `swe_market_metrics` |
| UK stocks | `uk_tickers` | `uk_metrics` | `uk_market_metrics` |

**Country routing:** US (default / other), Swedish (`.ST` / `se_market`), UK (`.L` / `uk_market`).

Watchlist columns include `exchange_name` (yfinance `fullExchangeName`) in addition to `company`, `sector`, `industry`, and listing `market`.

## New database

Run `schema.sql` once in the Neon SQL editor or via `psql`:

```bash
psql "$DATABASE_URL" -f schema.sql
```

`schema.sql` must create the US, Swedish, and UK table sets above (PRD §6), including `exchange_name` on each `*_tickers` table. Then seed the watchlists (`pipenv run python seed_tickers.py`) before running fetch or backfill jobs.

## Existing database

Apply only the migrations you have not yet run, **in order**. Each file is idempotent where possible but intended as a one-time step.

Steps 1–10 upgrade the **legacy** single-set tables (`tickers` / `metrics` / `market` → `market_metrics`). Step 11 splits that layout into US / Swedish country sets. Later steps add UK tables and `exchange_name`.

| Order | File | When to run |
|------:|------|-------------|
| 1 | `migrate_add_current_price.sql` | Legacy `metrics` lacks `current_price` column |
| 2 | `migrate_one_row_per_ticker.sql` | Legacy only — collapsed history to one row per ticker (superseded by step 4) |
| 3 | `migrate_add_tickers_table.sql` | Legacy `tickers` table or FK from `metrics` → `tickers` missing |
| 4 | `migrate_metrics_history.sql` | Restore one row per `(ticker, trading_date)` on legacy `metrics`; drops `metrics_ticker_key` if present |
| 5 | `migrate_add_trading_date_index.sql` | Add `idx_metrics_trading_date` if missing (also included in step 4) |
| 6 | `migrate_add_tickers_updated_at.sql` | Add `tickers.updated_at` if missing |
| 7 | `migrate_move_metadata_to_tickers.sql` | Add `tickers.sector`, `tickers.industry`, `metrics.currency`; drop misplaced `metrics.sector` / `metrics.industry` if present |
| 8 | `migrate_rename_name_to_company.sql` | Rename `name` → `company` on legacy `tickers` and `metrics` |
| 9 | `migrate_add_raw_ratios_and_market.sql` | Add `metrics.raw_50`, `metrics.raw_200`, legacy `market` table (watchlist-wide: PK on `trading_date` only) |
| 10 | `migrate_tickers_market_and_market_metrics.sql` | Add `tickers.market`; rename `market` → `market_metrics`, add `market` column, PK on `(market, trading_date)` |
| 11 | `migrate_split_us_swe_tables.sql` | Create `us_*` / `swe_*` table sets; move rows from legacy `tickers` / `metrics` / `market_metrics` by listing country; drop legacy tables |
| 12 | `migrate_add_exchange_name.sql` | Add `exchange_name` to `us_tickers` / `swe_tickers` / `uk_tickers` (yfinance `fullExchangeName`) |
| 13 | `migrate_add_uk_tables.sql` | Create `uk_tickers` / `uk_metrics` / `uk_market_metrics` (PRD §6); move existing `.L` / `uk_market` rows out of `us_*` |
| 14 | `migrate_momentum_zscore.sql` | Drop `raw_50` / `raw_200` / `raw_mean_*` / `raw_std_*`; add `momentum` / `z_score` on `*_metrics` and `momentum_mean` / `momentum_std` on `*_market_metrics` (PRD §6 / RFC-012) |
| 15 | `migrate_week_buckets.sql` | Add `week_start` (Monday of `trading_date`) to `*_metrics`, keep only the latest bar per `(ticker, week_start)`, replace `UNIQUE (ticker, trading_date)` with `*_metrics_week_start_ticker_key UNIQUE (week_start, ticker)`; recreate `*_market_metrics` keyed by `(market, week_start)` (PRD §6) |
| 16 | `migrate_add_business_summary.sql` | Add `business_summary TEXT` to `us_tickers` / `swe_tickers` / `uk_tickers` (yfinance `longBusinessSummary`) |
| 17 | `migrate_add_by_sector_tables.sql` | Create `us_by_sector` / `swe_by_sector` / `uk_by_sector` — equal-weighted weekly trend averages per sector, PK `(sector, week_start)` (PRD §5.7) |
| 18 | `migrate_add_indices_table.sql` | Create the shared `indices` table (`US-IDX` / `SWE-IDX` / `UK-IDX`) in the v1 shape: PK `(ticker, week_start)`, `avg_return`, `index_price` (superseded by step 19) |
| 19 | `migrate_indices_levels.sql` | If `indices` still has `week_start`, drop and recreate it in the v2 shape (PRD §5.8 / §6): PK `(ticker, trading_date)`, `ticker_count`, `current_price`, `sma_50`, `sma_200`, `momentum`. Index rows are derived, so they are rebuilt afterwards ([RFC-015](./rfc/RFC-015-equity-indices.md)) |
| 20 | `migrate_add_growth_columns.sql` | Add `price_growth`, `sma_50_growth`, `sma_200_growth` `NUMERIC(18, 6)` to `us_metrics` / `swe_metrics` / `uk_metrics` (PRD FR-5a / §6). Additive and idempotent (`ADD COLUMN IF NOT EXISTS`) ([RFC-016](./rfc/RFC-016-weekly-growth-columns.md)) |
| 21 | `migrate_indices_sectors.sql` | Add `currency`, `pct_uptrend`, `z_score` to `indices` for market + sector index rows; merge `name` into `sector` (`sector NOT NULL`, second column after `ticker` — the table is rebuilt and rows copied, since Postgres cannot reorder columns); index `idx_indices_country_trading_date` (PRD §5.8 / §6). Idempotent, not additive — apply together with the RFC-018 deploy ([RFC-018](./rfc/RFC-018-sector-indices.md)) |
| 22 | `migrate_drop_by_sector_tables.sql` | `DROP TABLE IF EXISTS` `us_by_sector` / `swe_by_sector` / `uk_by_sector`, superseded by the sector index rows. Destructive: only after step 21, the RFC-018 deploy and rebuild, and once `fansboda` no longer reads them ([RFC-018](./rfc/RFC-018-sector-indices.md)) |

**Outlier guard & email (PRD FR-37b, §5.9, [RFC-017](./rfc/RFC-017-outlier-guard-email.md)):** needs **no schema migration** — outliers are derived from the step-20 growth columns and the configured thresholds.

**Golden Cross / Death Cross detection (PRD §5.6):** Lives in the `fansboda` repo and needs **no schema migration** here — it reads existing `*_metrics` columns (`sma_50`, `sma_200`, `trading_date`).

See [RFC-001](./rfc/RFC-001-data-model.md) and [RFC-012](./rfc/RFC-012-normalized-ratios-market.md).

**Note:** Step 10 supersedes the watchlist-wide layout from step 9. Existing databases keep one aggregate row per `trading_date` until step 10 runs; recompute grouped rows with `backfill_market.py` or the next weekly run after migration.

**Note:** Step 11 supersedes the single-set layout from steps 1–10. Fresh installs use `schema.sql` with country sets only. Existing databases apply step 11 after step 10.

**Note:** Steps 12–13 bring an already-split US/SWE database in line with the UK + `exchange_name` target. Step 14 replaces SMA/price `raw_*` ratios with `momentum` / `z_score` and market `momentum_mean` / `momentum_std` (RFC-012). Fresh installs get the target layout from an updated `schema.sql`.

### Path by starting state

**Fresh install (no tables):** `schema.sql` only (US + Swedish + UK table sets, including `exchange_name`).

**Has legacy `metrics` with `(ticker, trading_date)` unique (never ran step 2):**

1. `migrate_add_current_price.sql` (if needed)
2. `migrate_add_tickers_table.sql` (if needed)

**Has legacy `metrics` with one row per ticker (`metrics_ticker_key`):**

1. `migrate_add_tickers_table.sql` (if `tickers` / FK missing)
2. `migrate_metrics_history.sql`

**After history migration, before backfill:**

Run `migrate_metrics_history.sql`, then `pipenv run python backfill_sma.py`.

**After step 9 (legacy `market` table), before per-market aggregates:**

Run step 10 (`migrate_tickers_market_and_market_metrics.sql`), refresh `tickers.market` (`refresh_tickers.py`), then `pipenv run python backfill_market.py` to recompute grouped rows.

**After step 10 (legacy single-set tables), before country partition:**

Run step 11 (`migrate_split_us_swe_tables.sql`), then re-seed / refresh as needed (`seed_tickers.py` / `refresh_tickers.py`) and verify with `scripts/verify_schema.sql`.

**After step 11 (US + SWE only), before full PRD §6 target:**

1. Run step 12 (`migrate_add_exchange_name.sql`) when available, then `refresh_tickers.py` to populate `exchange_name`.
2. Run step 13 (`migrate_add_uk_tables.sql`) when available; re-seed / refresh UK symbols (`.L`) as needed.

**After step 13 (raw_* ratios still present):**

Run step 14 (`migrate_momentum_zscore.sql`), then
`pipenv run python backfill_market.py` (optional `--country us|swe|uk`) to set
`momentum` from stored SMAs and refresh `momentum_mean` / `momentum_std` /
`z_score`. Fresh installs already have the target columns from `schema.sql`
(no `raw_*`).

**After step 14 (one metrics row per `trading_date`), before week buckets:**

1. Take a Neon branch snapshot — step 15 deletes all but the latest bar per
   ticker per calendar week and recreates `*_market_metrics` empty.
2. Run step 15 (`migrate_week_buckets.sql`).
3. Run `pipenv run python backfill_market.py` to rebuild `momentum_mean` /
   `momentum_std` per `(market, week_start)` and refresh every `z_score`.
4. Only then deploy code that writes `week_start` (the weekly job and backfill
   fail against a pre-step-15 schema).

**After step 15, before business summaries:**

1. Run step 16 (`migrate_add_business_summary.sql`) — safe to repeat.
2. Deploy code that writes `business_summary` (seeding fails against a
   pre-step-16 schema).
3. Fill existing tickers once:
   `pipenv run python seed_tickers.py --update-business-summary` (optional
   `--country us|swe|uk`; one yfinance lookup per ticker).

**After step 16, before sector trends:**

1. Run step 17 (`migrate_add_by_sector_tables.sql`) — safe to repeat.
2. Deploy code that writes `*_by_sector` (the weekly job fails against a
   pre-step-17 schema).
3. Fill history once: `pipenv run python compute_sector_trends.py` (DB only,
   no yfinance; optional `--country us|swe|uk`).

**After step 17, before equity indices (RFC-015 v1):**

1. Run step 18 (`migrate_add_indices_table.sql`) — safe to repeat.
2. Build history once: `pipenv run python compute_indices.py` (DB only, no
   yfinance; optional `--country us|swe|uk`). Index levels start at 100 on
   the earliest retained metrics week.
3. Deploy code that writes `indices` (the weekly job fails against a
   pre-step-18 schema). Rows older than `METRICS_RETENTION_DAYS` are then
   purged weekly.

**After step 18, before index levels (RFC-015 v2):**

1. Run step 19 (`migrate_indices_levels.sql`) — replaces the v1 `indices`
   table (its rows are dropped); a no-op once applied. No snapshot needed:
   index rows are fully derived from `*_metrics`.
2. Rebuild: `pipenv run python compute_indices.py`. The base week gets
   `current_price = 100` and SMA levels at `100 ×` the stocks' average
   SMA-to-price ratio.
3. Deploy v2 code (v1 code fails against the step-19 schema and vice versa,
   so apply step 19 and deploy together).

**After step 19, before weekly growth columns (RFC-016):**

1. Run step 20 (`migrate_add_growth_columns.sql`) — additive, safe to
   repeat; no snapshot needed. Old code keeps working (it ignores the new
   columns), so step 20 can be applied before the deploy.
2. Deploy code that writes the growth columns (it fails against a
   pre-step-20 schema).
3. Fill history **per country set** by re-running the backfill:
   `pipenv run python backfill_sma.py --country us` (then `swe`, `uk`).
   Stored rows keep their values; only all-NULL growth columns are filled.
4. Only then rebuild indices: `pipenv run python compute_indices.py` —
   weeks without growth values contribute no stocks, so rebuilding before
   step 3 would leave gaps.
5. (RFC-017) Complete the Gmail / domain-wide delegation setup (PRD §8.2),
   add `ALERT_EMAIL_FROM` / `ALERT_EMAIL_TO` secrets, deploy, and run
   `scripts/send_test_email.py` on the VM. No schema change.

**After step 20, before sector indices (RFC-018):**

1. Between Saturday runs, run step 21 (`migrate_indices_sectors.sql`, safe
   to repeat) and deploy the RFC-018 code together: step 21 drops `name`,
   which the old code still writes, and the new code needs the step-21
   columns. The new code no longer writes `*_by_sector`.
2. Rebuild: `pipenv run python compute_indices.py` — creates sector index
   history and fills the new columns on the market rows.
3. Switch consumers (e.g. `fansboda`) from `*_by_sector` to `indices`
   (`WHERE ticker LIKE '%-IDX-%'`; `sector` now holds the index label).
4. Take a Neon branch snapshot, then run step 22
   (`migrate_drop_by_sector_tables.sql`).

## Dev-backfill CI (`scripts/apply_migrations.sh`)

Used by `.github/workflows/dev-backfill.yml` (manual `workflow_dispatch`) against the Neon **dev** branch:

1. Apply `schema.sql` (country baseline, `CREATE IF NOT EXISTS`).
2. If legacy `tickers` / `metrics` still exist, run pre-split migrations (steps 1, 4–10; skips destructive steps 2–3).
3. If `us_metrics` still has `raw_50` (pre-step-14), run steps 11–14 (`migrate_split_us_swe_tables.sql`, `exchange_name`, UK tables, momentum/z_score). Otherwise skip them — they copy `raw_*` columns that step 14 dropped.
4. Always run steps 15–19 (`migrate_week_buckets.sql`, `migrate_add_business_summary.sql`, `migrate_add_by_sector_tables.sql`, `migrate_add_indices_table.sql`, `migrate_indices_levels.sql`; no-ops once applied). Then step 20 (`migrate_add_growth_columns.sql`, RFC-016). Then steps 21–22 (`migrate_indices_sectors.sql`, `migrate_drop_by_sector_tables.sql`, RFC-018) — the dev branch has no `*_by_sector` consumers, so step 22 runs there unconditionally.

Fresh databases get the target layout from `schema.sql`, so only steps 15–22 run (step 17 recreates `*_by_sector`, step 22 drops them again; the rest are no-ops).

## Verify schema

```bash
psql "$DATABASE_URL" -f scripts/verify_schema.sql
```

Or run the queries in the Neon SQL editor. Verification should assert all three country sets once the target schema is in place:

- `us_tickers`, `us_metrics`, `us_market_metrics`
- `swe_tickers`, `swe_metrics`, `swe_market_metrics`
- `uk_tickers`, `uk_metrics`, `uk_market_metrics`

And that each `*_tickers` table includes `exchange_name`.

## Rollback

Migrations are forward-only. Take a Neon branch snapshot before applying destructive steps (especially `migrate_one_row_per_ticker.sql`, which deletes duplicate rows, step 11, which drops legacy tables, and step 22, which drops `*_by_sector`).
