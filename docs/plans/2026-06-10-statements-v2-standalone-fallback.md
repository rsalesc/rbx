# Contest-less default-template fallback (S15) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let `rbx st b` / `rbx tut b` build an *rbx* problem statement outside a contest (or when a contest has no matching standalone statement) by falling back to the bundled default preset template, with clear messaging.

**Architecture:** Add a resolver-owned `resolve_standalone(statement, kind)` that returns a `StandaloneResolution` (real contest statement on a single match; a synthetic one derived from the bundled preset's `contest.rbx.yml` on zero matches). `build_statement` swaps its two resolver calls for this one and builds an empty/neutral `contest.*` namespace when no real contest is present. `>1` candidates and an unselected-dispatcher both stay hard errors.

**Tech Stack:** Python 3.14, Pydantic v2, Typer, pytest, the statements-v2 overlay engine, the e2e YAML DSL (`tests/e2e/`).

**Design doc:** `docs/plans/2026-06-10-statements-v2-standalone-fallback-design.md`.

---

## Conventions

- Run a single test: `uv run pytest tests/path::test_name -v`.
- Lint/format before each commit: `uv run ruff check --fix . && uv run ruff format .`.
- Commit with the `/commit` workflow (`.claude/skills/commit.md`): conventional commits, append `Co-Authored-By: Claude <noreply@anthropic.com>`, never amend.
- Single quotes; absolute imports only.

---

## Task 1: Directory-variant resource helper

`config.get_resources_file` is file-only; the overlay stager needs a *directory* path to the bundled preset chrome.

**Files:**
- Modify: `rbx/config.py` (after `get_resources_file`, ~line 108)
- Test: `tests/rbx/test_config.py` (create if absent; otherwise append)

**Step 1: Write the failing test**

```python
import pathlib

from rbx import config


def test_get_resources_dir_returns_existing_directory():
    path = config.get_resources_dir(
        pathlib.Path('presets') / 'default' / 'contest'
    )
    assert path.is_dir()
    assert (path / 'contest.rbx.yml').is_file()


def test_get_resources_dir_raises_for_missing():
    import pytest

    with pytest.raises(FileNotFoundError):
        config.get_resources_dir(pathlib.Path('does') / 'not' / 'exist')
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/test_config.py -v`
Expected: FAIL with `AttributeError: module 'rbx.config' has no attribute 'get_resources_dir'`.

**Step 3: Write minimal implementation**

In `rbx/config.py`, directly after `get_resources_file`:

```python
def get_resources_dir(path: pathlib.Path) -> pathlib.Path:
    dir_path = importlib.resources.files('rbx') / 'resources' / path  # type: ignore
    if dir_path.is_dir():
        return dir_path  # type: ignore
    raise FileNotFoundError(f'Directory {path} not found in {_RESOURCES_PKG}.')
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/test_config.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/config.py tests/rbx/test_config.py
git commit -m "feat(config): add get_resources_dir for bundled resource dirs"
```

---

## Task 2: `resolve_standalone` + `StandaloneResolution` in the resolver

The decision logic. Pure-ish: contest discovery is mocked in tests; the bundled-default load is real (the preset ships in-repo).

**Files:**
- Modify: `rbx/box/statements/resolver.py`
- Test: `tests/rbx/box/statements/test_resolver.py`

**Step 1: Write the failing tests**

Append to `tests/rbx/box/statements/test_resolver.py` (reuse the existing `_problem_statement` / `_contest_statement` helpers at the top of that file):

```python
import pathlib
from unittest import mock

from rbx.box.statements.schema import StatementKind


class TestResolveStandalone:
    def test_single_match_returns_real_resolution(self):
        st = _problem_statement(language='en', variant='default')
        contest = mock.Mock()
        contest.expanded_statements = [
            _contest_statement('main-en', language='en', variant='default'),
            _contest_statement('main-pt', language='pt', variant='default'),
        ]
        with (
            mock.patch.object(
                resolver, 'find_contest_for_problem', return_value=contest
            ),
            mock.patch.object(
                resolver.contest_package,
                'find_contest',
                return_value=pathlib.Path('/contest'),
            ),
        ):
            res = resolver.resolve_standalone(st, StatementKind.STATEMENTS)
        assert res.is_fallback is False
        assert res.contest is contest
        assert res.contest_statement.name == 'main-en'
        assert res.contest_root == pathlib.Path('/contest')

    def test_multiple_candidates_still_errors(self):
        st = _problem_statement(language='en', variant='default')
        contest = mock.Mock()
        contest.expanded_statements = [
            _contest_statement('a', language='en', variant='default'),
            _contest_statement('b', language='en', variant='default'),
        ]
        with mock.patch.object(
            resolver, 'find_contest_for_problem', return_value=contest
        ):
            with pytest.raises(StatementResolverError):
                resolver.resolve_standalone(st, StatementKind.STATEMENTS)

    def test_no_contest_falls_back_to_bundled_default(self):
        st = _problem_statement(language='en', variant='default')
        with (
            mock.patch.object(
                resolver, 'find_contest_for_problem', return_value=None
            ),
            mock.patch.object(
                resolver.contest_package, 'find_contest_root', return_value=None
            ),
        ):
            res = resolver.resolve_standalone(st, StatementKind.STATEMENTS)
        assert res.is_fallback is True
        assert res.contest is None
        # synthetic statement is rebound to the problem's (language, variant)
        assert res.contest_statement.language == 'en'
        assert res.contest_statement.variant == 'default'
        assert res.contest_statement.standaloneProblemTemplate is not None
        # contest_root is the bundled preset contest dir
        assert (res.contest_root / 'contest.rbx.yml').is_file()

    def test_fallback_rebinds_non_english_language(self):
        st = _problem_statement(language='pt', variant='short')
        with (
            mock.patch.object(
                resolver, 'find_contest_for_problem', return_value=None
            ),
            mock.patch.object(
                resolver.contest_package, 'find_contest_root', return_value=None
            ),
        ):
            res = resolver.resolve_standalone(st, StatementKind.STATEMENTS)
        assert res.contest_statement.language == 'pt'
        assert res.contest_statement.variant == 'short'

    def test_tutorials_kind_uses_preset_tutorial_template(self):
        st = _problem_statement(language='en', variant='default')
        with (
            mock.patch.object(
                resolver, 'find_contest_for_problem', return_value=None
            ),
            mock.patch.object(
                resolver.contest_package, 'find_contest_root', return_value=None
            ),
        ):
            res = resolver.resolve_standalone(st, StatementKind.TUTORIALS)
        assert res.is_fallback is True
        # preset tutorial entry's standalone template is editorial.rbx.tex
        assert res.contest_statement.standaloneProblemTemplate == pathlib.Path(
            'statements/editorial.rbx.tex'
        )

    def test_contest_present_no_match_falls_back(self):
        st = _problem_statement(language='pt', variant='default')
        contest = mock.Mock()
        contest.expanded_statements = [
            _contest_statement('main-en', language='en', variant='default'),
        ]
        with mock.patch.object(
            resolver, 'find_contest_for_problem', return_value=contest
        ):
            res = resolver.resolve_standalone(st, StatementKind.STATEMENTS)
        assert res.is_fallback is True
        assert res.contest is contest  # real contest metadata is preserved

    def test_unselected_dispatcher_errors_with_hint(self):
        st = _problem_statement(language='en', variant='default')
        with (
            mock.patch.object(
                resolver, 'find_contest_for_problem', return_value=None
            ),
            mock.patch.object(
                resolver.contest_package,
                'find_contest_root',
                return_value=pathlib.Path('/contest'),
            ),
            mock.patch.object(
                resolver.contest_state,
                'resolve_explicit_selection',
                return_value=None,
            ),
            mock.patch.object(
                resolver.contest_package,
                'discover_contest_variants',
                return_value=['div1', 'div2'],
            ),
        ):
            with pytest.raises(StatementResolverError):
                resolver.resolve_standalone(st, StatementKind.STATEMENTS)
```

**Step 2: Run to verify they fail**

Run: `uv run pytest tests/rbx/box/statements/test_resolver.py::TestResolveStandalone -v`
Expected: FAIL (`AttributeError: ... has no attribute 'resolve_standalone'`).

**Step 3: Implement**

In `rbx/box/statements/resolver.py`:

- Add imports at the top:
```python
import dataclasses

from rbx import config
from rbx.box.statements.schema import Statement, StatementKind
from rbx.box.yaml_validation import load_yaml_model
```
(`Statement` is already imported — extend that line to add `StatementKind`; `Contest`/`ContestStatement`/`contest_package`/`contest_state` are already imported.)

- Add the resource constant near the top (after imports):
```python
# The bundled default chrome reused for contest-less builds lives in the default
# preset's contest dir (design S15, decision 3).
_PRESET_CONTEST_RESOURCE = pathlib.Path('presets') / 'default' / 'contest'
```

- Refactor candidate-finding out of `select_standalone_contest_statement` so both it and the new resolver share it:
```python
def _standalone_candidates(
    statement: Statement, contest_statements: List[ContestStatement]
) -> List[ContestStatement]:
    return [
        cs
        for cs in contest_statements
        if cs.standaloneProblemTemplate is not None
        and (cs.language, cs.variant) == (statement.language, statement.variant)
    ]
```
Then change the `candidates = [...]` comprehension inside `select_standalone_contest_statement` to `candidates = _standalone_candidates(statement, contest_statements)`.

- Add the new dataclass + functions (place after `select_standalone_contest_statement`):
```python
@dataclasses.dataclass
class StandaloneResolution:
    """Resolved inputs for a standalone problem-statement build (design S15).

    ``contest_statement`` is a real contest statement (single match) or a
    synthetic one derived from the bundled default preset (fallback).
    ``contest`` is the real owning contest when present (its metadata feeds the
    ``contest.*`` namespace), ``None`` when there is no contest at all.
    ``contest_root`` is the dir the template + chrome resolve against (the real
    contest root, or the bundled preset contest dir).
    """

    contest: Optional[Contest]
    contest_statement: ContestStatement
    contest_root: pathlib.Path
    is_fallback: bool


def _require_no_unselected_dispatcher() -> None:
    """Hard-error (with the ``-C`` hint) when a contest root exists but is a
    dispatcher with no explicit selection. That is a 'forgot to select a
    contest' situation, not a genuinely contest-less problem, so we must NOT
    fall back to the bundled default here (design S15, decision 2)."""
    contest_root = contest_package.find_contest_root()
    if contest_root is not None and contest_state.resolve_explicit_selection() is None:
        variants = contest_package.discover_contest_variants(contest_root)
        available = sorted(v for v in variants if v is not None)
        if available:
            with StatementResolverError() as err:
                err.print(
                    '[error]Building a problem statement requires a contest, but '
                    'the contest here is a dispatcher with no explicit selection. '
                    f'Pass [item]-C <id>[/item] or set [item]RBX_CONTEST=<id>[/item]. '
                    f'Available contests: [item]{available}[/item].[/error]'
                )


def _bundled_default_statement(
    statement: Statement, kind: StatementKind
) -> tuple[ContestStatement, pathlib.Path]:
    """Synthesize a contest statement from the bundled default preset, rebound to
    the problem statement's ``(language, variant)`` so it matches any language."""
    preset_root = config.get_resources_dir(_PRESET_CONTEST_RESOURCE)
    preset_contest = load_yaml_model(preset_root / 'contest.rbx.yml', Contest)
    src_list = (
        preset_contest.expanded_tutorials
        if kind == StatementKind.TUTORIALS
        else preset_contest.expanded_statements
    )
    src = src_list[0]
    synthetic = src.model_copy(
        update={'language': statement.language, 'variant': statement.variant}
    )
    return synthetic, preset_root


def resolve_standalone(
    statement: Statement, kind: StatementKind
) -> StandaloneResolution:
    """Resolve the contest statement for a standalone problem-statement build.

    Returns a real contest statement when exactly one matches the problem's
    ``(language, variant)`` and carries a ``standaloneProblemTemplate``; on zero
    matches falls back to the bundled default preset template (design S15 /
    issue #571). ``>1`` matches and an unselected dispatcher both hard-error.
    """
    contest = find_contest_for_problem()
    contest_statements: List[ContestStatement] = []
    if contest is not None:
        contest_statements = (
            contest.expanded_tutorials
            if kind == StatementKind.TUTORIALS
            else contest.expanded_statements
        )
    candidates = _standalone_candidates(statement, contest_statements)

    if len(candidates) == 1:
        return StandaloneResolution(
            contest=contest,
            contest_statement=candidates[0],
            contest_root=contest_package.find_contest(),
            is_fallback=False,
        )
    if len(candidates) > 1:
        # Reuse the ambiguity error message (raises).
        select_standalone_contest_statement(statement, contest_statements)
        raise AssertionError('unreachable')  # pragma: no cover

    if contest is None:
        _require_no_unselected_dispatcher()
    synthetic, preset_root = _bundled_default_statement(statement, kind)
    return StandaloneResolution(
        contest=contest,
        contest_statement=synthetic,
        contest_root=preset_root,
        is_fallback=True,
    )
```

**Step 4: Run to verify they pass**

Run: `uv run pytest tests/rbx/box/statements/test_resolver.py -v`
Expected: PASS (all existing + new `TestResolveStandalone` tests).

**Step 5: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/statements/resolver.py tests/rbx/box/statements/test_resolver.py
git commit -m "feat(statements): resolve_standalone with bundled-default fallback"
```

---

## Task 3: Wire `build_statement` to the fallback

**Files:**
- Modify: `rbx/box/statements/build_statements.py` (the `is_rbx()` branch, ~lines 261–307)

**Step 1: Replace the resolution + contest-context block**

Replace these lines:

```python
    if statement.type.is_rbx():
        contest = resolver.require_contest_for_problem()
        contest_candidates = (
            contest.expanded_tutorials
            if kind == StatementKind.TUTORIALS
            else contest.expanded_statements
        )
        contest_statement = resolver.select_standalone_contest_statement(
            statement, contest_candidates
        )
        contest_root = contest_package.find_contest()
        assert contest_statement.file is not None
        chrome_dir = utils.abspath(contest_root / contest_statement.file).parent
```

with:

```python
    if statement.type.is_rbx():
        res = resolver.resolve_standalone(statement, kind)
        contest = res.contest
        contest_statement = res.contest_statement
        contest_root = res.contest_root
        if res.is_fallback:
            console.console.print(
                '[warning]No contest statement provides a standalone template '
                f'for {statement.language}/{statement.variant}; building with '
                "rbx's bundled default template.[/warning]"
            )
        assert contest_statement.file is not None
        chrome_dir = utils.abspath(contest_root / contest_statement.file).parent
```

And replace the `contest_ctx = ContestRenderContext(...)` block:

```python
        contest_ctx = ContestRenderContext(
            title=naming.get_contest_title(
                lang=statement.language, statement=contest_statement, contest=contest
            ),
            vars=contest.expanded_vars,
            params=contest_statement.expanded_vars,
            location=contest_statement.location,
            date=contest_statement.date,
        )
```

with (guard the `contest is None` case — case a):

```python
        contest_ctx = ContestRenderContext(
            title=(
                naming.get_contest_title(
                    lang=statement.language,
                    statement=contest_statement,
                    contest=contest,
                )
                if contest is not None
                else ''
            ),
            vars=contest.expanded_vars if contest is not None else {},
            params=contest_statement.expanded_vars,
            location=contest_statement.location,
            date=contest_statement.date,
        )
```

**Step 2: Verify existing statement build tests still pass**

Run: `uv run pytest tests/rbx/box/statements -v`
Expected: PASS (the contest-present path is unchanged behavior).

**Step 3: Commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/statements/build_statements.py
git commit -m "feat(statements): build st/tut standalone via bundled default fallback"
```

---

## Task 4: e2e — contest-less `st b` and `tut b`

A standalone problem (no `contest.rbx.yml`) must build a statement and a tutorial via the bundled default. Emit TeX (no pdflatex dependency) and assert the bundled body markers, plus the fallback warning.

**Files (create):**
- `tests/e2e/testdata/standalone-statement/problem.rbx.yml`
- `tests/e2e/testdata/standalone-statement/statement/statement.rbx.tex`
- `tests/e2e/testdata/standalone-statement/statement/editorial.rbx.tex`
- `tests/e2e/testdata/standalone-statement/sols/main.cpp`
- `tests/e2e/testdata/standalone-statement/gens/gen.cpp`
- `tests/e2e/testdata/standalone-statement/e2e.rbx.yml`

**Step 1: Author the fixture package.** Copy `tests/e2e/testdata/with-statement/A/`'s `problem.rbx.yml`, `statement/statement.rbx.tex`, `sols/main.cpp`, `gens/gen.cpp` into `standalone-statement/` at the fixture root (no contest dir, no `A/` nesting). Add a `tutorials` section to `problem.rbx.yml` pointing at an editorial:

```yaml
tutorials:
  - language: en
    file: statement/editorial.rbx.tex
    type: rbx-tex
```

`statement/editorial.rbx.tex` — a minimal editorial with a legend block:

```latex
%- block legend
Add $A$ and $B$ directly.
%- endblock
```

**Step 2: Author `e2e.rbx.yml`.** Base markers: the bundled `_problem-body.rbx.tex` emits `\includeProblem`; the bundled `_editorial-body.rbx.tex` is included by `editorial.rbx.tex`.

```yaml
scenarios:
  - name: standalone-statement-default
    description: >
      A problem with no contest builds its rbxTeX statement using rbx's bundled
      default template (S15 / #571). We emit TeX (no pdflatex), assert the
      artefact exists and carries the bundled body's \includeProblem macro, and
      check the fallback warning is printed.
    steps:
      - cmd: build
      - cmd: st b --output tex
        expect:
          stdout_contains: "bundled default template"
          files_exist:
            - "build/statement-en.tex"
          file_contains:
            "build/statement-en.tex": 'includeProblem'

  - name: standalone-tutorial-default
    description: >
      The same fallback applies to tutorials (rbx tut b) via the bundled
      editorial template.
    steps:
      - cmd: build
      - cmd: tut b --output tex
        expect:
          files_exist:
            - "build/tutorial-en.tex"
```

**Step 3: Run the scenario**

Run: `uv run pytest tests/e2e -k standalone_statement -v`
(If the e2e collector keys off directory names, run `mise run test-e2e` filtered to `standalone-statement`; see `tests/e2e/README.md`.)
Expected: PASS — both scenarios green.

**Step 4: Commit**

```bash
git add tests/e2e/testdata/standalone-statement
git commit -m "test(e2e): contest-less st/tut build via bundled default"
```

---

## Task 5: e2e — collision surfaces a clear error

A problem-local file named like a chrome file collides with the mirrored preset chrome and must error clearly (consistent with real-contest overlay behavior).

**Files:**
- Create: `tests/e2e/testdata/standalone-statement/statement/icpc.sty` (a 1-line stub, e.g. `% colliding stub`)
- Modify: `tests/e2e/testdata/standalone-statement/e2e.rbx.yml` — add a scenario. (Keep the stub OUT of the package used by Task 4's scenarios — put it in a separate fixture dir if the collision file would break the green scenarios. Prefer a dedicated dir `tests/e2e/testdata/standalone-collision/` mirroring the package + the stub, to keep Task 4 clean.)

Recommended: create a separate `tests/e2e/testdata/standalone-collision/` (copy of `standalone-statement` minus the editorial bits) that also contains `statement/icpc.sty`, with:

```yaml
scenarios:
  - name: standalone-collision-errors
    description: >
      A problem-local asset (icpc.sty) named like the bundled chrome collides
      when the default overlay is staged; the build must fail loudly rather than
      silently shadow the chrome.
    steps:
      - cmd: build
      - cmd: st b --output tex
        expect_exit: 1
        expect:
          stdout_contains: "collision"
```

(Adjust `stdout_contains` to the exact wording `overlay.merge_tree` emits — grep `rbx/box/statements/overlay.py` for the collision error text and match it.)

**Step 1: Verify the collision error wording**

Run: `grep -n "collision\|collide\|already" rbx/box/statements/overlay.py`
Use the real phrase in `stdout_contains`.

**Step 2: Run the scenario**

Run: `uv run pytest tests/e2e -k standalone_collision -v`
Expected: PASS (the scenario asserts a failing build).

**Step 3: Commit**

```bash
git add tests/e2e/testdata/standalone-collision
git commit -m "test(e2e): contest-less overlay collision errors clearly"
```

---

## Task 6: Docs

**Files:**
- Modify: `rbx/box/statements/CLAUDE.md` (the "A contest is required" line under "Core decisions")
- Modify: `docs/` statement page if one documents the contest requirement (grep first)

**Step 1: Update the module guide.** Change the core-decision bullet from "A contest is required to build an *rbx* problem statement" to note the fallback, e.g.:

> - **A contest is required** to build an *rbx* problem statement — the contest owns the templates. **If none is found** (no contest, or no matching standalone statement), `rbx st b` / `rbx tut b` fall back to rbx's **bundled default template** (the default preset chrome), rebound to the problem's `(language, variant)`. Static types (`tex`/`md`/`pdf`) always build standalone. (design S15 / #571)

Add a one-line note under `resolver.py`'s description that `resolve_standalone` is the entry point and `select_standalone_contest_statement` is now a helper it shares.

**Step 2: Update docs site if applicable.** Run `grep -rn "requires a contest\|outside a contest\|contest is required" docs/` and amend any user-facing page to mention the bundled default. Verify with a non-strict build (`mise run docs` or the project's docs build) — ignore the ~9 known pre-existing `--strict` warnings.

**Step 3: Commit**

```bash
git add rbx/box/statements/CLAUDE.md docs/
git commit -m "docs(statements): document contest-less bundled-default fallback"
```

---

## Final verification

```bash
uv run pytest tests/rbx/box/statements tests/rbx/test_config.py -v
uv run pytest tests/e2e -k "standalone" -v
uv run ruff check . && uv run ruff format --check .
```
Expected: all green; no lint/format diffs.

Then finish the branch via superpowers:finishing-a-development-branch (PR referencing #571).

---

## Notes / gotchas

- **rbxMarkdown out of scope:** the preset ships only a rbxTeX standalone template; a markdown-output contest-less default is deliberately not handled (design decision 7). If a contest-less rbxMarkdown statement is attempted, it will render the bundled rbxTeX template — acceptable for now; do not expand scope.
- **`model_copy` does not re-validate:** rebinding `(language, variant)` on the synthetic statement is safe (still an rbx type, so `_rbx_only_fields` holds).
- **Preset coupling:** the fallback reads `rbx/resources/presets/default/contest/contest.rbx.yml` and its `statements[0]` / `tutorials[0]`. If the preset's first entry changes shape, the fallback follows it by design — keep the preset's first statement/tutorial a valid rbxTeX standalone template.
- **Test isolation:** no new `@functools.cache` is added here, so no `clear_all_functools_cache` change is needed.
