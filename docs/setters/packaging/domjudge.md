# Packaging: DOMjudge

{{rbx}} provides a command to build packages for DOMjudge.

```bash
rbx package domjudge
```

Or, if you want to build the package for all problems in your contest:

```bash
rbx each package domjudge
```

Only **batch** problems are supported for now.

The produced zip follows the ICPC problem package format with the DOMjudge-specific
extensions (`domjudge-problem.ini`, a root-level `problem.pdf` statement), and can be
imported through the jury interface (*Problems → Import problem*) or the API.

## Package contents

```
domjudge-problem.ini      # short-name, name, time limit, balloon color
problem.yaml              # memory/output limits, validation settings
problem.pdf               # the problem statement, built by rbx
data/sample/              # sample testcases (001.in/001.ans, ...)
data/secret/              # all other testcases
output_validators/        # custom checker, when needed (see below)
submissions/              # jury solutions, judged by DOMjudge on import
```

- The problem **short-name** is the problem's contest letter when the problem belongs
  to a contest, and the package name otherwise. The balloon **color** is picked up
  from the contest definition when available.
- The statement PDF is the problem's main statement (or the one selected with
  `--language`/`-l`).

## Time and memory limits

The DOMjudge packager uses the `domjudge` [limits profile](../profiling/index.md) when
one exists (create it with `rbx time -p domjudge`), and falls back to the package
limits otherwise. DOMjudge has a single time limit per problem, so per-language
modifiers are not emitted; the time limit is written with exact fractional seconds
(e.g. a `1234 ms` limit becomes `1.234`).

## Checkers

{{rbx}} **always ships your problem's checker** as a custom output validator
(`validation: custom`), so DOMjudge judges with exactly the same checker {{rbx}} uses
locally — it never falls back to DOMjudge's built-in default validators. The checker
is shipped under `output_validators/` together with a `testlib.h` patched to speak the
DOMjudge validator protocol (exit codes 42/43, team output on stdin, feedback
directory), since that protocol differs from testlib's. This applies to the builtin
checkers (`wcmp`, `ncmp`, …) as well as your own.

Checkers must be written in C++ (testlib).

## Jury solutions

Every solution is placed under `submissions/` so DOMjudge judges it on import. **No
solution is dropped** — each one carries a faithful expected verdict. DOMjudge derives
the expected verdict from the submission directory name when that name is a verdict
(the directories below), and from an `@EXPECTED_RESULTS@` annotation that {{rbx}} adds
to the source otherwise. Mismatches are surfaced on DOMjudge's jury *Judging verifier*
page; they never block the import.

Single-verdict outcomes go to the matching directory (no annotation needed):

| rbx outcome             | DOMjudge directory      |
| ----------------------- | ----------------------- |
| `accepted`              | `accepted`              |
| `wrong answer`          | `wrong_answer`          |
| `time limit exceeded`   | `time_limit_exceeded`   |
| `runtime error`         | `run_time_error`        |
| `output limit exceeded` | `output_limit`          |

Outcomes that allow more than one verdict go to `submissions/mixed/` with an
`@EXPECTED_RESULTS@` annotation listing every acceptable verdict:

| rbx outcome             | `@EXPECTED_RESULTS@` tokens                            |
| ----------------------- | ------------------------------------------------------ |
| `memory limit exceeded` | `RUN-ERROR, TIMELIMIT` (*)                             |
| `accepted or tle`       | `CORRECT, TIMELIMIT`                                   |
| `tle or rte`            | `TIMELIMIT, RUN-ERROR`                                 |
| `incorrect`             | every non-`CORRECT` verdict                            |
| `any`                   | every verdict                                          |

(*) DOMjudge has no memory-limit verdict — an over-memory run surfaces as a runtime
error (sometimes a time limit). This is the one outcome that can't be expressed
exactly.

!!! note
    Solutions in `submissions/mixed/` trigger a harmless "result does not match
    directory" message on import; this is expected and does not block anything.
