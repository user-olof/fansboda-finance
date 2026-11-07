# Research: Weekly Fetch for a Missed Trading Date

## R1 — Run date drives the whole run

**Decision**: `fetch_sma.main` resolves one **run date** — today (UTC) without the option, the
given `--trading_date` otherwise — and uses it everywhere the job now uses "today": the freshness
check (`filter_stale_tickers(..., today=run_date)`, which already accepts `today`), the download
window start (`run_date - HISTORY_DAYS`), and the download end.

**Rationale**: Everything downstream (metric rows, week starts, market stats, z-scores, index
weeks, outlier email) derives from the downloaded bars and the rows written, so bounding the
download by the run date makes the run equal to a Saturday run on that date (FR-002, FR-003)
with no change to the shared computation.

**Alternatives considered**: A separate "backfill one week" script — duplicates the weekly job
(constitution: reuse shared logic). Using `backfill_sma.py` — downloads ~730 days, per country,
re-inserts purged weeks, and does not update indices or send the email.

## R2 — Download end date

**Decision**: `yfinance_client.download_batch` gets an optional keyword `end: date | None`
(inclusive last calendar day); it passes `end + 1 day` to `yf.download` (whose `end` is
exclusive). Default `None` keeps today's behaviour. `fetch_sma` passes it for the main batches
and for `_fold_missing_members` (index members not fetched this run).

**Rationale**: No bar after the run date reaches any value (FR-002); one optional parameter keeps
all other callers (`backfill_sma.py`, `index_anchor.py`) unchanged.

## R3 — Validation

**Decision**: Pure `resolve_run_date(trading_date, *, today, retention_days) -> date`: `None` →
`today`; a date after `today` → `ValueError("… is in the future")`; a date before
`today - retention_days` → `ValueError("… older than the N-day retention window …")`. `main` logs
the error and exits 1 before loading tickers. A malformed value is rejected by argparse (`type`
parser → usage error, exit 2).

**Rationale**: FR-006 / SC-005; rows older than retention would be deleted by the same run's
purge. Weekends and holidays are accepted (spec assumption) — the last bar on or before the date
is used naturally.

## R4 — CLI

**Decision**: `fetch_sma.build_parser()` with `--trading_date` (alias `--trading-date`),
`metavar YYYY-MM-DD`. `main(argv: list[str] | None = None)` parses `argv` (`None` → `[]`, so tests
calling `main()` don't read pytest's arguments); `__main__` passes `sys.argv[1:]`. The cron line
is unchanged (FR-009).

## R5 — Indices, new sectors, retention, email

**Decision**: No change to `_run_index_update`, `_start_new_sectors`, the retention purge, or
`_run_outlier_email`.
- Index weeks come from the rows written; each stored index continues from its latest stored row
  before that week (`load_previous_indices(..., min(weeks))`), so a filled week chains correctly
  even when later weeks are stored, and later weeks are not rewritten (FR-005).
- New sector indices are started from their own download to today and written for all stored
  weeks, as today (spec assumption).
- Retention purge runs relative to today, as today.
- The outlier email goes out for the filled week's newly detected outliers (clarified: same as the
  Saturday run).

**Rationale**: The spec asks for Saturday-run behaviour, not new behaviour.

## R6 — Documentation

**Decision**: `.cursor/rules/RULES.mdc` `fetch_sma.py` row mentions the option. README not
changed (no formula, window, threshold, default, or index name changes — RULES rule 6). Owner
usage in quickstart.md.
