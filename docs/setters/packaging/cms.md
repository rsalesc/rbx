# Packaging: CMS

{{cms}} is the contest system of the International Olympiad in Informatics. It doesn't
read one package format of its own: it imports problems and contests through *loaders*,
one per format it understands. {{rbx}} builds packages for two of them: its Polygon loader,
which imports problems and contests, and its Italian YAML loader, which imports a contest
with its settings and languages.

## Formats

Each section below covers one format: how to build a package in it, and how to import that
package into CMS.

### Polygon

CMS can import a [Polygon package](polygon.md), but a plain one misses what CMS needs and
Polygon can't describe. Pass `--cms` to `rbx package polygon` or
`rbx contest package polygon`, and the package also contains:

- subtask scoring that follows your test groups
- your checker, built so that CMS scores its [partial points](/setters/grading/scoring#awarding-partial-points) the way {{rbx}} does
- the statement PDFs
- a manager, for an interactive problem

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

!!! note "Checkers and interactors need C++"
    CMS compiles your checker as C++ when it imports the problem. It runs an interactive
    problem through a manager that {{rbx}} compiles from your interactor, and from your
    checker if the interactor needs one. Write both in C++: {{rbx}} refuses to build the
    package otherwise.

### Italian YAML

Italian YAML is CMS's own format, the one its `italy_yaml` loader reads. {{rbx}} builds
only the contest in it, and leaves the problems to the Polygon package.

Why a second package? CMS's Polygon loader sets the options of a contest itself, so a
contest imported from `build/contest.zip` gets none of your
[contest settings](#configuring-cms), and allows CMS's default languages rather than
[yours](#languages). To keep both, import the contest separately from its problems:

1. Build both packages:

    ```bash
    rbx contest package polygon --cms
    rbx contest package cms-contest
    ```

    The second command builds no problem. It writes `build/cms-contest.zip`, which holds
    one directory, named after the `name` in your `contest.rbx.yml`. Inside it,
    `contest.yaml` holds the contest's settings and languages, along with the list of
    its problems.

2. Import each problem with `cmsImportTask`, from the Polygon package:

    ```bash
    unzip build/contest.zip -d tasks
    cmsImportTask -L polygon_task tasks/problems/A
    cmsImportTask -L polygon_task tasks/problems/B
    ```

    Here, `A` and `B` are your problems' letters in the contest. CMS imports each one on
    its own, in no contest yet.

3. Import the contest with `-L italy_yaml`:

    ```bash
    unzip build/cms-contest.zip
    cmsImportContest -L italy_yaml my-contest
    ```

    Here, `my-contest` is the `name` of your contest. CMS finds each of its problems by
    letter and attaches it, in the order of your `contest.rbx.yml`.

Import the problems before the contest, since the contest attaches only problems that
CMS already has. To change a problem later, import it again with `cmsImportTask -u`,
and to change the contest, with `cmsImportContest -u`. Both keep the problems attached.

!!! warning "Never pass `--import-tasks` or `--update-tasks` to `cmsImportContest`"
    The contest package has a placeholder `task.yaml` for each problem, so that
    `cmsImportContest` can attach it. With `--import-tasks` or `--update-tasks`, or their
    short forms `-i` and `-U`, CMS would import that placeholder as the problem.

!!! warning "Problem names are global in CMS"
    CMS imports a problem under its letter, such as `A`, and refuses a second problem
    with the same name, even in another contest. So two contests whose problems share a
    letter can't both live on the same CMS instance: {{rbx}} has no way around this yet.

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

{{rbx}} leaves out any field you don't set, so CMS uses its own default for it. Three fields
are exceptions:

- `scoreMode` defaults to `max`, the highest score among a contestant's submissions, which
  is what a solution's score means in {{rbx}}. CMS's own default, `maxTokenedLast`, scores
  the last submission unless contestants use tokens.
- `publicTestcases` defaults to `samples`, so contestants see results for the tests in your
  `samples` group only. Set it to `all` or `none` to change that.
- `scorePrecision` defaults to `2`, so CMS shows scores with two decimal places, as
  {{rbx}} does. CMS's own default, `0`, rounds a score of 45.84 to 46.

Every setting so far goes under `task`. Next to it, `contest` holds the settings of the CMS
contest itself, such as `start`, `stop` and `allowUserTests`:

```yaml title="contest.rbx.yml"
extensions:
  cms:
    contest:
      start: 2026-11-01T09:00:00-03:00
      stop: 2026-11-01T14:00:00-03:00
      timezone: America/Sao_Paulo
      allowUserTests: true
```

This contest runs from 9:00 to 14:00, Brasília time. The offsets on `start` and `stop`
decide those instants; `timezone` only sets how CMS shows times to contestants. `start`,
`stop` and `perUserTime` describe one event, so {{rbx}} accepts them only in
`contest.rbx.yml`. `scorePrecision` also goes here, for the contest's total scores, and
defaults to `2` as it does on tasks. To import the `contest` settings into CMS, use an
[Italian YAML](#italian-yaml) package: no other package {{rbx}} builds contains them.

The [environment schema](../reference/environment/schema.md#cms) lists every field.

### Languages

CMS calls its languages by names of its own, such as `C++20 / g++`. List the ones each
language of your `env.rbx.yml` corresponds to under that language's own
`extensions.cms.languages`, not under the top-level `extensions.cms`, spelled exactly as
CMS spells them:

```yaml title="env.rbx.yml"
languages:
  - name: "cpp"
    # ...
    extensions:
      cms:
        languages: ["C++20 / g++"]
```

A contest you import from an [Italian YAML](#italian-yaml) package allows every CMS
language your languages list, and only those. The default preset lists one each for C++,
C, Python, and Java. Kotlin has no CMS counterpart, so it lists none, and {{rbx}} warns
you that the contest doesn't allow it. If none of your languages lists one, the contest
keeps CMS's default languages, and {{rbx}} warns you about that too.

### Compiler flags

CMS compiles your checker when it imports a [Polygon package](#polygon), and for an
interactive problem it compiles the manager built around your interactor. It compiles them
on the CMS machine with `g++ -std=gnu++20 -O2`, not with the commands in your
`env.rbx.yml`. To use other flags, set `flags` under the same `extensions.cms` as
`languages`:

```yaml title="env.rbx.yml"
languages:
  - name: "cpp"
    # ...
    extensions:
      cms:
        languages: ["C++20 / g++"]
        flags: "-std=gnu++17 -O2"
```

Here CMS builds the checker and the interactor as C++17, while contestants still submit in
C++20: `flags` never changes how CMS compiles submissions. Your flags replace
`-std=gnu++20 -O2`, and the checker and the interactor each take the flags of their own
language. {{rbx}} always adds `-static`, plus the include paths and definitions it needs,
so leave those out.

### Settings in a Polygon package

A [Polygon package](#polygon) contains every `task` setting, but neither the `contest` ones
nor the languages: CMS's Polygon loader sets the contest options itself. {{rbx}} warns you
when you set `contest` settings, and ignores them. To keep them and your languages, import
the contest from an [Italian YAML](#italian-yaml) package instead.
