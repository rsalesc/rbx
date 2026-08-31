# Config-level checks: a second detector family

Tracked by [#840](https://github.com/rsalesc/rbx/issues/840). Follow-up to
[#792](https://github.com/rsalesc/rbx/issues/792) /
[#834](https://github.com/rsalesc/rbx/pull/834). Builds on
[`2026-08-31-issues-view-design.md`](2026-08-31-issues-view-design.md).

## The problem

Some things are wrong with a problem before it is ever run. No solution declares
`accepted`, so nothing pins down what a correct answer even looks like. There is
no validator, so nothing checks that the generated tests obey the constraints
the statement promises. There are no samples. A group declared in
`problem.rbx.yml` generated zero tests. A sample explanation was authored in
English and the problem also ships a Portuguese statement, so the Portuguese PDF
silently comes out with no explanation at all.

None of these needs a run to detect, and none of them is detected today. `rbx
issues` was deliberately scoped to run-derived findings -- every detector reads
`.rbx/runs`, and a problem that was never run reports `neverRun` and nothing
else. `rbx summary` describes the package accurately but passes no judgement on
it: it will happily print `Solutions: WRONG_ANSWER 3` without remarking that
none of them is accepted.

The last one is the sharpest, because it fails silently in the one place a
setter is least likely to look. `engine._resolve_file_explanation` resolves a
`.rbx`-suffixed explanation through `render_jinja_blocks` and then does
`blocks.get(lang)`. A language the blocks file does not define is not an error;
it is `None`, and the explanation is simply absent from that language's build.

## Decisions

### Config checks are a second detector family, not a second command

`rbx/box/issues/` already owns everything this needs: a structured issue model
with computed severity, a discriminated union that a new kind slots into without
schema surgery, a renderer, a JSON contract, and a contest aggregator. A
separate `rbx check` would duplicate all of it and leave the setter asking two
commands what one question -- "is this problem in good shape" -- should answer.

So config checks become `CONFIG_DETECTORS`, sitting beside the existing
`DETECTORS`, producing the same `Issue` type into the same `IssueReport`.

`UntunedLimitsIssue` already established the precedent that an issue kind need
not be about a solution -- the renderer reads `getattr(issue, 'solution', None)`
-- so a package-level config issue needs no accommodation.

### Both `rbx summary` and `rbx issues` render them

`rbx summary` gains a **Checks** section listing the config family. It is the
command that already answers "what is this problem", it already loads the
package and extracts the testcases these checks need, and a setter reading a
summary is exactly the person who wants to be told the summary describes a
package with no accepted solution.

`rbx issues` shows both families, because "is this problem in good shape" is one
question. At contest level this is the point: `rbx contest issues` gains
"problem C has no validator" rows for free, which is the pre-contest checklist
#840 asked for, and it needs no code of its own -- the Err/Warn counts and the
`Worst issue` column aggregate whatever `build_report` returns.

Neither command re-derives anything. Both go through `detect_all_config`, and
both render through the same `summarize()`, for the reason `rbx run` re-reads
`report.yml` from disk rather than passing objects to the renderer: two callers
that word the same finding differently are worse than one caller.

### `rbx issues` pays for a package load

This is the real cost. `rbx issues` today is sync and close to instant: it reads
`report.yml` and `skeleton.yml` and touches nothing else, an invariant
`run_state.py`'s docstring states outright. Config detection needs a loaded
`Package` and `extract_generation_testcases_from_groups()`, which makes the
command async and meaningfully slower.

Gating it behind a flag was rejected. A flag whose default is off means `rbx
issues` and `rbx summary` disagree about the same package by default, and the
setter who most needs "you have no accepted solution" is the one least likely to
have discovered the flag. The cost is the cost `rbx summary` already pays
without complaint.

`run_state.py` keeps its invariant regardless: config inputs live in a separate
`ConfigState`, collected by a separate collector. The run detectors still see
only `.rbx/runs`.

### `ISSUES_FORMAT_VERSION` bumps to 2

Not for the new kinds. The discriminated union means an older reader can read
`kind` and `severity` off a kind it has never seen and show something sensible,
which is why the format version's docstring says adding a kind is not really a
breaking change.

It bumps because `neverRun` changes meaning. Today `neverRun: true` implies an
empty `issues` list, and three call sites short-circuit on it --
`contest.build_report`, `rendering.print_report`, and `run.py:_print_issues`. A
never-run problem can now carry config issues, so a v1 reader that short-circuits
would silently drop every finding. That is a read-breaking change and it gets a
version.

### `family` is a computed field

`'run' | 'config'`, computed on `_BaseIssue` beside `severity`, for the reason
`severity` is computed: so no client keeps its own table of which kind is which.
The VS Code extension wanting to show config problems before a run has happened
should filter on a field, not on a `kind` prefix convention it has to be told
about.

### Purity stays the point

Every config detector is a pure `ConfigState -> List[Issue]`. `ConfigState` is a
plain pydantic model of already-extracted facts -- counts, names, language lists
-- not a `Package` and not a filesystem path. A detector never opens a file,
never touches a contextvar, never loads a package.

This is what let the run detectors be exercised in 0.08s against states built by
hand, and it matters more here: a check like "this explanation blocks file does
not cover every statement language" would otherwise need a real package with
real statements and a real Jinja environment to test at all.

The one place that costs something is collecting `explanation_languages`. Jinja
exposes `template.blocks` as a compile-time property, so the collector loads the
template and reads the block names without rendering it -- no context, no vars,
no `UndefinedError` to handle. A block name that only exists after a conditional
render would be missed; a per-language explanation file is always literal, and
the alternative is rendering every explanation of every problem on every `rbx
summary`.

### `rbx contest summary` is left alone

`rbx contest issues` answers this at contest level once the family is folded in.
Adding a column to the contest summary table would put the same finding in two
tables and make an already-wide table wider, for a reader who has a command that
says it better.

## Architecture

### Layout

```
rbx/box/issues/
  schema.py            ~ 6 new kinds, `family` computed field, version 2
  run_state.py           unchanged
  detectors.py           unchanged
  config_state.py      NEW  ConfigState + its collector
  config_detectors.py  NEW  pure ConfigState -> List[Issue]
  contest.py           ~ build_report takes an optional ConfigState
  rendering.py         ~ summarize/explain for the new kinds; neverRun no
                         longer suppresses the list
  __init__.py          ~ re-exports
```

Callers keep importing only from `rbx.box.issues`.

### `ConfigState`

```python
class ConfigState(BaseModel):
    solutions: List[Solution]
    has_validator: bool
    group_test_counts: Dict[str, int]        # declared group -> tests generated
    sample_count: int
    statement_languages: List[str]           # this problem's own
    explanation_languages: Dict[int, List[str]]  # sample index -> blocks defined
    contest_languages: List[str] = []        # empty outside a contest
```

`explanation_languages` holds only samples whose explanation is a `.rbx`-suffixed
blocks file. A language-agnostic explanation covers every language by
construction and has nothing to check.

`contest_languages` is empty at problem level, which is not the same as "no
languages" -- the detector reading it emits nothing when it is empty rather than
accusing a standalone problem of missing every language.

### The checks

| kind | severity | fires when |
|---|---|---|
| `config_no_accepted_solution` | error | no solution declares `accepted` or `accepted_or_tle` |
| `config_no_validator` | warning | the package declares no validator |
| `config_no_samples` | warning | zero sample tests |
| `config_empty_test_group` | warning | a declared group generated zero tests |
| `config_missing_statement_language` | warning | no statements at all, or a contest language this problem has no statement for |
| `config_explanation_missing_language` | warning | a blocks explanation covers only some of the problem's statement languages |

`config_no_accepted_solution` is the only error. Without an accepted solution
nothing establishes what a correct output is, so the outputs the package
generates are unverified -- the package does not do what a package is for. The
rest are warnings because each has a legitimate package that does it on purpose:
an interactive problem may reasonably ship no samples, a problem whose tests are
all hand-written needs no validator, and a group can be empty mid-authoring.

`config_missing_statement_language` covers both "no statement" and "missing one
language" as one kind rather than two, because they are the same finding at
different granularity and a reader wants them in the same place. The payload
carries `missing: List[str]` and a `hasNoStatements: bool` so the renderer can
word them apart.

### Rendering

`rbx summary` prints a `Checks` section after `Solutions`, in the same shape
`print_report` uses -- one `marker + summarize(issue)` line per finding --
omitted entirely when there is nothing to say. `--detailed` expands them with
`explain()`, matching `rbx issues -d`.

`rbx issues` sorts config issues before run issues within each severity band:
the run's findings are downstream of the config, and "no accepted solution"
explains half the verdict failures under it.

### JSON

`rbx summary --format json` emits

```json
{"version": 1, "summary": {...ProblemSummary...}, "issues": [...]}
```

with its own `SUMMARY_FORMAT_VERSION`, independent of the issues one: the
`ProblemSummary` shape and the `Issue` shape change for unrelated reasons and
pinning them to one number would make each bump lie about the other. The
embedded issues are `Issue` values, carrying their own `version` nowhere -- the
issues version belongs to `IssueReport`, and this is not one.

`rbx issues --format json` is unchanged in shape; only its `version` and the
kinds inside it move.

### Error handling

A config collector that cannot read the package raises, and the CLI reports it
the way it already reports a missing package -- config checks do not get to
decide that an unreadable package is a warning. Inside the contest aggregator
the existing `except Exception -> failed_to_load=True` row already covers it,
which is the same treatment `collect_contest_rows` gives a package it cannot
summarize.

A statement template that fails to load when collecting `explanation_languages`
yields no languages for that sample rather than raising. The blocks file is only
being read to check coverage; a template broken enough not to compile is a
failure the statement build will report properly, and `rbx summary` is not the
command that should break on it.

## Deferred

- Checks needing a heavier read: unreferenced generator scripts, a checker that
  ignores its answer file, tests that duplicate one another.
- A `--fix`-shaped remedy for anything here. Every check names a thing the setter
  has to decide, not a thing rbx can write.
- Config findings in the VS Code extension's inline view. The JSON contract makes
  it possible; nothing consumes it yet.
