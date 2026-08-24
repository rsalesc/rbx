# Cheatsheet

## CLI

Below you can find a list of common {{rbx}} commands. You can read more about each of them in the [CLI reference](reference/cli.md).


| Task                                               | Command                                                        |
| -------------------------------------------------- | -------------------------------------------------------------- |
| Show help message                                  | `rbx --help`                                                   |
| Open {{rbx}} configuration for editing             | `rbx config edit`                                              |
| Create a new package in folder `package`           | `rbx create`                                                   |
| Compile a file given its path                      | `rbx compile my/file.cpp`                                      |
| Open the problem configuration in a text editor    | `rbx edit`                                                     |
| Generate all testcases                             | `rbx build`                                                    |
| Use dynamic timing to estimate time limits         | `rbx time`                                                     |
| Run all solutions and check their tags             | `rbx run`                                                      |
| Run all solutions with sanitizer                   | `rbx run -s`                                                   |
| Run all solutions with dynamic timing              | `rbx run -t`                                                   |
| Run all solutions except the slow ones             | `rbx run -v2`                                                  |
| Run all solutions without checking                 | `rbx run --no-check`                                           |
| Run a single solution                              | `rbx run sols/my-solution.cpp`                                 |
| Choose solutions and run                           | `rbx run -c`                                                   |
| Run all solutions interactively                    | `rbx irun`                                                     |
| Choose solutions and run interactively             | `rbx irun -c`                                                  |
| Run solutions in a single testcase                 | `rbx irun -t samples/0`                                        |
| Run solutions in a generator testcase              | `rbx irun -g gen 5 10`                                         |
| Interactively visualize outputs of a recent run    | `rbx ui`                                                       |
| Run the validator interactively                    | `rbx validate`                                                 |
| Run a stress test with name `break`                | `rbx stress break`                                             |
| Run a stress test for a generator                  | `rbx stress gen -g "[1..10]" -f "[sols/main.cpp ~ INCORRECT]"` |
| Run unit tests for validator and checker           | `rbx unit`                                                     |
| Download {{testlib}} to the current folder         | `rbx download testlib`                                         |
| Download {{jngen}} to the current folder           | `rbx download jngen`                                           |
| Download {{tgen}} to the current folder            | `rbx download tgen`                                            |
| Download a built-in {{testlib}} checker            | `rbx download checker wcmp.cpp`                                |
| Build all statements                               | `rbx statements build`                                         |
| Build a specific variant                           | `rbx statements build <variant>`                               |
| Build statements for English                       | `rbx statements build --languages en`                          |
| Build statements against a timing profile          | `rbx statements build -p icpc`                                 |
| Build all tutorials (editorials)                   | `rbx tutorials build`                                          |
| Package problem for {{polygon}}                    | `rbx package polygon`                                          |
| Package problem for {{boca}}                       | `rbx package boca`                                             |
| Package problem for {{boca}} but only validate     | `rbx package boca -v1`                                         |
| List all languages available in the environment    | `rbx languages`                                                |
| Format all YAML configuration files in the package | `rbx fix`                                                      |
| Clear cache                                        | `rbx clear`                                                    |

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
| Build each problem in the contest               | `rbx contest each build`              |
| Package each problem in the contest             | `rbx contest each package boca`       |
| Build problem A in the contest                  | `rbx contest on A build`              |
| Build a problem by name, alias or folder        | `rbx contest on knapsack build`       |
| Build problems A to C in the contest            | `rbx contest on A..C build`           |
| Build every problem but C                       | `rbx contest on '*,!C' build`         |

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
# A problem can also be selected by its own `name` or by its folder basename.
# See the contest reference for the full selector syntax.
```
