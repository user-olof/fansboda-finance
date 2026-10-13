# Feature Specification: Ticker Seed Validation

**Feature Branch**: `006-ticker-seed-validation`

**Created**: 2026-10-12

**Status**: Draft

**Input**: User description: "when seeding tickers there need to be a check that the tickers has the following data: symbol, company name, sector, industry, market, exchange. If symbol, company name, sector or industry is missing the ticker should be discarded. If market or exchange is missing there should be a warning logged"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Incomplete tickers are not stored (Priority: P1)

As the owner seeding the watchlist from a symbol file, I want a ticker that lacks a symbol,
company name, sector, or industry to be left out of the tickers tables, so that every stored
ticker can be named, placed in a sector index, and grouped by industry, and the weekly job does
not spend downloads on symbols that cannot be described (funds, delisted or mistyped symbols).

**Why this priority**: Today a ticker whose lookup returns nothing (or fails) is still stored
with empty fields; those rows end up in the market index only, with no name, and are hard to
spot afterwards.

**Independent Test**: Seed a file containing one complete symbol and symbols that each lack one
required field; only the complete symbol is stored, and each discarded symbol is named in the
log with the missing field(s).

**Acceptance Scenarios**:

1. **Given** a symbol whose lookup returns company name, sector, and industry, **When** seeding
   runs, **Then** the ticker is stored as today.
2. **Given** a symbol whose lookup has no company name, no sector, or no industry, **When**
   seeding runs, **Then** the ticker is not stored and the log names the symbol and every
   missing required field.
3. **Given** a symbol whose lookup fails entirely, **When** seeding runs, **Then** the ticker is
   not stored (instead of being stored with empty fields) and the failure is logged.
4. **Given** a discarded symbol that is already stored from an earlier run, **When** seeding
   runs, **Then** its stored row and its history are left untouched (not overwritten with empty
   values, not deleted).
5. **Given** a run with discarded symbols, **When** it finishes, **Then** the summary reports how
   many tickers were stored and how many were discarded, and the run still succeeds.

---

### User Story 2 - Missing market or exchange is flagged (Priority: P2)

As the owner, I want a warning in the log when a ticker's lookup has no market or no exchange,
so that I can review those tickers, while the ticker is still stored because it is usable
without them.

**Why this priority**: Market drives the stock z-score grouping and exchange is informational;
a missing value is worth knowing about but not worth losing the ticker.

**Independent Test**: Seed a symbol whose lookup has company name, sector, and industry but no
market and/or no exchange; the ticker is stored and a warning names the symbol and the missing
field(s).

**Acceptance Scenarios**:

1. **Given** a complete symbol except for market, **When** seeding runs, **Then** the ticker is
   stored with the market inferred from the symbol (as today) and a warning names the symbol and
   "market".
2. **Given** a complete symbol except for exchange, **When** seeding runs, **Then** the ticker is
   stored with an empty exchange and a warning names the symbol and "exchange".
3. **Given** a symbol missing both a required field and market/exchange, **When** seeding runs,
   **Then** it is discarded (User Story 1) and the log names all missing fields.
4. **Given** a run with warnings, **When** it finishes, **Then** the summary reports how many
   stored tickers had warnings.

---

### Edge Cases

- A field holding only whitespace counts as missing.
- A blank or comment line in the symbol file is not a ticker and is skipped as today, not
  reported as discarded.
- Every symbol is discarded: nothing is written, the summary says 0 stored, and the run still
  completes without error.
- The metadata refresh (which re-resolves stored tickers through the same seeding path) applies
  the same rules: a stored ticker whose fresh lookup lacks a required field keeps its stored row
  unchanged and is logged as discarded.
- `--country` filtering happens before the check; symbols outside the chosen country are neither
  stored nor reported as discarded.
- The one-off business summary update does not insert tickers and is not affected.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Before storing, seeding MUST check each resolved ticker for symbol, company name,
  sector, industry, market, and exchange; a value that is absent, empty, or whitespace-only
  counts as missing.
- **FR-002**: A ticker missing symbol, company name, sector, or industry MUST NOT be stored or
  updated; the log MUST record it at warning level with the symbol and every missing field.
- **FR-003**: A ticker whose metadata lookup fails MUST be discarded under FR-002 instead of
  being stored with empty fields.
- **FR-004**: A ticker with all required fields but missing market or exchange MUST be stored and
  the log MUST record a warning with the symbol and the missing field(s). "Market missing" means
  the data source did not provide one; the stored market keeps falling back to the value inferred
  from the symbol so country routing and z-score grouping keep working.
- **FR-005**: Discarding MUST NOT delete or modify a ticker already stored, nor its metrics.
- **FR-006**: At the end of a run, seeding MUST log the number of tickers stored, discarded, and
  stored with warnings; discards alone MUST NOT make the run fail.
- **FR-007**: The same rules MUST apply to every path that stores tickers through seeding,
  including the metadata refresh.
- **FR-008**: No change to the tickers tables' structure, the weekly job, metrics, indices, or the
  business summary update.

### Key Entities

- **Ticker**: a watchlist entry with symbol, company name, sector, industry, market, exchange
  (and business summary, which is not checked). Required: symbol, company name, sector, industry.
  Warn-only: market, exchange.
- **Seed run summary**: counts of stored, discarded, and warned tickers for one run.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After a seed run, 0 tickers written by that run lack a company name, sector, or
  industry.
- **SC-002**: 100 % of discarded tickers appear in the log with the symbol and the missing
  field(s), and the run summary's discarded count equals the number of such log entries.
- **SC-003**: 100 % of stored tickers without a provided market or exchange appear in a warning.
- **SC-004**: 0 previously stored tickers are deleted or blanked by a run in which they are
  discarded.

## Assumptions

- "Market" is the listing market from the data source (`us_market`, `se_market`, `gb_market`)
  and "exchange" is the exchange name; "company name" is the long name, falling back to the short
  name, as today.
- Discarded means "not written by this run"; cleaning up incomplete rows already stored is out of
  scope (the owner can re-seed or remove them by hand).
- The metadata refresh is in scope because it stores tickers through the same seeding step; a
  fresh lookup that lost a field should not blank a good stored row.
- Warnings go to the existing run log; no email or other alerting is added (constitution scope).
- No schema change, migration, new infrastructure, or cost (constitution I, II).
