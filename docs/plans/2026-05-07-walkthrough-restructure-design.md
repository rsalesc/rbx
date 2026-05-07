# Walkthrough section restructure — design

**Status:** approved 2026-05-07. Restructure landed in `mkdocs.yml`; new walkthrough authoring tracked in linked issues.

## Goal

Reshape the **Walkthrough** section of the docs so it serves two distinct reader roles end-to-end, instead of being a flat pair of pages. The Feature Guide continues to act as the instructional reference — Walkthrough is reserved for narrative, end-to-end stories.

## Audiences

1. **Setters** — authoring an individual problem. Care about correctness of one problem: tests, solutions, statement.
2. **Chief setters** — preparing the whole contest. Care about profiling, packaging, statements infrastructure, and shipping to a judge.

Recipe-style "how do I do X" content is explicitly *not* a walkthrough — it lives in the Feature Guide.

## Section structure

Two role-named tracks under **Walkthrough**, each linear with "Step N of M" framing:

```
Walkthrough
├── Authoring a problem
│   ├── 1. First steps                          (existing)
│   ├── 2. Adding a custom checker              (issue)
│   └── 3. Stress-testing your solutions        (issue)
└── Delivering a contest
    ├── 1. Scaffolding a contest                (issue — covers create + adding/importing problems)
    ├── 2. Profiling time limits                (issue — extracted from current packaging walkthrough)
    ├── 3. Building contest statements          (issue)
    ├── 4. Packaging a problem                  (existing — to be refactored)
    └── 5. Packaging & uploading a full contest (issue)
```

Naming chosen for newcomer scannability: "Authoring a problem" / "Delivering a contest" describe the activity. The role vocabulary (*setter*, *chief setter*) is preserved in subtitles on the track index pages.

Packaging — both problem-level and contest-level — sits entirely in the chief-setter track. In a real contest the chief setter typically packages problems written by other setters, so this matches the workflow.

## What landed in this session

- `mkdocs.yml` nav updated to express the two-track grouping. File paths unchanged so existing URLs remain stable.
- This design doc.
- GitHub issues for every new walkthrough and every CLI affordance discovered during the brainstorm.

No new walkthrough content is written in this session. Placeholder pages were rejected — they tend to rot; tracking issues do not.

## Out of scope

- Polishing existing `first-steps.md` (typos, dead links, prereq callout) — covered by issue #435 only; not a new walkthrough.
- A standalone "writing a problem statement from scratch" walkthrough — overlaps the rbxTeX feature-guide page; revisit only if a `--minimal` statement scaffold lands.
- A Polygon API upload walkthrough — feature-guide reference is sufficient for current audience.

## Linked issues

Polish to existing walkthroughs:

- #435 — `first-steps.md` prerequisites callout (env / toolchain).

Authoring track:

- #443 — Adding a custom checker walkthrough (step 2).
- #437 — Stress-testing narrative walkthrough (step 3).
- #442 — CLI affordance: promote a stress counterexample to a manual test.

Delivering track:

- #440 — Scaffolding a contest walkthrough (step 1, merges create + add/import).
- #439 — Profiling time limits across a contest walkthrough (step 2).
- #438 — Building contest statements walkthrough (step 3).
- #436 — Refactor `packaging-walkthrough.md` to fit step 4.
- #441 — Packaging & uploading a full contest walkthrough (step 5).
