# Feature Specification: Market Index Z-Score Set to 0

**Feature Branch**: `005-market-index-zero-z`

**Created**: 2026-10-09

**Status**: Draft

**Input**: User description: "set the z-values for market indices to 0 in the database"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - New market index rows carry z-score 0 (Priority: P1)

As a consumer of the indices (`fansboda` colours each index row by its z-score), I want every
market index row (`US-IDX`, `SWE-IDX`, `UK-IDX`) to carry a z-score of 0 instead of an empty
value, so that the market row is shown as neutral — the market is the reference its sectors are
compared against — rather than as "no data".

**Why this priority**: Without it, every weekly run keeps writing empty values.

**Independent Test**: Run the weekly index update (or the one-off initialization) for a country;
every newly written market row has z-score exactly 0, and sector rows keep their computed
z-scores.

**Acceptance Scenarios**:

1. **Given** the weekly run writes a week, **When** the market rows are stored, **Then** their
   z-score is 0.
2. **Given** the one-off initialization rewrites a country, **When** it finishes, **Then** every
   market row of that country has z-score 0.
3. **Given** sector rows in the same week, **When** they are stored, **Then** their z-scores are
   computed exactly as before (sector momentum vs the country's sectors), including staying
   empty with fewer than two sectors or zero spread.
4. **Given** a new sector index starts, **When** its rows are written and the week's z-scores
   are recomputed, **Then** the market row of those weeks still has z-score 0.

---

### User Story 2 - Stored market index rows are set to 0 (Priority: P1)

As the owner and as the consumer reading the history, I want the market rows already stored to
have z-score 0 as well, so that history and new weeks look the same.

**Why this priority**: The weekly run only rewrites recent weeks; without a one-time update the
history keeps empty values for up to a year.

**Independent Test**: After the one-time step, no market row has an empty or non-zero z-score;
row counts, tickers, dates, all other columns, and every sector row are unchanged.

**Acceptance Scenarios**:

1. **Given** stored market rows with an empty z-score, **When** the one-time step runs, **Then**
   all of them have z-score 0 and no other column changes.
2. **Given** the step has already run, **When** it runs again, **Then** nothing changes.
3. **Given** sector rows (including ones with an empty z-score), **When** the step runs, **Then**
   they are not touched.

---

### Edge Cases

- A market row written by an older deployment after the one-time step (the weekly job runs before
  the new code is deployed): running the step again fixes it.
- A country with no or a single sector index: the market row still gets 0; sector z-scores stay
  empty as today.
- The market rows' 0 must not enter the sector z-score calculation (the mean and spread are over
  sector rows only).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Every market index row written from now on (weekly run, new-sector start, one-off
  initialization) MUST have z-score exactly 0.
- **FR-002**: Sector index z-scores MUST be computed as before, over sector rows only; market rows
  MUST NOT be included in that calculation.
- **FR-003**: A one-time step MUST set the z-score of every stored market index row to 0 without
  changing any other column or any sector row; it MUST be safe to run more than once.
- **FR-004**: No change to stock z-scores, market statistics, index values, tickers, or labels.
- **FR-005**: The public front-page document and the contributor guidance MUST describe market
  index z-score as 0 (defined, by convention: the market is the reference level for its sectors);
  the frozen baseline documents are not edited.

### Key Entities

- **Market index row**: one per country and week (`US-IDX`, `SWE-IDX`, `UK-IDX`); its z-score
  changes from empty to 0.
- **Sector index row**: unchanged; its z-score compares sector momentum within the country.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After deploy and the one-time step, 100 % of stored market index rows have z-score
  0 and 0 have an empty z-score.
- **SC-002**: 0 changes to sector rows and to any other column (row counts and values identical
  before and after, apart from the market rows' z-score).
- **SC-003**: Every market index row written by the next weekly run has z-score 0.

## Assumptions

- "Market indices" means the three country market indices (`US-IDX`, `SWE-IDX`, `UK-IDX`), not
  the sector indices and not stock z-scores.
- Both new writes and the stored history are in scope ("in the database"); changing only the
  stored rows would be undone by the next weekly run.
- 0 is a display convention (the market is the neutral reference), not a computed standardized
  value; consumers that colour by z-score show the market as neutral.
- The one-time step is run by the owner like a migration step, after deploying the new code; it
  is a data change only (no table or column change).
- No new infrastructure or cost (constitution I, II).
