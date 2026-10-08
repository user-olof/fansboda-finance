# Feature Specification: Rename the Market Indices

**Feature Branch**: `003-market-index-names`

**Created**: 2026-10-08

**Status**: Draft

**Input**: User description: "Change market index names: OMX Equity Index to OMX Stockholm, US Equity Index to NYSE & Nasdaq and UK Equity Index to FTSE London"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Market indices carry exchange-based names (Priority: P1)

As the owner reading the indices, I want each country's market index to be labeled after the
exchanges it covers, so that the label says where the stocks trade:

| Index ticker | Current label | New label |
|---|---|---|
| `US-IDX` | US Equity Index | NYSE & Nasdaq |
| `SWE-IDX` | OMX Equity Index | OMX Stockholm |
| `UK-IDX` | FTSE Equity Index | FTSE London |

**Why this priority**: It is the whole feature.

**Independent Test**: Run the weekly index update (or the one-off initialization) for a country and
check that its new market rows carry the new label, while sector rows keep their sector name.

**Acceptance Scenarios**:

1. **Given** the weekly run writes a new week, **When** the market rows are stored, **Then** their
   label is "NYSE & Nasdaq", "OMX Stockholm", or "FTSE London" for US, Sweden, and UK.
2. **Given** a sector index row, **When** it is stored, **Then** its label is unchanged (the
   sector name, e.g. "Technology").
3. **Given** the one-off initialization for a country, **When** it rewrites the country's rows,
   **Then** every market row carries the new label.

---

### User Story 2 - Stored market rows are relabeled (Priority: P1)

As the owner and as the consumer (`fansboda`) reading the history, I want the market rows already
stored to carry the new label too, so that one index never shows two names over time.

**Why this priority**: The weekly run only writes new weeks; without a relabel, history would mix
old and new names until retention removes the old rows (up to a year).

**Independent Test**: After the relabel step, no stored row has an old label, and the number of
market rows, their tickers, dates, and values are unchanged.

**Acceptance Scenarios**:

1. **Given** stored market rows with the old labels, **When** the relabel step runs, **Then** all
   of them carry the new label and no other column changes.
2. **Given** the relabel step has already run, **When** it runs again, **Then** nothing changes.
3. **Given** sector rows, **When** the relabel step runs, **Then** they are not touched.

---

### Edge Cases

- A market row written by an older deployment after the relabel (for example the weekly job runs
  before the new code is deployed): running the relabel step again fixes it (idempotent).
- A consumer that identifies market rows by their label instead of the index ticker: it must
  switch to the new labels at the same time; consumers that use the ticker (`US-IDX`, `SWE-IDX`,
  `UK-IDX`) are unaffected.
- "&" in "NYSE & Nasdaq": stored and shown as is.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The market index labels MUST be "NYSE & Nasdaq" (US), "OMX Stockholm" (Sweden), and
  "FTSE London" (UK) on every market row written from now on, by the weekly run and the one-off
  initialization.
- **FR-002**: Index tickers (`US-IDX`, `SWE-IDX`, `UK-IDX`), sector index tickers and labels, and
  all index values MUST NOT change.
- **FR-003**: A one-time relabel step MUST change the label of every stored market row from the old
  to the new name, without changing any other column; it MUST be safe to run more than once and
  MUST NOT touch sector rows.
- **FR-004**: The labels on sector rows MUST stay unique within a country and MUST NOT collide with
  the new market labels.
- **FR-005**: Project guidance for contributors (the rules file) MUST show the new labels; the
  frozen baseline documents are not edited.

### Key Entities

- **Market index**: one per country (`US-IDX`, `SWE-IDX`, `UK-IDX`), stored weekly with a label;
  the label is the only thing this feature changes.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After deploy and the relabel step, 100% of stored market rows carry the new label and
  0 rows carry "US Equity Index", "OMX Equity Index", or "FTSE Equity Index".
- **SC-002**: 0 changes to index values, tickers, dates, or sector rows (row counts and values
  identical before and after).
- **SC-003**: Every market row written by the next weekly run carries the new label.

## Assumptions

- "UK Equity Index" in the request refers to the UK market index `UK-IDX`, currently labeled
  "FTSE Equity Index".
- Consumers (`fansboda`) identify the market index by its ticker; a consumer that matches on the
  label is updated by its owner together with this change.
- The relabel step is part of the deploy, run once by the owner like a migration step; it is a
  data change only (no table or column change).
- Historic references to the old names in frozen documents (`project-docs/`) and in earlier feature
  specs stay as they are.
- No new infrastructure or cost (constitution I, II).
