# Implementation Plan: Index SMA-50 / SMA-200 as True Moving Averages of the Index Price

**Branch**: `002-index-true-sma` | **Date**: 2026-10-08 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-index-true-sma/spec.md`

## Summary

Every index row's SMA-50 / SMA-200 becomes the mean of the last 50 / 200 levels of the index's
daily price, and the weekly price follows that same daily series. Each index's daily series is
built from its members' equal-weighted daily returns (outlier days dropped) and pinned at one
known point: price 100 on the start date for the one-off initialization and new sectors, or the
latest stored row for the weekly run (research R1). The weekly run folds its existing stock
download into per-index daily sums, downloads only members it skipped or failed (R2), and widens
its window from 300 to 400 calendar days (R3). The initialization downloads from the start date
to today, so the 001 weekly bridge over purged weeks disappears (R5). The SQL chaining by stored
weekly growth (`CHAINED_WEEK_STATS_SQL`, `GAP_WEEK_STATS_SQL`, `build_chained_row`) is removed;
SQL only supplies stock count and share in uptrend (R6). No schema change.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: pandas, yfinance (existing `download_batch`), psycopg2 — no new
dependencies

**Storage**: Neon Postgres, existing `indices`, `*_metrics`, `*_tickers`; no schema change

**Testing**: pytest (`PIPENV_DONT_LOAD_ENV=1 pipenv run pytest`), mocked DB and yfinance; manual
end-to-end check on a local Docker Postgres 16 ([quickstart.md](./quickstart.md))

**Target Platform**: GCP `e2-micro` VM (cron, Saturdays 11:00 UTC) and local manual runs

**Project Type**: Batch data pipeline (CLI scripts)

**Performance Goals**: Weekly run: same number of yfinance requests as today (each member once);
initialization of US + SWE + UK in under one hour (unchanged from 001)

**Constraints**: yfinance rate limits (batched, `threads=False`, backoff); 1 GB VM memory — keep
only per-index daily sums and counts, never the full price matrix; ~$0 cost

**Scale/Scope**: 3 countries, ≈40 indices, ≈5,800 tickers, ≈52 stored weeks per index

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Result |
|---|---|---|
| I. Weekly batch only | Weekly index update stays inside the Saturday `fetch_sma.py` run; `compute_indices.py` stays a one-off manual initialization. | Pass |
| II. Near-zero cost | No new infrastructure; the weekly run reuses its download (wider window, same request count); a supplemental download only for skipped / failed members. | Pass |
| III. Data pipeline only | No UI/API; SMA-50/200 of the index price are existing measures, not new indicators. | Pass |
| IV. Parameterized SQL in `db/` | Removes two queries; adds `load_previous_indices` over the existing parameterized `LOAD_PREVIOUS_INDICES_SQL`. No SQL in job scripts. | Pass |
| V. Keyless auth, no secrets | No auth or secret changes. | Pass |
| VI. Schema via `schema.sql` + `migrate_*.sql` | No DDL change; daily levels are not stored (FR-012). | Pass (N/A) |
| VII. Pure logic + unit tests | `daily_levels`, `week_levels`, return folding are pure functions in `index_anchor.py` with unit tests; DB and yfinance mocked. | Pass |
| Operational: reuse shared logic | Reuses `download_batch`, `chunked`, `_closes`, `daily_returns`, `DailyAccumulator`, `with_sector_z_scores`. | Pass |
| Operational: config in `config.py` | No new settings; existing `INDEX_*` and outlier bounds. | Pass |

No violations; Complexity Tracking is empty.

**Post-design re-check (after Phase 1)**: unchanged — Pass. The design removes code paths (SQL
chaining, gap weeks, weekly bridge) and adds two pure functions and one DB loader.

## Project Structure

### Documentation (this feature)

```text
specs/002-index-true-sma/
├── plan.md              # This file
├── research.md          # Phase 0 decisions
├── data-model.md        # Phase 1 entities and rules
├── quickstart.md        # Phase 1 validation guide
├── contracts/
│   ├── indices-table.md
│   └── compute-indices-cli.md
├── checklists/requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
index_anchor.py           # + daily_levels(averages, pin_date, pin_level)
                          # + week_levels(levels, week_start, *, row_date=None)
                          # + IndexSeries; compute_anchors → compute_index_series
                          #   (returns after the start date included; no weekly bridge)
                          # − reconstruct_levels, initial_smas (folded into week_levels),
                          #   WeeklyAccumulator, _bridge_weeks, build_anchor, Anchor
equity_index.py           # build_base_row → build_index_row (no price-100 check)
                          # − build_chained_row
db/indices.py             # write_index_weeks(database_url, week_levels, *, country,
                          #   rebuild, only_tickers); + load_previous_indices
                          # − CHAINED_WEEK_STATS_SQL, GAP_WEEK_STATS_SQL, growth bounds
fetch_sma.py              # HISTORY_DAYS 300 → 400; fold each batch into DailyAccumulator;
                          #   supplemental download of unfolded members; _run_index_update
                          #   pins at the previous stored row; new sectors via
                          #   compute_index_series
compute_indices.py        # initialization writes every stored week from IndexSeries
tests/
├── test_index_anchor.py  # daily_levels, week_levels, series scan (pre/post start returns)
├── test_compute_indices.py  # write_index_weeks with week_levels; initialization wiring
├── test_fetch_sma.py     # folding, supplemental download, weekly pins, new sector
└── test_retention.py     # index-update stub signature
.cursor/rules/RULES.mdc   # indices data-model sentence + fetch_sma row (project-docs/ frozen)
```

**Structure Decision**: Single-project layout as today; the daily-series logic stays in
`index_anchor.py` (pure + one download wrapper), SQL in `db/indices.py`, entrypoints unchanged.

## Complexity Tracking

No constitution violations to justify.
