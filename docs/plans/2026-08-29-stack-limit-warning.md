# Stack Limit Warning Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Warn on the issue stack, once per run, when a configured `stackLimit` cannot be honored --
because the machine's hard `RLIMIT_STACK` is lower on Linux, or because macOS does not enforce it at
all -- instead of degrading silently.

**Architecture:** A parent-side probe in `rbx/grading/steps.py`, placed immediately after
`_relax_limits_for_jvm` so it reads the final `params.stack_space` (JVM commands have theirs nulled
by then). It pushes a `StackLimitNotHonoredIssue` onto the issue stack rather than printing, so the
warning is deduped and reported once at the end of the command. Plus a separate fix to
`get_preexec_fn` so an unset `stackLimit` clamps to the hard limit rather than failing outright.

**Tech Stack:** Python 3, pytest, `unittest.mock`, `resource`, Pydantic v2 (`SandboxParams`), Rich
(via `rbx.box.sanitizers.issue_stack`).

**Design doc:** [`docs/plans/2026-08-29-stack-limit-warning-design.md`](2026-08-29-stack-limit-warning-design.md)

**Issue:** [#800](https://github.com/rsalesc/rbx/issues/800)

---

## Background you need before starting

Read these before Task 1. They are short.

- `rbx/grading/steps.py:506-519` -- `_relax_limits_for_jvm`, which nulls `params.stack_space` for
  Java/Kotlin. Called at `steps.py:832`, `:925` and `:969`. Your probe must run *after* it, or it
  will warn about a limit that is then discarded.
- `rbx/grading/steps.py:679-699` -- `_maybe_complain_about_sanitization`. The naming and shape
  precedent for a platform-conditional diagnostic in this file.
- `rbx/box/sanitizers/issue_stack.py` -- the whole file. Note that
  `IssueAccumulator._print_report_by` skips repeated messages within a section (`seen_issues`), so
  "warn once per run" is free as long as the message string is identical between calls. Do **not**
  add a seen-set.
- `rbx/box/solutions.py:2325-2342` -- `TimingIssue`, the closest existing `Issue` subclass. Copy its
  shape.
- `rbx/grading/judge/program.py:99-125` -- `get_preexec_fn`, for Task 5.

Two things that are **not** in scope and must not change:

- `rbx/box/code.py:298` `_check_stack_limit` -- the macOS shell soft-vs-hard nag. Different concern,
  stays exactly as it is.
- The `except (ValueError, OSError)` in `get_preexec_fn`. It stays. This work is a diagnostic, not a
  new failure mode.

---

## Task 1: The `StackLimitNotHonoredIssue` class

**Files:**
- Modify: `rbx/grading/steps.py` (add after `_relax_limits_for_jvm`, around line 520)
- Test: `tests/rbx/grading/steps_stack_limit_test.py` (create)

**Step 1: Write the failing tests**

Create `tests/rbx/grading/steps_stack_limit_test.py`:

```python
from rbx.grading.steps import StackLimitNotHonoredIssue
from rbx.box.sanitizers.issue_stack import IssueSeverity


class TestStackLimitNotHonoredIssue:
    def test_issue_is_a_warning_not_an_error(self):
        issue = StackLimitNotHonoredIssue(requested_mib=256, hard_limit=8 * 1024 * 1024)

        assert issue.get_severity() == IssueSeverity.WARNING

    def test_detailed_message_names_both_limits_and_links_the_docs(self):
        issue = StackLimitNotHonoredIssue(requested_mib=256, hard_limit=8 * 1024 * 1024)

        message = issue.get_detailed_message()

        assert '256 MiB' in message
        assert '8 MiB' in message
        assert 'https://rsalesc.github.io/rbx/stack-limit' in message

    def test_detailed_message_says_unenforced_when_there_is_no_hard_limit(self):
        issue = StackLimitNotHonoredIssue(requested_mib=256, hard_limit=None)

        message = issue.get_detailed_message()

        assert '256 MiB' in message
        assert 'macOS' in message
        assert 'https://rsalesc.github.io/rbx/stack-limit' in message

    def test_both_reports_file_the_issue_under_the_same_section(self):
        issue = StackLimitNotHonoredIssue(requested_mib=256, hard_limit=None)

        assert issue.get_detailed_section() == ('stack limit',)
        assert issue.get_overview_section() == ('stack limit',)

    def test_overview_message_is_present_and_links_the_docs(self):
        issue = StackLimitNotHonoredIssue(requested_mib=256, hard_limit=8 * 1024 * 1024)

        assert 'https://rsalesc.github.io/rbx/stack-limit' in issue.get_overview_message()

    def test_two_issues_with_the_same_values_produce_the_same_message(self):
        """The issue stack dedupes on the message string, so this is what makes
        the warning print once per run rather than once per program."""
        first = StackLimitNotHonoredIssue(requested_mib=256, hard_limit=8 * 1024 * 1024)
        second = StackLimitNotHonoredIssue(requested_mib=256, hard_limit=8 * 1024 * 1024)

        assert first.get_detailed_message() == second.get_detailed_message()
        assert first.get_overview_message() == second.get_overview_message()
```

**Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/rbx/grading/steps_stack_limit_test.py -v`
Expected: FAIL, `ImportError: cannot import name 'StackLimitNotHonoredIssue'`

**Step 3: Write the implementation**

In `rbx/grading/steps.py`, right after `_relax_limits_for_jvm` (which ends at line 519). Add the
import `from rbx.box.sanitizers import issue_stack` to the `rbx.box` import block near line 18 --
`steps.py` already imports `rbx.box.safeeval` and `rbx.box.exception`, so this is the same direction
of dependency, not a new layering violation.

```python
_STACK_LIMIT_DOCS = 'https://rsalesc.github.io/rbx/stack-limit'


class StackLimitNotHonoredIssue(issue_stack.Issue):
    """A configured `stackLimit` that the machine will not actually apply.

    `hard_limit` is the ceiling that will be used instead, in bytes, or `None`
    when the limit is not enforced at all (macOS, where `get_preexec_fn` never
    touches `RLIMIT_STACK`).
    """

    def __init__(self, requested_mib: int, hard_limit: Optional[int]):
        self.requested_mib = requested_mib
        self.hard_limit = hard_limit

    def get_detailed_section(self) -> Optional[Tuple[str, ...]]:
        return ('stack limit',)

    def get_overview_section(self) -> Optional[Tuple[str, ...]]:
        return ('stack limit',)

    def get_detailed_message(self) -> str:
        from rbx.box.formatting import get_formatted_memory

        requested = get_formatted_memory(self.requested_mib * 1024 * 1024)
        if self.hard_limit is None:
            return (
                f'[item]stackLimit[/item] is set to [item]{requested}[/item], but it is '
                'not enforced on macOS: the stack of a sandboxed program is whatever '
                f'your shell hands down. See [item]{_STACK_LIMIT_DOCS}[/item].'
            )
        effective = get_formatted_memory(self.hard_limit)
        return (
            f'[item]stackLimit[/item] is set to [item]{requested}[/item], but this '
            f"machine's hard stack limit is [item]{effective}[/item], so programs run "
            f'with [item]{effective}[/item]. See [item]{_STACK_LIMIT_DOCS}[/item].'
        )

    def get_overview_message(self) -> str:
        return self.get_detailed_message()

    def get_severity(self) -> issue_stack.IssueSeverity:
        return issue_stack.IssueSeverity.WARNING
```

Note `get_formatted_memory` is imported inside the method: `rbx.box.formatting` is a heavier import
than `steps.py` should pay for at module scope, and this path is cold.

Check `Optional` and `Tuple` are already imported in `steps.py`'s `typing` import; add them if not.

**Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/rbx/grading/steps_stack_limit_test.py -v`
Expected: PASS, 6 passed

**Step 5: Commit**

Stage `rbx/grading/steps.py` and `tests/rbx/grading/steps_stack_limit_test.py`, then commit with
`feat(grading): add an issue for a stack limit the machine will not honor`.

---

## Task 2: The probe

**Files:**
- Modify: `rbx/grading/steps.py` (add after `StackLimitNotHonoredIssue`)
- Test: `tests/rbx/grading/steps_stack_limit_test.py`

**Step 1: Write the failing tests**

Append to `tests/rbx/grading/steps_stack_limit_test.py`. Add these imports at the top of the file:

```python
import contextlib
import resource
from unittest import mock

import pytest

from rbx.box.sanitizers.issue_stack import IssueAccumulator, issue_stack_var
from rbx.grading.judge.sandbox import SandboxParams
from rbx.grading.steps import _maybe_complain_about_stack_limit


@contextlib.contextmanager
def _fresh_issue_stack():
    """Isolate the issue stack, so a test sees exactly the issues it caused."""
    accumulator = IssueAccumulator()
    token = issue_stack_var.set([accumulator])
    try:
        yield accumulator
    finally:
        issue_stack_var.reset(token)


@pytest.fixture
def stack_check_enabled():
    """`_maybe_complain_about_stack_limit` reads the setter config; pin it on."""
    with mock.patch('rbx.box.setter_config.get_setter_config') as mock_config:
        mock_config.return_value.judging.check_stack = True
        yield mock_config
```

Then the tests:

```python
class TestMaybeComplainAboutStackLimit:
    @mock.patch('sys.platform', 'linux')
    def test_warns_on_linux_when_the_hard_limit_is_below_the_request(
        self, stack_check_enabled
    ):
        params = SandboxParams(stack_space=256)

        with mock.patch(
            'resource.getrlimit', return_value=(8 * 1024 * 1024, 8 * 1024 * 1024)
        ):
            with _fresh_issue_stack() as accumulator:
                _maybe_complain_about_stack_limit(params)

        assert len(accumulator.issues) == 1
        issue = accumulator.issues[0]
        assert issue.requested_mib == 256
        assert issue.hard_limit == 8 * 1024 * 1024

    @mock.patch('sys.platform', 'linux')
    def test_silent_on_linux_when_the_hard_limit_is_above_the_request(
        self, stack_check_enabled
    ):
        params = SandboxParams(stack_space=64)

        with mock.patch(
            'resource.getrlimit', return_value=(8 * 1024 * 1024, 512 * 1024 * 1024)
        ):
            with _fresh_issue_stack() as accumulator:
                _maybe_complain_about_stack_limit(params)

        assert not accumulator.issues

    @mock.patch('sys.platform', 'linux')
    def test_silent_on_linux_when_the_hard_limit_is_unlimited(
        self, stack_check_enabled
    ):
        params = SandboxParams(stack_space=1024)

        with mock.patch(
            'resource.getrlimit',
            return_value=(8 * 1024 * 1024, resource.RLIM_INFINITY),
        ):
            with _fresh_issue_stack() as accumulator:
                _maybe_complain_about_stack_limit(params)

        assert not accumulator.issues

    @mock.patch('sys.platform', 'linux')
    def test_the_soft_limit_is_irrelevant_on_linux(self, stack_check_enabled):
        """We raise the soft limit ourselves in the child; only the hard one caps us."""
        params = SandboxParams(stack_space=64)

        with mock.patch(
            'resource.getrlimit',
            return_value=(1 * 1024 * 1024, resource.RLIM_INFINITY),
        ):
            with _fresh_issue_stack() as accumulator:
                _maybe_complain_about_stack_limit(params)

        assert not accumulator.issues

    @mock.patch('sys.platform', 'darwin')
    def test_warns_on_darwin_whenever_a_limit_is_configured(self, stack_check_enabled):
        """macOS never applies RLIMIT_STACK, so the numbers do not matter."""
        params = SandboxParams(stack_space=256)

        with mock.patch(
            'resource.getrlimit',
            return_value=(resource.RLIM_INFINITY, resource.RLIM_INFINITY),
        ):
            with _fresh_issue_stack() as accumulator:
                _maybe_complain_about_stack_limit(params)

        assert len(accumulator.issues) == 1
        assert accumulator.issues[0].hard_limit is None

    @mock.patch('sys.platform', 'linux')
    def test_silent_when_no_limit_is_configured(self, stack_check_enabled):
        params = SandboxParams(stack_space=None)

        with mock.patch(
            'resource.getrlimit', return_value=(8 * 1024 * 1024, 8 * 1024 * 1024)
        ):
            with _fresh_issue_stack() as accumulator:
                _maybe_complain_about_stack_limit(params)

        assert not accumulator.issues

    @mock.patch('sys.platform', 'linux')
    def test_silent_when_the_check_is_disabled_in_the_setter_config(self):
        params = SandboxParams(stack_space=256)

        with mock.patch('rbx.box.setter_config.get_setter_config') as mock_config:
            mock_config.return_value.judging.check_stack = False
            with mock.patch(
                'resource.getrlimit', return_value=(8 * 1024 * 1024, 8 * 1024 * 1024)
            ):
                with _fresh_issue_stack() as accumulator:
                    _maybe_complain_about_stack_limit(params)

        assert not accumulator.issues

    @mock.patch('sys.platform', 'linux')
    def test_survives_a_getrlimit_that_raises(self, stack_check_enabled):
        params = SandboxParams(stack_space=256)

        with mock.patch('resource.getrlimit', side_effect=OSError('nope')):
            with _fresh_issue_stack() as accumulator:
                _maybe_complain_about_stack_limit(params)

        assert not accumulator.issues
```

**Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/rbx/grading/steps_stack_limit_test.py -v`
Expected: FAIL, `ImportError: cannot import name '_maybe_complain_about_stack_limit'`

**Step 3: Write the implementation**

In `rbx/grading/steps.py`, right after `StackLimitNotHonoredIssue`. Check `resource` is imported at
the top of `steps.py`; add `import resource` if not.

```python
def _maybe_complain_about_stack_limit(params: SandboxParams) -> None:
    """Diagnose a `stackLimit` the machine will not actually apply.

    `get_preexec_fn` swallows a `setrlimit` that the system refuses -- raising in
    the forked child would take the whole run down -- so a limit above the hard
    `RLIMIT_STACK` degrades silently to whatever the process inherited, and the
    solutions that then blow their stack look like ordinary RTEs. Diagnose it
    here, in the parent, where it can still be attributed to the configuration
    that caused it.

    Call this *after* `_relax_limits_for_jvm`: a JVM command has no stack limit
    left to complain about by then.
    """
    if params.stack_space is None:
        # No limit configured: the stack is made as large as the system allows,
        # which is exactly what is documented.
        return

    from rbx.box import setter_config

    if not setter_config.get_setter_config().judging.check_stack:
        return

    if sys.platform == 'darwin':
        # `get_preexec_fn` never touches RLIMIT_STACK here, so the configured
        # limit is inert whatever the numbers say.
        issue_stack.add_issue(StackLimitNotHonoredIssue(params.stack_space, None))
        return

    try:
        _, hard = resource.getrlimit(resource.RLIMIT_STACK)
    except Exception:
        return

    if hard == resource.RLIM_INFINITY:
        return
    if hard >= params.stack_space * 1024 * 1024:
        return

    issue_stack.add_issue(StackLimitNotHonoredIssue(params.stack_space, hard))
```

**Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/rbx/grading/steps_stack_limit_test.py -v`
Expected: PASS, 14 passed

**Step 5: Commit**

Stage the same two files, then commit with
`feat(grading): probe the stack limit before spawning a program`.

---

## Task 3: Wire the probe into the three run paths

The probe is dead code until it is called. It must run at every site that calls
`_relax_limits_for_jvm`, immediately after it. Fold both into one helper so the pair cannot drift.

**Files:**
- Modify: `rbx/grading/steps.py:832`, `rbx/grading/steps.py:925`, `rbx/grading/steps.py:969` (line
  numbers will have shifted; find them by searching for `_relax_limits_for_jvm(`)
- Test: `tests/rbx/grading/steps_stack_limit_test.py`

**Step 1: Write the failing tests**

Append to `tests/rbx/grading/steps_stack_limit_test.py`. These go through `steps.run` and use the
same fixtures as `tests/rbx/grading/steps_run_test.py` -- read
`test_run_java_removes_memory_and_stack_constraints` there (around line 359) for the setup idiom,
including the `sandbox`, `cleandir` and `testdata_path` fixtures and the reusable
`steps_run_test/simple.java` and `steps_run_test/simple_output.py` testdata.

```python
class TestStackLimitProbeIsWired:
    @mock.patch('sys.platform', 'linux')
    async def test_a_run_with_an_unhonorable_limit_files_one_issue(
        self,
        sandbox,
        cleandir,
        testdata_path,
        stack_check_enabled,
    ):
        # ... same artifacts setup as steps_run_test.py's non-JVM test ...
        params = SandboxParams(stdout_file=pathlib.Path('output.txt'), stack_space=256)
        command = f'{sys.executable} script.py'

        with mock.patch(
            'resource.getrlimit', return_value=(8 * 1024 * 1024, 8 * 1024 * 1024)
        ):
            with _fresh_issue_stack() as accumulator:
                await steps.run(command, params, sandbox, artifacts)

        assert len(accumulator.issues) == 1

    @mock.patch('sys.platform', 'linux')
    async def test_a_jvm_run_files_no_issue(
        self,
        sandbox,
        cleandir,
        testdata_path,
        stack_check_enabled,
    ):
        """The JVM carve-out drops the limit, so there is nothing to warn about --
        this is the whole reason the probe cannot live in `rbx/box/code.py`."""
        # ... same artifacts setup as steps_run_test.py's Java test ...
        params = SandboxParams(stdout_file=pathlib.Path('output.txt'), stack_space=256)
        command = 'java Simple'

        with mock.patch(
            'resource.getrlimit', return_value=(8 * 1024 * 1024, 8 * 1024 * 1024)
        ):
            with _fresh_issue_stack() as accumulator:
                await steps.run(command, params, sandbox, artifacts)

        assert not accumulator.issues
```

The JVM test needs a JDK. Check how `steps_run_test.py`'s Java tests are skipped when one is absent
and mirror that; if they are not skipped at all, leave it unmarked.

**Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/rbx/grading/steps_stack_limit_test.py -v -k Wired`
Expected: FAIL on the first test -- `assert 0 == 1`, no issue filed.

**Step 3: Write the implementation**

Add the helper right after `_maybe_complain_about_stack_limit`:

```python
def _finalize_limits(command: str, params: SandboxParams) -> None:
    """Settle the limits a program will actually run under, and complain if they
    are not the ones that were asked for.

    The order matters: the JVM carve-out drops the stack limit, and a limit that
    was dropped is not one worth warning about.
    """
    _relax_limits_for_jvm(command, params)
    _maybe_complain_about_stack_limit(params)
```

Then replace all three `_relax_limits_for_jvm(...)` call sites:

- `steps.py:832` (in the compile loop): `_relax_limits_for_jvm(command, params)` ->
  `_finalize_limits(command, params)`
- `steps.py:925` (in `run`): `_relax_limits_for_jvm(command, params)` ->
  `_finalize_limits(command, params)`
- `steps.py:969` (in the coordinated/communication run):
  `_relax_limits_for_jvm(solution.command, solution_params)` ->
  `_finalize_limits(solution.command, solution_params)`

Verify no other caller remains with `grep -n '_relax_limits_for_jvm(' rbx/grading/steps.py`.
Expected: exactly two hits -- the `def` and the call inside `_finalize_limits`.

**Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/rbx/grading/steps_stack_limit_test.py -v
uv run pytest tests/rbx/grading/steps_run_test.py tests/rbx/grading/steps_compile_test.py tests/rbx/grading/steps_run_coordinated_test.py -v
```

Expected: all PASS. The existing JVM carve-out tests in `steps_run_test.py` must still pass
untouched -- they are what pins the ordering inside `_finalize_limits`.

**Step 5: Commit**

Stage the same two files, then commit with
`feat(grading): warn when a configured stack limit cannot be honored`.

---

## Task 4: Docs

**Files:**
- Modify: `docs/stack-limit.md` (the *Cap the stack of the programs rbx runs* section, at the end)

**Step 1: Write the docs**

Read [`docs/plans/docs-writing-style-guide.md`](docs-writing-style-guide.md) first. The page already
has an *Increase the hard stack limit* section earlier on, so this is a cross-link, not a new
recipe -- do not repeat the `limits.conf` instructions.

After the existing `!!! warning` about macOS and before the `!!! note` about the JVM, add:

```markdown
Your machine's hard limit is a ceiling on `stackLimit`. If you ask for 256 MiB on a machine whose
hard limit is 8 MiB, programs get 8 MiB, and {{rbx}} says so once at the end of the run. See
[Increase the hard stack limit](#increase-the-hard-stack-limit) for how to raise it.
```

**Step 2: Verify the docs build and the anchor resolves**

Run: `uv run mkdocs build`
Expected: builds. There are around nine pre-existing unrelated warnings on this project; ignore
those, but check that none of them is a broken link to `#increase-the-hard-stack-limit`. Do not use
`--strict`.

**Step 3: Commit**

Stage `docs/stack-limit.md` and commit with
`docs: note that the hard limit is a ceiling on stackLimit`.

---

## Task 5: Clamp an unset stack limit to the hard limit

Separable from the warning, and separately committed. When `stackLimit` is unset, `get_preexec_fn`
asks for `RLIM_INFINITY`; on a machine with a finite hard limit that call **fails**, and the
fallback is the inherited *soft* limit -- not the hard one. So `EnvironmentSandbox.stackLimit`'s
promise that "the stack is made as large as the system allows"
(`rbx/box/environment.py:133`) is false on any such machine: you get the shell's 8 MiB even when the
hard limit is far higher. Clamping the request fixes it without moving any syscall out of the child.

**Files:**
- Modify: `rbx/grading/judge/program.py:99-125` (`get_preexec_fn`)
- Test: `tests/rbx/grading/judge/test_program.py`

**Step 1: Write the failing tests**

Add to the same class that holds `test_preexec_fn_applies_stack_limit_on_linux`
(`tests/rbx/grading/judge/test_program.py:604`), following its idiom exactly:

```python
    @mock.patch('os.setpgid')
    @mock.patch('resource.setrlimit')
    @mock.patch('sys.platform', 'linux')
    def test_preexec_fn_clamps_an_unset_stack_limit_to_the_hard_limit(
        self, mock_setrlimit, _
    ):
        """Asking for RLIM_INFINITY under a finite hard limit fails outright and
        leaves the inherited soft limit in place, which is far smaller than what
        the system allows."""
        import resource as resource_module

        with mock.patch(
            'resource.getrlimit',
            return_value=(8 * 1024 * 1024, 512 * 1024 * 1024),
        ):
            get_preexec_fn(ProgramParams())()

        stack_calls = [
            call
            for call in mock_setrlimit.call_args_list
            if call[0][0] == resource_module.RLIMIT_STACK
        ]
        assert len(stack_calls) == 1
        assert stack_calls[0][0][1] == (512 * 1024 * 1024, 512 * 1024 * 1024)

    @mock.patch('os.setpgid')
    @mock.patch('resource.setrlimit')
    @mock.patch('sys.platform', 'linux')
    def test_preexec_fn_clamps_a_configured_stack_limit_to_the_hard_limit(
        self, mock_setrlimit, _
    ):
        import resource as resource_module

        with mock.patch(
            'resource.getrlimit',
            return_value=(8 * 1024 * 1024, 64 * 1024 * 1024),
        ):
            get_preexec_fn(ProgramParams(stack_limit=256))()

        stack_calls = [
            call
            for call in mock_setrlimit.call_args_list
            if call[0][0] == resource_module.RLIMIT_STACK
        ]
        assert len(stack_calls) == 1
        assert stack_calls[0][0][1] == (64 * 1024 * 1024, 64 * 1024 * 1024)
```

Note the existing `test_preexec_fn_applies_stack_limit_on_linux` does not mock `getrlimit`, so it
reads the real hard limit. On a CI machine with an unlimited hard limit it keeps passing unchanged;
on a machine whose hard limit is below 64 MiB it would now fail. Add a `getrlimit` mock returning
`(8 * 1024 * 1024, resource_module.RLIM_INFINITY)` to that test so it pins the behaviour it means to
pin regardless of the host. Do the same for the existing unset-limit assertion at
`test_program.py:585-599` if it asserts `RLIM_INFINITY` is requested -- with a mocked unlimited hard
limit, that assertion stays true.

**Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/rbx/grading/judge/test_program.py -v -k stack`
Expected: the two new tests FAIL -- the requested value is `RLIM_INFINITY` and `256 MiB`
respectively, not the clamped one.

**Step 3: Write the implementation**

In `get_preexec_fn`, replace the `sys.platform != 'darwin'` block:

```python
        # Darwin is left alone: it refuses most RLIMIT_STACK changes, so the
        # stack there is whatever the host shell hands down (which is what
        # `rbx`'s stack limit check nags about).
        if sys.platform != 'darwin':
            stack_limit = (
                params.stack_limit * 1024 * 1024
                if params.stack_limit is not None
                else resource.RLIM_INFINITY
            )
            # Clamp to the hard limit rather than let the call fail: a refused
            # `setrlimit` leaves the *inherited soft* limit in place, which is
            # usually far below what the system would actually allow.
            try:
                _, hard = resource.getrlimit(resource.RLIMIT_STACK)
                if hard != resource.RLIM_INFINITY and (
                    stack_limit == resource.RLIM_INFINITY or stack_limit > hard
                ):
                    stack_limit = hard
            except (ValueError, OSError):
                pass
            try:
                resource.setrlimit(resource.RLIMIT_STACK, (stack_limit, stack_limit))
            except (ValueError, OSError):
                # Asking for more than the hard limit allows; fall back to
                # whatever the process already inherited.
                pass
```

The second `try`/`except` stays. It is the backstop for anything the clamp did not anticipate, and
removing it would let an exception in the forked child take the whole run down.

**Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/rbx/grading/judge/test_program.py -v`
Expected: all PASS, including `test_preexec_fn_survives_a_stack_limit_the_system_refuses`.

**Step 5: Commit**

Stage `rbx/grading/judge/program.py` and `tests/rbx/grading/judge/test_program.py`, then commit with
`fix(grading): clamp the stack limit to the hard limit instead of failing`.

---

## Task 6: Verify nothing else regressed

**Step 1: Run the touched suites**

```bash
uv run pytest \
  tests/rbx/grading/steps_stack_limit_test.py \
  tests/rbx/grading/steps_run_test.py \
  tests/rbx/grading/steps_compile_test.py \
  tests/rbx/grading/steps_run_coordinated_test.py \
  tests/rbx/grading/judge/test_program.py \
  tests/rbx/box/code_run_test.py \
  tests/rbx/box/test_environment_sandbox.py \
  tests/rbx/box/sanitizers/issue_stack_test.py \
  -v
```

Expected: all PASS. `code_run_test.py`'s nine `test_stack_limit_check_*` tests cover
`rbx/box/code.py`, which this work does not touch -- if any of them changed behaviour, something was
edited that should not have been.

Do **not** run the whole suite. It is slow and produces spurious sandbox wall-clock timeouts.

**Step 2: Lint and format**

```bash
uv run ruff check . && uv run ruff format --check .
```

Expected: clean.

**Step 3: Push and open a draft PR**

Push the branch and open a draft PR referencing #800. Note that `gh pr create` works, but
`gh pr edit` and `gh pr view` fail on this repo with a classic-Projects GraphQL error -- use
`gh api -X PATCH repos/rsalesc/rbx/pulls/N` to edit instead.
