# Implementation Plan: Index Initial SMA from Daily History

**Branch**: `001-index-initial-sma` | **Date**: 2026-10-07 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-index-initial-sma/spec.md`

## Summary

Every market and sector index is anchored at price 100 on one common start date, 2025-10-03,
with initial SMA-50 / SMA-200 equal to real 50- / 200-trading-day averages of the index's own
price. That daily price history is reconstructed backwards from 100 using the member stocks'
equal-weighted average daily price change over the 250 trading days before the start date
(one adjusted yfinance download per country in the one-off `compute_indices.py` initialization). Weeks after the start date keep
chaining from the stored weekly growth exactly as today. When retention has already removed the
start week (from 2026-10-10 on), the weeks between the start date and the oldest stored week are
bridged from the same download with the same weekly rules, so every rebuild stays anchored on
2025-10-03. The weekly update moves into `fetch_sma.py`: after storing the stocks' growth, it
chains the new week onto existing indices without downloading, and creates a new sector index
with the same start-date rule and initial SMAs as the initialization, from a download of that
sector's stocks only (FR-016, research R12). An index starts on 2025-10-03 if at least 5 of its
stocks have a price on it, otherwise on the first later week-end with 5 (research R7).

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: pandas, yfinance (existing `download_batch`), psycopg2 — no new
dependencies

**Storage**: Neon Postgres, existing `indices` and `*_metrics` / `*_tickers` tables; no schema
change

**Testing**: pytest (`PIPENV_DONT_LOAD_ENV=1 pipenv run pytest`), mocked DB and yfinance; manual
end-to-end check on a local Docker Postgres 16 ([quickstart.md](./quickstart.md))

**Target Platform**: GCP `e2-micro` VM (cron, Saturdays 11:00 UTC) and local manual runs

**Project Type**: Batch data pipeline (CLI scripts)

**Performance Goals**: Full rebuild of US + SWE + UK (≈5,800 tickers, ≈2 years of daily bars
each) in under one hour; weekly run unchanged when no index is new

**Constraints**: yfinance rate limits (batched, `threads=False`, backoff); 1 GB VM memory —
process one batch at a time and keep only per-index daily sums and weekly sums, never the full
price matrix; ~$0 cost

**Scale/Scope**: 3 countries, 36 indices today (3 market + 33 sector), ≈52 stored weeks each

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Result |
|---|---|---|
| I. Weekly batch only | `compute_indices.py` is a one-off manual initialization (never cron), the weekly update lives in `fetch_sma.py`, chains existing indices without downloads, and downloads daily data only to start a new sector (FR-009, FR-015, FR-016) — still part of the one weekly batch. | Pass |
| II. Near-zero cost | No new infrastructure; extra yfinance calls only on the initialization and for a new sector's stocks (rare, a few batches). | Pass |
| III. Data pipeline only | No UI/API; no new indicator — SMA-50/200 of the index price are existing measures. | Pass |
| IV. Parameterized SQL in `db/` | New queries (index tickers per country, base-week stats without ratios) live in `db/indices.py`, parameterized. | Pass |
| V. Keyless auth, no secrets | No auth or secret changes. | Pass |
| VI. Schema via `schema.sql` + `migrate_*.sql` | No DDL change; stored rows only. | Pass (N/A) |
| VII. Pure logic + unit tests | Daily reconstruction, SMA averaging, bridge aggregation, and sector-key normalization are pure functions in `index_anchor.py` with unit tests; I/O (download, DB) mocked. | Pass |
| Operational: reuse shared logic | Reuses `download_batch`, `chunked`, `compute_weekly_growth` / `metric_rows_from_weekly_samples`, `is_outlier`. | Pass |
| Operational: config in `config.py` | `index_start_date`, `index_history_trading_days`, `index_min_components` added to `BaseConfig`. | Pass |

No violations; Complexity Tracking is empty.

**Post-design re-check (after Phase 1)**: unchanged — Pass. The design adds one module and one
config pair, no schema change, and keeps the weekly path download-free for existing indices.

## Project Structure

### Documentation (this feature)

```text
specs/001-index-initial-sma/
├── plan.md              # This file
├── research.md          # Phase 0 decisions
├── data-model.md        # Phase 1 entities and rules
├── quickstart.md        # Phase 1 validation guide
├── contracts/
│   ├── compute-indices-cli.md
│   └── indices-table.md
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
config.py                 # + index_start_date (INDEX_START_DATE, default 2025-10-03),
                          #   index_history_trading_days (INDEX_HISTORY_TRADING_DAYS, 250),
                          #   index_min_components (INDEX_MIN_COMPONENTS, 5)
index_anchor.py           # NEW pure logic: sector_key(), daily return accumulation,
                          #   backward reconstruction, initial SMAs, weekly bridge
                          #   aggregation, find_start_date() (≥ 5 listed members); plus
                          #   compute_anchors() I/O wrapper (download)
equity_index.py           # build_base_row takes anchor levels instead of SMA ratios
db/indices.py             # BASE_WEEK_STATS_SQL without ratio columns/bounds;
                          #   write_index_weeks(..., start_week, anchors, only_tickers);
                          #   weeks < start are skipped; only_tickers adds new sector rows
                          #   and recomputes the week's z-scores
compute_indices.py        # ONE-OFF initialization (manual, never cron): per country download,
                          #   anchors, delete + write the full weekly series from the start week;
                          #   incremental mode removed
fetch_sma.py              # weekly update: _run_index_update chains the new week via
                          #   write_index_weeks, starts new sector indices via
                          #   compute_anchors (R12), logs outliers; no longer imports
                          #   compute_indices
tests/
├── test_index_anchor.py  # NEW: reconstruction, SMAs, bridge, sector_key, edge cases
├── test_compute_indices.py  # initialization: anchors wiring, start-week filtering, CLI
├── test_fetch_sma.py     # weekly index update step, new sector start, no download otherwise
└── test_config.py        # new settings
.cursor/rules/RULES.mdc   # indices base-week rule; compute_indices now downloads on rebuild
                          # (project-docs/ is frozen — no changes there)
```

**Structure Decision**: Single-project layout as today. New pure logic goes in a new top-level
module `index_anchor.py` (next to `equity_index.py`), matching the existing "pure module + `db/`
SQL + script entrypoint" split.

## Complexity Tracking

No constitution violations to justify.
