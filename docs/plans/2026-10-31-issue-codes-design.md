# Issue codes, ignore lists and thresholds

Extends `rbx issues` (see `2026-08-31-issues-view-design.md` and
`2026-08-31-config-issues-design.md`).

## Goals

1. Every issue kind has a stable, user-facing **code**.
2. A problem (or a whole contest) can stop reporting chosen codes.
3. Two new warnings: the built testset is too large (default 20 MiB), and an
   accepted solution spends too much total CPU time over the testset (default
   60 s).
4. Thresholds are configurable.
5. One docs page documents every code, how to tune it and how to ignore it, and
   the console links to it under every issue list.

## Decisions

**Codes are readable kebab-case slugs**, not opaque `R004`-style codes:
`no-validator`, `noisy-stderr`, `slow-accepted-solution`. They read on their own
in a YAML file. The existing `kind` discriminator was already published in
`--format json`, so it stays; `schema.KIND_TO_CODE` maps it to the code and a
test holds the mapping bijective against `IssueCode`. The code is a computed
field, so it lands in JSON too.

`IssueCode` and the config models live in the leaf module
`rbx/box/issue_codes.py`, because `schema.py`, `contest/schema.py` and
`environment.py` all need them and `rbx.box.issues` imports a package loader --
putting them there would close an import cycle.

**Ignore lists live in `problem.rbx.yml` and `contest.rbx.yml`** under
`issues.ignore`, typed as `List[IssueCode]` so the JSON schema autocompletes
them and a typo is a validation error. The effective list is the contest's
plus the problem's (`settings.merge_ignored`). Outside a `rbx contest` command
the enclosing contest is read through
`contest_package.find_contest_without_validation`, which skips loading every
other problem.

Ignoring happens once, in `build_report`, after every detector ran -- detectors
stay pure and unaware of it. Ignored issues move to `IssueReport.ignored`
(additive, no format bump), are excluded from `errors()`/`warnings()`, are
counted in a footer, and are listed by `rbx issues --all`. `rbx summary`
filters its config findings the same way.

**Thresholds live only in `env.rbx.yml`** under `issues.thresholds`
(`testsetSizeMb`, `acceptedTotalTimeSeconds`, `stderrSizeMb`, the last
replacing the hard-coded 1 MiB). They describe the judge, and the environment
comes from the preset, which every problem of a contest shares. A problem that
legitimately exceeds one ignores the code instead. Plain numbers with the unit
in the name, matching `timeLimit`/`memoryLimit`. Detectors receive them on
`RunState`/`ConfigState`, never read the environment.

**`large-testset`** (package family) sums every built `.in` plus its `.ans`,
since both ship to the judge. It is silent when nothing is built.

**`slow-accepted-solution`** (run family) needs totals the run report did not
have, so `RunSolutionReport` gains `totalTime` (sum of per-test CPU time) and
`complete` (every skeleton entry evaluated, none `SKIPPED`), both additive. It
fires only for solutions declared `accepted`, only on complete runs, and never
on sanitized runs (`SkeletonView.sanitized`).

**Console**: each line ends with `(code)`; ignored ones shown with `--all` read
`(ignored code)`. A single line pointing at `https://rbx.rsalesc.dev/issues/`
follows every non-empty list (once per contest view).

## Docs

`docs/issues.md`, published at `/issues/` and listed under Reference. One
section per code with an explicit `{: #code }` anchor;
`issue_codes_test.py` fails if a code has no section.
