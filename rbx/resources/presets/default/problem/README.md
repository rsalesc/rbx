# rbx default problem

A minimal, ready-to-build A+B problem. Run `rbx build` to generate the testset
and `rbx run` to judge solutions against it. Everything below is optional — grow
the problem only as far as you need.

## Layout

- `documents/` — the statement (`statement.rbx.tex`), its assets, and `samples/`
  (sample inputs `*.in` plus `*.rbx.tex` explanations shown in the statement).
- `tests/` — `testplan.txt`, a static generator script (commented out for now),
  and the generators it calls (e.g. `gen.cpp`).
- `sols/` — solutions. `main.cpp` is the reference **accepted** solution.
- `validator.cpp` — checks every input is well-formed.
- `wcmp.cpp` — the checker that compares your output against the reference.

## Adding more

- **More solutions, by expected verdict** — `problem.rbx.yml` already declares
  patterns per outcome, so just drop files into `sols/`: `sols/ac-*` (accepted),
  `sols/wa-*`, `sols/tle-*`, `sols/mle-*`, `sols/re-*`, `sols/fail-*`.
  [Solutions & verdicts](https://rsalesc.github.io/rbx/setters/running/)
- **Generate tests** — uncomment lines in `tests/testplan.txt` to feed inputs
  and call generators.
  [Testset](https://rsalesc.github.io/rbx/setters/testset/)
- **Write generators** — add programs under `tests/` for randomized or
  programmatic test families.
  [Generators](https://rsalesc.github.io/rbx/setters/testset/generators/)
- **Stress testing** — pit solutions against each other to hunt for failing
  cases.
  [Stress testing](https://rsalesc.github.io/rbx/setters/stress-testing/)
- **Validators** — tighten and unit-test `validator.cpp` against the
  constraints.
  [Validators](https://rsalesc.github.io/rbx/setters/verification/validators/)
- **Checkers** — customize `wcmp.cpp` for problems with multiple valid answers.
  [Checkers](https://rsalesc.github.io/rbx/setters/grading/checkers/)
- **Unit tests** — assert validators and checkers behave on crafted inputs.
  [Unit tests](https://rsalesc.github.io/rbx/setters/verification/unit-tests/)
- **Variables** — share constants between the statement, validator, and
  generators.
  [Variables](https://rsalesc.github.io/rbx/setters/variables/)
- **Statements** — add languages or output formats (PDF, LaTeX, Markdown).
  [Statements](https://rsalesc.github.io/rbx/setters/statements/)
- **Everything else** — the full `problem.rbx.yml` reference.
  [Package schema](https://rsalesc.github.io/rbx/setters/reference/package/schema/)
