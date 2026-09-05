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

See [RFC-001](./rfc/RFC-001-data-model.md) and [RFC-012](./rfc/RFC-012-normalized-ratios-market.md).

**Note:** Step 10 supersedes the watchlist-wide layout from step 9. Existing databases keep one aggregate row per `trading_date` until step 10 runs; recompute grouped rows with `backfill_market.py` or the next weekly run after migration.

**Note:** Step 11 supersedes the single-set layout from steps 1–10. Fresh installs use `schema.sql` with country sets only. Existing databases apply step 11 after step 10.

**Note:** Steps 12–13 bring an already-split US/SWE database in line with the full PRD §6 target (exchange display names + UK set). Fresh installs get both from an updated `schema.sql` and do not need separate upgrade steps once those files ship.

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

## Dev-backfill CI (`scripts/apply_migrations.sh`)

Used by `.github/workflows/dev-backfill.yml` (manual `workflow_dispatch`) against the Neon **dev** branch:

1. Apply `schema.sql` (country baseline, `CREATE IF NOT EXISTS`).
2. If legacy `tickers` / `metrics` still exist, run pre-split migrations (steps 1, 4–10; skips destructive steps 2–3).
3. Always run steps 11–13 (`migrate_split_us_swe_tables.sql`, `exchange_name`, UK tables).

Fresh country-only databases skip the legacy chain and only get `schema.sql` + steps 11–13 (idempotent).

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

Migrations are forward-only. Take a Neon branch snapshot before applying destructive steps (especially `migrate_one_row_per_ticker.sql`, which deletes duplicate rows, and step 11, which drops legacy tables).
