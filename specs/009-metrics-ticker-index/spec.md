# Feature Specification: Fast Per-Stock Lookups in the Metrics Tables

**Feature Branch**: `009-metrics-ticker-index`

**Created**: 2026-11-09

**Status**: Draft

**Input**: User description: "responses from the prod database have become slow" — investigation
2026-11-09; use the proposed fix as the spec: add a per-stock lookup path (stock symbol, then
trading date) to the US, Swedish, and UK metrics tables, shipped as a schema change and a
re-runnable upgrade step that does not block the Saturday job.

## Context *(investigation 2026-11-09, production, read-only)*

- The database itself is healthy: trivial queries answer in ~20–30 ms, no long-running or
  idle-in-transaction sessions, no lock waits, ~5 % dead rows, autovacuum / analyze current,
  total size 104 MB.
- The consumer app (`fansboda`) looks up stored metrics **by stock symbol** (one stock's history,
  a stock's latest row, the latest row for a page of stocks, the stocks of a venue that have
  metrics, a venue's 52-week SMA history). The metrics tables have no lookup path that starts with
  the stock symbol, so every one of these reads the whole table: the US table (≈259 000 rows,
  ≈46 MB of data) had been read in full 11 445 times (≈1.2 billion rows).
- Measured with a warm cache: 34–312 ms per lookup; opening a Swedish or UK stock's chart walks the
  entire US table first (~300 ms) because the app tries the US table before the others. An
  uncached stock-list page runs several such reads (~0.5–1 s of database time); after the database
  has scaled to zero, the first reads must fetch the whole table from storage again, which takes
  seconds.
- The tables have grown to the full one-year retention window, so each full read keeps getting
  more expensive until it plateaus — "has become slow" rather than "suddenly slow".

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Stock pages respond quickly again (Priority: P1)

As a user of the consumer app, when I open the stock list for a venue, page through it, sort or
filter it, or open a stock's chart, I want the page to load without a noticeable wait, so that
browsing the published data is pleasant again — including the first page view after the database
has been idle.

**Why this priority**: This is the reported problem and the whole value of the feature.

**Independent Test**: On a database that holds a full year of metrics, run the consumer app's
per-stock lookups (one stock's history, a stock's latest row, the latest row for 25 stocks, a
venue's symbols with metrics, a venue's 52-week SMA history) before and after the upgrade; after
it, none of them reads the whole table and each finishes far faster.

**Acceptance Scenarios**:

1. **Given** the upgrade is applied, **When** the app loads one stock's 52-week history or its
   latest row (US, Swedish, or UK), **Then** only that stock's rows are read, not the whole table.
2. **Given** the upgrade is applied, **When** the app looks up a Swedish or UK stock in the US
   table first (no match), **Then** the miss is answered without walking the US table.
3. **Given** the upgrade is applied, **When** the app loads the latest row for a page of stocks,
   **Then** only those stocks' rows are read.
4. **Given** the database has just resumed from scale-to-zero, **When** a stock chart is opened,
   **Then** it loads without fetching the whole metrics table from storage.

---

### User Story 2 - The upgrade is safe to apply to production (Priority: P1)

As the owner, I want to apply the change to production with the existing upgrade script, at any
time, without stopping the weekly job, blocking the consumer app, or changing any stored value,
and to be able to apply it again harmlessly.

**Why this priority**: The fix only helps once it is on production; a risky upgrade would not be
applied.

**Independent Test**: Apply the upgrade to a copy of production (Neon branch) while reads run;
reads keep working, row counts and values are unchanged, and applying it a second time does
nothing.

**Acceptance Scenarios**:

1. **Given** production with a full year of metrics, **When** the upgrade is applied, **Then** it
   finishes within a minute, reads and writes to the metrics tables keep working while it runs,
   and no row is added, removed, or changed.
2. **Given** the upgrade was already applied, **When** it is applied again (or the full upgrade
   script is re-run), **Then** it succeeds without changes.
3. **Given** a fresh database built from the base schema, **When** it is created, **Then** it
   already has the same lookup paths, without running the upgrade step.
4. **Given** the upgrade is applied, **When** the Saturday job, backfill, retention purge, and
   index computation run, **Then** they produce the same results as before, no slower.

---

### Edge Cases

- An earlier interrupted upgrade left a half-built lookup path: re-applying the upgrade must leave
  a valid, usable one (not silently keep the broken one).
- The upgrade runs while the Saturday job is writing: neither is blocked for more than a moment
  and the job's results are unchanged.
- The connection used for the upgrade goes through a transaction pooler that cannot run
  non-blocking index builds: the upgrade notes say which connection to use.
- Existing lookup paths (week + symbol uniqueness, trading date for the retention purge) are still
  needed and are kept.
- Extra storage for the new lookup paths: a few MB on a 104 MB database — within the free tier.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The US, Swedish, and UK metrics tables MUST each have a lookup path by stock symbol,
  then trading date, so that a stock's rows (all, those after a date, or the latest) are found
  without reading the whole table.
- **FR-002**: The base schema for fresh databases MUST include these lookup paths.
- **FR-003**: Existing databases MUST get them through a new, re-runnable upgrade step, recorded as
  the next step in the upgrade order and run by the existing upgrade script.
- **FR-004**: Applying the upgrade MUST NOT block reads or writes to the metrics tables for more
  than a moment, and MUST NOT change, add, or remove any stored row.
- **FR-005**: Re-applying the upgrade MUST be harmless, and MUST repair a lookup path left
  invalid by an interrupted earlier attempt.
- **FR-006**: The schema verification checks MUST confirm the lookup paths exist and are valid.
- **FR-007**: No change to stored values, published formulas, table columns, the Saturday
  schedule, or the consumer app is required by this feature.
- **FR-008**: Contributor guidance MUST record the new upgrade step; the frozen baseline documents
  are not edited.

### Key Entities

- **Per-stock lookup path**: an ordering of each metrics table by stock symbol, then trading date;
  one per country set (US, Swedish, UK). Adds no data; only speeds up finding a stock's rows.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After the upgrade, 0 of the consumer app's per-stock lookups (listed in User Story 1)
  read the whole metrics table.
- **SC-002**: Loading one stock's 52-week history or latest row takes under 10 ms of database time
  (was 34–300 ms), including a miss in the US table for a Swedish or UK stock.
- **SC-003**: The database time for an uncached stock-list page drops by at least half.
- **SC-004**: Applying the upgrade to production takes under 1 minute and changes 0 stored rows;
  re-applying it changes nothing.
- **SC-005**: The Saturday job's results are identical before and after the upgrade.

## Assumptions

- Root cause is the missing per-stock lookup path (measured 2026-11-09); app-side causes such as
  memory pressure on the production server (4 web workers, ~159 MB free) are out of scope and may
  need separate attention.
- Lookups that read most of a venue's rows anyway (e.g. a whole venue's 52-week SMA history, the
  latest row for every stock) may still read much of the table; the target is the per-stock and
  per-page lookups. Changing the consumer app's queries is out of scope (separate repository).
- The owner applies the upgrade to production (the agent has read-only access); dev first via the
  dev-backfill workflow or a Neon branch.
- The Neon project remains on the free tier; the extra few MB are within its limits.
