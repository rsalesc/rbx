# "Profiling time limits" walkthrough — design

**Status:** approved 2026-08-24. Implements [#439], step 2 of the **Delivering a contest**
track defined in [`2026-05-07-walkthrough-restructure-design.md`](2026-05-07-walkthrough-restructure-design.md).

## Goal

Give the chief setter the contest-wide story of arriving at time limits the judge will
actually enforce: profile one problem to understand the numbers, then sweep the whole
contest, verify under the result, and commit it.

## Why the issue needs re-reading

[#439] was filed on 2026-05-07. Since then [#722] restructured Profiling into a six-page
feature guide (`index`, `profiles`, `estimating`, `computing`, `language-groups`,
`remote`), which now teaches four of the issue's five scope bullets in depth: the
interactive flow, the strategies, the default formula, and `modifiers` / language groups.

What no page covers is the contest scale. `rbx each time` appears nowhere in the profiling
guide. That gap — profiling *across* a contest, on the judge's hardware, and persisting the
result — is this page's territory. The single-problem material is narrated only as far as
the page needs to stand on its own, and links out for the rest.

## Register and placement

- File: `docs/setters/contest-profiling-walkthrough.md`.
- Nav: **Walkthrough → Delivering a contest → Profiling time limits**, between
  `contest-scaffolding-walkthrough.md` and `packaging-walkthrough.md`.
- Walkthrough register per [`docs-writing-style-guide.md`](docs-writing-style-guide.md):
  prerequisite note, running story, `!!! info` admonitions pointing at the feature guide
  rather than restating it, closing "Next steps" grid cards.
- No literal "Step 2 of 5" heading. The landed walkthroughs don't use them; continuity is
  carried by the prerequisite note and the closing cards.

## Continuity

The page continues the contest [Scaffolding a contest](/setters/contest-scaffolding-walkthrough)
builds: `summer-cup`, with `A = problems/chocolate`, `B = problems/gardens`, and
`C = problems/sum-of-n` adopted from [First steps](/setters/first-steps).

The hook is the summary table that page ends on. `rbx contest summary` printed a time limit
for every problem; those numbers came from each author's `problem.rbx.yml`, measured on each
author's laptop. This page replaces all of them with numbers measured for the judge.

## Outline

1. **Opening + prerequisite note.** Continues `summer-cup`; hooks off the summary table.
2. **One limit per judge, not one per problem.** What a profile is, why `.limits/` sits
   beside `problem.rbx.yml`, and that the name `boca` is chosen by the packager rather than
   by you — a forward link to step 4 that does not depend on it. `!!! info` →
   [Limits profiles](/setters/profiling/profiles).
3. **Profiling one problem.** `cd problems/gardens && rbx time -p boca`, narrated: the
   build, the accepted solutions' timings, the language-group screen, the limit it lands on,
   the upper-bound check against the too-slow solution. Prose only — the strategy table and
   the ratio arithmetic stay behind links to `estimating.md` and `computing.md`. **Cast 1.**
4. **Reading the profile you got.** `cat .limits/boca.yml`: what to eyeball (`timeLimit`,
   `modifiers`), what is written *for* you and should not be hand-maintained (the provenance
   record), and when overriding by hand is legitimate.
5. **The rest of the contest.** `rbx each time -p boca --auto` from the contest root. The
   narrative beat is the switch: interactive once to understand the numbers, unattended
   across the whole set. Covers what `--auto` gives up, `rbx on A,C time -p boca` for
   redoing a subset, and `-k`. States that there is no contest-level profile — every problem
   gets its own `.limits/boca.yml`. **Cast 2.**
6. **Verify under the limits you just wrote.** `rbx each -p boca run`; what a newly-failing
   accepted solution means, and the two ways out (re-profile, or raise that language's
   modifier).
7. **Make it stick.** Commit `.limits/`. The default preset's problem `.gitignore` ignores
   `.limits/local.yml` *only*, so `boca.yml` is tracked the moment it is written and `local`
   — the laptop throwaway — deliberately is not. Then the hardware point: profile on the
   judging machine if you can, your laptop is fine if you can't, with an `!!! info` →
   [On the judge itself](/setters/profiling/remote) for measuring on the park without leaving
   your desk.
8. **Next steps.** Grid cards → Packaging a problem, → the Profiling guide, → Contest
   statements.

`--runner` is deliberately kept out of the spine. It is MOJ-only and needs judge access; a
single admonition in section 7 is the whole of its presence here.

## Casts and fixture

Two casts. Both need a contest fixture that does not exist yet: the default preset's
scaffolded problems time at ~0 ms and ship no too-slow solution, so filming `rbx time`
against a freshly created `summer-cup` would show an empty table.

New `casts/fixtures/summer-cup/`, a real contest whose problem names match what step 1
established:

| Problem | Folder | Shape |
| :-- | :-- | :-- |
| `A` | `problems/chocolate` | C++ only, fast. The problem with nothing to say. |
| `B` | `problems/gardens` | C++ accepted, Python accepted, quadratic `tle`. Lifted from `timing-problem`. The one section 3 profiles. |
| `C` | `problems/sum-of-n` | Mirrors First steps. |

`gardens` carries the timing shape worth showing: a second accepted solution in another
language is what gives the language-group screen something to say, and the `tle` solution is
what the upper-bound check runs against.

- **Cast 1** — `rbx time -p boca` in `problems/gardens`, interactive.
- **Cast 2** — `rbx each time -p boca --auto` from the contest root. `--auto` is what keeps
  this from being N interactive TUI tabs driven blind.

The fixture then serves steps 3 and 5 of the track as well.

## Verification

[#439] asks for confirmation that `rbx each time -p <profile>` works end to end. `rbx each`
queues into the TUI command app (one tab per problem, terminal emulator) and `rbx time` is
interactive, so the composition is not obvious. It gets run against the fixture before
section 5 is written.

If it does not compose, an affordance issue is filed and linked, and the page falls back to
per-problem `rbx on <letter> time -p boca` while saying so plainly.

## Scope: #436 rides along

Step 1 of `packaging-walkthrough.md` is ~120 lines of profiling that this page replaces.
It is cut in the same PR ([#436]), and that page's opening is re-pointed here. Nothing
outside that file links to its `{: #profiling }` anchor, so the surgery is clean. Leaving it
for later would mean two pages teaching the same thing differently.

## Out of scope

- Re-teaching strategies, the ratio formula, or `modifiers` syntax — the Profiling feature
  guide owns all three.
- `--runner` beyond the one admonition.
- A contest-level limits profile. None exists; the page says so rather than wishing for one.

[#436]: https://github.com/rsalesc/rbx/issues/436
[#439]: https://github.com/rsalesc/rbx/issues/439
[#722]: https://github.com/rsalesc/rbx/pull/722
