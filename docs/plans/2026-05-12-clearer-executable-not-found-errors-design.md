# Clearer "executable not found" errors (#374)

## Problem

When a command fails because the referenced executable does not exist — a typo in
a generator/checker/validator/interactor command, or a missing compiler/interpreter
for a solution's language — `rbx` currently surfaces a generic failure. During
execution the user sees `INTERNAL ERROR` (or `FAILED with ... sandbox status
sandbox error`) with no hint that the real cause is a missing binary; the helpful
diagnostic produced internally is dropped on the floor.

## Current state (as found)

- `rbx/grading/judge/program.py:265-268` already detects the case: a
  `FileNotFoundError`/`PermissionError` from `subprocess.Popen` is turned into a
  `ProgramError("Command <exe> not found")`.
- Compilation path (`rbx/grading/steps.py:compile`, ~lines 749-755): the
  `ProgramError` message **is** printed via `CompilationError`. Functional but
  terse.
- Execution path (`rbx/grading/steps.py:run` → `_build_program_error_run_log`,
  ~lines 668-680, 824-825): the `ProgramError` becomes a `RunLog` with
  `exitstatus == EXIT_SANDBOX_ERROR` and the message stored in `RunLog.sandbox`.
  Nothing ever reads `RunLog.sandbox` for display — `get_summary()` ignores it,
  and `rbx/box/checkers.py` maps `EXIT_SANDBOX_ERROR` to `Outcome.INTERNAL_ERROR`
  with an empty (or hardcoded `"sandbox failed to run checker"`) message.
- Solution compile-failure semantics are already what we want:
  - `rbx run <single solution>` / `-s` selecting one: `compile_solutions()` sets
    `should_fail` (because `len(expanded_solutions) <= 1`) and re-raises the
    `CompilationError` — the command aborts with the full compiler error.
  - `rbx run` over many solutions / `rbx build` verify: the failing solution is
    marked `SKIPPED`, a `FailedToCompileSolutionIssue` is recorded, and the rest
    continue.
  - Main/model solution missing its compiler during `rbx build`: always aborts
    (`rbx/box/generators.py:641-670`) — you cannot generate outputs without it.

So the gap is **message quality**, not control flow. No new `Outcome` or sandbox
exit-status values are needed.

## Design

### 1. `ProgramNotFoundError`

Add `class ProgramNotFoundError(ProgramError)` in `rbx/grading/judge/program.py`.
The `FileNotFoundError`/`PermissionError` handlers raise it instead of a bare
`ProgramError`, with an actionable message that names the executable, e.g.:

> `Executable 'python3' was not found — is it installed and on your PATH?`

Because it is a strict subclass, every existing `except ProgramError` and
`except CompilationError` keeps catching it; nothing about control flow changes.
It just lets call sites format a friendlier message and detect the case without
string-sniffing.

### 2. Compilation path

In `rbx/grading/steps.py:compile()`, when the caught `ProgramError` is a
`ProgramNotFoundError`, print a "compiler/interpreter not found" framing rather
than the bare message — including the executable name and the offending command.

### 3. Execution path — stop dropping `RunLog.sandbox`

- `RunLog.get_summary()`: when `exitstatus == EXIT_SANDBOX_ERROR` and `sandbox`
  is non-empty, append the `sandbox` message to the summary string. (Only on that
  exitstatus — on success `sandbox` holds a JSON log dump, not a message.)
- `rbx/box/checkers.py`: at the two sites mapping `EXIT_SANDBOX_ERROR` →
  `Outcome.INTERNAL_ERROR`, set `CheckerResult.message` from `run_log.sandbox`
  (falling back to the existing text when empty).

With these, generators already print `get_summary()` and solution reporters
already print `eval.result.message`, so the not-found diagnostic reaches the user
on the execution path with no further plumbing.

### 4. Skipped-solution summary reason

`FailedToCompileSolutionIssue` takes the underlying exception (already stashed on
`key.exception`) and includes its reason in `get_detailed_message()`, so the
end-of-run skipped-solutions summary reads e.g.
`sol.py could not be compiled (python3 not found) and was skipped.`

## Testing

- `tests/rbx/grading/judge/test_program.py::test_nonexistent_program`: assert
  `ProgramNotFoundError` is raised and the message names the executable.
- `rbx/grading/steps.py`: unit test that `RunLog.get_summary()` includes the
  `sandbox` message when `exitstatus == EXIT_SANDBOX_ERROR`.
- `rbx/box/checkers.py`: a checker run hitting `EXIT_SANDBOX_ERROR` yields a
  `CheckerResult` whose `message` carries the sandbox text.
- Test-package fixture(s):
  - a generator referencing a bogus executable → `rbx build` shows the
    not-found message;
  - a solution whose language compiler is (test-)missing: run alone → abort with
    a clear message; run alongside other solutions → skipped, and the
    skipped-solutions summary names the reason.

## Out of scope

- `SKIPPED (<reason>)` in the `LiveTasks` progress view — tracked in #448
  (mirrors the `WARNINGS (<summary>)` pattern from #447), to be done after this
  PR merges.
- The shell exit-code-127 "command not found" case (command run via a shell that
  reports the failure itself rather than Python raising `FileNotFoundError`).
- Any new `Outcome` enum value or sandbox exit-status value.
