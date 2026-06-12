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

DOMjudge output validators follow the Kattis protocol, which is different from
testlib's. {{rbx}} handles the translation automatically:

- When your problem uses one of the builtin checkers with a default-validator
  equivalent (`wcmp`, `ncmp`, `yesno`, `dcmp`), no checker is shipped and DOMjudge's
  built-in default validator is used (with `float_tolerance 1e-6` for `dcmp`).
- Any other (custom, testlib) checker is shipped under `output_validators/`, along
  with a `testlib.h` patched to speak the DOMjudge validator protocol (exit codes
  42/43, team output on stdin, feedback directory). Custom checkers must be written
  in C++.

## Jury solutions

Solutions are placed under `submissions/` according to their expected outcome, and
DOMjudge judges them when the problem is imported:

| rbx outcome             | DOMjudge directory      |
| ----------------------- | ----------------------- |
| `accepted`              | `accepted`              |
| `wrong answer`          | `wrong_answer`          |
| `time limit exceeded`   | `time_limit_exceeded`   |
| `runtime error`         | `run_time_error`        |
| `memory limit exceeded` | `run_time_error` (*)    |

(*) DOMjudge reports memory limit violations as runtime errors by default.

Solutions with ambiguous expected outcomes (e.g. `accepted or tle`) are not included
in the package.
