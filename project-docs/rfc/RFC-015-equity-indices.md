# RFC-015: Equal-Weighted Equity Indices

| Field | Value |
|-------|-------|
| **Priority** | P3 |
| **Status** | **Implemented** |
| **Depends on** | RFC-001, RFC-003, RFC-004, RFC-014 |
| **PRD** | §5.1 (FR-7, FR-7b), §5.8 (FR-34–FR-43), §6 |
| **Feature** | [Equity indices](../FEATURES.md#equity-indices) |

## Summary

One synthetic, equal-weighted price index per country set, stored in a single
`indices` table with one row per index per week. The index level is
chain-linked from the plain average of every stock's weekly price growth, so
each company counts once regardless of size. Computed in SQL from stored
`*_metrics.current_price`; no yfinance.

| Country set | Index name | Ticker | Source |
|-------------|------------|--------|--------|
| US | US Equity Index | `US-IDX` | `us_metrics` |
| Swedish | OMX Equity Index | `SWE-IDX` | `swe_metrics` |
| UK | FTSE Equity Index | `UK-IDX` | `uk_metrics` |

## Requirements (PRD §5.8)

| ID | Requirement |
|----|-------------|
| FR-34 | Three indices: `US-IDX`, `SWE-IDX`, `UK-IDX` with the names above |
| FR-35 | One `indices` row per ticker per `week_start`, PK `(ticker, week_start)` |
| FR-36 | Stock return `r_i = price_i(w) / price_i(p) − 1`; only stocks priced in both `w` and the previous stored week `p` |
| FR-37 | `avg_return(w)` = plain mean of `r_i` (equal weight, reset weekly) |
| FR-38 | `index_price(w) = index_price(p) × (1 + avg_return(w))`; base week = 100, `avg_return` NULL |
| FR-39 | No contributing stocks → no row; next week chains from the last stored row |
| FR-40 | Upsert on `(ticker, week_start)`; compute weeks in ascending order |
| FR-41 | Weekly job (FR-7b) for weeks just written; standalone full rebuild (optional `--country`) |
| FR-42 | Purge rows with `week_start` older than `METRICS_RETENTION_DAYS` (same window as metrics) |
| FR-43 | Log per index week / `ticker_count` / `avg_return` / `index_price` + summary; non-zero exit on DB failure |

## Calculation

For index ticker `X` (country set `c`) and week `w`:

1. `p` = the latest `week_start < w` that already has an `indices` row for `X`.
   If none, `w` is the base week → write `index_price = 100`,
   `avg_return = NULL`, `ticker_count` = stocks priced in `w`.
2. Pair each stock's `current_price` in `w` with its price in `p` from
   `{c}_metrics`; drop stocks with a NULL or missing price in either week, or
   a zero price in `p`.
3. `avg_return = AVG(price_w / price_p − 1)`, `ticker_count = COUNT(*)`.
4. If `ticker_count = 0`, write nothing (FR-39).
5. `index_price = index_price(p) × (1 + avg_return)`.

Using the previous **stored** week (not strictly `w − 7 days`) keeps the
chain intact across a missed weekly run: the return simply spans the gap.

Returns are unit-free, so mixed price units in one set (UK `GBp` vs `GBP`)
do not distort the index as long as a stock's own units are stable.
`current_price` is the adjusted close at fetch time; a dividend or split
adjustment between two weekly fetches can introduce a small one-week error
for that stock (accepted limitation).

### SQL sketch (one country, one week)

```sql
WITH prev AS (
    SELECT week_start, index_price
    FROM indices
    WHERE ticker = %(ticker)s AND week_start < %(week)s
    ORDER BY week_start DESC
    LIMIT 1
),
pairs AS (
    SELECT cur.current_price / old.current_price - 1 AS r
    FROM {metrics} cur
    JOIN {metrics} old
      ON old.ticker = cur.ticker
     AND old.week_start = (SELECT week_start FROM prev)
    WHERE cur.week_start = %(week)s
      AND cur.current_price IS NOT NULL
      AND old.current_price > 0
)
SELECT COUNT(*) AS ticker_count, AVG(r) AS avg_return,
       (SELECT index_price FROM prev) * (1 + AVG(r)) AS index_price
FROM pairs;
```

The base-week branch (no `prev` row) is handled in Python before this
query. Only `ticker` and `week_start` are runtime values, passed as
parameters; the table name comes from the `{metrics}` placeholder
(`sql_for_countries`).

## Design

| Path | Role |
|------|------|
| `migrate_add_indices_table.sql` | Step 18 — `CREATE TABLE IF NOT EXISTS indices` (mirrored in `schema.sql`) |
| `equity_index.py` | Pure logic: `INDEX_DEFINITIONS`, `IndexRow`, `build_index_row` (base week / chaining / skip empty week) |
| `db/indices.py` | Parameterized SQL, `write_index_weeks` (ascending weeks in one transaction, optional `rebuild`), `purge_stale_indices` |
| `compute_indices.py` | `refresh_indices(url, week_starts=None, *, country=None)` — `None` = full rebuild; a list recomputes every stored week from the earliest given week onward so later rows stay chained; CLI `--country us|swe|uk` (always a full rebuild) |
| `fetch_sma.py` | `_run_indices` after `_run_sector_trends` (FR-7b) when the run wrote any week; skipped on the all-fresh path |
| `db/retention.py` | `purge_stale_data` returns `(metrics, market_metrics, indices)`; `indices` purged with the metrics cutoff (FR-42); counts in the job summary (`purged_indices`) |
| `scripts/apply_migrations.sh` / `scripts/verify_schema.sql` / `db/truncate.py` | Step 18, schema checks, dev truncate |
| `tests/test_compute_indices.py` | Base week, chaining, equal weighting, empty week, SQL shape, transaction order, orchestration, CLI |
| `tests/test_retention.py` / `tests/test_schema.py` | Weekly-job hook, 3-way purge, DDL + migration order |

**Full rebuild:** delete the selected index's rows, then recompute every
metrics week ascending. The base week becomes the earliest retained metrics
week, so levels (not weekly returns) shift after retention purges history.

## Schema

```sql
CREATE TABLE IF NOT EXISTS indices (
    ticker        TEXT            NOT NULL,
    name          TEXT            NOT NULL,
    country       TEXT            NOT NULL,
    week_start    DATE            NOT NULL,
    updated_at    TIMESTAMPTZ     NOT NULL,
    ticker_count  INTEGER         NOT NULL,
    avg_return    NUMERIC(18, 6),
    index_price   NUMERIC(18, 6)  NOT NULL,
    PRIMARY KEY (ticker, week_start)
);
```

## Rollout

1. Apply step 18 (safe to repeat).
2. Build history once: `pipenv run python compute_indices.py`.
3. Deploy — the weekly job then appends one row per index per week.

Verified on Postgres 16: equal weighting (+10% / −10% → flat), new listing
and NULL price excluded, a skipped week chained from the last stored week,
recompute from an earlier week re-chains later rows, re-runs idempotent.

## Open questions

- None.
