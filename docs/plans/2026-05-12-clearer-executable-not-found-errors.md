# Clearer "executable not found" errors (#374) — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** When a command fails because the referenced executable does not exist (typo in a generator/checker command, or a missing compiler/interpreter), surface a clear "executable not found" message instead of a generic `INTERNAL ERROR` / terse `Command X not found`.

**Architecture:** Introduce a `ProgramNotFoundError(ProgramError)` subclass raised when `subprocess.Popen` hits `FileNotFoundError`/`PermissionError`. On the compilation path, format a friendlier message and stash the missing executable name on the raised `CompilationError`. On the execution path, stop dropping `RunLog.sandbox` — include it in `get_summary()` and propagate it as `CheckerResult.message`. The skipped-solutions end-of-run summary names the reason. No new `Outcome` or sandbox exit-status values.

**Tech Stack:** Python 3, pytest, Pydantic v2, Typer/Rich. Run tests with `uv run pytest`.

**Design doc:** `docs/plans/2026-05-12-clearer-executable-not-found-errors-design.md`

**Conventions:** single quotes; absolute imports only; commits via the `/commit` skill (conventional commits — use `feat`/`test`/`refactor` as appropriate). Run `uv run ruff check . && uv run ruff format .` before each commit.

---

### Task 1: `ProgramNotFoundError` exception

**Files:**
- Modify: `rbx/grading/judge/program.py` (around `class ProgramError` at line 183, and the `_run` handlers at lines 265-268)
- Test: `tests/rbx/grading/judge/test_program.py` (`TestEdgeCases.test_nonexistent_program`, line 672)

**Step 1: Update the failing test**

In `tests/rbx/grading/judge/test_program.py`, replace `test_nonexistent_program`:

```python
    def test_nonexistent_program(self):
        """Test execution of non-existent program."""
        from rbx.grading.judge.program import ProgramNotFoundError

        params = ProgramParams()
        command = ['/nonexistent/program']

        with pytest.raises(ProgramNotFoundError) as exc_info:
            Program(command, params)

        assert exc_info.value.executable == '/nonexistent/program'
        assert '/nonexistent/program' in str(exc_info.value)
```

**Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/rbx/grading/judge/test_program.py::TestEdgeCases::test_nonexistent_program -v`
Expected: FAIL — `ImportError`/`AttributeError` for `ProgramNotFoundError`.

**Step 3: Implement**

In `rbx/grading/judge/program.py`, after `class ProgramError(Exception): pass` (line ~184), add:

```python
class ProgramNotFoundError(ProgramError):
    def __init__(self, executable: str, *, permission_denied: bool = False):
        self.executable = executable
        self.permission_denied = permission_denied
        if permission_denied:
            msg = f"Permission denied when running executable '{executable}'."
        else:
            msg = (
                f"Executable '{executable}' was not found "
                '— is it installed and on your PATH?'
            )
        super().__init__(msg)
```

Then change the handlers in `_run` (lines 265-268) from:

```python
        except FileNotFoundError as e:
            raise ProgramError(f'Command {self.command[0]} not found') from e
        except PermissionError as e:
            raise ProgramError(f'Permission denied for command {self.command}') from e
```

to:

```python
        except FileNotFoundError as e:
            raise ProgramNotFoundError(self.command[0]) from e
        except PermissionError as e:
            raise ProgramNotFoundError(
                self.command[0], permission_denied=True
            ) from e
```

**Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/rbx/grading/judge/test_program.py -v`
Expected: PASS.

**Step 5: Commit** (via `/commit` skill)

`feat(grading): add ProgramNotFoundError for missing executables`

---

### Task 2: Friendlier compilation message + stash missing executable on `CompilationError`

**Files:**
- Modify: `rbx/box/exception.py` (`class CompilationError` lives in `rbx/grading/steps.py`, line ~714 — check; `RbxException` base is in `rbx/box/exception.py`)
- Modify: `rbx/grading/steps.py` — import (`from rbx.grading.judge.program import ProgramError` at line 24) and the `except ProgramError` block at lines 753-759
- Test: `tests/rbx/grading/steps_compile_test.py`

**Step 1: Write the failing test**

Add to `tests/rbx/grading/steps_compile_test.py` (mirror the style of existing tests there — they use the `sandbox` and `cleandir` fixtures and `steps.compile`). The test compiles a "compilable" whose compilation command references a bogus executable and asserts the raised `CompilationError` mentions the executable and exposes `not_found_executable`:

```python
async def test_compile_missing_compiler_reports_not_found(
    sandbox: SandboxBase, cleandir: pathlib.Path
):
    artifacts = steps.GradingArtifacts(root=cleandir)
    with pytest.raises(steps.CompilationError) as exc_info:
        await steps.compile(
            commands=['definitely-not-a-real-compiler-xyz src.cpp -o exe'],
            params=SandboxParams(),
            sandbox=sandbox,
            artifacts=artifacts,
        )
    assert exc_info.value.not_found_executable == 'definitely-not-a-real-compiler-xyz'
    assert 'definitely-not-a-real-compiler-xyz' in str(exc_info.value)
    assert 'not found' in str(exc_info.value).lower()
```

(Check `steps.compile`'s actual signature in `rbx/grading/steps.py` near line 720 and adjust kwarg names if needed.)

**Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/rbx/grading/steps_compile_test.py::test_compile_missing_compiler_reports_not_found -v`
Expected: FAIL — `not_found_executable` attribute missing (and/or message not friendly).

**Step 3: Implement**

(a) In `rbx/grading/steps.py`, add `ProgramNotFoundError` to the import on line 24:

```python
from rbx.grading.judge.program import ProgramError, ProgramNotFoundError
```

(b) Give `CompilationError` an optional attribute. Find `class CompilationError(RbxException)` in `rbx/grading/steps.py` (~line 714) and add a class-level default:

```python
class CompilationError(RbxException):
    not_found_executable: Optional[str] = None
```

(c) In the `except ProgramError as e:` block inside `compile()` (lines 753-759), special-case `ProgramNotFoundError`:

```python
        except ProgramError as e:
            with CompilationError() as err:
                if isinstance(e, ProgramNotFoundError):
                    err.not_found_executable = e.executable
                    err.print(
                        f"[error]FAILED[/error] The compiler/interpreter "
                        f"'[item]{e.executable}[/item]' was not found while running",
                        utils.highlight_json_obj(cmd),
                    )
                    err.print(
                        '[warning]Is it installed and on your PATH?[/warning]'
                    )
                else:
                    err.print(
                        '[error]FAILED[/error] Preprocessing failed with command',
                        utils.highlight_json_obj(cmd),
                    )
                    err.print(e)
```

Note: the `with CompilationError() as err:` block raises the `err` on exit (see `RbxException.__exit__`), so `not_found_executable` is carried to the caller.

**Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/rbx/grading/steps_compile_test.py -v`
Expected: PASS.

**Step 5: Commit** (`/commit` skill)

`feat(grading): clearer compilation error when compiler is missing`

---

### Task 3: `RunLog.get_summary()` surfaces the sandbox error message

**Files:**
- Modify: `rbx/grading/steps.py` — `RunLog.get_summary()` at lines 266-271
- Test: `tests/rbx/grading/steps_run_test.py`

**Step 1: Write the failing test**

Add to `tests/rbx/grading/steps_run_test.py` (no fixtures needed — it's a pure model test; put it near `test_run_handles_program_error_and_returns_sandbox_error`):

```python
def test_run_log_summary_includes_sandbox_message_on_sandbox_error():
    log = steps.RunLog(
        exitcode=1,
        exitstatus=SandboxBase.EXIT_SANDBOX_ERROR,
        sandbox="Executable 'python3' was not found — is it installed and on your PATH?",
    )
    summary = log.get_summary()
    assert 'python3' in summary
    assert 'not found' in summary.lower()


def test_run_log_summary_no_sandbox_message_when_empty():
    log = steps.RunLog(exitcode=1, exitstatus=SandboxBase.EXIT_SANDBOX_ERROR, sandbox='')
    assert 'None' not in log.get_summary()  # sanity: no dangling text
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/grading/steps_run_test.py -k run_log_summary -v`
Expected: FAIL — `python3` not in summary.

**Step 3: Implement**

Replace `RunLog.get_summary()` (lines 266-271):

```python
    def get_summary(self) -> str:
        if self.exitcode == 0:
            return 'OK'
        time = self.time or 0.0
        memory = self.memory or 0
        summary = (
            f'FAILED with exit code {self.exitcode} and sandbox status '
            f'{self.exitstatus} (time: {time}s, memory: {memory // (1024 * 1024)}MB)'
        )
        if self.exitstatus == SandboxBase.EXIT_SANDBOX_ERROR and self.sandbox:
            summary += f'\nReason: {self.sandbox}'
        return summary
```

(`SandboxBase` is already imported in `steps.py`.)

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/grading/steps_run_test.py -k run_log_summary -v`
Expected: PASS.

**Step 5: Commit** (`/commit` skill)

`feat(grading): include sandbox failure reason in RunLog summary`

---

### Task 4: Propagate the sandbox message into `CheckerResult.message`

**Files:**
- Modify: `rbx/box/checkers.py` — `_check_pre_output` (line 168-169) and `process_checker_run_log` (lines 220-231)
- Test: `tests/rbx/box/checkers_test.py`

**Step 1: Write the failing test**

Add to `tests/rbx/box/checkers_test.py` (check existing imports; `Outcome` and `SandboxBase` should be importable; build a minimal `RunLog`):

```python
def test_process_checker_run_log_surfaces_sandbox_message():
    from rbx.box import checkers
    from rbx.grading import steps
    from rbx.grading.judge.sandbox import SandboxBase
    from rbx.grading.steps import Outcome

    run_log = steps.RunLog(
        exitcode=1,
        exitstatus=SandboxBase.EXIT_SANDBOX_ERROR,
        sandbox="Executable 'checker' was not found — is it installed and on your PATH?",
    )
    result = checkers.process_checker_run_log(run_log, message='')
    assert result.outcome == Outcome.INTERNAL_ERROR
    assert 'checker' in result.message
    assert 'not found' in result.message.lower()


def test_process_checker_run_log_falls_back_when_no_sandbox_message():
    from rbx.box import checkers
    from rbx.grading import steps
    from rbx.grading.judge.sandbox import SandboxBase

    run_log = steps.RunLog(
        exitcode=1, exitstatus=SandboxBase.EXIT_SANDBOX_ERROR, sandbox=''
    )
    result = checkers.process_checker_run_log(run_log, message='')
    assert result.message == 'sandbox failed to run checker'
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/checkers_test.py -k surfaces_sandbox_message -v`
Expected: FAIL — message is the hardcoded string, no `checker`/`not found`.

**Step 3: Implement**

In `rbx/box/checkers.py`:

(a) `process_checker_run_log` (lines ~220-231) — change the `EXIT_SANDBOX_ERROR` branch:

```python
    if (
        checker_run_log is not None
        and checker_run_log.exitstatus == SandboxBase.EXIT_SANDBOX_ERROR
    ):
        # When the sandbox fails, it means the checker failed to run.
        return CheckerResult(
            outcome=Outcome.INTERNAL_ERROR,
            message=checker_run_log.sandbox or 'sandbox failed to run checker',
        )
```

(b) `_check_pre_output` (line 168-169) — change:

```python
    if run_log.exitstatus == SandboxBase.EXIT_SANDBOX_ERROR:
        return CheckerResult(
            outcome=Outcome.INTERNAL_ERROR, message=run_log.sandbox or ''
        )
```

Leave the other `INTERNAL_ERROR` returns (`run_log is None`, line 234, etc.) as-is — there's no message available there.

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/checkers_test.py -v`
Expected: PASS (all of `checkers_test.py`, to catch regressions).

**Step 5: Commit** (`/commit` skill)

`feat(box): surface sandbox failure reason in checker results`

---

### Task 5: Name the reason in the skipped-solutions summary

**Files:**
- Modify: `rbx/box/solutions.py` — `FailedToCompileSolutionIssue` (lines ~248-256) and its construction in `compile_solutions().failed` (line ~317)
- Test: `tests/rbx/box/solutions_test.py` (or `tests/rbx/box/solutions_compile_warnings_test.py` — pick whichever has the lighter fixture setup; a direct unit test of the issue class is fine)

**Step 1: Write the failing test**

Add a focused unit test (no package fixture needed):

```python
def test_failed_to_compile_issue_includes_not_found_reason():
    from rbx.box.solutions import FailedToCompileSolutionIssue
    from rbx.box.schema import Solution, ExpectedOutcome
    from rbx.grading.steps import CompilationError

    sol = Solution(path=pathlib.Path('sols/wa.py'), outcome=ExpectedOutcome.WRONG_ANSWER)
    exc = CompilationError()
    exc.not_found_executable = 'python3'
    issue = FailedToCompileSolutionIssue(sol, exception=exc)
    msg = issue.get_detailed_message()
    assert 'wa.py' in msg
    assert 'python3' in msg


def test_failed_to_compile_issue_generic_message_without_reason():
    from rbx.box.solutions import FailedToCompileSolutionIssue
    from rbx.box.schema import Solution, ExpectedOutcome

    sol = Solution(path=pathlib.Path('sols/wa.py'), outcome=ExpectedOutcome.WRONG_ANSWER)
    issue = FailedToCompileSolutionIssue(sol)
    assert 'could not be compiled and was skipped' in issue.get_detailed_message()
```

(Adjust `Solution` construction to match the real schema — check `rbx/box/schema.py` for required fields. Use `package`/conftest fixtures if `Solution` can't be built standalone.)

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/rbx/box/solutions_test.py -k failed_to_compile_issue -v`
Expected: FAIL — `FailedToCompileSolutionIssue` doesn't accept `exception`.

**Step 3: Implement**

In `rbx/box/solutions.py`:

```python
class FailedToCompileSolutionIssue(issue_stack.Issue):
    def __init__(self, solution: Solution, exception: Optional[BaseException] = None):
        self.solution = solution
        self.exception = exception

    def get_detailed_section(self) -> Tuple[str, ...]:
        return ('solutions',)

    def _reason(self) -> Optional[str]:
        from rbx.grading.steps import CompilationError

        if isinstance(self.exception, CompilationError) and self.exception.not_found_executable:
            return f"'{self.exception.not_found_executable}' not found"
        return None

    def get_detailed_message(self) -> str:
        reason = self._reason()
        if reason is not None:
            return f'{self.solution.href()} could not be compiled ({reason}) and was skipped.'
        return f'{self.solution.href()} could not be compiled and was skipped.'
```

And in `compile_solutions().failed` (line ~317), pass the exception:

```python
                key.exception = exception
                issue_stack.add_issue(
                    FailedToCompileSolutionIssue(key.solution, exception=exception)
                )
```

(`Optional` is already imported in `solutions.py`; if not, add it.)

**Step 4: Run to verify it passes**

Run: `uv run pytest tests/rbx/box/solutions_test.py -k failed_to_compile_issue -v`
Expected: PASS.

**Step 5: Commit** (`/commit` skill)

`feat(box): name the reason in the skipped-solutions summary`

---

### Task 6: Full-suite check + lint

**Step 1:** Run: `uv run ruff check . && uv run ruff format --check .` — fix anything reported (`uv run ruff check --fix . && uv run ruff format .`).

**Step 2:** Run the touched test modules together:

```bash
uv run pytest tests/rbx/grading/judge/test_program.py tests/rbx/grading/steps_compile_test.py tests/rbx/grading/steps_run_test.py tests/rbx/box/checkers_test.py tests/rbx/box/solutions_test.py -v
```

Expected: all pass. (The repo has known pre-existing unrelated failures in `validators_test.py` / `code_run_test.py` / docker e2e — out of scope; verify on `main` if unsure.)

**Step 3:** If any formatting/lint changes were made, commit them: `style: ruff formatting` (only if needed).

---

### Notes for the implementer

- `superpowers:test-driven-development` — follow the red/green cycle per task.
- `superpowers:verification-before-completion` — run the listed commands and confirm output before claiming done.
- Do **not** add a new `Outcome` value or sandbox exit-status; that was explicitly ruled out.
- The `SKIPPED (<reason>)` LiveTasks UI is out of scope — tracked in issue #448.
- If `steps.compile`'s signature differs from what Task 2's test assumes, look at an existing test in `tests/rbx/grading/steps_compile_test.py` and copy its call shape.
