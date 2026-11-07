# Feature Specification: Weekly Fetch for a Missed Trading Date

**Feature Branch**: `008-fetch-trading-date`

**Created**: 2026-11-07

**Status**: Draft

**Input**: User description: "change fetch_sma so that it accepts an optional --trading_date flag. I want to run the script for dates that have been missed"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Fill a missed week by running the weekly job for a past date (Priority: P1)

As the owner, when the Saturday job did not run (e.g. the server was down for two weekends), I
want to run the weekly job manually for a given past date, so that the missed week gets the same
stock rows, market statistics, and index rows it would have had if the job had run then — without
re-downloading two years of history or touching other weeks.

**Why this priority**: This is the whole feature; missed weeks otherwise stay empty in the
published series (stock rows, market statistics, indices) that the consumer app reads.

**Independent Test**: With a week missing for some stocks, run the weekly job with that week's
Friday as the date; the week now holds one row per stock (the stock's last trading day on or
before that date), the market statistics and index rows for that week exist, and no other week
changed.

**Acceptance Scenarios**:

1. **Given** no stored rows for the week of 2026-10-19, **When** the owner runs the job with date
   2026-10-23 (a Friday), **Then** every stock with enough history gets a row for that week dated
   its last trading day on or before 2026-10-23, with the same values (price, SMA-50, SMA-200,
   momentum, weekly growth) a Saturday run on 2026-10-24 would have stored.
2. **Given** the same run, **When** it finishes, **Then** that week's market statistics, stock
   z-scores, and market and sector index rows exist, computed as by the weekly run.
3. **Given** a date that falls on a weekend or a market holiday, **When** the job runs, **Then**
   each stock uses its last trading day on or before that date.
4. **Given** the job was already run for that date, **When** it is run again, **Then** stocks that
   already hold that bar are skipped and nothing is duplicated (idempotent).
5. **Given** two missed weeks, **When** the owner runs the job once per date, **Then** both weeks
   are filled.
6. **Given** no date, **When** the job runs (the Saturday schedule), **Then** it behaves exactly as
   today.

---

### User Story 2 - Unsafe dates are refused (Priority: P2)

As the owner, I want a date that cannot be filled correctly to stop the run before anything is
downloaded or written, so that a typo cannot create rows that are wrong or immediately deleted.

**Why this priority**: Protects production data from a mistyped argument; secondary to the main
capability.

**Independent Test**: Run with a future date, a date older than the retention window, and a
malformed value; each run stops with a clear error and writes nothing.

**Acceptance Scenarios**:

1. **Given** a date after today, **When** the job starts, **Then** it stops with an error naming
   the date and writes nothing.
2. **Given** a date older than the retention window (default 365 days), **When** the job starts,
   **Then** it stops with an error (rows that old would be deleted by the same run's retention
   purge).
3. **Given** a value that is not a date in `YYYY-MM-DD` form, **When** the job starts, **Then** it
   stops with a usage error.

---

### Edge Cases

- A stock that already holds a later bar in that week (e.g. the date is a Wednesday and Friday's
  bar is stored): its stored row is kept; a week's row is only ever replaced by a newer bar.
- A stock with no trading day in that week (halted, not yet listed): it gets no row for that week,
  as in the Saturday run.
- A stock with fewer than 200 trading days up to the date: no row, as in the Saturday run.
- Later weeks are already stored (the job ran again after the outage): they are not changed; the
  filled week's index rows continue from the latest stored index row before that week.
- Indices that have no stored row before the date (the week precedes the index start date): no
  index row is written for that week.
- Download failures for some batches: logged and the run continues, as today; re-running the same
  date fills the rest.
- The outlier email for a filled week: sent as the Saturday run would have, for outliers newly
  detected in that week (not an outlier the week before); filling several weeks may send several
  emails.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The weekly job MUST accept an optional date (`--trading_date YYYY-MM-DD`); without it,
  behaviour is unchanged.
- **FR-002**: With a date, the job MUST act as if it ran on that date: the target week is the
  calendar week containing the date, and each stock's row uses its last trading day on or before
  the date, with no price data after the date used for any value.
- **FR-003**: With a date, the stored values for that week (stock rows including weekly growth,
  market statistics, stock z-scores, market and sector index rows, and the momentum band for index
  membership) and the outlier email for that week MUST follow the same definitions as the Saturday
  run.
- **FR-004**: The freshness check MUST use the target week: a stock already holding its last bar on
  or before the date for that week is skipped.
- **FR-005**: Rows of other weeks MUST NOT be changed, except by the run's normal retention purge.
- **FR-006**: A date in the future, older than the retention window, or not a valid `YYYY-MM-DD`
  date MUST stop the run with a clear error before any download or write.
- **FR-007**: The run log MUST state the date the run acts as of.
- **FR-008**: Contributor guidance MUST describe the option; the frozen baseline documents are not
  edited.
- **FR-009**: No change to the Saturday schedule, the database structure, or published formulas.

### Key Entities

- **Run date**: the date the weekly job acts as of — today by default, or the given past date;
  determines the target week and the last price data used.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After one run per missed date, 100 % of stocks that had a trading day and enough
  history in each missed week have a row for that week.
- **SC-002**: Values stored for a filled week equal those a Saturday run at the time would have
  stored (same price data), for every stock and index.
- **SC-003**: Re-running the same date adds 0 rows and changes 0 values.
- **SC-004**: 0 rows outside the target week change (apart from the normal retention purge).
- **SC-005**: A future, too-old, or malformed date writes 0 rows.

## Assumptions

- The owner runs it manually on the production server, as the job's service user, one date per
  run; filling several weeks means several runs.
- Any calendar date is accepted; a weekend or holiday maps to the last trading day before it.
- The retention window is the existing metrics retention setting (default 365 days).
- Price data from the provider for past dates is the same adjusted series the weekly run uses; a
  later split or dividend adjustment may make values differ slightly from what a run at the time
  would have seen (accepted, as for the backfill).
- New sector indices may still be started by the run as today.
- Index rows for later weeks already stored are not rebuilt; a full rebuild remains the one-off
  index initialization.
- Clarified 2026-11-07 ("no changes to technical requirements"): a run for a past date behaves
  exactly like the Saturday run, including the outlier email for that week.
