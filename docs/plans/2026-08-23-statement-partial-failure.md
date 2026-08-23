# Isolated Statement Build Failures Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** A failure building one statement must never stop another statement from building, and a statement must never be silently produced with a problem missing.

**Architecture:** Two changes to the statement build loops. (1) The *outer* loops — over contest statements in `rbx/box/contest/statements.py` and over problem statements in `rbx/box/statements/build_statements.py` — become fault-isolating: each statement builds in its own `try`, failures are collected, and the loop always runs to completion. (2) The *inner* loop over problems in `rbx/box/contest/build_contest_statements.py` drops its exception-type-based tiering (`except (typer.Exit, RbxException): raise`) in favour of an explicit `partial` policy: by default any problem-level failure fails that whole statement; under `--partial` the problem is dropped and the statement is still produced. Failures are reported through the existing `issue_stack` overview plus an explicit end-of-run summary.

**Tech Stack:** Python 3, Typer (CLI), pytest + pytest-asyncio, `rbx.box.sanitizers.issue_stack` (existing failure-reporting mechanism), `rbx.box.exception.RbxException`.

**Design doc:** `docs/plans/2026-08-23-statement-partial-failure-design.md` — read it first. It explains *why* the current tiering is wrong, which this plan assumes.

---

## Background you need before starting

Read these, in this order. You will not be able to write correct code without them.

1. `docs/plans/2026-08-23-statement-partial-failure-design.md` — the design.
2. `rbx/box/statements/CLAUDE.md` — how statements v2 builds. In particular the
   "Build entry points" section.
3. `rbx/box/contest/statements.py` — the contest CLI driver. `_execute_build` at
   `:29` is the outer loop.
4. `rbx/box/contest/build_contest_statements.py` — `build_statement` at `:155`
   holds the inner loop at `:209`.
5. `rbx/box/sanitizers/issue_stack.py` — the `Issue` base class (`:19`) and
   `add_issue` (`:140`). Issues are accumulated and rendered as a tree,
   **deduplicated by message**. That dedup is why we also keep an explicit
   summary; do not rely on the issue tree alone to enumerate failures.

### Vocabulary

- A **contest statement** is one entry under `statements:` in `contest.rbx.yml`.
  There is one per language (per `(language, variant)`), and each produces one
  joined PDF containing every problem. `main-en` and `main-pt` are two contest
  statements.
- A **problem statement** is one entry under `statements:` in a
  `problem.rbx.yml`.
- A contest statement **joins** the problem statements whose
  `(language, variant)` matches its own. A problem that has no matching entry
  cannot be joined.
- **Partial** means: a contest statement was produced without one or more of the
  contest's problems in it.

### Test conventions in this repo

- Tests are `async def` and run under pytest-asyncio; no `@pytest.mark.asyncio`
  decorator is needed (see `tests/rbx/box/contest/test_contest_build_v2.py`).
- `@pytest.mark.test_pkg('contests/<name>')` + the `cleandir_with_testdata`
  fixture copies `rbx/testdata/contests/<name>/` into a temp cwd and yields the
  path. **The fixture directory lives under `rbx/testdata/`, not under
  `tests/`.**
- Contest CLI commands are Typer + `@syncer.sync`; tests call the unwrapped
  coroutine via `inspect.unwrap(...)`. See the `_run` helper at
  `tests/rbx/box/contest/test_contest_build_v2.py:12`.
- Build with `output=StatementType.TeX` to avoid needing pdflatex.
- Single quotes for strings, absolute imports only (ruff `TID`).

### Running tests

```bash
uv run pytest tests/rbx/box/contest/test_contest_partial_build.py -v
```

Never run the full suite to check your work — it has known unrelated local
failures. Run the specific test file.

---

## Task 1: Test fixture with a problem missing a language

A fixture where one contest statement can build and another cannot, so every
later task has something to assert against.

**Files:**
- Create: `rbx/testdata/contests/statements_v2_partial/contest.rbx.yml`
- Create: `rbx/testdata/contests/statements_v2_partial/A/problem.rbx.yml`
- Create: `rbx/testdata/contests/statements_v2_partial/A/statement/statement.rbx.tex`
- Create: `rbx/testdata/contests/statements_v2_partial/A/statement/statement-pt.rbx.tex`
- Create: `rbx/testdata/contests/statements_v2_partial/B/problem.rbx.yml`
- Create: `rbx/testdata/contests/statements_v2_partial/B/statement/statement.rbx.tex`
- Create: `rbx/testdata/contests/statements_v2_partial/statements/contest.rbx.tex`
- Create: `rbx/testdata/contests/statements_v2_partial/statements/problem-standalone.rbx.tex`
- Create: `rbx/testdata/contests/statements_v2_partial/statements/problem-in-contest.rbx.tex`

**Step 1: Copy the existing fixture as a base**

```bash
cp -r rbx/testdata/contests/statements_v2 rbx/testdata/contests/statements_v2_partial
rm -rf rbx/testdata/contests/statements_v2_partial/A/statement/editorial.rbx.tex \
       rbx/testdata/contests/statements_v2_partial/B/statement/editorial.rbx.tex \
       rbx/testdata/contests/statements_v2_partial/statements/editorial-in-contest.rbx.tex \
       rbx/testdata/contests/statements_v2_partial/statements/editorial-sheet.rbx.tex \
       rbx/testdata/contests/statements_v2_partial/statements/editorial-standalone.rbx.tex \
       rbx/testdata/contests/statements_v2_partial/statements/info.jinja.tex
```

We drop tutorials and documents: this fixture exists to exercise statement
isolation only, and fewer moving parts means clearer failures.

**Step 2: Write the contest config**

`rbx/testdata/contests/statements_v2_partial/contest.rbx.yml`:

```yaml
---
name: 'sv2-partial'
titles:
  en: 'Partial Contest'
  pt: 'Contest Parcial'
vars:
  year: 2026
problems:
  - short_name: 'A'
  - short_name: 'B'
statements:
  - name: 'main-pt'
    language: 'pt'
    file: 'statements/contest.rbx.tex'
    type: 'rbxTeX'
    standaloneProblemTemplate: 'statements/problem-standalone.rbx.tex'
    contestProblemTemplate: 'statements/problem-in-contest.rbx.tex'
  - name: 'main-en'
    language: 'en'
    file: 'statements/contest.rbx.tex'
    type: 'rbxTeX'
    standaloneProblemTemplate: 'statements/problem-standalone.rbx.tex'
    contestProblemTemplate: 'statements/problem-in-contest.rbx.tex'
```

**`main-pt` is listed first, deliberately.** It is the one that will fail (B has
no `pt` statement). Ordering it first is what makes the tests prove that a
*later* statement still builds after an earlier one blew up — which is the whole
bug. Do not reorder these.

**Step 3: Give A both languages, B only English**

`A/problem.rbx.yml`:

```yaml
name: 'problem-a'
timeLimit: 1000
memoryLimit: 256
vars:
  author: 'Alice'
statements:
  - language: 'en'
    title: 'Problem A'
    file: 'statement/statement.rbx.tex'
    type: 'rbxTeX'
  - language: 'pt'
    title: 'Problema A'
    file: 'statement/statement-pt.rbx.tex'
    type: 'rbxTeX'
```

`B/problem.rbx.yml` — note there is **no `pt` entry**; this is the fixture's
whole point:

```yaml
name: 'problem-b'
timeLimit: 1000
memoryLimit: 256
vars:
  author: 'Bob'
statements:
  - language: 'en'
    title: 'Problem B'
    file: 'statement/statement.rbx.tex'
    type: 'rbxTeX'
```

**Step 4: Write the statement bodies**

`A/statement/statement.rbx.tex`:

```tex
%- block legend
Problem A in English, authored by \VAR{vars.author}.
%- endblock
```

`A/statement/statement-pt.rbx.tex`:

```tex
%- block legend
Problema A em portugues, escrito por \VAR{vars.author}.
%- endblock
```

`B/statement/statement.rbx.tex`:

```tex
%- block legend
Problem B in English, authored by \VAR{vars.author}.
%- endblock
```

**Step 5: Keep the templates from the copy**

`statements/contest.rbx.tex`, `statements/problem-standalone.rbx.tex` and
`statements/problem-in-contest.rbx.tex` come from the `statements_v2` copy
unchanged. Verify `statements/contest.rbx.tex` still contains the join loop:

```bash
grep -n 'subimport' rbx/testdata/contests/statements_v2_partial/statements/contest.rbx.tex
```

Expected: a line with `\subimport{\VAR{problem.import_dir}}{\VAR{problem.import_file}}`.

**Step 6: Confirm the fixture reproduces the bug**

Create `tests/rbx/box/contest/test_contest_partial_build.py`:

```python
import inspect

import pytest
import typer

from rbx.box.contest import statements as contest_statements_cli
from rbx.box.statements.schema import StatementType

_build_async = inspect.unwrap(contest_statements_cli.build)


async def _run(**kwargs):
    defaults = dict(
        verification=0,
        names=None,
        languages=None,
        validate=False,
        output=StatementType.TeX,
        samples=False,
        vars=None,
        install_tex=False,
        profile=None,
    )
    defaults.update(kwargs)
    await _build_async(**defaults)


@pytest.mark.test_pkg('contests/statements_v2_partial')
async def test_fixture_currently_aborts_every_statement(cleandir_with_testdata):
    # Characterization of the bug: main-pt fails (B has no pt statement) and
    # takes main-en down with it. Deleted in Task 3.
    with pytest.raises(Exception):
        await _run()
    assert not (cleandir_with_testdata / 'build' / 'main-en.tex').exists()
```

Run: `uv run pytest tests/rbx/box/contest/test_contest_partial_build.py -v`
Expected: PASS. This is a characterization test proving the bug exists. If it
fails, the fixture is wrong — fix the fixture before continuing.

**Step 7: Commit**

```bash
git add rbx/testdata/contests/statements_v2_partial tests/rbx/box/contest/test_contest_partial_build.py
git commit -m "$(cat <<'EOF'
test(statements): add fixture reproducing cross-language build abort (#705)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Failure types

Two small types the later tasks need. No test of their own — Task 3 exercises
them.

**Files:**
- Modify: `rbx/box/contest/build_contest_statements.py` (after
  `StatementBuildIssue`, around `:61`)

**Step 1: Add `StatementFailedIssue` next to the existing `StatementBuildIssue`**

`StatementBuildIssue` already exists at `:50-61` and reports *a problem* that
failed. This new one reports *a whole statement* that failed.

```python
class StatementFailedIssue(Issue):
    """An issue-stack entry flagging that an entire statement failed to build,
    surfaced in the contest build overview.

    Distinct from :class:`StatementBuildIssue`, which flags a single problem
    that was dropped from an otherwise-successful statement (only possible
    under ``--partial``).
    """

    def __init__(self, statement_name: str, reason: str):
        self.statement_name = statement_name
        self.reason = reason

    def get_overview_section(self) -> Optional[Tuple[str, ...]]:
        return ('statement',)

    def get_overview_message(self) -> str:
        return (
            f'Failed to build statement [item]{self.statement_name}[/item]: '
            f'{self.reason}'
        )
```

**Step 2: Add `StatementBuildError`**

This is what the inner loop raises when a problem fails and `--partial` was not
given. It carries enough to render a one-line reason in the summary.

`RbxException.__init__` takes no arguments and builds its message through a
captured console (see `rbx/box/exception.py:32-40`), so follow that shape rather
than passing a string to `super().__init__`:

```python
class StatementBuildError(RbxException):
    """A problem failed to render into a statement, so that statement cannot be
    produced.

    Raised instead of silently dropping the problem. Under ``--partial`` the
    caller drops the problem and keeps building instead of raising this.
    """

    def __init__(self, statement_name: str, problem_short_name: str, cause: str):
        super().__init__()
        self.statement_name = statement_name
        self.problem_short_name = problem_short_name
        self.cause = cause
        with self.possibly_capture() as err:
            err.print(
                f'[error]Cannot build statement [item]{statement_name}[/item]: '
                f'problem [item]{problem_short_name}[/item] failed to render '
                f'({cause}). Pass [item]--partial[/item] to build it without '
                f'this problem.[/error]'
            )
```

Read `rbx/box/exception.py` and confirm the `possibly_capture` usage matches how
other `RbxException` subclasses build their message (e.g.
`rbx/box/statements/resolver.py:211-216` uses `with StatementResolverError() as
err: err.print(...)`). **Match the established idiom** — if the codebase's
pattern is `with SomeError() as err`, adapt this constructor accordingly rather
than inventing a new one.

**Step 3: Verify it imports**

Run: `uv run python -c "from rbx.box.contest.build_contest_statements import StatementFailedIssue, StatementBuildError; print('ok')"`
Expected: `ok`

**Step 4: Commit**

```bash
git add rbx/box/contest/build_contest_statements.py
git commit -m "$(cat <<'EOF'
feat(statements): add statement-level failure types (#705)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Isolate the contest outer loop

**This is the bug fix.** Everything else is consequence management.

**Files:**
- Modify: `rbx/box/contest/statements.py:130-148` (the statement loop) and
  `:165-182` (the report)
- Test: `tests/rbx/box/contest/test_contest_partial_build.py`

**Step 1: Delete the characterization test and write the real one**

Remove `test_fixture_currently_aborts_every_statement` from Task 1 and add:

```python
@pytest.mark.test_pkg('contests/statements_v2_partial')
async def test_failing_statement_does_not_stop_later_ones(cleandir_with_testdata):
    # main-pt is listed first and fails (problem B has no pt statement).
    # main-en must still build.
    with pytest.raises(typer.Exit) as exc_info:
        await _run()

    assert exc_info.value.exit_code == 1
    assert (cleandir_with_testdata / 'build' / 'main-en.tex').exists()
    assert not (cleandir_with_testdata / 'build' / 'main-pt.tex').exists()


@pytest.mark.test_pkg('contests/statements_v2_partial')
async def test_successful_statement_joins_all_problems(cleandir_with_testdata):
    with pytest.raises(typer.Exit):
        await _run()

    contest_tex = (cleandir_with_testdata / 'build' / 'main-en.tex').read_text()
    assert '\\subimport{.problems/A/}{statement}' in contest_tex
    assert '\\subimport{.problems/B/}{statement}' in contest_tex
```

**Step 2: Run to verify they fail**

Run: `uv run pytest tests/rbx/box/contest/test_contest_partial_build.py -v`
Expected: FAIL. `main-en.tex` does not exist, because the `main-pt` failure
aborted the loop before `main-en` was reached.

**Step 3: Wrap the statement loop**

In `rbx/box/contest/statements.py`, replace the loop at `:132-148`. Note it is
inside the `with limits_info.use_profile(...)` block — keep it there.

```python
    failed_statements: List[Tuple[str, str]] = []

    with limits_info.use_profile(profile, when=lambda: profile is not None):
        for statement in valid_statements:
            try:
                built_statements.append(
                    await build_statement(
                        statement,
                        contest,
                        problems_of_interest=problems_of_interest,
                        output_type=output,
                        use_samples=samples,
                        install_tex=install_tex,
                        custom_vars=expand_any_vars(
                            annotations.parse_dictionary_items(vars)
                        ),
                        kind=kind,
                    )
                )
            except Exception as exc:
                reason = _describe_failure(exc)
                console.console.print(
                    f'[error]Failed to build {kind.singular} '
                    f'[item]{statement.name}[/item]: {reason}[/error]'
                )
                issue_stack.add_issue(StatementFailedIssue(statement.name, reason))
                failed_statements.append((statement.name, reason))
```

Two things to be careful about:

- `built_statements` is later `zip`ped against `valid_statements` at `:166` to
  print the report. That zip is now **wrong**, because a failed statement
  appends nothing and the lists fall out of alignment. Change
  `built_statements` to collect `(statement, path)` pairs and iterate those
  directly instead of zipping.
- Do the same for the `valid_documents` / `built_documents` loop at `:152-161`.
  Documents fail independently of statements for the same reason.

**Step 4: Add the failure-description helper**

Near the top of `rbx/box/contest/statements.py`:

```python
def _describe_failure(exc: BaseException) -> str:
    """A one-line reason for the build summary.

    ``typer.Exit`` carries no message (the code that raised it already printed
    one), and ``RbxException`` accumulates its message into ``msg`` rather than
    ``str(exc)``, so neither renders usefully via ``str``.
    """
    if isinstance(exc, typer.Exit):
        return 'see the error above'
    if isinstance(exc, RbxException):
        return ' '.join(part.strip() for part in exc.msg).strip() or 'see the error above'
    return str(exc) or type(exc).__name__
```

Check `rbx/box/exception.py` for how `RbxException.msg` is populated and whether
a helper for flattening it already exists. **Reuse it if so** — do not duplicate.

**Step 5: Extend the report and the exit**

Replace `:165-182`:

```python
    console.console.rule(title=f'Built {kind.value}')
    for statement, built_path in built_statements:
        console.console.print(
            f'[item]{statement.name} {statement.language}[/item] -> {href(built_path)}'
        )
    for document, built_path in built_documents:
        console.console.print(
            f'[item]{document.name} {document.language}[/item] (document) -> {href(built_path)}'
        )

    if failed_statements:
        console.console.rule(title=f'Failed {kind.value}')
        for name, reason in failed_statements:
            console.console.print(f'[error]{name}[/error]: {reason}')

    if failed_statements or failed_problems:
        raise typer.Exit(1)
```

Note `failed_problems` (the samples-phase list) still contributes to the exit;
Task 6 changes what it *does*, not whether it fails the command.

**Step 6: Add the imports**

`StatementFailedIssue` from `rbx.box.contest.build_contest_statements`,
`RbxException` from `rbx.box.exception`, and `Tuple` from `typing`.

**Step 7: Run tests**

Run: `uv run pytest tests/rbx/box/contest/test_contest_partial_build.py -v`
Expected: PASS.

Then the existing contest suite, to catch the zip change:

Run: `uv run pytest tests/rbx/box/contest/ -v`
Expected: PASS. If `test_statements_profile.py` or `test_contest_build_v2.py`
break, it is almost certainly the `built_statements` shape change — fix the
call sites, do not weaken the tests.

**Step 8: Commit**

```bash
git add rbx/box/contest/statements.py tests/rbx/box/contest/test_contest_partial_build.py
git commit -m "$(cat <<'EOF'
fix(statements): build every contest statement even when one fails (#705)

A statement that failed aborted the whole command, so a broken en statement
prevented pt from building. Each statement now builds in isolation and the
failures are collected into an end-of-run summary.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Replace the type-based tiering with an explicit `--partial` policy

**Files:**
- Modify: `rbx/box/contest/build_contest_statements.py:155` (`build_statement`
  signature) and `:214-241` (the inner loop)
- Test: `tests/rbx/box/contest/test_contest_partial_build.py`

**Step 1: Write the failing tests**

```python
@pytest.mark.test_pkg('contests/statements_v2_partial')
async def test_partial_builds_the_statement_without_the_problem(
    cleandir_with_testdata,
):
    await _run(partial=True)

    pt_tex = (cleandir_with_testdata / 'build' / 'main-pt.tex').read_text()
    assert '\\subimport{.problems/A/}{statement}' in pt_tex
    assert '\\subimport{.problems/B/}{statement}' not in pt_tex


@pytest.mark.test_pkg('contests/statements_v2_partial')
async def test_partial_exits_zero(cleandir_with_testdata):
    # --partial is an explicit request for best-effort output, so a dropped
    # problem is not a command failure. The issue report still lists it.
    await _run(partial=True)
    assert (cleandir_with_testdata / 'build' / 'main-en.tex').exists()
    assert (cleandir_with_testdata / 'build' / 'main-pt.tex').exists()
```

**Step 2: Run to verify they fail**

Run: `uv run pytest tests/rbx/box/contest/test_contest_partial_build.py -v`
Expected: FAIL with `TypeError: ... unexpected keyword argument 'partial'`.

**Step 3: Thread `partial` through**

Add `partial: bool = False` to `build_statement` (`:155`) and to
`_execute_build` in `rbx/box/contest/statements.py`, and pass it at the call
site added in Task 3. Document it in the `build_statement` docstring's `Args:`
block alongside the existing entries.

**Step 4: Replace the tiering**

At `build_contest_statements.py:214-241`, the current code is:

```python
        try:
            problem_ctx = await _render_problem_fragment_async(...)
        except (typer.Exit, RbxException):
            # Hard config/abort errors ... must surface, not be downgraded ...
            raise
        except Exception as exc:
            console.console.print(...)
            issue_stack.add_issue(StatementBuildIssue(problem))
            continue
```

Replace with:

```python
        try:
            problem_ctx = await _render_problem_fragment_async(...)
        except Exception as exc:
            if not partial:
                # Dropping the problem would silently produce a statement that
                # is missing it. Fail this statement instead; the caller keeps
                # building the other statements.
                raise StatementBuildError(
                    statement.name, problem.short_name, _describe_cause(exc)
                ) from exc
            console.console.print(
                f'[warning]Dropping problem [item]{problem.short_name}[/item] '
                f'from {kind.singular} [item]{statement.name}[/item]: '
                f'{exc}[/warning]'
            )
            issue_stack.add_issue(StatementBuildIssue(problem))
            continue
```

**Delete the `(typer.Exit, RbxException)` clause entirely**, along with its
comment. That comment describes the old policy and is now false. This is the
change that fixes the `typer.Abort` and `AssertionError` misclassification
described in the design — those types no longer take a different path because
there is no longer a different path.

`_describe_cause` is the same flattening logic as `_describe_failure` from Task
3. **Do not write it twice** — put one helper somewhere both modules can import
(a small function in `rbx/box/exception.py` is the natural home, since it is
about rendering an `RbxException`) and import it from both.

**Step 5: Run tests**

Run: `uv run pytest tests/rbx/box/contest/test_contest_partial_build.py -v`
Expected: PASS, including the Task 3 tests (default is still fail-that-statement).

**Step 6: Commit**

```bash
git add rbx/box/contest/build_contest_statements.py rbx/box/contest/statements.py rbx/box/exception.py tests/rbx/box/contest/test_contest_partial_build.py
git commit -m "$(cat <<'EOF'
feat(statements): fail a statement whose problem cannot render (#705)

Failures were tiered by exception type, which routed Jinja abort and
assertion errors into a silent per-problem skip at exit 0. Any problem-level
failure now fails that statement unless --partial is given.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Turn the bare asserts into real errors

Under the new rule these are fatal either way, but an `AssertionError` in the
summary tells the user nothing.

**Files:**
- Modify: `rbx/box/contest/build_contest_statements.py:196`, `:306`, `:314`

**Step 1: Write the failing test**

Add a second fixture variant, or reuse the existing one with a monkeypatched
config. The simplest honest test: a fixture whose contest statement omits
`contestProblemTemplate`.

```python
@pytest.mark.test_pkg('contests/statements_v2_partial')
async def test_missing_contest_problem_template_reports_clearly(
    cleandir_with_testdata, capsys
):
    config = cleandir_with_testdata / 'contest.rbx.yml'
    config.write_text(
        config.read_text().replace(
            "    contestProblemTemplate: 'statements/problem-in-contest.rbx.tex'\n",
            '',
        )
    )

    with pytest.raises(typer.Exit):
        await _run()

    out = capsys.readouterr().out
    assert 'contestProblemTemplate' in out
    assert 'AssertionError' not in out
```

Verify by hand first that removing that key is actually accepted by the schema
(`ContestStatement` in `rbx/box/contest/schema.py` — check whether
`contestProblemTemplate` is `Optional`). If the schema rejects it outright, the
assert is unreachable and this test should instead assert the *schema* error is
clear; adjust the test to match reality rather than forcing the fixture.

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/contest/test_contest_partial_build.py::test_missing_contest_problem_template_reports_clearly -v`

**Step 3: Replace the asserts**

Each becomes a `StatementResolverError`-style raise naming the missing field and
the statement it belongs to. Follow the idiom in
`rbx/box/statements/resolver.py:211-216`.

- `:196` `assert statement.file is not None` → contest statement has no `file`.
- `:306` `assert problem_statement.file is not None` → problem statement has no
  `file`.
- `:314` `assert contest_statement.contestProblemTemplate is not None` → contest
  statement defines no `contestProblemTemplate`, which is required to join.

**Step 4: Run tests**

Run: `uv run pytest tests/rbx/box/contest/test_contest_partial_build.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add rbx/box/contest/build_contest_statements.py tests/rbx/box/contest/test_contest_partial_build.py
git commit -m "$(cat <<'EOF'
fix(statements): report missing join config instead of asserting (#705)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Close the samples-phase silent-partial hole

Today a problem whose samples fail is dropped from `problems_of_interest` and
the joined PDF is built without it. That is a partial statement produced without
`--partial`.

**Files:**
- Modify: `rbx/box/contest/statements.py:97-127`
- Test: `tests/rbx/box/contest/test_contest_partial_build.py`

**Step 1: Write the failing test**

You need a fixture whose samples fail. Look at how existing tests provoke a
sample failure — search for `build_samples` in `tests/` and reuse that approach
rather than inventing one:

```bash
grep -rn 'build_samples' tests/ | head
```

The test asserts: without `--partial`, a problem whose samples fail causes every
joining statement to fail and **no `.tex` is written**; with `--partial`, the
statements are written without that problem.

If provoking a real sample failure is disproportionately awkward, patch
`rbx.box.testcase_sample_utils.build_samples` to return `False` for problem `B`
with `mock.patch` (stdlib `unittest.mock`, per the repo's testing conventions).
Patching that public function is acceptable; do not patch private helpers.

**Step 2: Run to verify it fails**

**Step 3: Gate the drop on `partial`**

At `:111-118`, when `build_samples` returns `False` or raises:

- if `partial`: current behaviour — issue, add to `failed_problems`, exclude
  from `problems_of_interest`.
- if not `partial`: record the problem as failed and **do not** exclude it from
  `problems_of_interest`. Leaving it in means the render loop will hit it, fail,
  and raise `StatementBuildError` — which is exactly the desired outcome and
  avoids a second, parallel failure path.

Consider instead marking those problems in a set and raising
`StatementBuildError` up-front for any statement that joins them, if that reads
more clearly. Either is fine; pick one and say why in a comment.

**Step 4: Run tests**

Run: `uv run pytest tests/rbx/box/contest/ -v`
Expected: PASS. Existing tests that relied on short PDFs being produced on
sample failure will now fail — those encode the old behaviour and should be
updated to pass `partial=True`, with a comment saying so.

**Step 5: Commit**

```bash
git add rbx/box/contest/statements.py tests/rbx/box/contest/
git commit -m "$(cat <<'EOF'
fix(statements): do not join a contest without a problem whose samples failed (#705)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Isolate the problem-level loop, keeping packagers fail-fast

**Files:**
- Modify: `rbx/box/statements/build_statements.py:371-415`
  (`execute_build_on_statements`) and `:418` (`execute_build`)
- Test: `tests/rbx/box/statements/test_build_statements.py`

**Step 1: Write the failing test**

A problem with two statements where the first fails (e.g. a Jinja undefined
variable) and the second is fine. Assert the second still builds. Follow the
existing conventions in `tests/rbx/box/statements/test_build_statements.py`.

Also write the guard test:

```python
async def test_packager_callers_still_fail_fast():
    # execute_build_on_statements defaults to keep_going=False so a packager
    # never ships a silently incomplete set of statements.
    import inspect

    from rbx.box.statements import build_statements

    sig = inspect.signature(build_statements.execute_build_on_statements)
    assert sig.parameters['keep_going'].default is False
```

That signature assertion is a weak test on its own. Pair it with a real one that
calls `execute_build_on_statements(..., keep_going=False)` over two statements
where the first fails, and asserts it raises without building the second.

**Step 2: Run to verify they fail**

**Step 3: Add `keep_going` and wrap the loop**

```python
async def execute_build_on_statements(
    statements: List[Statement],
    ...,
    keep_going: bool = False,
) -> List[pathlib.Path]:
```

Document in the docstring: *"``keep_going`` isolates each statement so one
failure does not stop the rest; it defaults to False so packagers, which cannot
ship an incomplete set, keep aborting on the first failure. The CLI passes
True."*

Wrap the loop at `:403-414` the same way as Task 3. When `keep_going` and
anything failed, print a summary and raise `typer.Exit(1)` at the end.

**Step 4: Pass `keep_going=True` from the CLI only**

`execute_build` (`:418`) is called by both the CLI and packagers. Check every
caller:

```bash
grep -rn 'execute_build_on_statements\|execute_build(' rbx/ --include='*.py'
```

Only the CLI path (`build` at `:477` and the tutorials twin) sets it. Every
packager caller keeps the default. **List the callers you found in the commit
body** so the reviewer can check you did not miss one.

**Step 5: Run tests**

Run: `uv run pytest tests/rbx/box/statements/ -v`
Expected: PASS.

**Step 6: Commit**

```bash
git add rbx/box/statements/build_statements.py tests/rbx/box/statements/test_build_statements.py
git commit -m "$(cat <<'EOF'
fix(statements): build every problem statement even when one fails (#705)

Packagers keep the fail-fast default; only the CLI opts into keep_going.

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Wire the `--partial` CLI flag

**Files:**
- Modify: `rbx/box/contest/statements.py:188` (`build`) and `:258`
  (`build_tutorials`)
- Modify: `rbx/box/statements/build_statements.py:477` (`build`) and its
  tutorials twin
- Test: `tests/rbx/box/completion/drift_test.py` (regenerated, not edited)

**Step 1: Add the option to all four commands**

```python
    partial: Annotated[
        bool,
        typer.Option(
            '--partial',
            help='Build a statement even if some of its problems fail, '
            'omitting them. Without this, a problem that fails makes its '
            'statement fail.',
        ),
    ] = False,
```

Pass it down to `_execute_build` / `execute_build`.

**Step 2: Verify the help renders**

Run: `uv run rbx contest statements build --help`
Expected: the `--partial` line appears.

**Step 3: Regenerate the completion spec**

This repo commits a serialized Typer spec, and a drift test compares it against
the live app. A new CLI flag **will** trip it.

Run: `uv run python -m rbx.box.completion.serialize && uv run ruff format rbx/box/completion/_spec.py`

Do **not** use `mise run gen-completion-spec` — it is a no-op inside a worktree.
Run the two commands directly, as above.

**Step 4: Run the drift test**

Run: `uv run pytest tests/rbx/box/completion/drift_test.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add rbx/box/contest/statements.py rbx/box/statements/build_statements.py rbx/box/completion/_spec.py
git commit -m "$(cat <<'EOF'
feat(statements): add --partial to the statement build commands (#705)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Documentation

**Files:**
- Modify: `rbx/box/statements/CLAUDE.md` ("Build entry points" section)
- Modify: the user-facing statements docs under `docs/` — find them with
  `grep -rln 'contest st b\|statements build' docs/`

**Step 1: Update the module guide**

Add to the "Build entry points" section: statement builds are fault-isolated
(one failure never stops another), a problem that fails makes its statement fail
by default, and `--partial` opts into dropping it. Note that
`execute_build_on_statements` defaults to `keep_going=False` for packagers.

Keep it to a few sentences — that file is a map, not a manual.

**Step 2: Update the user docs**

Document `--partial` and the exit-code contract (any statement failed → 1;
`--partial` with dropped problems but every statement produced → 0).

**Step 3: Verify the docs build**

Run: `uv run mkdocs build 2>&1 | tail -20`

Use the **non-strict** build. `--strict` fails on about nine pre-existing
warnings unrelated to this change; do not try to fix those.

**Step 4: Commit**

```bash
git add rbx/box/statements/CLAUDE.md docs/
git commit -m "$(cat <<'EOF'
docs(statements): document --partial and statement build isolation (#705)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Final verification

**Step 1: Lint and format**

```bash
uv run ruff check .
uv run ruff format --check .
```

Expected: clean. Fix anything reported.

**Step 2: Run the affected suites**

```bash
uv run pytest tests/rbx/box/contest/ tests/rbx/box/statements/ tests/rbx/box/completion/ -v
```

Expected: PASS.

**Step 3: Run the broader suite, minus the slow CLI tests**

```bash
uv run pytest --ignore=tests/rbx/box/cli -n auto 2>&1 | tail -30
```

There are known pre-existing local failures in this repo unrelated to this work
(C++/sandbox/docker-dependent tests, and a stale
`test_compute_walltime_uses_active_environment`). **Compare against a baseline
rather than assuming**: if anything fails, run the same command on `main`
(`git stash` or a second worktree) and confirm it failed there too. Report any
failure you cannot attribute to the baseline — do not wave it away.

**Step 4: Manual smoke test**

```bash
cd $(mktemp -d)
cp -r <repo>/rbx/testdata/contests/statements_v2_partial .
cd statements_v2_partial
uv run --project <repo> rbx contest statements build --output tex ; echo "exit=$?"
uv run --project <repo> rbx contest statements build --output tex --partial ; echo "exit=$?"
```

Expected: first run builds `build/main-en.tex` only, prints a "Failed
statements" section naming `main-pt` and problem `B`, exits 1. Second run builds
both, exits 0.

**Step 5: Push and open a draft PR**

```bash
git push -u origin worktree-statement-partial-failure
gh pr create --draft --title 'fix(statements): isolate statement build failures (#705)' --body '...'
```

`gh pr edit` / `gh pr view` fail in this repo with a classic-Projects GraphQL
error; if you need to edit the PR afterwards use
`gh api -X PATCH repos/rsalesc/rbx/pulls/<N>` instead.

The PR body should state: closes #705; the two defects fixed; the accepted
behaviour change (a sample failure without `--partial` now fails the statements
rather than emitting short PDFs); and that packagers are unaffected.
