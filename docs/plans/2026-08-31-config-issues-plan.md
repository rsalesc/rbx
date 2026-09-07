# Config-Level Checks Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add six config-level checks — findings about a problem that need no run at all — as a second detector family inside `rbx/box/issues/`, rendered by both `rbx summary` and `rbx issues`.

**Architecture:** A new pure `ConfigState` (a pydantic model of already-extracted facts, not a `Package`) feeds `CONFIG_DETECTORS`, module-level pure functions registered in a list exactly like the existing `DETECTORS`. They produce the same `Issue` union into the same `IssueReport`, so the existing renderer, JSON contract and contest aggregator carry them for free. A separate collector does the impure work of building a `ConfigState` from the package on disk.

**Tech Stack:** Python 3, pydantic v2 (discriminated unions, `computed_field`), Typer, Rich, Jinja2, pytest.

**Design doc:** [`2026-08-31-config-issues-design.md`](2026-08-31-config-issues-design.md). Read it first — it records *why* each decision went the way it did, and this plan does not repeat the reasoning.

---

## Orientation: things that will bite you

Read these before Task 1. Each one is a trap this codebase has already been burned by.

1. **Severity is never a field.** `_BaseIssue` declares an abstract `@computed_field @property severity`; each concrete kind returns a constant. Same for the new `family`. Do not add `severity: IssueSeverity` to a model — see the docstring at the top of `rbx/box/issues/schema.py`.

2. **Detectors are pure.** No console, no contextvar, no filesystem, no `Package`. Everything a detector needs is already on the state it is handed. This is what makes the suite run in 0.08s. If you find yourself importing `rbx.box.package` into `config_detectors.py`, stop — the fact belongs on `ConfigState` instead.

3. **Callers import from `rbx.box.issues`, never a submodule.** Add every new public name to `__init__.py`'s imports *and* its `__all__`.

4. **`ruff` enforces single quotes and bans relative imports.** Run `uv run ruff format .` and `uv run ruff check --fix .` before every commit.

5. **Commits must be conventional.** Use the `/commit` skill (`.claude/skills/commit.md`). The pre-commit hook rejects anything else, and you must never `--amend` past a rejection — make a new commit.

6. **Do not run the full test suite.** It is slow and produces spurious sandbox wall-clock failures. Run only the files you touched.

---

## Task 1: The schema — `family`, six kinds, version 2

**Files:**
- Modify: `rbx/box/issues/schema.py`
- Test: `tests/rbx/box/issues_test.py`

**Step 1: Write the failing tests**

Add a new class at the end of `tests/rbx/box/issues_test.py`:

```python
class TestConfigIssueSchema:
    def test_config_issues_carry_the_config_family(self):
        issue = NoAcceptedSolutionIssue()
        assert issue.family == IssueFamily.CONFIG
        assert issue.severity == IssueSeverity.ERROR

    def test_run_issues_carry_the_run_family(self):
        issue = UntunedLimitsIssue(affectedSolutions=['sol/a.cpp'])
        assert issue.family == IssueFamily.RUN

    def test_family_and_severity_are_serialized(self):
        payload = NoValidatorIssue().model_dump()
        assert payload['family'] == 'config'
        assert payload['severity'] == 'warning'
        assert payload['kind'] == 'config_no_validator'

    def test_config_kinds_round_trip_through_the_union(self):
        report = IssueReport(
            issues=[
                MissingStatementLanguageIssue(missing=['pt'], hasNoStatements=False),
                EmptyTestGroupIssue(group='big'),
            ]
        )
        restored = IssueReport.model_validate_json(report.model_dump_json())
        assert restored.issues == report.issues

    def test_format_version_is_two(self):
        assert ISSUES_FORMAT_VERSION == 2
```

Extend the existing import block at the top of the file with the new names.

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/issues_test.py::TestConfigIssueSchema -v`
Expected: FAIL — `ImportError: cannot import name 'IssueFamily'`.

**Step 3: Implement**

In `rbx/box/issues/schema.py`:

Bump the version constant and extend its comment to say why:

```python
# Bump when a change would make an older reader misread the output.
#
# Adding a new issue *kind* is such a change only in the sense that an older
# reader will not know how to word it; the discriminated union means it can
# still read `kind`, `family` and `severity` and show something. Adding an
# optional field to an existing kind is not a change at all.
#
# 2: config-level issues joined the run-level ones, and `neverRun` stopped
#    implying an empty `issues` list. A v1 reader short-circuiting on
#    `neverRun` would silently drop every config finding.
ISSUES_FORMAT_VERSION = 2
```

Add the family enum next to `IssueSeverity`:

```python
class IssueFamily(str, Enum):
    """Which question an issue answers.

    Computed rather than declared, for the reason `severity` is: a client
    splitting "what did my run reveal" from "what is wrong with this package
    before it is ever run" should read a field, not keep its own table of which
    `kind` belongs where.
    """

    # Derived from `.rbx/runs`: needs a run to exist.
    RUN = 'run'
    # Derived from the package itself: true before anything is ever run.
    CONFIG = 'config'
```

On `_BaseIssue`, add the abstract computed field beside `severity`:

```python
    @computed_field  # type: ignore[prop-decorator]
    @property
    def family(self) -> IssueFamily:
        raise NotImplementedError
```

Give each of the eight existing kinds `return IssueFamily.RUN`. Rather than eight copies, introduce two intermediate bases and reparent:

```python
class _RunIssue(_BaseIssue):
    """An issue derived from `.rbx/runs`."""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def family(self) -> IssueFamily:
        return IssueFamily.RUN


class _ConfigIssue(_BaseIssue):
    """An issue derived from the package config, true before any run."""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def family(self) -> IssueFamily:
        return IssueFamily.CONFIG
```

Change the eight existing kinds to subclass `_RunIssue` instead of `_BaseIssue`. Nothing else about them changes.

Then the six new kinds:

```python
class NoAcceptedSolutionIssue(_ConfigIssue):
    """No solution claims to be correct.

    The one config-level error. Without an accepted solution nothing establishes
    what a correct output is, so every output the package generates is
    unverified -- the package does not do the thing a package is for.
    """

    kind: Literal['config_no_accepted_solution'] = 'config_no_accepted_solution'

    @computed_field  # type: ignore[prop-decorator]
    @property
    def severity(self) -> IssueSeverity:
        return IssueSeverity.ERROR


class NoValidatorIssue(_ConfigIssue):
    """The package declares no validator.

    A warning, not an error: a problem whose tests are all hand-written has
    nothing for a validator to do.
    """

    kind: Literal['config_no_validator'] = 'config_no_validator'

    @computed_field  # type: ignore[prop-decorator]
    @property
    def severity(self) -> IssueSeverity:
        return IssueSeverity.WARNING


class NoSamplesIssue(_ConfigIssue):
    """The package generates no sample tests."""

    kind: Literal['config_no_samples'] = 'config_no_samples'

    @computed_field  # type: ignore[prop-decorator]
    @property
    def severity(self) -> IssueSeverity:
        return IssueSeverity.WARNING


class EmptyTestGroupIssue(_ConfigIssue):
    """A group declared in `problem.rbx.yml` generated no tests.

    One issue per group rather than one listing them all: the remedy is
    per-group -- a generator that produced nothing, a glob that matched
    nothing -- unlike `UntunedLimitsIssue`, where the remedy is a single
    `rbx time` for the whole package.
    """

    kind: Literal['config_empty_test_group'] = 'config_empty_test_group'
    group: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def severity(self) -> IssueSeverity:
        return IssueSeverity.WARNING


class MissingStatementLanguageIssue(_ConfigIssue):
    """The problem has no statement, or none for a language the contest wants.

    One kind for both because they are the same finding at two granularities and
    a reader wants them in the same place; `hasNoStatements` lets the renderer
    word them apart. `missing` is empty exactly when `hasNoStatements` is set --
    outside a contest, rbx does not know which languages were wanted.
    """

    kind: Literal['config_missing_statement_language'] = (
        'config_missing_statement_language'
    )
    missing: List[str] = []
    hasNoStatements: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def severity(self) -> IssueSeverity:
        return IssueSeverity.WARNING


class ExplanationMissingLanguageIssue(_ConfigIssue):
    """A sample explanation covers only some of the problem's statements.

    The silent one. `engine._resolve_file_explanation` reads a `.rbx`-suffixed
    explanation through `render_jinja_blocks` and then does `blocks.get(lang)`:
    a language the file does not define is not an error, it is `None`, and the
    explanation is simply absent from that language's build with nothing said.
    """

    kind: Literal['config_explanation_missing_language'] = (
        'config_explanation_missing_language'
    )
    # The sample's index among the samples, as the statement build numbers them.
    sample: int
    # The explanation file, relative to the package root.
    path: pathlib.Path
    missing: List[str] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def severity(self) -> IssueSeverity:
        return IssueSeverity.WARNING
```

Add all six to the `Issue` union, after the run kinds.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/issues_test.py -v`
Expected: PASS, including the pre-existing classes. If `TestJsonOutput` fails on a hardcoded `"version": 1`, update that expectation to `2` — that is the bump doing its job.

**Step 5: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add rbx/box/issues/schema.py tests/rbx/box/issues_test.py
```
Commit as `feat(issues): add config-level issue kinds and the issue family`.

---

## Task 2: Reading a template's block names without rendering it

**Files:**
- Modify: `rbx/box/statements/render.py`
- Test: `tests/rbx/box/statements/render_test.py` (create if absent)

This is the one piece of machinery the collector needs that does not exist. Jinja parses `{% block %}` at compile time and exposes the table as `template.blocks`, so the block *names* are readable without a context, without vars, and without the `UndefinedError` handling a real render needs.

**Step 1: Write the failing test**

```python
import pathlib

from rbx.box.statements.render import parse_jinja_block_names


class TestParseJinjaBlockNames:
    def test_reads_latex_block_names(self, tmp_path: pathlib.Path):
        content = (
            b'%- block en\nThe answer is 42.\n%- endblock\n'
            b'%- block pt\nA resposta e 42.\n%- endblock\n'
        )
        assert sorted(parse_jinja_block_names(tmp_path, content)) == ['en', 'pt']

    def test_reads_markdown_block_names(self, tmp_path: pathlib.Path):
        content = b'{% block en %}The answer is 42.{% endblock %}'
        assert parse_jinja_block_names(tmp_path, content, mode='markdown') == ['en']

    def test_drops_per_sample_explanation_blocks(self, tmp_path: pathlib.Path):
        content = (
            b'%- block en\nhi\n%- endblock\n'
            b'%- block explanation_0\nhi\n%- endblock\n'
        )
        assert parse_jinja_block_names(tmp_path, content) == ['en']

    def test_undefined_variables_do_not_raise(self, tmp_path: pathlib.Path):
        # The body is never evaluated, so a var that would explode on render is
        # irrelevant to the block names.
        content = b'%- block en\n\\VAR{vars.nonexistent.deeply}\n%- endblock\n'
        assert parse_jinja_block_names(tmp_path, content) == ['en']
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/statements/render_test.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_jinja_block_names'`.

**Step 3: Implement**

In `rbx/box/statements/render.py`, beside `render_jinja_blocks`:

```python
def parse_jinja_block_names(
    root: pathlib.Path,
    content: bytes,
    mode: Mode = 'latex',
) -> List[str]:
    """The names of the ``%- block <name>`` chunks in ``content``, in order.

    Compiles the template but never renders it. Jinja fills ``template.blocks``
    while parsing, so the names are available without a context, without vars,
    and without any chance of an ``UndefinedError`` -- which is what makes this
    cheap enough for `rbx summary` to call on every sample of every problem.

    A block whose name only exists after a conditional render is invisible here.
    A per-language explanation file is always literal, and rendering every
    explanation of every problem to find out otherwise is not a trade worth
    making.
    """
    if mode == 'latex':
        temp_file = '__blocknames__.tex'
        env_args = (FilterTarget.LATEX, JinjaSyntax.LATEX)
    elif mode == 'markdown':
        temp_file = '__blocknames__.md'
        env_args = (FilterTarget.MARKDOWN, JinjaSyntax.PLAIN)
    else:
        raise ValueError(f'Invalid mode: {mode}')

    temp_path = root / temp_file
    temp_path.write_bytes(content)
    try:
        env = make_jinja_env(
            env_args[0],
            syntax=env_args[1],
            loader=jinja2.FileSystemLoader(str(root)),
        )
        names = list(env.get_template(temp_file).blocks)
    finally:
        temp_path.unlink(missing_ok=True)

    # `render_jinja_blocks` splits these out into `explanations`; they are a
    # sample index, never a language.
    pattern = re.compile(r'explanation_(\d+)$')
    return [name for name in names if not pattern.match(name)]
```

Import `make_jinja_env`, `FilterTarget`, `JinjaSyntax` and `jinja2` if `render.py` does not already have them — check what `render_jinja_blocks` reaches for and follow it.

Note the `try/finally` unlink: `render_jinja_blocks` leaves its temp file behind, but this one runs on every sample of every `rbx summary` and would otherwise litter the package root.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/statements/render_test.py -v`
Expected: PASS (4 tests).

**Step 5: Commit**

`feat(statements): read a template's block names without rendering it`

---

## Task 3: `ConfigState` and its collector

**Files:**
- Create: `rbx/box/issues/config_state.py`
- Test: `tests/rbx/box/issues_test.py`

**Step 1: Write the failing test**

The collector is impure and needs a real package, so it gets a package-backed test; the model itself needs none.

```python
class TestConfigState:
    def test_state_is_constructible_by_hand(self):
        state = ConfigState(
            solutions=[],
            has_validator=False,
            group_test_counts={'samples': 0},
            sample_count=0,
            statement_languages=[],
        )
        assert state.contest_languages == []
        assert state.explanation_languages == {}

    @pytest.mark.test_pkg('box/interactive')
    @pytest.mark.asyncio
    async def test_collects_from_a_real_package(
        self, pkg_from_testdata: Package
    ):
        state = await collect_config_state(pkg_from_testdata)
        assert state.has_validator == (pkg_from_testdata.validator is not None)
        assert set(state.group_test_counts) == {
            group.name for group in pkg_from_testdata.testcases
        }
        assert state.sample_count == state.group_test_counts.get('samples', 0)
        assert state.statement_languages == [
            st.language for st in pkg_from_testdata.expanded_statements
        ]
```

Match the fixture name and marker style already used in `tests/rbx/box/` — check `tests/rbx/box/conftest.py` for `pkg_from_testdata` and pick a `test_pkg` package that actually exists under `rbx/testdata/problems/`.

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/issues_test.py::TestConfigState -v`
Expected: FAIL — no `config_state` module.

**Step 3: Implement**

```python
"""What the *package* says, as the config detectors need it.

The mirror of `run_state`, and deliberately not a `Package`: a detector is handed
counts, names and language lists that have already been extracted, so it stays a
pure function testable against a state built by hand. `run_state`'s promise --
that it reads `.rbx/runs` and nothing else -- is unaffected, because these inputs
live here instead of being bolted onto it.

Collecting a state is the impure half, and it lives here rather than in the
detectors so the split stays visible.
"""

import pathlib
from typing import Dict, List, Optional

from pydantic import BaseModel

from rbx.box import package, testcase_sample_utils, testcase_extractors
from rbx.box.schema import Package, Solution, StatementType
from rbx.box.statements.render import parse_jinja_block_names


class ConfigState(BaseModel):
    """Everything the config detectors read. No package, no paths to open."""

    solutions: List[Solution]
    has_validator: bool
    # Every group declared in `problem.rbx.yml`, mapped to how many tests it
    # actually generated. A group present with a 0 is the finding; a group
    # absent from the map was never declared.
    group_test_counts: Dict[str, int]
    sample_count: int
    # This problem's own statement languages, in declaration order.
    statement_languages: List[str] = []
    # Sample index -> the languages a `.rbx`-suffixed explanation blocks file
    # defines. Only samples with such a file appear: a language-agnostic
    # explanation covers every language by construction.
    explanation_languages: Dict[int, List[str]] = {}
    # Sample index -> that explanation file, relative to the package root, so
    # the issue can name it.
    explanation_paths: Dict[int, pathlib.Path] = {}
    # The languages the contest declares. Empty outside a contest, which is not
    # the same as "no languages wanted" -- the detector emits nothing when it is
    # empty rather than accusing a standalone problem of missing every language.
    contest_languages: List[str] = []


def _explanation_suffix_of(statement) -> str:
    """The on-disk suffix of a sample explanation for this statement's type.

    The same rule `build_statements._explanation_suffix` applies. Duplicated
    rather than imported: `build_statements` drags in the whole statement build
    graph, and `rbx summary` should not pay for it.
    """
    return '.md' if statement.type == StatementType.rbxMarkdown else '.tex'


async def collect_config_state(
    pkg: Package,
    contest_languages: Optional[List[str]] = None,
) -> ConfigState:
    """Build a `ConfigState` from the package in the current directory."""
    entries = await testcase_extractors.extract_generation_testcases_from_groups()

    group_test_counts: Dict[str, int] = {
        group.name: 0 for group in pkg.testcases
    }
    for entry in entries:
        group = entry.group_entry.group
        group_test_counts[group] = group_test_counts.get(group, 0) + 1

    statements = pkg.expanded_statements
    explanation_languages, explanation_paths = await _collect_explanations(
        pkg, statements
    )

    return ConfigState(
        solutions=package.get_solutions(),
        has_validator=pkg.validator is not None,
        group_test_counts=group_test_counts,
        sample_count=sum(1 for entry in entries if entry.is_sample()),
        statement_languages=[st.language for st in statements],
        explanation_languages=explanation_languages,
        explanation_paths=explanation_paths,
        contest_languages=list(contest_languages or []),
    )
```

`_collect_explanations` is the fiddly half. The suffix depends on the statement's *type*, so statements are grouped by suffix and each group checked against the samples resolved with that suffix:

```python
async def _collect_explanations(pkg, statements):
    """The languages each blocks-file explanation defines.

    Grouped by suffix because the suffix is a property of the *statement type*:
    an `.md` statement's explanations live in `.rbx.md` files and a `.tex`
    statement's in `.rbx.tex` ones, so a problem shipping both has two
    independent sets of explanations to check.
    """
    languages: Dict[int, List[str]] = {}
    paths: Dict[int, pathlib.Path] = {}
    root = package.find_problem_path()

    suffixes = {_explanation_suffix_of(st) for st in statements}
    for suffix in sorted(suffixes):
        samples = await testcase_sample_utils.get_statement_samples(
            explanation_suffix=suffix
        )
        for index, sample in enumerate(samples):
            if not sample.explanationFromBlocks or sample.explanationPath is None:
                continue
            try:
                names = parse_jinja_block_names(
                    root,
                    sample.explanationPath.read_bytes(),
                    mode='markdown' if suffix == '.md' else 'latex',
                )
            except Exception:
                # A template broken enough not to compile is a failure the
                # statement build reports properly, with a location and a
                # message. `rbx summary` is not the command that should die on
                # it, and reporting "covers no languages" would be a lie.
                continue
            languages[index] = names
            paths[index] = sample.explanationPath
    return languages, paths
```

Check `package.find_problem_path` exists under that name; if the accessor is called something else, use whatever `summary.py` or `testcase_sample_utils.py` already uses for the package root.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/issues_test.py::TestConfigState -v`
Expected: PASS.

**Step 5: Commit**

`feat(issues): collect the package facts config checks read`

---

## Task 4: The six detectors

**Files:**
- Create: `rbx/box/issues/config_detectors.py`
- Test: `tests/rbx/box/issues_test.py`

This is the task with the most tests and the least machinery. Every test builds a `ConfigState` by hand — no package, no fixture, no `await`.

**Step 1: Write the failing tests**

```python
def _state(**kwargs) -> ConfigState:
    """A config state with nothing wrong with it, overridden per test."""
    defaults = dict(
        solutions=[_solution('sol/ac.cpp', ExpectedOutcome.ACCEPTED)],
        has_validator=True,
        group_test_counts={'samples': 2, 'main': 10},
        sample_count=2,
        statement_languages=['en'],
    )
    defaults.update(kwargs)
    return ConfigState(**defaults)


class TestConfigDetectors:
    def test_a_healthy_package_produces_nothing(self):
        assert detect_all_config(_state()) == []

    def test_no_accepted_solution(self):
        state = _state(
            solutions=[_solution('sol/wa.cpp', ExpectedOutcome.WRONG_ANSWER)]
        )
        (issue,) = detect_no_accepted_solution(state)
        assert issue.kind == 'config_no_accepted_solution'
        assert issue.severity == IssueSeverity.ERROR

    def test_accepted_or_tle_counts_as_accepted(self):
        state = _state(
            solutions=[_solution('sol/ac.cpp', ExpectedOutcome.ACCEPTED_OR_TLE)]
        )
        assert detect_no_accepted_solution(state) == []

    def test_a_package_with_no_solutions_at_all(self):
        assert len(detect_no_accepted_solution(_state(solutions=[]))) == 1

    def test_no_validator(self):
        (issue,) = detect_no_validator(_state(has_validator=False))
        assert issue.kind == 'config_no_validator'

    def test_no_samples(self):
        (issue,) = detect_no_samples(_state(sample_count=0))
        assert issue.kind == 'config_no_samples'

    def test_empty_test_group_one_issue_per_group(self):
        state = _state(group_test_counts={'samples': 2, 'big': 0, 'huge': 0})
        issues = detect_empty_test_groups(state)
        assert [issue.group for issue in issues] == ['big', 'huge']

    def test_an_empty_samples_group_is_reported_only_as_no_samples(self):
        # Saying both "no samples" and "group samples is empty" names one
        # mistake twice, the way UNEXPECTED_SCORE is excluded upstream.
        state = _state(sample_count=0, group_test_counts={'samples': 0, 'main': 1})
        assert detect_empty_test_groups(state) == []
        assert len(detect_no_samples(state)) == 1

    def test_no_statements_at_all(self):
        (issue,) = detect_missing_statement_languages(_state(statement_languages=[]))
        assert issue.hasNoStatements
        assert issue.missing == []

    def test_a_contest_language_with_no_statement(self):
        state = _state(statement_languages=['en'], contest_languages=['en', 'pt'])
        (issue,) = detect_missing_statement_languages(state)
        assert issue.missing == ['pt']
        assert not issue.hasNoStatements

    def test_no_contest_languages_means_no_language_finding(self):
        state = _state(statement_languages=['en'], contest_languages=[])
        assert detect_missing_statement_languages(state) == []

    def test_explanation_missing_a_language(self):
        state = _state(
            statement_languages=['en', 'pt'],
            explanation_languages={0: ['en']},
            explanation_paths={0: pathlib.Path('tests/samples/000.rbx.tex')},
        )
        (issue,) = detect_explanation_languages(state)
        assert issue.sample == 0
        assert issue.missing == ['pt']

    def test_explanation_covering_every_language_is_fine(self):
        state = _state(
            statement_languages=['en', 'pt'],
            explanation_languages={0: ['pt', 'en']},
            explanation_paths={0: pathlib.Path('tests/samples/000.rbx.tex')},
        )
        assert detect_explanation_languages(state) == []

    def test_detect_all_config_puts_errors_first(self):
        state = _state(
            solutions=[_solution('sol/wa.cpp', ExpectedOutcome.WRONG_ANSWER)],
            has_validator=False,
        )
        issues = detect_all_config(state)
        assert [issue.severity for issue in issues] == [
            IssueSeverity.ERROR,
            IssueSeverity.WARNING,
        ]
```

Write a `_solution(path, outcome)` helper if the test file has no equivalent; check what the existing classes use to build a `Solution`.

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/issues_test.py::TestConfigDetectors -v`
Expected: FAIL — no `config_detectors` module.

**Step 3: Implement**

```python
"""The config detectors: pure functions from a package's config to its issues.

The mirror of `detectors`, and under the same contract -- a detector reads only
the `ConfigState` it was handed, never a `Package`, a path, a console or a
contextvar. What that buys is the same thing it bought there: the whole suite is
exercised against states built by hand, with no package on disk and no sandbox.

These answer a different question from the run detectors. A run detector asks
what happened; these ask whether the package was ever in a state worth running.
"""

from typing import Callable, List

from rbx.box.issues.config_state import ConfigState
from rbx.box.issues.schema import (
    EmptyTestGroupIssue,
    ExplanationMissingLanguageIssue,
    Issue,
    IssueSeverity,
    MissingStatementLanguageIssue,
    NoAcceptedSolutionIssue,
    NoSamplesIssue,
    NoValidatorIssue,
)
from rbx.box.schema import ExpectedOutcome

SAMPLES_GROUP = 'samples'


def detect_no_accepted_solution(state: ConfigState) -> List[Issue]:
    """No solution claims to be correct."""
    for solution in state.solutions:
        if solution.outcome in (
            ExpectedOutcome.ACCEPTED,
            ExpectedOutcome.ACCEPTED_OR_TLE,
        ):
            return []
    return [NoAcceptedSolutionIssue()]


def detect_no_validator(state: ConfigState) -> List[Issue]:
    """Nothing checks that the generated tests obey the constraints."""
    if state.has_validator:
        return []
    return [NoValidatorIssue()]


def detect_no_samples(state: ConfigState) -> List[Issue]:
    """The statement will have nothing to show the contestant."""
    if state.sample_count > 0:
        return []
    return [NoSamplesIssue()]


def detect_empty_test_groups(state: ConfigState) -> List[Issue]:
    """A declared group that generated nothing.

    The samples group is skipped: an empty one is already reported, better, by
    `detect_no_samples`, and naming it twice would make one mistake look like
    two -- the same reason `detect_unmet_expectations` skips UNEXPECTED_SCORE.
    """
    return [
        EmptyTestGroupIssue(group=group)
        for group, count in state.group_test_counts.items()
        if count == 0 and group != SAMPLES_GROUP
    ]


def detect_missing_statement_languages(state: ConfigState) -> List[Issue]:
    """No statement at all, or none for a language the contest declares.

    Silent outside a contest, where rbx has no way to know which languages were
    wanted: a problem shipping only English is not thereby missing Portuguese.
    """
    if not state.statement_languages:
        return [MissingStatementLanguageIssue(hasNoStatements=True)]
    have = set(state.statement_languages)
    missing = [lang for lang in state.contest_languages if lang not in have]
    if not missing:
        return []
    return [MissingStatementLanguageIssue(missing=missing)]


def detect_explanation_languages(state: ConfigState) -> List[Issue]:
    """A blocks-file explanation that covers only some statements.

    Fires per sample, because each file is authored separately and each is fixed
    separately.
    """
    issues: List[Issue] = []
    for index, languages in sorted(state.explanation_languages.items()):
        covered = set(languages)
        missing = [
            lang for lang in state.statement_languages if lang not in covered
        ]
        if not missing:
            continue
        path = state.explanation_paths.get(index)
        if path is None:
            continue
        issues.append(
            ExplanationMissingLanguageIssue(
                sample=index, path=path, missing=missing
            )
        )
    return issues


CONFIG_DETECTORS: List[Callable[[ConfigState], List[Issue]]] = [
    detect_no_accepted_solution,
    detect_no_validator,
    detect_no_samples,
    detect_empty_test_groups,
    detect_missing_statement_languages,
    detect_explanation_languages,
]


def detect_all_config(state: ConfigState) -> List[Issue]:
    """Every config issue, worst first.

    Sorted the way `detect_all` sorts: stable, by severity only, so the detector
    order and the declaration order survive inside each band.
    """
    issues: List[Issue] = []
    for detector in CONFIG_DETECTORS:
        issues.extend(detector(state))
    return sorted(issues, key=lambda issue: issue.severity != IssueSeverity.ERROR)
```

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/issues_test.py -v`
Expected: PASS.

**Step 5: Commit**

`feat(issues): add the six config-level detectors`

---

## Task 5: Wording and rendering

**Files:**
- Modify: `rbx/box/issues/rendering.py`
- Test: `tests/rbx/box/issues_test.py` (extend `TestRendering`)

**Step 1: Write the failing tests**

```python
class TestConfigRendering:
    def test_summarizes_each_config_kind(self):
        assert summarize(NoAcceptedSolutionIssue()) == (
            'no solution is declared as accepted'
        )
        assert summarize(NoValidatorIssue()) == 'the problem has no validator'
        assert summarize(NoSamplesIssue()) == 'the problem has no samples'
        assert summarize(EmptyTestGroupIssue(group='big')) == (
            "test group 'big' has no tests"
        )
        assert summarize(
            MissingStatementLanguageIssue(hasNoStatements=True)
        ) == 'the problem has no statement'
        assert summarize(MissingStatementLanguageIssue(missing=['pt', 'es'])) == (
            'no statement for language(s): pt, es'
        )

    def test_never_run_still_lists_config_issues(self, capsys):
        report = IssueReport(neverRun=True, issues=[NoValidatorIssue()])
        print_report(report)
        out = capsys.readouterr().out
        assert 'no validator' in out
        assert 'has not been run yet' in out

    def test_never_run_with_no_issues_is_unchanged(self, capsys):
        print_report(IssueReport(neverRun=True))
        out = capsys.readouterr().out
        assert 'has not been run yet' in out
        assert 'rbx run' in out

    def test_config_issues_sort_before_run_issues_in_a_band(self):
        report = build_combined_report(...)  # see Task 6
        ...
```

Follow whatever capture idiom `TestRendering` already uses — it may use a Rich console recorder rather than `capsys`. Match it rather than inventing a second one.

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/issues_test.py::TestConfigRendering -v`
Expected: FAIL — `summarize` returns `'unknown issue'`.

**Step 3: Implement**

In `summarize`, before the `return 'unknown issue'` fallback:

```python
    if isinstance(issue, NoAcceptedSolutionIssue):
        return 'no solution is declared as accepted'
    if isinstance(issue, NoValidatorIssue):
        return 'the problem has no validator'
    if isinstance(issue, NoSamplesIssue):
        return 'the problem has no samples'
    if isinstance(issue, EmptyTestGroupIssue):
        return f"test group '{issue.group}' has no tests"
    if isinstance(issue, MissingStatementLanguageIssue):
        if issue.hasNoStatements:
            return 'the problem has no statement'
        return f'no statement for language(s): {", ".join(issue.missing)}'
    if isinstance(issue, ExplanationMissingLanguageIssue):
        return (
            f'sample {issue.sample}: explanation missing for '
            f'language(s): {", ".join(issue.missing)}'
        )
```

In `explain`, add detail only where the one-liner leaves something out:

```python
    if isinstance(issue, NoAcceptedSolutionIssue):
        return [
            'Without an accepted solution nothing establishes what a correct '
            'output is, so the outputs this package generates are unverified.',
            'Declare one with `outcome: accepted` in problem.rbx.yml.',
        ]
    if isinstance(issue, ExplanationMissingLanguageIssue):
        return [
            f'file: {href(issue.path)}',
            'A language this file does not define is not an error at build '
            'time -- the explanation is simply absent from that language.',
        ]
```

In `print_report`, the `neverRun` branch stops returning early:

```python
    console.console.print(_headline(report))
    if report.neverRun:
        console.console.print(
            '[info]Run [item]rbx run[/item] to populate it.[/info]'
        )
        # Config issues are true whether or not the problem was ever run, so
        # they are printed under this notice rather than suppressed by it.
    if not report.issues:
        return
    console.console.print()
```

And `_headline` says something true for a never-run problem that nonetheless has findings:

```python
def _headline(report: IssueReport) -> str:
    errors = len(report.errors())
    warnings = len(report.warnings())
    if report.neverRun:
        if not errors and not warnings:
            return '[warning]This problem has not been run yet.[/warning]'
        return (
            f'{_counts(errors, warnings)} '
            '[warning](this problem has not been run yet)[/warning]'
        )
    ...
```

Extract the `n error(s), m warning(s)` fragment into a `_counts(errors, warnings)` helper so the two branches cannot drift.

Finally, sort config first within a severity band. In `contest.build_report` (Task 6), sort the merged list with a two-key sort:

```python
    key=lambda issue: (
        issue.severity != IssueSeverity.ERROR,
        issue.family != IssueFamily.CONFIG,
    )
```

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/issues_test.py -v`
Expected: PASS.

**Step 5: Commit**

`feat(issues): render config-level issues alongside run ones`

---

## Task 6: `build_report` merges the two families

**Files:**
- Modify: `rbx/box/issues/contest.py`
- Modify: `rbx/box/issues/__init__.py`
- Test: `tests/rbx/box/issues_test.py`

**Step 1: Write the failing test**

```python
class TestBuildReportMergesFamilies:
    def test_config_issues_survive_a_never_run_problem(self, tmp_path):
        state = ConfigState(
            solutions=[], has_validator=False,
            group_test_counts={}, sample_count=0, statement_languages=[],
        )
        report = build_report(tmp_path / 'runs', config_state=state)
        assert report.neverRun
        assert report.issues
        assert all(i.family == IssueFamily.CONFIG for i in report.issues)

    def test_no_config_state_leaves_the_report_run_only(self, tmp_path):
        report = build_report(tmp_path / 'runs')
        assert report.neverRun
        assert report.issues == []
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/issues_test.py::TestBuildReportMergesFamilies -v`
Expected: FAIL — `build_report() got an unexpected keyword argument 'config_state'`.

**Step 3: Implement**

```python
def build_report(
    runs_dir: pathlib.Path,
    config_state: Optional[ConfigState] = None,
) -> IssueReport:
    """Everything known about a problem: what its config says and what its last
    run revealed.

    Still the single place an `IssueReport` is built, so the problem command,
    the contest table and the post-run section cannot disagree about what "no
    run" or "no issues" looks like. `config_state` is optional because the
    post-run section already has the package loaded and the contest collector
    may fail to load one at all -- an absent state means the run family only,
    never an empty package.
    """
    config_issues = detect_all_config(config_state) if config_state else []
    state = load_run_state(runs_dir)
    run_issues = detect_all(state) if state is not None else []

    return IssueReport(
        neverRun=state is None,
        ranAt=state.ran_at if state is not None else None,
        runsDir=str(state.runs_dir) if state is not None else None,
        issues=_ordered(config_issues + run_issues),
    )
```

with

```python
def _ordered(issues: List[Issue]) -> List[Issue]:
    """Errors before warnings, config before run inside each band.

    Config first because the run is downstream of the config: "no solution is
    declared as accepted" explains half the verdict failures under it, and
    reading it after them is reading the answer after the puzzle.
    """
    return sorted(
        issues,
        key=lambda issue: (
            issue.severity != IssueSeverity.ERROR,
            issue.family != IssueFamily.CONFIG,
        ),
    )
```

In `collect_contest_rows`, collect a config state per problem inside the existing `cd.new_package_cd(...)` block and pass it to `build_report`. The function becomes `async` — check every caller (`rbx/box/contest/main.py`) and add `await`. The existing `except Exception -> failed_to_load=True` already covers a package that will not load; do not add a second handler.

Export `ConfigState`, `CONFIG_DETECTORS`, `IssueFamily`, `collect_config_state`, `detect_all_config` and the six new kinds from `__init__.py`, adding each to `__all__`.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/issues_test.py -v`
Expected: PASS.

**Step 5: Commit**

`feat(issues): merge config and run findings into one report`

---

## Task 7: `rbx summary` grows a Checks section and JSON output

**Files:**
- Modify: `rbx/box/summary.py`
- Modify: `rbx/box/cli/commands/run.py:388-405`
- Test: `tests/rbx/box/test_summary.py`

**Step 1: Write the failing tests**

```python
class TestSummaryChecks:
    def test_json_output_carries_the_summary_and_the_issues(self):
        payload = json.loads(summary_to_json(a_summary, [NoValidatorIssue()]))
        assert payload['version'] == SUMMARY_FORMAT_VERSION
        assert payload['summary']['name'] == a_summary.name
        assert payload['issues'][0]['kind'] == 'config_no_validator'
        assert payload['issues'][0]['family'] == 'config'

    def test_checks_section_is_omitted_when_there_is_nothing_to_say(self, ...):
        # print_checks_section([]) prints nothing at all -- not an empty heading.
        ...

    def test_checks_section_lists_findings(self, ...):
        ...
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/test_summary.py -v`
Expected: FAIL — no `summary_to_json`.

**Step 3: Implement**

In `summary.py`:

```python
# Independent of ISSUES_FORMAT_VERSION on purpose: the `ProblemSummary` shape
# and the `Issue` shape change for unrelated reasons, and pinning them to one
# number would make each bump lie about the other.
SUMMARY_FORMAT_VERSION = 1


class SummaryFormat(str, Enum):
    RICH = 'rich'
    JSON = 'json'


def summary_to_json(summary: ProblemSummary, issues: List[Issue]) -> str:
    return SummaryOutput(summary=summary, issues=issues).model_dump_json(indent=2)
```

Give `print_problem_summary` a `config_issues: List[Issue]` argument and print the section after Solutions:

```python
    if config_issues:
        console.console.print()
        console.console.print('[bold]Checks[/bold]')
        for issue in config_issues:
            marker = issues.severity_marker(issue)
            console.console.print(f'{marker} {issues.summarize(issue)}')
            if not detailed:
                continue
            for line in issues.explain(issue):
                console.console.print(
                    Padding(Text.from_markup(f'[info]{line}[/info]'), (0, 0, 0, 4))
                )
```

Export `severity_marker` from the issues package rather than reaching into `_SEVERITY_MARKER` — `SLF` bans the private access, and the marker table belongs to the renderer.

In `run.py`'s `summary_cmd`, add the `--format` option mirroring `issues_cmd`'s, collect the state, and branch:

```python
    pkg = package.find_problem_package_or_die()
    config_issues = issues.detect_all_config(
        await issues.collect_config_state(pkg)
    )
    if format is SummaryFormat.JSON:
        entries = await testcase_extractors.extract_generation_testcases_from_groups()
        print(
            summary.summary_to_json(
                summary.get_problem_summary(
                    pkg, package.get_solutions(), entries
                ),
                config_issues,
            )
        )
        return
    await summary.print_problem_summary(
        pkg, detailed=detailed, config_issues=config_issues
    )
```

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/test_summary.py -v`
Expected: PASS.

Then run it for real against a package that has something wrong:

```bash
cd rbx/testdata/problems/<some-problem> && uv run rbx summary
uv run rbx summary --format json | python -m json.tool > /dev/null && echo 'valid json'
```

**Step 5: Commit**

`feat(summary): report config-level checks and add --format json`

---

## Task 8: `rbx issues` picks up the family, plus docs

**Files:**
- Modify: `rbx/box/cli/commands/issues.py`
- Modify: `rbx/box/contest/main.py` (the `issues` and `summary` commands)
- Modify: `rbx/box/cli/__init__.py` (only if a `help=` string changes)
- Modify: `docs/` — the CLI reference and wherever `rbx issues` is documented
- Test: `tests/rbx/box/issues_test.py`, `tests/rbx/box/lazy_cli_test.py`

**Step 1: Wire the command**

`issues_cmd` becomes async (add `@syncer.sync` the way `summary_cmd` has it) because collecting a config state is async. Its docstring gains a line saying why it is no longer the cheap sync command it was, pointing at the design doc.

```python
    pkg = package.find_problem_package_or_die()
    config_state = await issues.collect_config_state(pkg)
    try:
        report = issues.build_report(
            package.get_problem_runs_dir(), config_state=config_state
        )
    except issues.UnsupportedReportVersion as exception:
        ...
```

`rbx contest issues` passes each problem's contest languages down. Get them from `contest.expanded_statements`:

```python
    contest_languages = [st.language for st in contest.expanded_statements]
```

and thread that into `collect_contest_rows`.

**Step 2: Check the lazy CLI table**

If any `help=` string changed, update the matching `LazyCommand` row in `rbx/box/cli/__init__.py`. Run:

`uv run pytest tests/rbx/box/lazy_cli_test.py -v`
Expected: PASS. This test exists precisely to catch the copy drifting.

**Step 3: Regenerate the completion spec**

The drift test will flag the new `--format` flag on `rbx summary`. Regenerate the spec directly rather than via `mise run gen-completion-spec`, which is a no-op in a worktree. Find the command the drift test names and run it.

Run: `uv run pytest tests/rbx/box/completion -v`
Expected: PASS.

**Step 4: Docs**

Follow [`docs/plans/docs-writing-style-guide.md`](docs-writing-style-guide.md). Two things to write:

- Wherever `rbx issues` is documented, a section on the config family: what the six checks are, that they need no run, and that `rbx summary` shows the same findings.
- The CLI reference row for `rbx summary --format`. **Hand-insert the row**; do not regenerate `cli.md`, which has drifted badly from the generator and would produce an enormous unrelated diff.

Verify with a non-strict build — `--strict` fails on about nine pre-existing unrelated warnings:

```bash
uv run mkdocs build 2>&1 | tail -20
```

**Step 5: End-to-end check**

```bash
cd rbx/testdata/problems/<a problem with no validator>
uv run rbx issues
uv run rbx issues --format json | python -m json.tool | head -30
uv run rbx summary
```

Confirm the same finding is worded identically by both commands, and that `rbx issues` on a never-run problem now lists config findings instead of only "has not been run yet".

**Step 6: Commit**

`feat(issues): fold config checks into rbx issues and rbx contest issues`

---

## Task 9: Review and open the PR

**Step 1:** Run every touched test file:

```bash
uv run pytest tests/rbx/box/issues_test.py tests/rbx/box/test_summary.py \
  tests/rbx/box/lazy_cli_test.py tests/rbx/box/statements/ -v
```

**Step 2:** `uv run ruff check . && uv run ruff format --check .`

**Step 3:** REQUIRED SUB-SKILL: use superpowers:requesting-code-review before opening the PR.

**Step 4:** Open a draft PR against `main` closing #840, with a body in the shape PR #834 used: the problem, what this adds with a worked `$ rbx issues` transcript, the design decisions, and what changed in the format version.

Note for the PR body: `gh pr create` works, but `gh pr edit` and `gh pr view` fail on this repo with a classic-Projects GraphQL error — use `gh api -X PATCH repos/rsalesc/rbx/pulls/N` to edit instead.
