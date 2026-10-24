# Points scoring configuration (#941)

## Problem

`TestcaseGroup.deps` documented that `samples` is "implicitly a dependency of every
other group", but scoring never added that edge: a solution failing a sample still
collected every other group's points. Rather than make the edge implicit (which
would silently change the score of every existing points problem), the dependency
structure becomes an explicit, opt-in part of the scoring configuration.

## Schema

```yaml
scoring: binary          # unchanged
scoring: points          # unchanged; shorthand for the defaults below

scoring:                 # the mapping form always means points
  dependencies: ladder   # manual (default) | samples | ladder
  aggregation: min       # min (default)
```

- `Package.scoring: Union[ScoreType, PointsScoring]`. A before-validator turns the
  string `points` into `PointsScoring()`; `binary` stays the enum. There is no `type`
  key: binary has nothing to configure today, and the mapping can grow one if it ever
  does.
- `dependencies` is a policy that *adds* edges to the graph, unioned with every
  group's hand-written `deps`:
  - `manual`: no extra edges (today's behavior, so existing problems keep their score).
  - `samples`: every non-sample group depends on `samples`.
  - `ladder`: every group depends on the one declared before it, the first one
    depending on `samples`. A strict superset of `samples`.
- `aggregation` is how a group's per-test results combine into its score, after
  CMS's [score types](https://cms.readthedocs.io/en/latest/Score%20types.html). Only
  `min` (CMS `GroupMin`: the group scores fully iff every test passes) exists. `mul`,
  `threshold` and `sum` are the planned extensions; they only differ from `min` once a
  checker can award fractional per-test scores. Unknown values fail validation.
- `Package.score_type` (always a `ScoreType`) and `Package.points_scoring` (the config,
  or `None` for binary) are what call sites read, so none of them parses the union.
- The cycle check and `check_scoring_fields` run over the *resolved* graph.

## The dependency library: `rbx/box/scoring/dependencies.py`

Pure, no I/O. The only place that knows `scoring.dependencies` exists.

- `resolve(pkg) -> GroupDependencies`: policy edges ∪ declared `deps`.
- `GroupDependencies.direct(group)`, `.closure(group)` (transitive, in declaration
  order, excluding the group itself), `.dependents(group)` (reverse closure).
- `flatten(deps, tests_by_group, aggregation)`: `{group: own tests + tests of every
  group in its closure}`. This is how a judge with independent groups reproduces
  dependencies exactly — under `min`, a group passes iff its own and every
  transitive dependency's tests pass. It raises for an aggregation duplication does
  not reproduce, so a future `sum` fails loudly instead of scoring wrong.

## Consumers

| Consumer | Uses |
|---|---|
| `solutions.py` skeleton, `_check_deps`, `_AbortGate` | resolved `direct` edges; gate uses `dependents` |
| `testset_manifest.py` | resolved `direct` edges |
| Polygon `<groups>` | resolved `direct` edges (native dependencies) |
| Polygon `--cms` `cms_conf.py` | `closure` (overlapping GroupMin regexes) |
| MOJ `tests/score` | `flatten`: dependency tests are copied into each dependent group, continuing that group's own counter so both of `score-summary.sh`'s group heuristics match. Probe packages are never scored and are not duplicated, keeping `testcase_names()` the runner's exact pairing contract. |

Duplication costs package size and judge time: a k-group `ladder` repeats the low
groups up to k times. MOJ reports how many tests it duplicated.

## Testing

Library unit tests per policy, union, cycles through policy edges, `flatten` on
ladder/diamond/empty groups and its aggregation guard; schema tests for both forms;
a scoring test reproducing #941 under `samples` (0/100) and `manual` (100/100);
MOJ and Polygon/CMS packaging tests. Live: MOJ and CMS.
