# Research: Repository Front-Page Document

**Feature**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

## R1 — Location and the old README

**Decision**: The document is the root `README.md`; its current content is replaced entirely.
`RULES.mdc` drops `README.md` from the do-not-commit list. `.gitignore` is already changed by the
owner (uncommitted).

**Rationale**: GitHub shows the root `README.md` on the repository page. The old local notes are
obsolete and partly unsafe to publish: daily 11:00 cron (now Saturdays), single `tickers` /
`metrics` tables (now `us_*` / `swe_*` / `uk_*`), `GCP_SA_KEY` JSON-key deploy (forbidden by
constitution V), VM name and zone. Nothing in them is still correct that is not in `RULES.mdc`
or the specs.

**Alternatives considered**: `.github/README.md` (keeps local notes) — moot since the owner
un-ignored the root file; merging old sections — rejected, they are outdated.

**Side effect to note**: removing the `README.md` pattern from `.gitignore` also un-ignores
`project-docs/rfc/README.md` (RFC index, frozen baseline). Owner decision (2026-10-09): commit it
unchanged with this feature (FR-011).

## R2 — Math notation on GitHub

**Decision**: GitHub-flavored Markdown math:
- display formulas in fenced ```` ```math ```` blocks (robust: no clash with Markdown `_` / `*`);
- inline math as `` $`…`$ `` (backtick-delimited form, also immune to Markdown escaping);
- every formula followed by a plain-language sentence, so it reads even where math does not render
  (spec edge case).

**Rationale**: GitHub renders LaTeX via MathJax in `README.md`; the plain `$…$` inline form breaks
on underscores and asterisks (`SMA_{50}` next to `*`), the backtick and fenced forms do not.

**Alternatives considered**: images of formulas (not editable, not searchable); plain text only
(fails "thorough walk-through" readability).

## R3 — Architecture diagram

**Decision**: One Mermaid `flowchart LR` (yfinance → weekly job on VM → Neon Postgres →
`fansboda`), with the one-off tools as a side branch. No project, VM, or account names.

**Rationale**: GitHub renders Mermaid natively; text-based, reviewable in diffs; FR-005 allows one
diagram.

## R4 — Facts the document must state (verified against code, 2026-10-09)

| Topic | Fact | Source |
|---|---|---|
| Weekly row | One row per stock per calendar week (`week_start` = Monday); value from the last trading day of the week; a newer bar in the same week replaces it | `db/metrics.py` upsert |
| SMA | Arithmetic mean of the last 50 / 200 daily (adjusted) closes; stock needs ≥ 200 closes, else no row | `fetch_sma.compute_smas`, `metric_row_from_history` |
| Momentum | `sma_50 / sma_200`; empty if either missing or `sma_200 = 0` | `compute_momentum` |
| Weekly growth | `x_t / x_{t'} − 1` for price, SMA-50, SMA-200; `t'` = last bar of the previous calendar week in the **same** download, each SMA from closes up to its own bar; empty without a previous-week bar | `compute_weekly_growth` |
| Stock z-score | `(m − μ) / σ` over all stocks of the same yfinance `market` (e.g. `us_market`) that week; σ population std; stored mean/std in `*_market_metrics`; empty if σ = 0 or missing | `aggregate_market_stats`, `UPDATE_Z_SCORES_SQL` |
| Outlier | Any of the three growths `> 9.0` (×10) or `< −0.999` (−99.9 %); emailed once; excluded from index returns | `is_outlier`, config defaults |
| Index member return | `r_{i,d} = P_{i,d} / P_{i,prev} − 1` on the stock's own consecutive bars; returns outside the outlier bounds dropped | `index_anchor._returns` |
| Index average return | Equal-weighted mean over members with a return that day | `DailyAccumulator` |
| Index level | `L_d = L_{d−1} (1 + \bar r_d)`; pinned: `L = 100` on the start date (initialization, new sectors) or the latest stored level (weekly run); before the pin divided backward | `daily_levels` |
| Start date | `INDEX_START_DATE` (2025-10-03) if ≥ 5 members have a close on it, else last trading day of the first later week that has; 250 trading days of history kept before it | `find_start_date`, config |
| Index SMA | Mean of the last 50 / 200 daily levels up to the row date (fewer if not available) | `week_levels` |
| Index weekly row | Last series date in the week (start date on the start week); `current_price` = that level | `week_levels` |
| Member count / uptrend | Stocks in the group with stored price, SMA-50, SMA-200 > 0 that week; `pct_uptrend = 100 × share with SMA-50 > SMA-200` | `BASE_WEEK_STATS_SQL` |
| Sector z-score | Sector momentum vs the country's sector indices that week, population std; empty with < 2 sectors or σ = 0; empty on market rows | `with_sector_z_scores` |
| Names | Market: NYSE & Nasdaq (`US-IDX`), OMX Stockholm (`SWE-IDX`), FTSE London (`UK-IDX`); sectors `US-IDX-TECHNOLOGY` / "Technology" | `equity_index.py` |
| Retention | Rows older than 365 days deleted each run | config, `db/retention.py` |
| Precision | Stored with 6 decimals | `NUMERIC(18, 6)` |

## R5 — Worked examples

**Decision**: Use small, hand-checkable numbers, and short windows where the long windows would
be unreadable — state explicitly that the example uses a 3-day / 5-day window "for illustration,
the app uses 50 / 200". Examples:
1. SMA + momentum: 5 closes, SMA-3 and SMA-5, momentum = their ratio.
2. Weekly growth: two Friday closes → price growth.
3. Z-score: four stocks' momenta → mean, population std, one z-score.
4. Index: three members over three days from 100, including one dropped outlier return.

**Rationale**: SC-002 requires hand-reproducible results; the quickstart recomputes them with the
repository's own functions to guarantee they match the definitions.

## R6 — Keeping it current

**Decision**: Add one line to `RULES.mdc` ("When implementing changes"): a change to a published
formula, window, threshold, default, or index name also updates `README.md` (FR-010). No CI
check.

**Alternatives considered**: a test asserting README numbers equal config defaults — rejected as
brittle prose parsing; revisit if drift happens.
