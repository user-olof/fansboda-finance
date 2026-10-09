# Feature Specification: Repository Front-Page Document (Mathematics and Architecture)

**Feature Branch**: `004-repo-readme`

**Created**: 2026-10-09

**Status**: Draft

**Input**: User description: "write a specification of the app that can be added to the github repo page for user information. First, add a thorough walk-through of the mathematics and then a give a brief summary of the architecture"

## Clarifications

### Session 2026-10-09

- Q: What should happen to `project-docs/rfc/README.md` as part of 004? → A: Commit it unchanged
  as part of the frozen baseline; no edits.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Understand every published number (Priority: P1)

As a reader of the published data (the owner, a `fansboda` user, or a visitor to the repository
page), I want a walk-through of the mathematics behind every value the pipeline stores, so that I
can interpret a stock's or an index's numbers correctly and reproduce them by hand.

**Why this priority**: The mathematics is the substance of the app; the user asked for it first
and for it to be thorough.

**Independent Test**: A reader with only the document and a short price history for one stock can
compute that week's SMA-50, SMA-200, momentum, and weekly growth and match the stored values;
given a set of stocks' momenta, they can compute a z-score; given a small index example, they can
follow the index level from 100 forward.

**Acceptance Scenarios**:

1. **Given** the repository front page, **When** a reader opens it, **Then** the mathematics
   section is the first main section after a short introduction.
2. **Given** any stored stock value (current price, SMA-50, SMA-200, momentum, z-score, price /
   SMA-50 / SMA-200 weekly growth), **When** the reader looks it up, **Then** the document gives its
   definition as a formula, the meaning of each symbol, its unit or range, and when it is empty.
3. **Given** any stored index value (level, SMA-50, SMA-200, momentum, share of members in
   uptrend, member count, sector z-score), **When** the reader looks it up, **Then** the document
   explains how it is derived from the members' daily prices, including the starting level of 100,
   equal weighting, and dropped outlier days.
4. **Given** a formula, **When** the reader wants to check their understanding, **Then** a small
   worked numeric example is available for the stock measures, the z-score, and the index level.

---

### User Story 2 - Know how the system fits together (Priority: P2)

As a reader, I want a brief summary of the architecture, so that I know where the data comes
from, when it is refreshed, where it is stored, and which parts do what.

**Why this priority**: Context for the numbers; the user asked for it to be brief and after the
mathematics.

**Independent Test**: After reading only the architecture section, a reader can answer: data
source, refresh schedule, storage, the three country sets, which job writes what, how long data
is kept, and what the outlier email is.

**Acceptance Scenarios**:

1. **Given** the document, **When** the reader reaches the architecture section, **Then** it comes
   after the mathematics and fits on about one screen, with at most one simple diagram.
2. **Given** the architecture section, **When** read, **Then** it names the weekly schedule
   (Saturdays), the data source, the database, the country sets (US, Sweden, UK) and their market
   index names, the main jobs, the 365-day retention, and the data-quality email.

---

### User Story 3 - Trust that the document is current and safe to publish (Priority: P3)

As the owner, I want the document to match the system as built and contain nothing private, so
that it can be shown publicly on the repository page.

**Why this priority**: A wrong or leaky front page is worse than none.

**Independent Test**: Review the document against the current code and configuration defaults;
search it for credentials, hostnames, e-mail addresses, and project identifiers.

**Acceptance Scenarios**:

1. **Given** the document, **When** compared with the current behavior, **Then** every formula,
   window length, threshold, and default (e.g. 50 / 200 days, ×10 / −99.9 % outlier bounds, start
   date, 5-member minimum, 365-day retention) matches.
2. **Given** the document, **When** searched, **Then** it contains no secrets, connection strings,
   e-mail addresses, VM or cloud project names, or other private identifiers.
3. **Given** the previous root `README.md` (outdated local notes: daily schedule, JSON-key
   deploy, VM name and zone), **When** the document is published, **Then** it replaces that
   content entirely and none of the outdated or private details remain.

---

### Edge Cases

- Empty values: the document states when each measure is empty (fewer than 200 closes, SMA-200 of
  zero, no previous-week bar, fewer than two sectors with momentum, zero spread).
- Stock splits and dividends: the document explains that growth compares both weeks from one
  adjusted price history, and that stored rows from different weeks may sit on different bases.
- Indices that start later than the common start date (too few members with a price on it).
- Mathematical notation must render on the repository page; formulas must also stay readable as
  plain text where rendering fails.
- A future change to any formula must update the document (otherwise User Story 3 fails).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The repository front page MUST show a user-facing document with, in order: a short
  introduction (what the app produces and for whom), the mathematics walk-through, and a brief
  architecture summary.
- **FR-002**: The mathematics section MUST define, with formulas and symbol explanations:
  - the trading-day close series and the weekly snapshot (last trading day of each calendar week,
    one row per stock per week, a later bar in the same week replaces the row);
  - SMA-50 and SMA-200 (arithmetic mean of the last 50 / 200 daily closes; at least 200 closes
    needed);
  - momentum (SMA-50 ÷ SMA-200), with its interpretation (> 1 short-term trend above long-term);
  - weekly growth of price, SMA-50, and SMA-200 versus the previous calendar week's last bar,
    computed within one adjusted price history;
  - the stock z-score: momentum standardized against all stocks of the same market that week
    (mean and population standard deviation), and when it is empty;
  - the outlier rule (any weekly growth above +900 % (×10) or below −99.9 %) and what happens to
    outliers (reported by email, left out of index daily returns).
- **FR-003**: The mathematics section MUST explain the equal-weighted indices:
  - one market index per country and one per sector, with their naming;
  - daily return of each member, equal-weighted average return per day, outlier daily returns
    dropped;
  - the daily index level as a chained product of (1 + average return), set to 100 on the start
    date, and continued each week from the latest stored level;
  - the start-date rule (common start date if at least 5 members have a price on it, otherwise the
    last trading day of the first later week that has);
  - index SMA-50 / SMA-200 as means of the last 50 / 200 daily index levels, index momentum, the
    weekly index row (level on the week's last trading day);
  - member count and share of members in uptrend (SMA-50 above SMA-200) for the week;
  - the sector z-score (sector momentum vs the country's sector indices that week, population
    standard deviation; empty on market rows and with fewer than two sectors).
- **FR-004**: The mathematics section MUST include worked numeric examples for at least: SMA and
  momentum of one stock, a z-score across a few stocks, and three days of an index level from 100.
- **FR-005**: The architecture section MUST be brief (about one screen) and cover data source,
  weekly schedule, storage, the three country sets and their tables in plain terms, the jobs and
  one-off tools at a high level, retention, the outlier email, and the consumer (`fansboda`); it
  MAY include one simple flow diagram.
- **FR-006**: All numbers in the document (windows, thresholds, defaults) MUST match the current
  configuration defaults and behavior, including the market index names from
  specs/003-market-index-names (NYSE & Nasdaq, OMX Stockholm, FTSE London).
- **FR-007**: The document MUST NOT contain secrets, connection strings, e-mail addresses, cloud
  project / VM / service-account names, or other private identifiers.
- **FR-008**: The document MUST be the repository's root `README.md` (no longer git-ignored),
  replacing its previous content; contributor guidance MUST stop listing `README.md` as a
  do-not-commit local file.
- **FR-011**: `project-docs/rfc/README.md` (RFC index, un-ignored together with `README.md`) MUST
  be committed unchanged; it is part of the frozen baseline and is not edited.
- **FR-009**: The document MUST state that it describes behavior, not investment advice, and that
  the app has no UI or API (consumers read the database).
- **FR-010**: Project guidance for contributors MUST say that a change to any published formula,
  window, threshold, or index name also updates this document; the frozen baseline documents are
  not edited.

### Key Entities

- **Front-page document**: the user-facing description shown on the repository page; sections:
  introduction, mathematics, architecture.
- **Stock measure**: a per-stock, per-week value (price, SMAs, momentum, growth, z-score).
- **Index measure**: a per-index, per-week value (level, SMAs, momentum, member count, share in
  uptrend, sector z-score).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100 % of the values stored for stocks and indices are defined in the document (each
  stored measure maps to a definition).
- **SC-002**: A reader can reproduce the worked examples' results by hand to the shown precision,
  and the stock example matches the definitions exactly.
- **SC-003**: The architecture section can be read in under 3 minutes (≈ 400 words or fewer, plus
  at most one diagram).
- **SC-004**: 0 private identifiers or secrets found when the document is reviewed before
  publishing.
- **SC-005**: 0 mismatches between the document's numbers and the current defaults at publication.

## Assumptions

- "Repo page" means the GitHub repository front page; the document is the root `README.md`. The
  owner removed `README.md` from `.gitignore` (2026-10-09), and the previous local notes are
  replaced (they described the obsolete daily job and key-based deploy).
- Audience: the owner, `fansboda` users, and technically curious visitors; English; mathematics
  written in standard notation that renders on GitHub, with plain-text fallbacks.
- The document describes the system as built through specs 001–003; the frozen `project-docs/`
  stay unchanged and are not linked as the primary reference.
- No code, data, or schema change; no new infrastructure or cost (constitution I–III).
- Whether the repository is public is the owner's choice; FR-007 keeps the document safe either
  way.
