# RFC-013: Golden Cross & Death Cross Detection

| Field | Value |
|-------|-------|
| **Priority** | P2 |
| **Status** | **Implemented** |
| **Depends on** | RFC-001, RFC-003, RFC-005, RFC-006 |
| **PRD** | §3, §5.6 (FR-19–FR-26) |
| **Feature** | [Golden Cross & Death Cross detection](../FEATURES.md#golden-cross--death-cross-detection) |

## Summary

Ad-hoc detection of **completed** Golden Cross and Death Cross processes from
retained weekly `sma_50` / `sma_200` history in country `*_metrics` tables
(`us_metrics` / `swe_metrics` / `uk_metrics`). Detection reads stored SMA
snapshots only — **no yfinance**, **no Thursday cron**, **no alerting /
watchers**, and **no dedicated detections table**.

This RFC freezes the **pattern definitions** already owned by the PRD (§3 /
§5.6) and proposes **FR-26 config defaults** plus an implementation sketch
for a pure detection layer + CLI. Application code is **not** introduced by
this document.

## Requirements (PRD §5.6)

| ID | Requirement |
|----|-------------|
| FR-19 | Source of truth: country `*_metrics` only (`sma_50`, `sma_200`, `trading_date`), ordered per ticker |
| FR-20 | MA pair: SMA-50 = shorter; SMA-200 = longer |
| FR-21 | Golden Cross: emit only when all three stages complete in order |
| FR-22 | Death Cross: emit only when all three stages complete in order (mirror) |
| FR-23 | Scope: all three country sets; optional country and/or symbol filters |
| FR-24 | Ad-hoc CLI (or equivalent) with human- and machine-readable output; not cron-scheduled in v1 |
| FR-25 | Skip NULL SMA rows; incomplete / out-of-order sequences do not emit |
| FR-26 | Stage windows and thresholds configurable; defaults live in config / this RFC (not frozen in the PRD) |

### Pattern definitions (owner / PRD wording)

**Golden Cross** — emit an event only when a ticker completes all three
stages over retained weekly snapshots:

1. **Downtrend or consolidation** — SMA-50 sits **below** SMA-200.
2. **Convergence** — the gap between them narrows as recent prices
   strengthen.
3. **Crossover** — SMA-50 crosses **above** SMA-200.

**Death Cross** — mirror of Golden Cross:

1. **Uptrend or consolidation** — SMA-50 sits **above** SMA-200.
2. **Convergence** — the gap narrows as recent prices weaken vs the longer
   trend.
3. **Crossover** — SMA-50 crosses **below** SMA-200.

Incomplete sequences (stages 1–2 without a completed stage 3, or
out-of-order history) **must not** emit an event.

## Design decisions (FR-26) — Proposed defaults

All knobs below are **Proposed** defaults for shared use by both patterns.
They belong on `BaseConfig` (RFC-006) and may be overridden via env / `.env`.

### Shared knobs

| Config attribute | Env var | Default | Constraint / meaning |
|------------------|---------|---------|----------------------|
| `cross_min_regime_weeks` | `CROSS_MIN_REGIME_WEEKS` | **4** | Consecutive valid weekly snapshots in the stage-1 regime **immediately before** the crossover week |
| `cross_convergence_weeks` | `CROSS_CONVERGENCE_WEEKS` | **3** | Must be `<= cross_min_regime_weeks`. Lookback window ending at the **last regime week** (the week before the crossover week) |

Validation at config load (or CLI start): reject
`cross_convergence_weeks > cross_min_regime_weeks`.

### Gap and convergence (first-vs-last)

| Pattern | Stage-1 regime | Gap definition |
|---------|----------------|----------------|
| Golden | below-regime (`sma_50 < sma_200`) | `gap = sma_200 - sma_50` |
| Death | above-regime (`sma_50 > sma_200`) | `gap = sma_50 - sma_200` |

**Convergence** over the lookback window of `cross_convergence_weeks` valid
snapshots ending at the last regime week:

- Compare **first** gap in the window to **last** gap in the window.
- Convergence holds iff `last_gap < first_gap` (**strict**).
- Do **not** require a fully monotonic narrowing sequence across every
  intermediate week.

### Crossover (strict inequality)

On the crossover week `t` (the first valid week after the regime window):

| Pattern | Condition on week `t` |
|---------|------------------------|
| Golden | `sma_50[t] > sma_200[t]` |
| Death | `sma_50[t] < sma_200[t]` |

Equal SMAs (`sma_50 == sma_200`) do **not** count as a cross (PRD: “crosses
above / below”). Combined with the regime window immediately before `t`
(strict below for Golden, strict above for Death), this is a completed
cross from the prior regime into the opposite side.

### Null SMA rows

When walking a ticker’s ordered series, skip any row where `sma_50` or
`sma_200` is NULL (FR-25). Regime / convergence / crossover windows count
**valid** weekly snapshots only — NULLs do not occupy a week slot in those
windows.

### Emission rule

Emit one detection event for a `(ticker, pattern, crossover_trading_date)`
only when:

1. The crossover week satisfies the strict crossover rule, **and**
2. The immediately preceding `cross_min_regime_weeks` valid snapshots are
   entirely in the stage-1 regime for that pattern, **and**
3. The convergence window of `cross_convergence_weeks` ending at the last
   regime week satisfies first-vs-last gap narrowing.

Otherwise emit nothing for that candidate.

## CLI & consumption (FR-23, FR-24) — Proposed

One ad-hoc entrypoint covers both patterns (suggested name:
`detect_crosses.py` — guidance only; file does not exist yet).

```bash
# Illustrative — not implemented by this RFC
pipenv run python detect_crosses.py
pipenv run python detect_crosses.py --pattern golden|death|all
pipenv run python detect_crosses.py --country us|swe|uk
pipenv run python detect_crosses.py --symbols AAPL,MSFT.ST,VOD.L
pipenv run python detect_crosses.py --format table|json|csv
```

| Flag | Default | Notes |
|------|---------|-------|
| `--pattern` | `all` | `golden`, `death`, or `all` |
| `--country` | all sets | Same country filter convention as other jobs |
| `--symbols` | all tickers in scope | Optional subset |
| `--format` | `table` | Human-readable table; `json` / `csv` for machine use |

Not cron-scheduled in v1. No push notifications, alerting, or watchers
(PRD §11 / FEATURES out of scope).

## Schema / migrations

**No schema migration.** Detection reads existing `*_metrics` columns
(`sma_50`, `sma_200`, `trading_date`) on demand. Per
[MIGRATIONS.md](../MIGRATIONS.md): this product pass adds **no detections
table** and **no new columns**. Steps 1–14 and an up-to-date `schema.sql`
remain sufficient.

## Implementation guidance (design only)

Filenames below are **suggested**; they do not exist yet and must not be
treated as present in the tree until a follow-up implementation PR.

### Suggested layout

| Suggested path | Role |
|----------------|------|
| `cross_detection.py` (or `crosses.py`) | Pure detection logic — no DB I/O |
| `detect_crosses.py` | CLI entrypoint / orchestration |
| `db/metrics.py` (extend) or `db/crosses.py` | Parameterized SQL to load ordered SMA snapshots from `*_metrics` |
| `config.py` | `cross_min_regime_weeks`, `cross_convergence_weeks` on `BaseConfig` |
| `tests/test_cross_detection.py` | Unit tests for both patterns (pure logic) |
| `tests/test_detect_crosses.py` / `tests/test_sql_security.py` | CLI wiring mocks; list new SQL in SQL-security tests when coded |

### Separation of concerns

- **Pure module:** given an ordered series of `(trading_date, sma_50, sma_200)`
  plus the config knobs, return zero or more detection events. No
  `psycopg` / env / yfinance imports.
- **DB helper:** load ordered snapshots for a country set (optional symbol
  filter); SQL stays in `db/` — always parameterized (repo SQL-security
  rules).
- **CLI:** `get_config()`, parse flags, call DB helper + pure detector,
  format output. Reuse country / symbol parsing patterns from existing
  scripts where practical.

### Suggested event shape (output)

| Field | Meaning |
|-------|---------|
| `pattern` | `golden` or `death` |
| `ticker` | Symbol |
| `country` | `us` / `swe` / `uk` |
| `crossover_date` | `trading_date` of the crossover week |
| `regime_start_date` | First week of the satisfied regime window |
| `regime_weeks` | Count used (`cross_min_regime_weeks`) |
| `convergence_first_gap` / `convergence_last_gap` | Gaps compared for stage 2 |
| `sma_50` / `sma_200` at crossover | Snapshot values on crossover week |

Exact column names in table/CSV output may be refined at implementation
time; keep JSON keys stable once shipped.

## Acceptance criteria

- [x] Pure detection module covers Golden and Death patterns with shared
      knobs; incomplete sequences do not emit
- [x] Null SMA rows are skipped when walking series
- [x] Crossover uses strict inequality (`>` Golden, `<` Death); equal SMAs
      do not count
- [x] Convergence is first-vs-last gap narrowing over
      `cross_convergence_weeks` ending at the last regime week
- [x] Regime requires `cross_min_regime_weeks` consecutive valid weeks in
      stage-1 regime immediately before the crossover week
- [x] Config defaults: `CROSS_MIN_REGIME_WEEKS=4`,
      `CROSS_CONVERGENCE_WEEKS=3` on `BaseConfig`; convergence ≤ regime
      validated
- [x] One ad-hoc CLI for both patterns (`--pattern`, optional `--country`,
      ticker subset, `table` / `json` / `csv`)
- [x] DB load helper uses parameterized SQL in `db/`; listed in
      SQL-security tests when coded
- [x] No yfinance calls; not cron-scheduled; no alerting / watchers
- [x] No detections table / no new metrics columns (MIGRATIONS.md)
- [x] Unit tests for both patterns (including edge cases: equals, NULLs,
      incomplete regime, non-converging gap)
- [x] Docs (FEATURES status → Shipped when implemented; this RFC →
      Implemented) updated in the implementation PR

## Resolved decisions

- **Source of truth:** Retained weekly `*_metrics` only (FR-19); no live
  price fetch at detection time.
- **Emit completeness:** All three stages required; incomplete sequences
  never emit (FR-21 / FR-22 / FR-25).
- **Persistence:** No dedicated detections table in this product pass —
  compute on demand from retained history (FEATURES; MIGRATIONS.md).
- **Scheduling / alerting:** Ad-hoc CLI only in v1; no cron, no push /
  watchers (PRD §11).
- **FR-26 defaults (Proposed):** `min_regime_weeks=4`,
  `convergence_weeks=3`, shared across both patterns; first-vs-last gap
  narrowing; strict crossover inequality.
- **CLI surface (Proposed):** Single entrypoint for both patterns with
  optional `--pattern golden|death|all`.

## Open questions

- Split knobs per pattern later (`CROSS_GOLDEN_*` / `CROSS_DEATH_*`) if
  tuning shows asymmetric needs? Prefer shared knobs until evidence
  appears.
- Persist detections in a dedicated table / history store in a later
  product pass? Explicitly out of scope here; revisit only with a new
  RFC + migration.
- Interaction with a future **gap-detection** RFC (missed weekly runs,
  PRD §11): should detection treat calendar gaps between valid snapshots
  differently from NULL SMA rows, or continue counting consecutive valid
  snapshots only?
- Equal-SMA weeks (`sma_50 == sma_200`) break stage-1 regime under the
  strict below/above rule and never satisfy crossover. If product later
  wants equal weeks to count as consolidation-within-regime, that needs
  an explicit knobs change.
- Output schema versioning for `json` consumers if fields evolve after
  first ship.
