# `rbx package moj --upload` Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `-u` / `--upload` to `rbx package moj`, which builds the package as it does today and then uploads it to MOJ through the `moj` CLI, under `<org>#<slug>`.

**Architecture:** `run_packager` grows an optional `into_dir` so the caller can keep the built *tree* (the zip loses the `0o755` bits the judge needs). A new `rbx/box/packaging/moj/upload.py` resolves `<org>#<slug>` from `moj whoami` plus a new env-level `extensions.moj.org`, and drives the existing `rbx.box.runners.moj.cli` wrapper. The design and its rationale are in [`2026-08-24-moj-package-upload-design.md`](2026-08-24-moj-package-upload-design.md) — read it before starting.

**Tech Stack:** Python 3, Typer, Pydantic v2, pytest. The `moj` CLI is shelled out to; tests stub it with a shell script, exactly as `tests/rbx/box/runners/moj/test_cli.py` already does. Nothing here touches the network.

**Before you start:** run `uv sync`. Run tests with `uv run pytest <path>`; run only the files you touch — a full run is slow and produces spurious sandbox wall timeouts.

---

## Task 1: The env-level `moj` extension

Today `rbx/box/extensions.py` has an env-level extension only for `boca`; `moj` exists solely as a *language*-level one. This adds `MojExtension`, holding the single optional `org` field.

**Files:**
- Modify: `rbx/box/packaging/moj/extension.py`
- Modify: `rbx/box/extensions.py:11-15`
- Test: `tests/rbx/box/packaging/moj/test_extension.py` (create)

**Step 1: Write the failing test**

```python
import pytest
from pydantic import ValidationError

from rbx.box.extensions import Extensions
from rbx.box.packaging.moj.extension import MojExtension


def test_org_defaults_to_none():
    # Absent means "upload under my own login"; see `resolve_problem_id`.
    assert MojExtension().org is None


def test_org_is_read_off_the_environment_extensions():
    extensions = Extensions.model_validate({'moj': {'org': 'unicamp'}})
    assert extensions.moj is not None
    assert extensions.moj.org == 'unicamp'


def test_unknown_field_is_rejected():
    # `extra='forbid'`, as every other extension: a typo in `env.rbx.yml` must
    # fail loudly rather than be silently ignored at upload time.
    with pytest.raises(ValidationError):
        MojExtension.model_validate({'orgs': 'unicamp'})
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/packaging/moj/test_extension.py -v`
Expected: FAIL with `ImportError: cannot import name 'MojExtension'`.

**Step 3: Write minimal implementation**

In `rbx/box/packaging/moj/extension.py`, above `MojLanguageExtension`:

```python
class MojExtension(RejectsRemovedFields):
    """Environment-level extensions for MOJ packaging."""

    model_config = ConfigDict(extra='forbid')

    org: typing.Optional[str] = Field(
        default=None,
        description='The MOJ org to upload the package to, as `<org>#<problem>`. '
        'Leave unset to upload under your own login, which is a private personal '
        'org nobody else can see.',
    )
```

In `rbx/box/extensions.py`, import `MojExtension` alongside `MojLanguageExtension` and add to `Extensions`:

```python
    moj: Optional[MojExtension] = Field(
        default=None, description='Environment-level extensions for MOJ packaging.'
    )
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/packaging/moj/test_extension.py -v`
Expected: 3 passed.

**Step 5: Commit**

```bash
git add rbx/box/packaging/moj/extension.py rbx/box/extensions.py tests/rbx/box/packaging/moj/test_extension.py
git commit -m "feat(moj): add an env-level moj extension with an org field

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: Building and validating the problem id

The id is `<org>#<slug>`. MOJ's slug rule is stricter than rbx's — rbx names allow uppercase and contest short names *are* uppercase letters, while MOJ requires lowercase — so the basename is lowercased. Keep this a **pure function**: it takes the login, the configured org and the package basename, and needs no loaded package or environment, which is what makes it cheap to test exhaustively.

The two regexes are MOJ's own, read off `cmd_new` in the `moj` CLI.

**Files:**
- Create: `rbx/box/packaging/moj/upload.py`
- Test: `tests/rbx/box/packaging/moj/test_upload.py` (create)

**Step 1: Write the failing test**

```python
import pytest

from rbx.box.packaging.moj.upload import build_problem_id
from rbx.box.runners.moj.cli import MojCliError


def test_uses_the_configured_org():
    assert build_problem_id('alice', 'unicamp', 'a-aplusb') == 'unicamp#a-aplusb'


def test_falls_back_to_the_login_when_no_org_is_configured():
    assert build_problem_id('alice', None, 'a-aplusb') == 'alice#a-aplusb'


def test_lowercases_the_slug():
    # rbx allows uppercase in a problem name and contest short names ARE
    # uppercase letters, but MOJ slugs are lowercase-only.
    assert build_problem_id('alice', None, 'A-APlusB') == 'alice#a-aplusb'


def test_rejects_a_slug_that_is_not_a_legal_moj_slug():
    with pytest.raises(MojCliError, match='problem name'):
        build_problem_id('alice', None, 'a+b')


def test_rejects_an_illegal_org():
    with pytest.raises(MojCliError, match='org'):
        build_problem_id('alice', 'not an org', 'aplusb')


def test_refuses_a_slug_that_looks_like_an_rbx_timing_problem():
    # `rbxt-` marks a throwaway problem `rbx time --runner moj` created and may
    # overwrite. A real package must never land on an id that looks like one.
    with pytest.raises(MojCliError, match='rbxt-'):
        build_problem_id('alice', None, 'rbxt-aplusb')
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/packaging/moj/test_upload.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rbx.box.packaging.moj.upload'`.

**Step 3: Write minimal implementation**

Create `rbx/box/packaging/moj/upload.py`:

```python
"""Uploading a built MOJ package to the judge.

Unlike `rbx time --runner moj`, which uploads a throwaway probe to a private
`rbxt-` problem, this uploads a package meant to be used. It goes through the
same CLI wrapper -- `rbx.box.runners.moj.cli` -- so credentials never pass
through rbx and the session `moj login` established is reused.
"""

import re
from typing import Optional

from rbx.box.runners.moj.cli import MojCliError
from rbx.box.runners.moj.problem_id import RBXT_PREFIX

# MOJ's own rules, read off `cmd_new` in the CLI, which mirrors what the server's
# `/problems/create` enforces. Checked here so an illegal name fails by name
# rather than as a server-side 400 long after the build was paid for.
_ORG_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$')
_SLUG_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{1,80}$')


def build_problem_id(login: str, org: Optional[str], basename: str) -> str:
    """The `<org>#<slug>` this package uploads to.

    Pure on purpose: everything that needs a loaded package or a live CLI lives
    in `resolve_problem_id`, so the naming rules can be tested on their own.
    """
    resolved_org = org or login
    if not _ORG_RE.match(resolved_org):
        raise MojCliError(
            f'`{resolved_org}` is not a valid MOJ org: an org is 2-64 characters '
            f'of `[A-Za-z0-9._-]` and cannot start with a punctuation character. '
            f'Set `extensions.moj.org` in your `env.rbx.yml`.'
        )

    # Lowercased rather than refused: rbx names legally contain uppercase and a
    # contest short name always does, so refusing would reject the common case.
    slug = basename.lower()
    if not _SLUG_RE.match(slug):
        raise MojCliError(
            f'`{slug}` is not a valid MOJ problem name: it must be 2-81 '
            f'characters of `[a-z0-9._-]` and cannot start with a punctuation '
            f'character. Rename the problem in your `problem.rbx.yml`.'
        )
    if slug.startswith(RBXT_PREFIX):
        raise MojCliError(
            f'`{slug}` starts with `{RBXT_PREFIX}`, which marks the throwaway '
            f'problems `rbx time --runner moj` creates and may overwrite without '
            f'asking. Rename the problem in your `problem.rbx.yml`.'
        )

    return f'{resolved_org}#{slug}'
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/packaging/moj/test_upload.py -v`
Expected: 6 passed.

**Step 5: Commit**

```bash
git add rbx/box/packaging/moj/upload.py tests/rbx/box/packaging/moj/test_upload.py
git commit -m "feat(moj): build and validate the upload problem id

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: Resolving the id against the live CLI, and the personal-org warning

`resolve_problem_id` is the thin, impure half: it asks `moj whoami` for the login, reads `extensions.moj.org`, takes the basename from the packager's own naming rule, and warns when the upload is heading for the setter's private personal org.

Note `BasePackager.package_basename` (`rbx/box/packaging/packager.py:74-80`) is `<short>-<name>` inside a contest and `<name>` outside one — reuse it rather than re-deriving, so the remote id matches the local artifact name.

**Files:**
- Modify: `rbx/box/packaging/moj/upload.py`
- Test: `tests/rbx/box/packaging/moj/test_upload.py`

**Step 1: Write the failing test**

Append. `whoami` and the configured org are patched; nothing spawns a process here.

```python
from unittest import mock

from rbx.box.packaging.moj.upload import resolve_problem_id


async def test_resolve_warns_when_uploading_to_the_personal_org(capsys):
    with (
        mock.patch('rbx.box.packaging.moj.upload.cli.whoami', return_value='alice'),
        mock.patch(
            'rbx.box.packaging.moj.upload._configured_org', return_value=None
        ),
    ):
        problem_id = await resolve_problem_id('a-aplusb')

    assert problem_id == 'alice#a-aplusb'
    assert 'personal org' in capsys.readouterr().out


async def test_resolve_does_not_warn_when_an_org_is_configured(capsys):
    with (
        mock.patch('rbx.box.packaging.moj.upload.cli.whoami', return_value='alice'),
        mock.patch(
            'rbx.box.packaging.moj.upload._configured_org', return_value='unicamp'
        ),
    ):
        problem_id = await resolve_problem_id('a-aplusb')

    assert problem_id == 'unicamp#a-aplusb'
    assert 'personal org' not in capsys.readouterr().out
```

`cli.whoami` is async, so patch it with an `AsyncMock` (or `mock.patch(..., new_callable=mock.AsyncMock, return_value='alice')`) if a plain `return_value` does not await cleanly.

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/packaging/moj/test_upload.py -v`
Expected: FAIL with `ImportError: cannot import name 'resolve_problem_id'`.

**Step 3: Write minimal implementation**

Add to `rbx/box/packaging/moj/upload.py`:

```python
from rbx import console
from rbx.box import environment
from rbx.box.packaging.moj.extension import MojExtension
from rbx.box.runners.moj import cli


def _configured_org() -> Optional[str]:
    """`extensions.moj.org` from `env.rbx.yml`, if it is set."""
    return environment.get_extension_or_default('moj', MojExtension).org


async def resolve_problem_id(basename: str) -> str:
    """The remote problem this package uploads to, warning if it is private.

    `basename` is the packager's own `package_basename()`, so the id on the
    server matches the artifact name on disk.
    """
    login = await cli.whoami()
    org = _configured_org()
    problem_id = build_problem_id(login, org, basename)

    if org is None:
        # Not an error -- uploading under your own login is a perfectly good way
        # to try the flow -- but it is invisible to everyone else, and finding
        # that out from a co-setter is worse than hearing it here.
        console.console.print(
            f'[warning]No `extensions.moj.org` is set, so this package is going '
            f'to [item]{problem_id}[/item] -- your private personal org, which '
            f'nobody else can see.[/warning]\n'
            f'[warning]Set `extensions.moj.org` in your `env.rbx.yml` to upload '
            f'it somewhere shared.[/warning]'
        )
    return problem_id
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/packaging/moj/test_upload.py -v`
Expected: 8 passed.

**Step 5: Commit**

```bash
git add rbx/box/packaging/moj/upload.py tests/rbx/box/packaging/moj/test_upload.py
git commit -m "feat(moj): resolve the upload id and warn on a personal org

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: Let `run_packager` build into a caller-owned directory

`run_packager` (`rbx/box/packaging/packager.py:276-293`) builds into a `TemporaryDirectory` that is gone by the time it returns, and hands back only the `.zip`. `moj upload` wants the tree, and the tree cannot be recovered from the zip: `MojPackager` `chmod`s the checker (`packager.py:1195`) and every `scripts/<lang>/` file (`packager.py:1337`) to `0o755`, and `zipfile.extract` does not restore mode bits.

**Files:**
- Modify: `rbx/box/packaging/packager.py:208-293`
- Test: `tests/rbx/box/packaging/moj/test_packager.py`

**Step 1: Write the regression guard**

The packager is exercised directly here, as the rest of that file already does — `run_packager` itself needs a full verification run. This asserts the property the whole decision exists for: the tree keeps its executable bits.

```python
import stat


def test_package_writes_executable_scripts_into_the_tree(tmp_path, ...):
    # Fill in `...` from the existing fixtures in this file (see the tests around
    # `MojPackager(...)` for how one is constructed).
    build_path = tmp_path / 'build'
    into_path = tmp_path / 'package'
    build_path.mkdir()

    packager.package(build_path, into_path, [])

    scripts = list((into_path / 'scripts').rglob('*.sh'))
    assert scripts, 'expected per-language scripts in the package tree'
    for script in scripts:
        assert script.stat().st_mode & stat.S_IXUSR, f'{script} is not executable'
```

**Step 2: Run it**

Run: `uv run pytest tests/rbx/box/packaging/moj/test_packager.py -k executable -v`
Expected: **PASS** — `package()` already chmods. This is a regression guard, not a red test: it fails if anyone later routes the upload through the zip. Say so in the commit message, so a reader does not mistake it for TDD gone wrong.

**Step 3: Write the implementation**

In `run_packager`, replace the unconditional temp dir with an optional caller-owned one:

```python
async def run_packager(
    packager_cls: Type[BasePackager],
    verification: environment.VerificationParam,
    samples_only: bool = False,
    skip_packaging: bool = False,
    into_dir: Optional[pathlib.Path] = None,
    **kwargs,
) -> Optional[pathlib.Path]:
```

and, at the packaging step:

```python
    console.console.print(f'Packaging problem for [item]{packager.name()}[/item]...')
    with contextlib.ExitStack() as stack:
        # `into_dir` lets a caller keep the built *tree*, not just the archive:
        # `moj upload` uploads the directory, and the zip cannot stand in for it
        # because unzipping drops the 0o755 bits the judge's scripts need.
        if into_dir is None:
            into_dir = pathlib.Path(stack.enter_context(tempfile.TemporaryDirectory()))
        stack.enter_context(limits_info.use_profile(packager_cls.name()))
        result_path = packager.package(
            package.get_build_path(), into_dir, built_statements
        )
```

Add `import contextlib` at the top. Leave everything after this block untouched.

**Step 4: Verify nothing regressed**

Run: `uv run pytest tests/rbx/box/packaging -x -q`
Expected: the suite passes unchanged — `into_dir` defaults to the old behaviour.

**Step 5: Commit**

```bash
git add rbx/box/packaging/packager.py tests/rbx/box/packaging/moj/test_packager.py
git commit -m "feat(packaging): let run_packager build into a caller-owned dir

The MOJ upload needs the package tree, not the zip: unzipping drops the
0o755 bits the judge's per-language scripts need. The new test is a
regression guard for that, and passes before the change.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: The `-u` flag

Wire it together. The build is unchanged; the upload is appended.

**Files:**
- Modify: `rbx/box/packaging/main.py` (the `moj` command)
- Modify: `rbx/box/packaging/moj/upload.py`
- Modify: `rbx/box/packaging/packager.py:74-80` (make `package_basename` a classmethod)
- Test: `tests/rbx/box/packaging/moj/test_cli.py`
- Test: `tests/rbx/box/packaging/moj/test_upload.py`

**Step 1: Write the failing tests**

In `test_cli.py`, following the shape already there:

```python
def test_moj_command_takes_an_upload_flag():
    result = CliRunner().invoke(app, ['moj', '--help'])
    assert result.exit_code == 0
    assert '--upload' in _plain(result.output)
```

In `test_upload.py`, drive the real stub binary so the argv assertion comes from a process that was actually spawned. Reuse the `_stub_moj` helper from `tests/rbx/box/runners/moj/test_cli.py` — copy it, or lift it into a shared conftest and import it from both.

```python
async def test_upload_shells_out_to_moj_upload(monkeypatch, tmp_path):
    log = _stub_moj(monkeypatch, tmp_path, 'exit 0')
    directory = tmp_path / 'package'
    directory.mkdir()

    await upload_package('unicamp#a-aplusb', directory, calibrate=False)

    assert log.read_text().split() == ['upload', 'unicamp#a-aplusb', str(directory)]


async def test_upload_queues_a_calibration_when_asked(monkeypatch, tmp_path):
    log = _stub_moj(monkeypatch, tmp_path, 'exit 0')
    directory = tmp_path / 'package'
    directory.mkdir()

    await upload_package('unicamp#a-aplusb', directory, calibrate=True)

    # Queued and NOT waited on: no `check` poll follows it.
    argv = log.read_text().split()
    assert argv[-2:] == ['calibrate', 'unicamp#a-aplusb']
    assert 'check' not in argv
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rbx/box/packaging/moj/test_upload.py tests/rbx/box/packaging/moj/test_cli.py -v`
Expected: FAIL — `--upload` is not in the help, and `upload_package` does not exist.

**Step 3: Write minimal implementation**

Add to `rbx/box/packaging/moj/upload.py`:

```python
import pathlib


async def upload_package(
    problem_id: str, directory: pathlib.Path, calibrate: bool
) -> None:
    """Upload the built tree, and optionally queue a calibration.

    The server creates the problem when it does not exist -- that is how
    `rbx time --runner moj` bootstraps its own -- so there is nothing to create
    here first. What it does *not* create is the **org**: an upload to an org
    that does not exist fails, and the CLI's own message is what says so.

    The calibration is queued and **not waited on**. Calibrating is a long
    server-side job, and a setter who has just uploaded has nothing to block on;
    `moj check <id>` reports the state whenever they want it.
    """
    console.console.print(f'Uploading the package to [item]{problem_id}[/item]...')
    await cli.upload(problem_id, directory)
    console.console.print(
        f'[success]Package uploaded to [item]{problem_id}[/item]![/success]'
    )

    if calibrate:
        await cli.calibrate(problem_id)
        console.console.print(
            f'[status]Calibration queued for [item]{problem_id}[/item]. It runs on '
            f'the judge; check on it with [item]moj check {problem_id}[/item].'
            f'[/status]'
        )
```

In `rbx/box/packaging/main.py`, add the option to the `moj` command, before `language`:

```python
    upload: bool = typer.Option(
        False,
        '--upload',
        '-u',
        help='If set, will upload the package to MOJ.',
    ),
```

and replace the `await run_packager(...)` call at the end of the command with:

```python
    if not upload:
        await run_packager(
            MojPackager,
            verification=verification,
            main_language=language,
            timing_mode=timing_mode,
        )
        return

    from rbx.box.packaging.moj.upload import resolve_problem_id, upload_package

    # Resolved *before* the build: a missing `moj login`, or a name MOJ will not
    # accept, should not cost a full verification run to find out about.
    problem_id = await resolve_problem_id(MojPackager.package_basename())

    with tempfile.TemporaryDirectory(prefix='rbx-moj-upload-') as tmp:
        directory = pathlib.Path(tmp) / 'package'
        await run_packager(
            MojPackager,
            verification=verification,
            main_language=language,
            timing_mode=timing_mode,
            into_dir=directory,
        )
        await upload_package(problem_id, directory, calibrate=calibrate)
```

Add `import pathlib` and `import tempfile` to `main.py`.

**`package_basename` must become callable without an instance.** It is an instance method at `packager.py:74` and does not touch `self`; make it a `@classmethod` and update its one call site at `packager.py:1358`. Mechanical, no behaviour change — say so in the commit message.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rbx/box/packaging/moj -v`
Expected: all pass.

**Step 5: Commit**

```bash
git add rbx/box/packaging/main.py rbx/box/packaging/moj/upload.py rbx/box/packaging/packager.py tests/rbx/box/packaging/moj/
git commit -m "feat(moj): add --upload to rbx package moj

Closes #755.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: Regenerate the completion spec

A new CLI flag makes the completion drift test fail.

**Files:**
- Modify: `rbx/box/completion/_spec.py` (generated)

**Step 1: Regenerate**

```bash
uv run python -m rbx.box.completion.serialize && uv run ruff format rbx/box/completion/_spec.py
```

Run the generator directly rather than through `mise run gen-completion-spec` — inside a worktree the mise task is a no-op.

**Step 2: Verify**

Run: `uv run pytest tests/rbx/box/completion -v`
Expected: PASS. `git diff` should show `--upload` / `-u` on the `moj` command and nothing else.

**Step 3: Check the schemas**

`docs/schemas` is written as an import side effect and is not checked in, so there is most likely nothing to commit for the new extension field. Confirm with `git status`; if a schema file *is* tracked and changed, include it.

**Step 4: Commit**

```bash
git add rbx/box/completion/_spec.py
git commit -m "chore(completion): regenerate the spec for package moj --upload

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7: Final verification

**Step 1: Lint and format**

```bash
uv run ruff check . && uv run ruff format --check .
```

**Step 2: Run the touched suites**

```bash
uv run pytest tests/rbx/box/packaging tests/rbx/box/runners/moj tests/rbx/box/completion -q
```

Run only these. A full suite run is slow and produces spurious sandbox wall timeouts unrelated to this change.

**Step 3: Eyeball the help**

```bash
uv run rbx package moj --help
```

Expected: `-u, --upload` listed, alongside the existing `--language` and `--calibrate`.

---

## Follow-ups, deliberately not in this plan

- **Docs.** The docs site has no page for MOJ packaging at all — MOJ is not even in the backend table in `docs/setters/packaging/index.md` — so a section documenting only `-u` would be orphaned. The CLI reference (`docs/setters/reference/cli.md`) picks the flag up on the next docs build. A `docs/setters/packaging/moj.md` covering the backend as a whole is the real fix, and is its own piece of work.
- **A pre-flight org check.** `moj org list` before the build would turn "the org does not exist" into a precise error instead of a failed upload after a full verification run.
- **Publishing.** `moj upload` neither publishes nor unpublishes; a newly created problem stays private until published by hand.
