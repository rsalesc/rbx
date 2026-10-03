# Packaging: DOMjudge

{{rbx}} provides a command to build packages for DOMjudge.

```bash
rbx package domjudge
```

Or, if you want to build the package for all problems in your contest:

```bash
rbx each package domjudge
```

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
output_validators/        # checker (or interactor), with a patched testlib.h
submissions/              # jury solutions, judged by DOMjudge on import
```

- The problem **short-name** is the problem's contest letter when the problem belongs
  to a contest, and the package name otherwise. The balloon **color** is picked up
  from the contest definition when available.
- The statement PDF is the problem's main statement (or the one selected with
  `--language`/`-l`).

## Time and memory limits

The DOMjudge packager uses the `domjudge` [limits profile](../profiling/profiles.md) when
one exists (create it with `rbx time -p domjudge`), and falls back to the package
limits otherwise. DOMjudge has one time limit per problem, so per-language
modifiers are not emitted; the time limit is written with exact fractional seconds
(for example, a `1234 ms` limit becomes `1.234`).

## Checkers

For a batch problem, {{rbx}} **always ships your problem's checker** as a custom output validator
(`validation: custom`), so DOMjudge judges with exactly the same checker {{rbx}} uses
locally, and never with DOMjudge's built-in default validators. The checker
is shipped under `output_validators/` together with a `testlib.h` patched to speak the
DOMjudge validator protocol (exit codes 42/43, team output on stdin, feedback
directory), since that protocol differs from {{testlib}}'s. This applies to the builtin
checkers (`wcmp`, `ncmp`, …) as well as your own.

Checkers must be written in C++ ({{testlib}}).

## Interactive problems

Interactive problems are packaged with `validation: custom interactive`, and the interactor
takes the checker's place under `output_validators/`:

- A modern interactor judges the interaction on its own, so it becomes DOMjudge's output
  validator.
- A [legacy interactor](../grading/interactors.md#do-i-need-to-write-a-checker) paired with a
  checker (`legacy: true`) ships together with that checker,
  and a generated `run` script chains the two, so both still run.

Either way, the interactor (and the checker, when there is one) must be written in C++
({{testlib}}).

## Jury solutions

Every solution is placed under `submissions/` so DOMjudge judges it on import. **No
solution is dropped**, and each one is shipped with its expected verdict. DOMjudge derives
the expected verdict from the submission directory name when that name is a verdict
(the directories below), and from an `@EXPECTED_RESULTS@` annotation that {{rbx}} adds
to the source otherwise. Mismatches are surfaced on DOMjudge's jury *Judging verifier*
page; they never block the import.

Single-verdict outcomes go to the matching directory (no annotation needed):

| Expected outcome        | DOMjudge directory      |
| ----------------------- | ----------------------- |
| `accepted`              | `accepted`              |
| `wrong answer`          | `wrong_answer`          |
| `time limit exceeded`   | `time_limit_exceeded`   |
| `runtime error`         | `run_time_error`        |
| `output limit exceeded` | `output_limit`          |

Outcomes that allow more than one verdict go to `submissions/mixed/` with an
`@EXPECTED_RESULTS@` annotation listing every acceptable verdict:

| Expected outcome        | `@EXPECTED_RESULTS@` tokens                            |
| ----------------------- | ------------------------------------------------------ |
| `memory limit exceeded` | `RUN-ERROR, TIMELIMIT` (*)                             |
| `accepted or tle`       | `CORRECT, TIMELIMIT`                                   |
| `tle or rte`            | `TIMELIMIT, RUN-ERROR`                                 |
| `incorrect`             | every non-`CORRECT` verdict                            |
| `any`                   | every verdict                                          |

(*) DOMjudge has no memory-limit verdict: it reports an over-memory run as a runtime
error (sometimes a time limit). This is the one outcome that can't be expressed
exactly.

!!! note
    Solutions in `submissions/mixed/` trigger a harmless "result does not match
    directory" message on import; this is expected and does not block anything.

## Configuring the server

A package says nothing about which languages a DOMjudge instance accepts, or how it
compiles them: both are part of the server's own configuration. So a
package built against `-std=c++20` can still fail to compile on a judge whose C++
script passes no `-std` at all, and the stock script doesn't pass one.

`rbx tool domjudge configure` fixes this by pushing your environment to the
server:

```bash
export RBX_DOMJUDGE_SERVER=https://judge.example.com/
export RBX_DOMJUDGE_USERNAME=...
export RBX_DOMJUDGE_PASSWORD=...

rbx tool domjudge configure
```

It prints everything it is about to change before changing it.

!!! warning
    Every setting here is **instance-wide** and needs an admin account. DOMjudge has
    no per-contest equivalent for languages, compilation or limits, so this
    reconfigures the whole server — every contest on it, including other people's.

It pushes the following settings.

**Which languages accept submissions.** Each language in `env.rbx.yml` is matched
against the server's language list by file extension, and the result is enabled.
Languages the server has enabled that are missing from `env.rbx.yml` stay enabled, and
{{rbx}} only ever *adds* file extensions to a language, never removes one.

Matching by extension only sees languages that are currently enabled, because DOMjudge's
API doesn't list disabled ones. Name it explicitly to switch it back on:

```yaml
languages:
  - name: "py"
    extension: "py"
    extensions:
      domjudge:
        languages: ["python3"]
        timeFactor: 3.0
```

The id here is DOMjudge's *external* id, which is not always the one the admin
interface shows: `py3` is externally `python3`, `pas` is `pascal`, `rs` is `rust`.
DOMjudge silently ignores an id that doesn't match any language, so {{rbx}} re-reads the
language list afterwards and tells you which entries weren't applied.

`timeFactor` is the multiplier DOMjudge applies to every problem's time limit for that
language. It is only ever pushed when you set it here: nothing in `env.rbx.yml` means
the same thing, so there is nothing to derive it from.

**How they are compiled.** For a language whose compilation is one command that
produces the program {{rbx}} then executes — C and C++, in the default preset — the
command is translated into DOMjudge's compile wrapper and uploaded:

```sh
g++ -std=c++20 -O2 -o "$DEST" "$@"
```

Anything else keeps the script the server already has, and the summary says why:
Java compiles in two steps, Python compiles not at all, and Kotlin leaves a jar rather
than a program, so DOMjudge's own script has to go on producing the wrapper it runs.

Use `compileCommand` when the judge needs flags your machine does not, `-static` being
the usual one, or `compile: false` to enable a language and leave its script alone:

```yaml
    extensions:
      domjudge:
        compileCommand: "g++ -std=c++20 -O2 -static -o {executable} {compilable}"
```

**Server limits.** Only the ones you declare, so that running the command does not
quietly change a limit you never thought about:

```yaml
extensions:
  domjudge:
    memoryLimit: 2048      # MiB
    outputLimit: 8192      # KiB
    processLimit: 64
    sourceSizeLimit: 256   # KiB
```

These are the defaults for problems that don't set their own; a package built by
`rbx package domjudge` always ships its own time and memory limits.

!!! note "There is no stack limit to configure"
    DOMjudge's sandbox always sets the stack size to unlimited and enforces memory
    through cgroups instead, so a submission's stack is bounded only by the memory
    limit. That matches an `env.rbx.yml` with no `stackLimit` set; a *finite*
    `stackLimit` has no equivalent on DOMjudge and cannot be pushed.
