# Statement builds should fail in isolation

Design for [#705](https://github.com/rsalesc/rbx/issues/705).
Date: 2026-08-23.

## Problem

`rbx contest st b` aborts the whole command the moment any one statement fails.
If a contest builds `en` and `pt` and one problem has no `en` statement, `pt`
never builds — even though nothing about `pt` is broken.

Two distinct defects hide behind that symptom, and they pull in opposite
directions.

### Defect 1 — statements are not isolated from each other

The command has two nested loops and only the inner one is protected:

- **outer loop**, `rbx/box/contest/statements.py:130`, over `valid_statements`
  (one per contest statement, i.e. per language/name) — bare, no `try`. The
  first statement that raises kills every later one.
- **inner loop**, `rbx/box/contest/build_contest_statements.py:209`, over the
  contest's problems — has a `try`, and deliberately re-raises a subset of
  errors.

A problem with no matching `en` statement raises `StatementResolverError`
(`rbx/box/statements/resolver.py:211-216`), an `RbxException`. That hits the
inner loop's deliberate re-raise at `build_contest_statements.py:228-232`,
escapes `build_statement`, and lands in the unprotected outer loop. `pt` dies
with it.

The missing-language case in the issue is not the only vector. A pdflatex
failure exits through `_finish` → `render.compile_pdf`
(`rbx/box/statements/render.py:247-250`) with `typer.Exit(1)`, which kills the
remaining languages just as effectively and is more common in practice.

The problem-level command has the same unprotected shape at
`rbx/box/statements/build_statements.py:403`, so a broken `en` also stops `pt`
under plain `rbx st b`.

A further consequence of the escape: the built/failed report at
`contest/statements.py:165-173` never prints, because the exception leaves the
function before it. The user gets a traceback-or-error and no account of what
did build.

### Defect 2 — criticality is decided by accident, not by design

The inner loop classifies failures by exception *type*:

```python
except (typer.Exit, RbxException):
    raise            # "hard config/abort errors must surface"
except Exception as exc:
    ...              # warn, add issue, drop this problem, continue
```

That tuple is not a policy, it is a guess about which types authors reach for.
Two common failures fall on the wrong side of it:

- A **Jinja undefined-variable** error in a problem fragment raises
  `typer.Abort` (`rbx/box/statements/latex_jinja.py:305-318`), which is not in
  the tuple. It is silently demoted to a per-problem skip — exactly the
  "statement silently goes partial" outcome the tiering was meant to prevent.
- A missing `contestProblemTemplate` is a bare `assert`
  (`build_contest_statements.py:314`) → `AssertionError`, also outside the
  tuple. Every problem is skipped, each with a confusing per-problem message,
  and a near-empty PDF is produced.

And the soft branch does not affect the exit code. `build_statement` returns
normally after skipping a problem, and only the samples-phase `failed_problems`
list drives `typer.Exit(1)` (`contest/statements.py:175-182`). So **a problem
can vanish from the problemset PDF and the command reports success.**

### The pre-existing silent-partial paths

Partial problemset PDFs are already emitted today, in two places, neither
flagged:

1. **Samples phase** — a problem whose samples fail to build is dropped from
   `problems_of_interest` (`contest/statements.py:111-118`). The joined PDF is
   then built without it, written to `build/`, and the command exits 1
   afterwards.
2. **Inner render skip** — as above, exit 0.

Structurally nothing notices: `problem_ctxs` is just a list
(`build_contest_statements.py:240-241`), the contest template emits one fewer
`\subimport`, the problem lettering shifts, and the PDF compiles fine. There is
no cross-check between `contest.problems` and `problem_ctxs`.

This matters for the design: shipping a `--partial` flag while these paths stay
unflagged would make the flag describe something the tool already does without
it.

## Requirements

1. A failure building one statement must never prevent another statement from
   building. This is unconditional, not opt-in.
2. Within one statement, anything that would make that statement *partial* is
   fatal **to that statement** — by default.
3. `--partial` opts into best-effort: a problem that fails is dropped and the
   statement is still produced.
4. No partial artifact is ever written without `--partial`.
5. The packagers must keep fail-fast. A silently incomplete Polygon/MOJ/BOCA
   upload is worse than an aborted one.
6. The command ends with an account of what built and what did not, and exits
   nonzero if anything failed.

## Design

### 1. Explicit criticality, replacing type-based tiering

Delete the `(typer.Exit, RbxException)` tuple from
`build_contest_statements.py`. The inner problem loop becomes:

```python
except Exception as exc:
    if partial:
        console.console.print(...)          # warn
        issue_stack.add_issue(StatementBuildIssue(problem))
        continue                            # drop the problem, keep the statement
    raise StatementBuildError(statement, problem, exc) from exc
```

Default: any problem-level failure fails **this statement**. `--partial`: drop
the problem and carry on.

This satisfies requirement 2 directly and fixes the `typer.Abort` /
`AssertionError` misclassification for free — the classification no longer
exists, so nothing can fall on the wrong side of it.

`StatementBuildError` is a new `RbxException` subclass carrying the statement,
the offending problem and the underlying error, so the summary can render a
one-line reason.

The bare `assert`s at `build_contest_statements.py:196`, `:306` and `:314`
should become real errors with messages; under the new rule they are fatal to
the statement either way, but an `AssertionError` in the summary tells the user
nothing.

### 2. Outer-loop isolation

`contest/statements.py:_execute_build` and
`build_statements.py:execute_build_on_statements` wrap each `build_statement`
call:

```python
for statement in valid_statements:
    try:
        built.append(await build_statement(...))
    except Exception as exc:
        issue_stack.add_issue(StatementFailedIssue(statement, exc))
        failed_statements.append((statement, exc))
```

Unconditional — no flag gates it. Requirement 1.

`execute_build_on_statements` is shared with the packagers, so it takes
`keep_going: bool = False`. The CLI passes `True`; every packager caller keeps
the current fail-fast behaviour by default. Requirement 5.

### 3. Closing the silent-partial holes

The samples-phase drop (`contest/statements.py:111-118`) currently removes a
problem from `problems_of_interest` and lets the join proceed. Under the new
rule a problem that failed its samples makes every joining statement partial,
so without `--partial` those statements fail; with `--partial` the problem is
dropped as today. Requirement 4.

### 4. Reporting

The summary goes through the existing issue stack rather than a second channel:

- `StatementBuildIssue(problem)` — already exists
  (`build_contest_statements.py:50-61`, overview section `('statement',)`).
  Retained for the `--partial` per-problem drop.
- `StatementFailedIssue(statement, reason)` — new, same section, for a whole
  statement failing.

`within_contest` already calls `issue_stack.print_current_report()` in a
`finally` (`rbx/box/contest/contest_package.py:230-238`), so the report survives
a nonzero exit.

The issue tree dedups by message, so it can under-report when several
statements fail the same way. The explicit built/failed rule at
`contest/statements.py:165-173` therefore stays and is extended with a failed
section listing each statement and its one-line reason. Outer-loop isolation is
what makes that rule reachable at all.

### 5. The flag

`--partial`, off by default, on `rbx contest st b`, `rbx contest tut b`,
`rbx st b`, `rbx tut b`. Not exposed to packagers.

Named for what it permits (an incomplete statement) rather than `--keep-going`,
which would describe the outer-loop behaviour — and that is unconditional, so it
needs no flag.

### Exit codes

- Any statement failed → **1**.
- `--partial` given and problems were dropped, but every statement was produced
  → **0**. The flag is an explicit statement of intent; forcing nonzero would
  make it unusable in scripts. The dropped problems are still listed in the
  issue report.

## Consequences accepted

- **Without `--partial`, one problem's sample failure now fails every
  statement**, where today it produced short PDFs and exit 1. This is
  requirement 4 working as intended, but it makes `--partial` load-bearing for a
  workflow that currently needs no flag. Accepted: the current behaviour writes
  a wrong PDF, and a wrong artifact is worse than a missing one.
- Keep-going makes failing runs slower — each language re-renders every problem
  fragment from scratch (`_fresh_dir`, `build_contest_statements.py:197`), so a
  contest that used to abort on language 2 now does the full N×M work. No
  correctness impact.

## Testing

- Contest, two languages, problem B has no `en` statement: `pt` PDF exists, no
  `en` PDF, exit 1, summary names `en` and problem B.
- Same, with `--partial`: both PDFs exist, `en` omits problem B, issue report
  lists the drop, exit 0.
- pdflatex failure in `en`: `pt` still builds, exit 1.
- Jinja undefined variable in a problem fragment: fatal to that statement (no
  partial PDF), not a silent skip — the current-behaviour regression test.
- Missing `contestProblemTemplate`: one clear error, not one confusing message
  per problem.
- Sample-build failure in one problem: all joining statements fail without
  `--partial`; dropped with it.
- Packager path (`execute_build_on_statements` default `keep_going=False`) still
  aborts on the first statement failure.
- Problem-level `rbx st b` with a broken `en`: `pt` still builds.
