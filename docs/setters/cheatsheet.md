# Cheatsheet

## CLI

Below you can find a list of common {{rbx}} commands. You can read more about each of them in the [CLI reference](reference/cli.md).


Where a command has a page of its own, the :material-open-in-new: next to it takes you there.

| Task | Command |
| ---- | ------- |
| Show help message | `rbx --help` |
| Show the installed version | `rbx --version` |
| Open {{rbx}} configuration for editing | `rbx config edit` |
| Create a new package in folder `package` [:material-open-in-new:](/setters/first-steps) | `rbx create` |
| Compile a file given its path | `rbx compile my/file.cpp` |
| Compile every asset of the package | `rbx compile -a` |
| Open the problem configuration in a text editor [:material-open-in-new:](/setters/reference/package) | `rbx edit` |
| Generate all testcases [:material-open-in-new:](/setters/testset#building-the-testset) | `rbx build` |
| Generate all testcases and their visualizations [:material-open-in-new:](/setters/testset/visualizers) | `rbx build --visualize` |
| Print a summary of the problem | `rbx summary` |
| Use dynamic timing to estimate time limits [:material-open-in-new:](/setters/profiling) | `rbx time` |
| Estimate time limits skipping the language picker [:material-open-in-new:](/setters/profiling#language-groups) | `rbx time -a` |
| Estimate limits and write them into a profile [:material-open-in-new:](/setters/profiling#limits-profiles) | `rbx time -p icpc -i` |
| Run all solutions and check their tags [:material-open-in-new:](/setters/running) | `rbx run` |
| Run all solutions with sanitizer | `rbx run -s` |
| Run all solutions with dynamic timing | `rbx run -t` |
| Run all solutions except the slow ones [:material-open-in-new:](/setters/verification#verification-level) | `rbx run -v2` |
| Run all solutions without checking [:material-open-in-new:](/setters/grading/checkers) | `rbx run --no-check` |
| Run a single solution [:material-open-in-new:](/setters/running#running-solutions-on-the-whole-testset) | `rbx run sols/my-solution.cpp` |
| Run only the main solution | `rbx run @main` |
| Choose solutions and run | `rbx run -c` |
| Run only the solutions expected to be too slow | `rbx run -o tle` |
| Run only the solutions carrying a [tag](#tag-a-solution) | `rbx run --tag brute-force` |
| Stop a solution at its first non-accepted verdict [:material-open-in-new:](/setters/running#failing-fast) | `rbx run --ff` |
| Run against a timing profile [:material-open-in-new:](/setters/profiling#using-profiles-when-running-solutions) | `rbx run -p icpc` |
| Copy the run report to the clipboard [:material-open-in-new:](/setters/running#sharing-a-report) | `rbx run --share png` |
| Run a submission downloaded from {{boca}} | `rbx run @boca/123` |
| Run all solutions interactively [:material-open-in-new:](/setters/running#running-tests-with-custom-inputs) | `rbx irun` |
| Choose solutions and run interactively | `rbx irun -c` |
| Run solutions in a single testcase | `rbx irun -t samples/0` |
| Run solutions in a generator testcase [:material-open-in-new:](/setters/testset/generators#generator-call) | `rbx irun -g gen 5 10` |
| Run interactively and print the outputs | `rbx irun -p` |
| Print the outputs with stderr interleaved | `rbx irun -p -e` |
| Interactively visualize outputs of a recent run [:material-open-in-new:](/setters/testset/visualizers) | `rbx ui` |
| Run the validator interactively [:material-open-in-new:](/setters/verification/validators) | `rbx validate` |
| Run the validator over an existing test | `rbx validate -p tests/manual/000.in` |
| Run a stress test with name `break` [:material-open-in-new:](/setters/stress-testing) | `rbx stress break` |
| Run a stress test for a generator [:material-open-in-new:](/setters/stress-testing#running-a-stress-test) | `rbx stress gen -g "[1..10]" -f "[sols/main.cpp ~ INCORRECT]"` |
| Run unit tests for validator and checker [:material-open-in-new:](/setters/verification/unit-tests) | `rbx unit` |
| Download all libraries declared by the preset [:material-open-in-new:](/setters/presets#libraries) | `rbx download lib` |
| Download {{testlib}} to the current folder [:material-open-in-new:](/setters/testset/generators) | `rbx download testlib` |
| Download {{jngen}} to the current folder | `rbx download jngen` |
| Download {{tgen}} to the current folder | `rbx download tgen` |
| Download a built-in {{testlib}} checker [:material-open-in-new:](/setters/grading/checkers) | `rbx download checker wcmp.cpp` |
| Download a {{boca}} submission into the package | `rbx download remote @boca/123` |
| Generate the `rbx.h` header in the package [:material-open-in-new:](/generators-and-rbx-h) | `rbx header` |
| Build all statements [:material-open-in-new:](/setters/statements) | `rbx statements build` |
| Build a specific variant [:material-open-in-new:](/setters/statements#keeping-two-recipes-for-one-language) | `rbx statements build <variant>` |
| Build statements for English [:material-open-in-new:](/setters/statements#building-only-some-languages) | `rbx statements build --languages en` |
| Build statements against a timing profile [:material-open-in-new:](/setters/statements#rendering-against-a-timing-profile) | `rbx statements build -p icpc` |
| Build statements without samples | `rbx statements build --no-samples` |
| Build all tutorials (editorials) [:material-open-in-new:](/setters/statements/tutorials) | `rbx tutorials build` |
| Package problem for {{polygon}} [:material-open-in-new:](/setters/packaging/polygon) | `rbx package polygon` |
| Package problem and [upload](/setters/packaging/polygon#using-the-polygon-api) it to {{polygon}} | `rbx package polygon -u` |
| Package problem for {{boca}} [:material-open-in-new:](/setters/packaging/boca) | `rbx package boca` |
| Package problem for {{boca}} but only validate [:material-open-in-new:](/setters/verification#verification-level) | `rbx package boca -v1` |
| Package problem for MOJ | `rbx package moj` |
| List all languages available in the environment | `rbx languages` |
| Format all YAML configuration files in the package | `rbx fix` |
| Clear cache | `rbx clear` |
| Clear the global cache as well | `rbx clear -g` |

### Contest CLI

| Task                                            | Command                               |
| ----------------------------------------------- | ------------------------------------- |
| Show help message                               | `rbx contest --help`                  |
| Create a new contest                            | `rbx contest create`                  |
| Add a new problem to the contest with letter A  | `rbx contest add`                     |
| Remove a problem from the contest               | `rbx contest remove A`                |
| Remove a problem at a certain path              | `rbx contest remove path/to/problem`  |
| Open the contest configuration in a text editor | `rbx contest edit`                    |
| Build all statements                            | `rbx contest statements build`        |
| Build a specific statement                      | `rbx contest statements build <name>` |
| Build statements for English                    | `rbx contest statements build --languages en` |
| Build statements against a timing profile       | `rbx contest statements build -p icpc` |
| Build all tutorials (editorials)                | `rbx contest tutorials build`         |
| Package contest for {{polygon}}                 | `rbx contest package polygon`         |
| Package contest for {{boca}}                    | `rbx contest package boca`            |
| Build each problem in the contest               | `rbx contest each build`              |
| Build each problem, not stopping at failures    | `rbx contest each -k build`           |
| Package each problem in the contest             | `rbx contest each package boca`       |
| Build problem A in the contest                  | `rbx contest on A build`              |
| Build problems A to C in the contest            | `rbx contest on A-C build`            |
| Chain commands for a problem                    | `rbx contest on A build :: run`       |
| Print a summary of the contest                  | `rbx contest summary`                 |
| List all contests in the current directory      | `rbx contest list`                    |
| Scaffold a new contest variant                  | `rbx contest add_variant div2`        |
| Run a command against a contest variant         | `rbx -C div2 contest statements build` |

### Testcase CLI

| Task                                 | Command                            |
| ------------------------------------ | ---------------------------------- |
| Open a testcase in your editor       | `rbx testcases view samples/0`     |
| Open only the input of a testcase    | `rbx testcases view samples/0 -i`  |
| Show how a testcase was generated    | `rbx testcases info samples/0`     |
| Show information about a whole group | `rbx testcases info main`          |
| Pick generated tests and freeze them | `rbx testcases promote`            |
| Freeze a specific generated test     | `rbx testcases promote main/3`     |

!!! tip
    `rbx testcases` is also spelled `rbx tc`.

### Configuration CLI

| Task                                            | Command                          |
| ----------------------------------------------- | -------------------------------- |
| Show the path to the setter configuration       | `rbx config path`                |
| Print the setter configuration                  | `rbx config list`                |
| List details about the active preset            | `rbx presets ls`                 |
| Pull the latest version of the installed preset | `rbx presets update`             |
| Re-sync the package with the preset assets      | `rbx presets sync`               |
| Create a new preset                             | `rbx presets create`             |
| Install the editor extension                    | `rbx vscode install`             |

## `problem.rbx.yml`

### Change problem constraints

```yaml
timeLimit: 1000  # In milliseconds
memoryLimit: 256  # In megabytes
modifiers:
  java:
    time: 5000  # Override time for Java
```

### Add testlib assets

#### Set a built-in {{testlib}} checker

```bash
rbx download checker yesno.cpp
```

```yaml
checker:
  path: "yesno.cpp"
```

!!! tip
    Find [here](https://github.com/MikeMirzayanov/testlib/tree/master/checkers) a full list of existing built-in {{testlib}} checkers.

#### Set a custom checker

```yaml
checker:
  path: "my-checker.cpp"
```

See [here](https://codeforces.com/blog/entry/18431) how to write a custom {{testlib}} checker.

#### Add a generator

Add a new generator entry to the `generators` field.

```yaml
generators:
  # ...other generators
  - name: "my-gen"
    path: "my-gen.cpp"
```

See [here](https://codeforces.com/blog/entry/18291) how to write a {{testlib}}-based generator.

!!! tip
    To actually generate tests with this new generator, you have to add testcase groups
    and call the generator.

#### Set a validator

```yaml
validator:
  path: 'my-validator.cpp`
```

See [here](https://codeforces.com/blog/entry/18426) how to write a {{testlib}}-based validator.

#### Set an interactor

```yaml
interactor:
  path: 'my-interactor.cpp'
```

See [here](https://codeforces.com/blog/entry/18455) how to write a {{testlib}}-based interactor.

### Add a new solution

Implement your solution (for instance, a wrong solution in `sols/my-wa-solution.cpp`) and add it to the `solutions` field.

```yaml
solutions:
  - path: 'sols/my-wa-solution.cpp'
    outcome: WRONG_ANSWER
```

You can see the list of possible expected outcomes [here][rbx.box.schema.ExpectedOutcome].

#### Tag a solution

Tags are free-form labels you can later filter runs by, with `rbx run --tag <tag>`.

```yaml
solutions:
  - path: 'sols/brute.cpp'
    outcome: ACCEPTED
    tags: ['brute-force']
```

### Add testcases

#### Add a testcase group with manually defined tests

```yaml
testcases:
  # ...other testcase groups
  - name: "manual-tests"
    testcaseGlob: "tests/manual/*.in" # (1)!
```

  1. Import all tests in the `tests/manual/` folder in lexicographic order.

       The test input files must end in `.in`.

#### Add a testcase group with a list of generated tests

```yaml
testcases:
  # ...other testcase groups
  - name: "single-generated"
    generators:
      - name: "gen"
        args: "1000 123" # (1)!
      - name: "gen"
        args: "1000 456" # (2)!
```

  1. A generated test obtained from the output of the command `gen 1000 123`.
  2. A generated test obtained from the output of the command `gen 1000 456`.
  
#### Add a testcase group with a list of generated tests from a generator script

=== "problem.rbx.yml"
    ```yaml
    testcases:
      # ...other testcase groups
       - name: "generated-from-text-script"
         generatorScript:
            path: "script.txt"
    ```

=== "script.txt"
    ```bash
    gen 1000 123
    gen 1000 456
    gen 1000 789
    # other tests...
    ```

#### Add a testcase group with a list of generated tests from a dynamic generator script

=== "problem.rbx.yml"
    ```yaml
    testcases:
      # ...other testcase groups
       - name: "generated-from-program-script"
         generatorScript:
            path: "script.py"
    ```

=== "script.py"
    ```python
    for i in range(50):
      print(f'gen 1000 {i}') # (1)!
    ```

    1.   Generates 50 random tests.

#### Add testgroup-specific validator

```yaml
validator:
  path: "my-validator.cpp"
testcases:
  - name: "small-group"
    # Define tests...
    validator:
      path: "my-small-validator.cpp" # (1)!
  - name: "large-group"
    # Define tests...
```

1. Add a specific validator to verify constraints of a smaller sub-task of the problem.

#### Vary constraints per testgroup

Prefer this over a testgroup-specific validator (and over branching on the group name
inside the validator) whenever the subtasks differ only in their constraints.

```yaml
vars:
  N:
    min: 1
    max: 1000
testcases:
  - name: "small"
    # Define tests...
    vars:
      N:
        max: 50 # (1)!
  - name: "large"
    # Define tests... # (2)!
```

1. Overrides `N.max` for this group only. The merge is leaf-by-leaf, so `N.min` stays
   at the package-level `1`. The validator is untouched: `getVar<int>("N.max")` returns
   `50` here and `1000` elsewhere.

2. No override, so the package-level values apply.

### Add variables

The variables below can be reused across validators and statements.

```yaml
vars:
  N:
    min: 1
    max: 1000
  V:
    max: 100000
  MOD: py`10**9+7` # Backticks force the var to be evaluated as a Python expression.
```

#### Use variables

=== "In testlib components"
    ```cpp
    #include "rbx.h"

    int32_t main() {
      registerValidation(argc, argv);

      int MIN_N = getVar<int>("N.min"); // Read from package vars.
      int MAX_N = getVar<int>("N.max"); // Read from package vars.

      // Rest of the validator
    }
    ```

=== "In statements"
    ```tex
    The maximum value of N is \VAR{N.max | sci} % (1)!
    ```

    1.   If `N.max` has lots of trailing zeroes, `sci` converts it to scientific notation.

### Add statements

Problem statements are keyed by `(language, variant)` and have **no `name`**. See [writing statements](statements/writing.md).

#### Add a {{rbxTeX}} statement

```yaml
statements:
  # ...other statements
  - language: en
    file: "statements/statement.rbx.tex" # (1)!
    params: { show_limits: true }       # (2)!
    assets: ['statements/*.png']         # (3)!
```

1. Path to the {{rbxTeX}} source, relative to the package root. `type` defaults to `rbx-tex`, so it's omitted.

2. Free-form values passed to the template as `params.*`.

3. Extra globs shipped alongside the statement on export (e.g. to {{polygon}}); files next to `file` are staged automatically.

#### Reuse another statement with `extends`

```yaml
statements:
  - language: en
    file: "statements/statement.rbx.tex"
    params: { show_limits: true }
  - language: pt
    extends: en                    # (1)!
    params: { show_limits: false } # (2)!
```

1. Reuses `en`'s `file`, `type`, `assets`, and `params`.

2. `params` deep-merges, so `pt` overrides only `show_limits`.

#### Add a PDF statement

```yaml
statements:
  # ...other statements
  - language: fr
    file: "statements/statement.pdf"
    type: pdf
```

### Add a stress test

#### Add a stress to look for an error in a solution

```yaml
stresses:
  - name: "my-stress"
    generator:
      name: 'gen'
      args: '[1..<N.max>] @' # (1)!
    finder: "[sols/my-wa-solution.cpp] ~ INCORRECT" # (2)!
```

1. The `<N.max>` variable expands into the `vars.N.max` value that could be declared in
    `problem.rbx.yml`.

    The `[1..<N.max>]` picks a random number in this interval before generating every test in the stress run.

    The `@` appends a few extra random characters to the end of the generator call to re-seed the generator.

2. Expression that refers to solution `sols/my-wa-solution.cpp` and check whether it returns an incorrect outcome.

#### Add a stress to look for a test that causes TLE in a solution

```yaml
stresses:
  - name: "my-stress"
    generator:
      name: 'gen'
      args: '1000000 @' # (1)!
    finder: "[sols/my-potentially-slow-sol.cpp] ~ TLE"
```

1. The `@` at the end of the `args` string appends a random string to it. This is necessary here because `gen 100000` would return the same testcase over and over, since {{testlib}} rng is seeded from its command line argc and argv.

### Add unit tests

```yaml
unitTests:
  validator:
    - glob: "unit/validator/valid_*.in"  # (1)!
      outcome: VALID
    - glob: "unit/validator/invalid_*.in"
      outcome: INVALID
  checker:
    - glob: "unit/checker/ac*"  # (2)!
      outcome: ACCEPTED
    - glob: "unit/checker/wa*"
      outcome: WRONG_ANSWER
    # ...other checker unit tests
```

1. Matches `.in` files relative to the problem root directory that when validated should be considered valid.

2. Matches `.in`, `.out`, `.ans` files that when checked should be considered ACCEPTED.

## `contest.rbx.yml`

### Add a new problem

```yaml
problems:
  - short_name: "A"  # Letter of the problem
    path: "problem_folder"
    color: "ff0000"  # Optional
    aliases: ["apple", "prob-a"]  # Optional; use any of these or short_name in e.g. rbx on <name> run
```

## `env.rbx.yml`

The environment is installed globally, not carried inside the package, so it is shared by every
problem you work on. The sections below are ordered by how often you will touch them.

| Task                                       | Command                                 |
| ------------------------------------------ | --------------------------------------- |
| Show which environment is in use           | `rbx environment`                       |
| Install an environment from a file         | `rbx environment my-env -i env.rbx.yml` |
| Switch to another installed environment    | `rbx environment my-env`                |
| List the languages the environment defines | `rbx languages`                         |

### Change how time limits are estimated

Drives `rbx time`. Pick **either** ratios or a formula — declaring both is an error.

=== "Ratios"
    ```yaml
    timing:
      multipliers:
        acToTimeLimit: 2.0   # (1)!
        timeLimitToTle: 1.5  # (2)!
        timeResolution: 100  # (3)!
    ```

    1. The limit is at least 2x the slowest accepted solution.
    2. Every too-slow solution must take at least 1.5x the limit.
    3. Round the limit up to a multiple of 100ms.

=== "Formula"
    ```yaml
    timing:
      formula: "step_up(max(fastest * 3, slowest * 1.5), 100)"  # (1)!
    ```

    1. Bounds the limit from below only. `fastest` and `slowest` are the timings of the
       accepted solutions.

#### Cap how long a solution may run while being timed

```yaml
timing:
  inferenceTimeout: 20000  # (1)!
```

1. In milliseconds; defaults to 10s. An accepted solution that hits it is an error.

#### Estimate a separate limit per group of languages

```yaml
timing:
  groups:
    - languages: ["py"]
      whenEmpty: {relativeTo: "cpp", multiplier: 3.0}  # (1)!
    - languages: ["java", "kt"]
      whenEmpty: {relativeTo: "cpp", multiplier: 2.0}
```

1. Used only when the group has no solutions: 3x the limit of the group holding `cpp`.
   Add `increment: 500` for a constant offset, in milliseconds.

   Languages in no group share a single leftover pool.

#### Give slow languages more wall time

```yaml
timing:
  wallTimeMultiplier: 2.0  # (1)!
  wallTimeIncrement: 1000
languages:
  - name: "java"
    timing:
      wallTimeIncrement: 3000  # (2)!
```

1. The wall limit is `wallTimeMultiplier * limit + wallTimeIncrement`, in milliseconds.
2. JVM startup headroom. The multiplier is inherited.

### Raise the sandbox limits

Bounds the programs that carry no limits of their own — compilers, checkers, validators,
generators. Raise them on a slow machine.

```yaml
defaultCompilation:
  sandbox:
    maxProcesses: 1000    # (1)!
    timeLimit: 50000      # 50 seconds
    wallTimeLimit: 50000
    memoryLimit: 1024     # 1gb
defaultExecution:
  sandbox:
    timeLimit: 50000
    wallTimeLimit: 50000
    memoryLimit: 1024
```

1. Some compilers fork a lot.

### Change how a language is compiled

```yaml
languages:
  - name: "cpp"
    readableName: "C++20"
    extension: "cpp"
    compilation:
      commands: ["g++ -std=c++20 -O2 -o {executable} {compilable}"]  # (1)!
    execution:
      command: "./{executable}"
```

1. `{compilable}` and `{executable}` are the file names inside the sandbox. Rename them per
   language with `fileMapping`.

### Add a new language

```yaml
languages:
  - name: "java"
    readableName: "Java"
    extension: "java"
    compilation:
      commands:
        - "javac -Xlint -encoding UTF-8 {compilable}"
        - "jar cvf {executable} @glob:*.class"  # (1)!
    execution:
      command: "java -Xss100m -Xmx{{memory}}m -cp {executable} Main"
    fileMapping:  # (2)!
      compilable: "Main.java"
      executable: "Main.jar"
```

1. `@glob:...` expands into every file matching the pattern.
2. Java needs the source named after its class, so the sandbox names are pinned here.

### Map a language onto a judge system

```yaml
languages:
  - name: "cpp"
    extensions:  # (1)!
      boca:
        languages: ["cc", "cpp"]
        template: "cc"
      moj:
        languages: ["cpp"]
        template: "cpp"
        flags: "-std=c++20 -O2 -lm -static"
      polygon:
        polygonLanguage: "cpp.gcc13-64-winlibs-g++20"
```

1. Tells packaging which language on the target judge this one corresponds to.

### Lint your assets at compilation time

```yaml
languages:
  - name: "cpp"
    linters:
      - testlib                  # (1)!
      - name: testlib            # (2)!
        applies_to: [generators]
```

1. Shorthand form: applies to every asset kind the linter supports.
2. Full form: `applies_to` restricts the linter to specific asset kinds.

Warnings are surfaced; errors abort the build. To silence a linter for a whole file:

```cpp
// testlib-linter: disable
```
