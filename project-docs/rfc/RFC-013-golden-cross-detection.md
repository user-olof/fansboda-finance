# RFC-013: Golden Cross Detection from Stored SMA History

| Field | Value |
|-------|-------|
| **Priority** | P2 |
| **Status** | Implemented |
| **Depends on** | RFC-001, RFC-003, RFC-005, RFC-006 |
| **PRD** | §3 (primary use case); not an alerting product (§11) |
| **Feature** | [Golden Cross detection](../FEATURES.md#golden-cross-detection) |

## Summary

Ad-hoc detector that classifies weekly stored `sma_50` / `sma_200` history into
the classic **Golden Cross** process and emits crossover events. Reads Neon
Postgres country metrics tables only — **no yfinance / live market APIs**.

This is **detection + CLI output**, not a notification/alerting layer (still
out of scope per PRD §11).

## Pattern definition

Three stages (user definition; weekly Thursday cadence):

1. **Downtrend or consolidation** — `sma_50 < sma_200` for at least
   `min_below_weeks` consecutive valid snapshots before the cross.
2. **Convergence** — over the last `convergence_weeks` of that below-run, the
   gap (`sma_200 - sma_50`) narrows (last gap strictly less than first gap in
   the window).
3. **Crossover** — `sma_50` moves from below to **at or above** `sma_200`
   between consecutive valid snapshots.

Death crosses (above → below) are ignored. Rows with null SMAs are skipped when
walking the series. Events that fail stages 1–2 are not emitted.

## Tunables

| Setting | Default | Env / CLI |
|---------|---------|-----------|
| `min_below_weeks` | 4 | `GOLDEN_CROSS_MIN_BELOW_WEEKS` / `--min-below-weeks` |
| `convergence_weeks` | 3 | `GOLDEN_CROSS_CONVERGENCE_WEEKS` / `--convergence-weeks` |

`convergence_weeks` must be `<= min_below_weeks`. Defaults suit ~52 weekly
points under 365-day retention.

## Implementation

### Files

| File | Role |
|------|------|
| `golden_cross.py` | Pure detection: params, stages, events |
| `detect_golden_cross.py` | CLI: load from DB, print table/json/csv |
| `models.py` | `SmaSnapshot` |
| `db/metrics.py` | `load_sma_history` |
| `config.py` | Golden-cross defaults on `BaseConfig` |
| `tests/test_golden_cross.py` | Synthetic series + CLI/DB mocks |

### Key functions

| Function | Module | Purpose |
|----------|--------|---------|
| `detect_golden_crosses(...)` | `golden_cross.py` | Emit events for one ticker series |
| `classify_series_stages(...)` | `golden_cross.py` | Stage annotations for accepted processes |
| `load_sma_history(...)` | `db/metrics.py` | Ordered SMA rows per `(country, ticker)` |
| `collect_events(...)` | `detect_golden_cross.py` | Scan one or all country sets |

### CLI

```bash
pipenv run python detect_golden_cross.py
pipenv run python detect_golden_cross.py --country us
pipenv run python detect_golden_cross.py --country swe --format json
pipenv run python detect_golden_cross.py --tickers AAPL,MSFT --min-below-weeks 6
```

Output fields: `ticker`, `country`, `trading_date` (cross week), SMAs,
`weeks_below`, gap metadata; JSON also includes per-week `stages`.

## Acceptance criteria

- [x] Deterministic stage classification + crossover events from fixture series
- [x] Unit tests: clear cross, no cross while below, death-cross ignored, null
      SMAs, multi-ticker/country, param validation
- [x] CLI reads `DATABASE_URL` via `get_config()`; `--country` / `--format`
- [x] SQL stays in `db/`; job script listed in SQL-security tests
- [x] FEATURES + this RFC document the feature (not an alerting product)

## Resolved decisions

- **MA lengths:** Use stored SMA-50 / SMA-200 only — no new indicator lengths.
- **Equal SMAs:** `sma_50 >= sma_200` counts as the cross (at/above).
- **Convergence test:** First-vs-last gap shrink in the convergence window
  (strict `<`); not a full monotonic requirement (weekly noise).
- **Scope:** Detection + runnable CLI; no cron, no push notifications.

## Open questions

- Optional death-cross detector as a sibling module (same SMA series).
- Whether to persist detections in a table later (still out of scope).
