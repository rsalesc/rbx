# Warn when a configured `stackLimit` cannot be honored

Design for [#800](https://github.com/rsalesc/rbx/issues/800). Follow-up to #799, which wired
`EnvironmentSandbox.stackLimit` through to `RLIMIT_STACK` on Linux.

## Problem

`get_preexec_fn` (`rbx/grading/judge/program.py`) applies the stack limit inside the forked child
and swallows failures, because an exception raised in `preexec_fn` takes the whole run down. The
`except` is correct, but it means a setter who configures `stackLimit: 256` on a machine whose hard
`RLIMIT_STACK` is 8 MiB silently gets 8 MiB. Solutions then fail in ways that look like genuine
RTEs.

The diagnosis has to happen in the parent, before the fork, where a message can be printed and
attributed to the configuration that caused it.

## Why the check is OS-dependent

The two platforms fail differently, so one check with a platform guard will not do.

- **Linux** -- `setrlimit(RLIMIT_STACK)` does run, so the inherited *soft* limit is irrelevant: we
  raise it ourselves. Only the **hard** limit caps us, and exceeding it is the silent degradation
  #800 describes.
- **macOS** -- `get_preexec_fn` skips `RLIMIT_STACK` entirely, so the effective stack is whatever
  the shell handed down. A configured `stackLimit` is inert there regardless of the numbers,
  including the case where a deep-recursion solution that *should* be caught by the cap is not.

`_check_stack_limit` (`rbx/box/code.py:298`) is macOS-only today and stays that way. It is about a
different thing -- the *machine's* soft-vs-hard shell misconfiguration -- and it keeps its existing
`ulimit -s` guidance. The new check is about the *package's* `env.rbx.yml`, and gets its own home.

## Placement

`params.stack_space` is not final at `code.py`. `_relax_limits_for_jvm` (`rbx/grading/steps.py:506`)
nulls it for JVM commands, since an `RLIMIT_STACK` bounds only the JVM launcher's main thread. That
runs at three sites -- `steps.py:832`, `:925`, `:969` -- all of them well after the
`_check_stack_limit()` calls at `code.py:647` and `code.py:872`. Probing from `code.py` would warn
about a limit that is subsequently dropped, on every Java and Kotlin run.

So the probe goes in `steps.py`, immediately after the relax, folded into a single
`_finalize_limits(command, params)` helper called from those three sites so the pair cannot drift
apart. That is the last point at which `params.stack_space` is still the value that reaches
`stupid_sandbox.py:128` and `ProgramParams.stack_limit`, and it is still parent-side.

`steps.py` already imports from `rbx.box` (`safeeval`, `exception`), and
`_maybe_complain_about_sanitization` (`steps.py:679`) is the precedent for a platform-conditional
diagnostic in this file.

## Surfacing

The warning goes on the issue stack (`rbx/box/sanitizers/issue_stack.py`), not to the console.

- `IssueAccumulator._print_report_by` already skips repeated messages within a section, so "warn
  once per run" falls out of identical message strings -- no seen-set needed however many programs
  are spawned.
- `package.within_problem` prints the report once at the end of the command
  (`rbx/box/package.py:106`), so the warning lands in the Issues rule instead of scrolling past
  mid-build.

`StackLimitNotHonoredIssue(issue_stack.Issue)`, defined beside the probe:

- `get_severity()` -> `WARNING`, matching `TimingIssue` (`rbx/box/solutions.py:2325`). The run still
  produces meaningful results, and erroring would block runs that do not involve the affected
  language at all.
- Section key `('stack limit',)` for both detailed and overview.
- Overview is implemented, not just detailed: `IssueLevel.OVERVIEW` is set for contest-level runs
  (`rbx/box/contest/contest_package.py:296`), and a machine-wide ceiling affects every problem in
  the contest.

Messages carry the numbers and a link, nothing else -- no inline `ulimit -Hs` or `limits.conf`
recipe, since `docs/stack-limit.md` already has an *Increase the hard stack limit* section:

- Linux: "`stackLimit` is set to 256 MiB, but this machine's hard stack limit is 8 MiB, so programs
  run with 8 MiB. See https://rsalesc.github.io/rbx/stack-limit"
- macOS: "`stackLimit` is set to 256 MiB, but it is not enforced on macOS. See
  https://rsalesc.github.io/rbx/stack-limit"

## Conditions

Gated on `setter_config.judging.check_stack`, the same switch that silences the existing check.
No-op when `params.stack_space is None` -- both because that is the documented "as large as the
system allows" path and because it is what JVM commands look like after the relax.

| Platform | Condition | Result |
| --- | --- | --- |
| Linux | `stack_space` set, hard limit finite and below it | warn, naming both values |
| Linux | `stack_space` set, hard limit unlimited or above it | silent |
| macOS | `stack_space` set | warn, "not enforced on macOS" |
| any | `stack_space` unset | silent |

## Related fix

When `stackLimit` is unset, the child asks for `RLIM_INFINITY`. On a machine with a finite hard
limit that call *fails*, and the fallback is the inherited **soft** limit -- not the hard one. So
`EnvironmentSandbox.stackLimit`'s promise that "the stack is made as large as the system allows"
(`rbx/box/environment.py:133`) is false on any such machine: you get the shell's 8 MiB even when the
hard limit is far higher.

`get_preexec_fn` should request `min(requested, hard)` rather than let the call fail outright. This
ships as a separate commit; it needs no syscall moved out of the child.

## Not in scope

Moving the `setrlimit` calls themselves out of `preexec_fn` -- they have to run in the child. Only
the probe moves. The child-side `except` stays exactly as it is: this is a diagnostic, not a new
failure mode.

## Docs

A short cross-link from *Cap the stack of the programs rbx runs* in `docs/stack-limit.md` to the
existing *Increase the hard stack limit* section, noting that the hard limit is a ceiling on
`stackLimit`.
