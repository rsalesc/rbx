# Packaging: CMS

{{cms}} is the contest system of the International Olympiad in Informatics. It doesn't
read one package format of its own: it imports problems and contests through *loaders*,
one per format it understands. {{rbx}} builds packages that CMS imports with its Polygon
loader.

## Formats

Each section below covers one format: how to build a package in it, and how to import that
package into CMS.

### Polygon

CMS can import a [Polygon package](polygon.md), but a plain one misses what CMS needs and
Polygon can't describe. Pass `--cms` to `rbx package polygon` or
`rbx contest package polygon`, and the package also contains:

- subtask scoring that follows your test groups
- the statement PDFs
- a manager, for an interactive problem.

```bash
rbx contest package polygon --cms
```

This writes `build/contest.zip`, a Polygon contest package with the CMS files added. Don't
upload it to Codeforces Gym, which refuses it: build without `--cms` for that. To import it,
unzip it, run CMS's contest importer, `cmsImportContest`, and choose its Polygon loader with
`-L polygon_contest`:

```bash
unzip build/contest.zip -d my-contest
cmsImportContest -L polygon_contest my-contest
```

A problem package, from `rbx package polygon --cms`, goes through CMS's task importer,
`cmsImportTask`, and its `polygon_task` loader instead:

```bash
unzip build/problem.zip -d my-problem
cmsImportTask -L polygon_task my-problem
```

!!! note "Interactive problems need C++"
    CMS runs an interactive problem through a manager that {{rbx}} compiles from your
    interactor, and from your checker if the interactor needs one. Write both in C++:
    {{rbx}} refuses to build the package otherwise.

## Configuring CMS

CMS has settings of its own that no package format describes, such as how a task's score
comes out of a contestant's submissions, or how long contestants must wait between two
submissions. You can declare them under `extensions.cms`, either in `env.rbx.yml` or in
`contest.rbx.yml`. Put the ones you always use in your
[preset](../presets/index.md)'s `env.rbx.yml`, and the ones specific to an event in its
`contest.rbx.yml`:

```yaml title="env.rbx.yml"
extensions:
  cms:
    task:                        # applied to every task
      scoreMode: maxSubtask
      feedbackLevel: restricted
      maxSubmissionNumber: 50
      minSubmissionInterval: 60  # seconds
```

```yaml title="contest.rbx.yml"
extensions:
  cms:
    task:
      minSubmissionInterval: 30
```

The `contest.rbx.yml` block wins, field by field: in the preceding example, tasks keep
`maxSubtask` scoring and wait 30 seconds between submissions. The one exception is
`tokens`, which a contest replaces as a whole. A problem you package outside a contest
gets only the `env.rbx.yml` settings.

{{rbx}} leaves out any field you don't set, so CMS uses its own default for it. Two fields
are exceptions:

- `scoreMode` defaults to `max`, the highest score among a contestant's submissions, which
  is what a solution's score means in {{rbx}}. CMS's own default, `maxTokenedLast`, scores
  the last submission unless contestants use tokens.
- `publicTestcases` defaults to `samples`, so contestants see results for the tests in your
  `samples` group only. Set it to `all` or `none` to change that.

Every setting so far goes under `task`. Next to it, `contest` holds the settings of the CMS
contest itself, such as `start`, `stop` and `allowUserTests`. No format {{rbx}} builds
today carries them, so set them in CMS after importing (see
[Settings in a Polygon package](#settings-in-a-polygon-package)). `start`, `stop` and
`perUserTime` describe one event, so {{rbx}} accepts them only in `contest.rbx.yml`.

The [environment schema](../reference/environment/schema.md#cms) lists every field.

### Settings in a Polygon package

A [Polygon package](#polygon) contains every `task` setting, but none of the `contest` ones:
CMS's Polygon loader sets the contest options itself. {{rbx}} accepts them anyway, and
warns you that it ignores them. Set them in CMS's administration interface after importing.
