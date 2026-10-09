# Implementation Plan: Repository Front-Page Document (Mathematics and Architecture)

**Branch**: `004-repo-readme` | **Date**: 2026-10-09 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-repo-readme/spec.md`

## Summary

Replace the root `README.md` (now tracked; previously git-ignored, outdated local notes) with a
public front-page document: a short introduction, a thorough mathematics walk-through of every
stored measure (stock SMAs, momentum, weekly growth, market z-score, outliers, equal-weighted
daily index series, index SMAs, uptrend share, sector z-score) with worked examples, then a brief
architecture summary with one Mermaid diagram. Formulas use GitHub math (```` ```math ```` blocks
and `` $`…`$ `` inline) with plain-language readings (research R2). All facts are taken from the
code as verified in research R4. `RULES.mdc` stops listing `README.md` as do-not-commit and gains
a keep-the-README-current rule. No code, schema, or data change.

## Technical Context

**Language/Version**: GitHub-flavored Markdown with MathJax math and Mermaid

**Primary Dependencies**: none (GitHub renders math and Mermaid natively)

**Storage**: N/A — documentation only

**Testing**: manual validation ([quickstart.md](./quickstart.md)): coverage, defaults match,
private-identifier scan, examples recomputed with repo functions, GitHub render; existing
`pytest` suite must stay green

**Target Platform**: GitHub repository page (and raw-text readers)

**Project Type**: Batch data pipeline (documentation for it)

**Performance Goals**: Architecture section readable in < 3 minutes (≈ 400 words + 1 diagram)

**Constraints**: No secrets or private identifiers (FR-007); every number equals current defaults
(FR-006); `project-docs/` frozen

**Scale/Scope**: one file (`README.md`, est. 300–450 lines), one rules-file edit

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Result |
|---|---|---|
| I. Weekly batch only | Documents the existing weekly job; no change. | Pass |
| II. Near-zero cost | No infrastructure. | Pass |
| III. Data pipeline only | A README is not a UI/API; it describes existing measures only. | Pass |
| IV. Parameterized SQL in `db/` | No SQL. | Pass (N/A) |
| V. Keyless auth, no secrets | Document contains no secrets or identifiers (FR-007, quickstart §3); removes the old README's `GCP_SA_KEY` JSON-key instructions, which contradicted V. | Pass |
| VI. Schema via migrations | No DDL. | Pass (N/A) |
| VII. Pure logic + tests | No code change; examples validated against the real functions (quickstart §4). | Pass |
| Development workflow | New documentation outside `project-docs/` (frozen, unchanged); `RULES.mdc` kept consistent. | Pass |

**Post-design re-check**: unchanged — all Pass. Complexity Tracking empty.

## Project Structure

### Documentation (this feature)

```text
specs/004-repo-readme/
├── plan.md              # This file
├── research.md          # R1–R6 (location, math notation, diagram, verified facts, examples, upkeep)
├── data-model.md        # measure catalogue (traceability for SC-001)
├── quickstart.md        # validation guide
├── contracts/
│   └── readme-outline.md   # section order and conventions
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
README.md                  # REPLACED — intro, mathematics, architecture
.cursor/rules/RULES.mdc    # drop README.md from do-not-commit; add keep-README-current rule
.gitignore                 # already edited by the owner (README.md line removed)
project-docs/rfc/README.md # committed unchanged (frozen RFC index, FR-011)
```

**Structure Decision**: Single root document; no new directories.

## Open owner decisions (outside this feature)

- `project-docs/rfc/README.md` became untracked when `.gitignore` stopped ignoring every
  `README.md`. Resolved (Clarifications 2026-10-09): commit it unchanged (FR-011).
- The old `README.md` content is untracked and will be overwritten; copy it elsewhere first if
  you want to keep it.

## Complexity Tracking

No violations.
