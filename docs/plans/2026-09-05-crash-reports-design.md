# Crash reports

## Problem

When rbx dies of an uncaught exception, everything useful about the failure
lives in terminal scrollback: the traceback, the command that produced it, the
directory it ran in. By the time someone -- or something -- gets around to
debugging it, the scrollback has been scrolled past, truncated, or lost with the
window. There is no artifact to hand over.

A crash should leave a file behind.

## What counts as a crash

Only exceptions that actually end the process unexpectedly. `KeyboardInterrupt`,
`typer.Abort`, `typer.Exit` and `SystemExit` are how rbx and its user stop it on
purpose, and `RbxException` is rbx's own channel for telling the user they did
something wrong -- a missing generator, a malformed `problem.rbx.yml`. None of
those are bugs, and logging them would bury the reports that are.

Task exceptions surfacing through the asyncio exception handler, and exceptions
raised in background threads, are out of scope: they frequently do not end the
process at all.

## Where the hook goes

`rbx/box/main.py:app()` already wraps `run_app_cli()` in a `try` with a clause
per intentional-exit case. The crash clause goes last, reports, and re-raises so
the traceback still renders exactly as it does today.

It cannot hang off `sys.excepthook`. `Typer.__call__` opens with

```python
if sys.excepthook != except_hook:
    sys.excepthook = except_hook
```

so any hook installed before the CLI runs is replaced the moment it runs. (This
is also why the `KeyboardInterrupt` suppression in
`_install_no_exception_handlers` never takes effect -- untouched here, but worth
knowing.) The `try` block is the seam that survives, because typer re-raises
into it.

## Format

Markdown with a YAML frontmatter block. The frontmatter is a clean parse target;
the body is what a person reads.

```markdown
---
rbx_version: "1.4.2"
timestamp: "2026-09-05T14:12:33+00:00"
command: "rbx run -s sol.cpp"
cwd: "/Users/x/probs/a-plus-b"
package: "/Users/x/probs/a-plus-b"
exception: "KeyError"
message: "'foo'"
python: "3.11.9"
platform: "darwin"
pid: 48211
argv: ["rbx", "run", "-s", "sol.cpp"]
---

# rbx crash

`rbx run -s sol.cpp` in `/Users/x/probs/a-plus-b`

## Traceback

```
Traceback (most recent call last):
...
```
```

`command` is the shell-quoted reconstruction of the invocation and `cwd` its
absolute working directory -- the two facts a reader needs first, named plainly
and sitting at the top. Scalars are emitted as JSON strings, which are valid
YAML double-quoted scalars, so no value can break the block.

## Where the file goes

The canonical report is written to `<app path>/crashes/<UTC timestamp>-<pid>.md`
and the directory is pruned to the newest 20 reports. A `latest.md` symlink
points at the most recent one.

If the crash happened inside a package whose `.rbx` cache directory already
exists, a `last-crash.md` symlink is dropped in there too. `.rbx` is gitignored
by every preset and wiped whenever the cache is cleared, so the pointer expires
on its own and never reaches a commit. The package is located by walking
ancestors for `problem.rbx.yml` or `contest.rbx.yml` -- not by
`package.get_problem_cache_dir()`, which takes cache locks and can itself raise.

Symlinks are best-effort. On a filesystem that refuses them the report is still
written, and only the global path is reported.

## Failure is not an option

`report_crash` is wrapped end to end in `except Exception: return None`. A bug in
the crash reporter must never mask, replace, or add noise to the crash it exists
to record. The caller prints a path only when it gets one back.
