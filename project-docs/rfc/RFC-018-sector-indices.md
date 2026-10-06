# RFC-018: Sector Indices in `indices` (Retire `*_by_sector`)

| Field | Value |
|-------|-------|
| **Priority** | P3 |
| **Status** | **Implemented** (code, migrations 21–22, tests). Production rollout follows MIGRATIONS.md: step 22 only after `fansboda` stops reading `*_by_sector` |
| **Depends on** | RFC-014, RFC-015, RFC-016, RFC-017 |
| **Supersedes** | RFC-014 (sector trend tables) |
| **PRD** | §3, §5.1 (FR-7a, FR-7b), §5.7, §5.8 (FR-34–FR-45), §6, §10 |
| **Feature** | [Equity indices](../FEATURES.md#equity-indices) |

## Summary

Extend the equal-weighted indices (RFC-015) from one market index per
country set to the market index **plus one index per sector**, all in the
single `indices` table. Every row gets `currency`, `pct_uptrend`, and
`z_score` next to the existing levels, `momentum`, and `ticker_count`; the
former `name` column is merged into `sector`, which holds the index label.
Levels are chained from the stored growth columns exactly as today
(RFC-016), with the outlier guard (RFC-017) applied to market and sector
indices alike. The sector index rows replace the sector trend tables, so
`us_by_sector` / `swe_by_sector` / `uk_by_sector`, `compute_sector_trends.py`,
and `db/sector.py` are removed.

| Index | Ticker | `sector` (label) | `currency` |
|-------|--------|------------------|------------|
| US market | `US-IDX` | `US Equity Index` | `USD` |
| US sector `technology` | `US-IDX-TECHNOLOGY` | `Technology` | `USD` |
| Swedish market | `SWE-IDX` | `OMX Equity Index` | `SEK` |
| Swedish sector `financial-services` | `SWE-IDX-FINANCIAL-SERVICES` | `Financial Services` | `SEK` |
| UK market | `UK-IDX` | `FTSE Equity Index` | `GBP` |

Sector labels carry no market-name prefix; a label repeats across countries
(`Technology` for `us` / `swe` / `uk`) but is unique within one, since sector
keys are. The `sectorKey` (`technology`) drives grouping and z-scores in code
(`IndexRow.sector_key`) but is not stored; sector rows are
`ticker LIKE '%-IDX-%'`.

## Requirements (PRD §5.8)

| ID | Requirement |
|----|-------------|
| FR-7a | Retired — no separate sector-trend step in the weekly job |
| FR-7b | Weekly job writes market + sector index rows for the weeks it wrote, right after the retention purge |
| FR-34 | Market indices as today plus one sector index per sector key: ticker `<market ticker>-<SECTOR KEY UPPER>`, name `<index name> – <Title Case Sector>`, `sector` = key; currency per set (`USD` / `SEK` / `GBP`) |
| FR-34a | Membership by current `*_tickers.sector`, normalized `lower(replace(btrim(sector), ' ', '-'))`; blank/NULL sector → market index only; every sector gets an index regardless of size |
| FR-35 | One row per index ticker per calendar week; `trading_date` = latest contributing bar of that index |
| FR-36 | Contributing stocks: members of the index with positive price / SMAs and non-NULL growth columns; one set `N` drives the levels and `pct_uptrend` |
| FR-37 / 37a / 37b | Equal-weighted mean of stored growth; gap weeks use the stored-row ratio; outlier stock-weeks excluded from market **and** sector indices |
| FR-38 / 39 | Chain-linked levels; base week (100 / SMA-to-price anchoring, ratios outside 0.001–10 excluded, FR-39a) per index ticker — a sector's base week can be later than its market's |
| FR-40 | `momentum = sma_50 / sma_200` |
| FR-40a | `pct_uptrend = 100 × share of the N contributing stocks with sma_50 > sma_200` |
| FR-40b | Sector rows: `z_score = (momentum − mean) / std` over the set's sector index rows with non-NULL momentum that week (population std, like stock `z_score`); NULL with fewer than two sectors or `std = 0`; market rows always NULL |
| FR-40c | `currency` = the set's currency; levels stay unit-free |
| FR-41 / 42 | `N = 0` → no row for that index/week; ascending recompute; a sector without members keeps history until retention |
| FR-43 | Weekly job + standalone full rebuild `compute_indices.py [--country]` (also after `refresh_tickers.py` sector changes) |
| FR-44 | Retention purge on `trading_date` covers sector rows too |
| FR-45 | Log per set: market row values, number of sector rows written; one `WARNING` per outlier (once per stock-week, not per index) |

## Calculation

Per country set `c` and calendar week `w`:

1. **Member stocks:** `{c}_metrics` ⋈ `{c}_tickers` on `ticker = symbol`, with
   `sector_key = NULLIF(lower(replace(btrim(sector), ' ', '-')), '')`.
2. **Week stats per index:** one query per `(c, w)` aggregates the
   contributing stocks with `GROUP BY GROUPING SETS ((), (sector_key))` —
   the empty set is the market index, each `sector_key` group a sector index
   (rows with NULL `sector_key` contribute only to `()`). It returns per
   group: `ticker_count`, `MAX(trading_date)`, the three mean growths, and
   `100 × AVG((sma_50 > sma_200)::int)` for `pct_uptrend`. The FR-37b bounds
   filter stock-weeks before grouping.
3. **Per index ticker:** look up its previous stored row `p`
   (`trading_date < w`):
   - no `p` → base week (FR-39) from a base-week query with the same
     grouping;
   - `week_start_of(p.trading_date) = w − 7` → chain with the step-2
     growths;
   - otherwise (gap week) → FR-37a ratio query for that index's members
     between `p`'s week and `w`.
4. **Z-score:** every index row of `(c, w)` is built in the same pass, so
   the pure `with_sector_z_scores` sets `(momentum − mean) / std` on the
   sector rows (population std; NULL with fewer than two sectors or zero
   std; market row NULL) before anything is written.
5. **Write:** delete all of the country's rows with `trading_date` in
   `[w, w + 7)` and insert the week's rows — a sector that lost all members
   disappears from recomputed weeks but keeps earlier history.

Runtime values (country, week bounds, outlier bounds, index tickers) are
always parameters; table names come from `sql_for_countries`.

## Design

| Path | Change |
|------|--------|
| `migrate_indices_sectors.sql` | **Step 21** — unless `sector` is already column 2: add `sector` / `currency` / `pct_uptrend` / `z_score`, copy `name` into `sector`, then rebuild `indices` (create `indices_new` with `ticker, sector, country, …`, copy rows, drop old, rename, restore `indices_pkey`) — Postgres cannot reorder columns; `name` is not carried over; index `idx_indices_country_trading_date`. Idempotent, but not additive — old code writes `name`, so apply with the deploy |
| `migrate_drop_by_sector_tables.sql` | **Step 22** — `DROP TABLE IF EXISTS us_by_sector, swe_by_sector, uk_by_sector`; applied only after the new code is deployed and `fansboda` no longer reads them |
| `schema.sql` | `indices` with the four new columns; `*_by_sector` tables removed |
| `equity_index.py` | `IndexRow` gains `sector`, `currency`, `pct_uptrend`, `z_score`; `COUNTRY_CURRENCY`; `sector_index_definition(country, sector)` (ticker / name); `with_sector_z_scores(rows)` (step 4) |
| `db/indices.py` | Grouped `BASE_WEEK_STATS_SQL` / `CHAINED_WEEK_STATS_SQL`, per-index `GAP_WEEK_STATS_SQL` (NULL sector = market); `LOAD_PREVIOUS_INDICES_SQL` (latest row per ticker, `DISTINCT ON`); `DELETE_COUNTRY_WEEK_SQL` / `DELETE_COUNTRY_INDICES_SQL`; insert with the new columns |
| `compute_indices.py` | Builds market + sector rows per country/week; outlier `WARNING`s once per stock-week; FR-45 logging |
| `fetch_sma.py` | Drop `_run_sector_trends`; `_run_indices` follows the retention purge |
| `compute_sector_trends.py`, `db/sector.py`, `tests/test_compute_sector_trends.py` | Removed |
| `db/country.py` | Remove `BY_SECTOR_TABLE` and the `{by_sector}` placeholder |
| `scripts/apply_migrations.sh` / `scripts/verify_schema.sql` | Steps 21–22; column checks; assert `*_by_sector` absent after step 22 |
| Tests | Grouping SQL shape, sector ticker/name helpers, base week per sector, gap week per sector, `pct_uptrend`, z-score (n < 2, std 0, market NULL), outlier excluded from market + sector, migration order, weekly job ordering without the sector step |

## Rollout

1. Apply step 21 and deploy the code together, between Saturday runs (old
   code fails without `name`; new code fails without the step-21 columns).
2. The new code no longer writes `*_by_sector`.
3. Rebuild: `pipenv run python compute_indices.py` (creates sector index
   history and fills the new columns on market rows).
4. Point `fansboda` (or any query) from `*_by_sector` to `indices`
   (`WHERE ticker LIKE '%-IDX-%'`).
5. Apply step 22 to drop `*_by_sector`.

Verified on Postgres 16: steps 21–22 upgrade a pre-RFC-018 schema and are
no-ops on re-run; `apply_migrations.sh` on a fresh database ends without
`*_by_sector`; a rebuild over sample data matched hand-computed market and
sector levels, `pct_uptrend`, and z-scores, merged a display-name sector into
its key, kept a blank-sector stock in the market index only, excluded a ×500
outlier from market and sector indices, gave a sector first seen in week 3 its
own base week, and used the ratio query in a gap week; an incremental refresh
reproduced the rebuild exactly.

## Trade-offs

- `momentum_median` and `z_score_mean` from `*_by_sector` have no
  replacement; `pct_uptrend` and a sector-level `z_score` remain.
- Sector indices with few stocks are noisy, and excluding a genuine ×10 move
  (FR-37b) biases them more than the market index; consumers filter on
  `ticker_count`.
- Membership uses the **current** ticker sector, so a reclassified stock
  moves its whole history on the next full rebuild.

## Open questions

- None.
