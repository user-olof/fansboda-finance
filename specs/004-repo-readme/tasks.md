---

description: "Task list for 004-repo-readme"
---

# Tasks: Repository Front-Page Document (Mathematics and Architecture)

**Input**: Design documents from `/specs/004-repo-readme/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: No automated tests (documentation only). Validation is the quickstart checks; the
existing suite must stay green (`PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q`).

**Organization**: Grouped by user story. All writing tasks edit the same file (`README.md`), so
they run in order; only the rules-file edit and read-only checks can run in parallel.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1 (mathematics), US2 (architecture), US3 (current and safe to publish)
- Facts to use: research.md R4 table; outline and notation: contracts/readme-outline.md

---

## Phase 1: Setup

- [X] T001 Replace the whole content of `README.md` with the skeleton from
  `contracts/readme-outline.md`: title `# fansboda-finance`, the intro paragraph (weekly
  SMA-50 / SMA-200 pipeline for US, Swedish, and UK stocks plus equal-weighted market and sector
  indices; data in Postgres read directly by consumers such as `fansboda`; no UI or API; describes
  calculations, not investment advice — FR-001, FR-009), a short table of contents, and empty
  headings `## The mathematics` (with all `###` / `####` subsections in outline order) and
  `## Architecture`. Do not carry over anything from the old content (research R1)

---

## Phase 2: Foundational

- [X] T002 In `README.md` write `### Notation`: closes `$`P_{i,d}`$` (stock i, trading day d,
  adjusted), week w (Monday `week_start`), last trading day of the week `$`t(w)`$`, window
  `$`n \in \{50, 200\}`$`, members `$`N`$`, index level `$`L_d`$`; state the conventions once
  (display math in ```` ```math ```` blocks, inline `` $`…`$ ``, values stored with 6 decimals)

---

## Phase 3: User Story 1 - Understand every published number (Priority: P1) 🎯 MVP

**Goal**: Every stored stock and index measure is defined with formula, symbols, unit/range, and
empty condition; worked examples reproduce by hand (FR-002–FR-004, SC-001, SC-002).

**Independent Test**: quickstart §1 (coverage against data-model.md) and §4 (examples recomputed
with the repo's functions) pass.

- [X] T003 [US1] In `README.md` write the stock sections — `### Weekly snapshot` (one row per
  stock per calendar week from the last trading day; a later bar in the same week replaces it;
  `current_price`, `currency`), `### Simple moving averages`
  (`$`\mathrm{SMA}_n(d) = \frac{1}{n}\sum_{k=0}^{n-1} P_{d-k}`$` over trading days; ≥ 200 closes
  needed or the stock gets no row), `### Momentum` (`SMA_50 / SMA_200`, > 1 means the 50-day
  average is above the 200-day, empty if missing or SMA-200 = 0) — each with a plain-language
  reading
- [X] T004 [US1] In `README.md` write `### Weekly growth`: `$`g = x_{t(w)} / x_{t(w-1)} - 1`$` for
  price, SMA-50, SMA-200; previous week's last bar from the same adjusted download, each SMA from
  closes up to its own bar; why (splits / dividends re-base history, so two stored rows are never
  divided); empty without a previous-week bar
- [X] T005 [US1] In `README.md` write `### Market z-score`: per yfinance market (e.g. `us_market`)
  and week, `$`\mu`$` = mean momentum, `$`\sigma`$` = population standard deviation (÷ N), stored
  as `momentum_mean` / `momentum_std`; `$`z = (m-\mu)/\sigma`$`; reading (standard deviations
  above / below the market that week); empty if momentum missing or σ = 0
- [X] T006 [US1] In `README.md` write `### Outliers`: a stock-week is an outlier if any weekly
  growth > 9.0 (×10, +900 %, `OUTLIER_MAX_GROWTH`) or < −0.999 (−99.9 %, `OUTLIER_MIN_GROWTH`);
  newly found outliers are emailed to the owner once; the same bounds drop daily returns from
  the indices; the stock's own row is still stored
- [X] T007 [US1] In `README.md` write `### Equal-weighted indices` → `#### Index names` (one
  market index per country: `US-IDX` NYSE & Nasdaq, `SWE-IDX` OMX Stockholm, `UK-IDX` FTSE London;
  one per sector, e.g. `US-IDX-TECHNOLOGY` "Technology"; label stored in `sector`; currency USD /
  SEK / GBP) and `#### Daily returns and averaging` (`$`r_{i,d} = P_{i,d}/P_{i,d^-} - 1`$` on the
  stock's own previous bar `d^-`; returns outside the outlier bounds dropped; equal-weighted
  `$`\bar r_d = \frac{1}{|M_d|}\sum_{i \in M_d} r_{i,d}`$` over members with a return that day)
- [X] T008 [US1] In `README.md` write `#### Index level` (`$`L_d = L_{d^-}(1+\bar r_d)`$`; pinned
  at 100 on the start date by the one-off initialization and for new sectors; the weekly run
  continues from the latest stored level; days before the pin divided backward) and
  `#### Start date` (2025-10-03 `INDEX_START_DATE` if ≥ 5 members (`INDEX_MIN_COMPONENTS`) have a
  close on it, else the last trading day of the first later week that has; 250 trading days
  (`INDEX_HISTORY_TRADING_DAYS`) of levels before it so the SMAs are full from the first row)
- [X] T009 [US1] In `README.md` write `#### Index moving averages and momentum` (means of the last
  50 / 200 daily levels up to the row date — same definition as for stocks, fewer if not
  available; momentum = ratio), `#### Weekly index row` (row date = last series date in the
  week, the start date on the start week; `current_price` = level that day; one row per index
  per week), `#### Members and uptrend` (`ticker_count` = stocks in the group with stored price,
  SMA-50, SMA-200 > 0 that week; `pct_uptrend` = 100 × share with SMA-50 > SMA-200), and
  `#### Sector z-score` (sector momentum vs the country's sector indices that week, population σ;
  empty on market rows, with < 2 sectors, or σ = 0)
- [X] T010 [US1] In `README.md` write `### When a value is empty`: one table, measure →
  condition, covering every measure from T003–T009 (data-model.md catalogue)
- [X] T011 [US1] In `README.md` write `### Worked examples` (research R5), labelling short windows
  "for illustration; the app uses 50 / 200": (1) closes 10, 11, 12, 13, 14 → SMA-3 = 13,
  SMA-5 = 12, momentum = 1.083333; (2) Friday closes 50 → 55 → price growth = 0.10;
  (3) momenta 1.10, 1.00, 0.95, 0.95 → μ = 1.00, σ = 0.061237, z of 1.10 = 1.632993;
  (4) three members over three days from L = 100 with one return dropped as an outlier, showing
  each day's average and level. Recompute every number per quickstart §4 before writing it
  - *Recomputed 2026-10-09: the stored z uses the 6-decimal σ (0.061237), so the README shows
    z ≈ 1.633 instead of 1.632993.*

**Checkpoint**: Mathematics complete; quickstart §1 and §4 pass.

---

## Phase 4: User Story 2 - Know how the system fits together (Priority: P2)

**Goal**: A brief architecture summary after the mathematics (FR-005, SC-003).

**Independent Test**: The section is ≤ ≈ 400 words plus one diagram and answers: data source,
schedule, storage, country sets, jobs, retention, outlier email, consumer.

- [X] T012 [US2] In `README.md` write `## Architecture`: one Mermaid `flowchart LR` (Yahoo
  Finance via yfinance → weekly job on a small cloud VM → Postgres (Neon) → `fansboda`; one-off
  tools as a side branch; no names of VMs, projects, or accounts), then bullets: Saturdays
  11:00 UTC weekly run (`fetch_sma.py`: skip fresh stocks, batch download ≈ 400 days, compute,
  store, update indices, purge, email new outliers); storage per country set (`*_tickers`,
  `*_metrics`, `*_market_metrics`) plus shared `indices`; one-off tools (`seed_tickers.py`,
  `backfill_sma.py`, `backfill_market.py`, `compute_indices.py`); 365-day retention; the outlier
  email is the only notification; CI tests on every push, deploy after tests pass on `main`;
  ~$0/month on free tiers. Keep it to ≈ 400 words

**Checkpoint**: Document complete in outline order.

---

## Phase 5: User Story 3 - Current and safe to publish (Priority: P3)

**Goal**: Numbers match the code, nothing private, guidance updated (FR-006–FR-008, FR-010,
SC-004, SC-005).

**Independent Test**: quickstart §2 and §3 return the expected results; `RULES.mdc` no longer
lists `README.md` as do-not-commit.

- [X] T013 [P] [US3] In `.cursor/rules/RULES.mdc`: remove `` `README.md` (local notes) `` from the
  "Local / git-ignored files" do-not-commit list; add to "When implementing changes": "A change
  to a published formula, window, threshold, default, or index name also updates `README.md`
  (specs/004-repo-readme)."
- [X] T014 [US3] Run quickstart §2 (numbers vs `config.py` / code defaults) and §3
  (private-identifier scan) on `README.md`; fix any mismatch or match in `README.md`
- [X] T015 [US3] Run quickstart §1 (every data-model.md column has a definition) and re-check the
  outline order against `contracts/readme-outline.md`; fix gaps in `README.md`

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T016 Run `PIPENV_DONT_LOAD_ENV=1 pipenv run pytest -q` (expect all pass) and
  `git status --short` — the 004 change is `README.md`, `.cursor/rules/RULES.mdc`,
  `specs/004-repo-readme/`, the owner's `.gitignore` edit, and `project-docs/rfc/README.md`
  committed unchanged (FR-011; confirm `git status --short project-docs/` shows only
  `?? project-docs/rfc/README.md` and no modified file)
- [ ] T017 Manual (owner): after pushing, open `README.md` on GitHub and confirm the math blocks,
  inline math, and Mermaid diagram render (quickstart §5)

---

## Dependencies & Execution Order

- T001 → T002 → T003 … T011 → T012 (same file, in outline order).
- T013 independent of everything (different file).
- T014, T015 after T012; T016 after T013–T015; T017 after commit and push.

## Parallel Opportunities

- T013 (`RULES.mdc`) alongside any `README.md` task.
- The read-only checks in T014 and T015 can run together once writing is done.

## Implementation Strategy

1. **MVP = Setup + US1** (T001–T011): a README with intro and the full mathematics is already
   useful on the repo page.
2. **US2** (T012): add the architecture summary.
3. **US3** (T013–T015): verify facts and safety, update guidance; then T016–T017.
