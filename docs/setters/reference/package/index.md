# Problem package

This documentation goes over how each field (or group of fields) in `problem.rbx.yml` works.

## Problem definition

**Schema**: [rbx.box.schema.Package][]

The three main required fields in a `problem.rbx.yml` package are:

- `name`: supports anything matching the regex `^[a-zA-Z0-9\-]+$`
- `timeLimit`: the time limit of your problem, in milliseconds.
- `memoryLimit`: the memory limit of your problem, in megabytes.

A barebones package would look something like:

```yaml
name: "test-problem"
timeLimit: 1000  # 1 second TL
memoryLimit: 256  # 256 MB ML
```

## Language Modifiers

You can add extra language-based limit modifiers to problems.

```yaml
name: "test-problem"
timeLimit: 1000  # 1 second TL
memoryLimit: 256  # 256 MB ML
modifiers:
  java:
    time: 2000  # 2 second TL for Java
    memory: 512  # 512 MB ML for Java
```

## Task Type

**Field**: `type`
**Schema**: [rbx.box.schema.TaskType][]

You can use this (optional) field to specify the type of your problem. If you're building an interactive problem, for instance, you should
set this to `COMMUNICATION`, otherwise the default `BATCH` will be used.

```yaml
name: "interactive-problem"
type: COMMUNICATION
timeLimit: 1000  # 1 second TL
memoryLimit: 256  # 256 MB ML
```

## Variables

**Field**: `vars`
**Schema**: `#!python Dict[str, Union[str, int, float, bool]]`

In the package definition you can define variables that can be referenced in statements, validators, checkers, interactors and stress tests.

This is useful to maintain consistency when changing constraints of your problem. A common mistake this field tries to solve is changing constraints in the statement, but not updating them in the other components.

```yaml
vars:
  MAX_N: 10000
  MAX_A: 100000
  MOD: py`10**9+7` # Backticks force the var to be evaluated as a Python expression.
```

{{rbx}} automatically generates an `rbx.h` header file in the root of your package that you can include in your code to read these variables.

```cpp
#include "rbx.h"

int main() {
  int MAX_N = getVar<int>("MAX_N");
  // Rest of your code...
}
```

If you're not using C++ for your components, consider doing so as the {{rbx}} experience is tightly integrated with {{testlib}}.

If not, you can still use the variables in validators, see the [Validators](#validators) section for more information.

!!! warning
    Refrain from using variables in generators. Although it is tempting to use `rbx.h` in there, it is not recommended to do so.

    Read more on the [Generators](#generators) section.

!!! note
    Variable names should be valid Python identifiers.

## Checker

**Field**: `checker`
**Schema**: [rbx.box.schema.CodeItem][]

Checkers are also a very important part of your problem package, and define how the output of a solution will be judged.

The checker is controlled through the top-level parameter `checker`, and is optional. In the case it is not specified, {{rbx}} falls back to {{testlib}}'s [wcmp.cpp](https://github.com/MikeMirzayanov/testlib/blob/master/checkers/wcmp.cpp), which is a token-based checker that compares the output of the solution with the expected answer. In case of interactive problems, a checker is not required.

{{rbx}} is **tightly integrated** with {{testlib}}, and thus you can either specify:

1. The name of any checker in defined in [testlib's checkers folder](https://github.com/MikeMirzayanov/testlib/tree/master/checkers). The checker will be automatically downloaded when running solutions and building the package.

    ```yaml
    checker:
      path: "yesno.cpp"
    ```

    !!! tip
        If you want to explicitly download a checker from {{testlib}}, you can run `rbx download checker [name-of-the-checker]`.

2. A custom {{testlib}}-based checker of your own, placed in the folder (or any sub-folder) of your package.

    ```yaml
    checker:
      path: "my-testlib-based-checker.cpp"
    ```

    !!! tip
        {{rbx}} automatically places `testlib.h` together with your code when compiling it, but you can explicitly download it with `rbx download testlib` if you want.

    !!! success "Recommended"
        This is usually the recommended solution when building a custom checker, as {{rbx}} provides a clear integration with {{testlib}}
        and you can use include `rbx.h` in your checker to read variables.

3. A custom checker (not necessarily using {{testlib}}). It can even be in other language, in which case we suggest specifying the `language` property.

    ```yaml
    checker:
      path: "my-custom-checker.py"
      language: "python"
    ```

    !!! warning
        Currently, it is not possible to use variables in custom checkers not written in C++.

    !!! note
        Although this is not a {{testlib}}-based checker, we still expect checker programs to follow the same command line structure as {{testlib}}, which is
        receiving and reading three file paths from the command line.
        
        Thus, your checker program will be called as `<program> <input-file> <output-file> <expected-answer-file>`.

## Interactor

**Field**: `interactor`
**Schema**: [rbx.box.schema.Interactor][]

You can specify an interactor for your problem, or leave this field empty for non-interactive problems.

```yaml
interactor:
  path: "my-interactor.cpp"
```

According to the [ICPC package specification](https://icpc.io/problem-package-format/spec/legacy-icpc.html), used by the ICPC World Finals, interactors **cannot** be specified together with a checker, and an error will be thrown if both are present.

{{rbx}} enforces this rule, but supports interactive problems with a checker if you set the `legacy` flag in the interactor definition.

```yaml
interactor:
  path: "my-interactor.cpp"
  legacy: true
```

!!! danger
    {{rbx}} currently only supports {{testlib}}-based interactors. If you do not use a {{testlib}}-based interactor,
    {{rbx}} will not complain but might behave unexpectedly.

!!! warning
    Notice that a few judges do not support interactors with a checker, and an error will be thrown if you try to build a package
    for an unsupported judge with both components specified.

## Generators

**Field**: `generators`
**Schema**: `List[`[`Generator`][rbx.box.schema.Generator]`]`

You can also specify a set of testcase generators that can be re-used in different places in your package (testgroup generation, stress tests to name a couple).

Again, we encourage the use of {{testlib}}-based generators, but give you the flexibility to develop however you like.

After implementing a generator, you can define it in `problem.rbx.yml` similar to how you define a checker, but you also have to name it to be able to reference it down the line.

```yaml
generators:
  - name: "gen"
    path: "my-gen.cpp"
```

Notice also how the `generators` field is a list, and as such you can define multiple generators.

!!! danger
    Refrain from using [Variables](#variables) in generators. Although it is tempting to depend on them, it is not a good practice.
    
    This will make your generator sensible to the changes you make to the `vars` field, meaning if you found a testcase that breaks
    a specific solution, but it depends on a `vars` entry and you change it, you might end up with a totally different test. Instead,
    you should be able to describe all your generator parameters through static variables.



## Solutions

**Field**: `solutions`
**Schema**: `List[`[`Solution`][rbx.box.schema.Solution]`]`

You can specify multiple solutions to your problem, including incorrect ones to check that your testset is strong enough.

You can define them similarly to generators and checkers, but you also have to provide an expected outcome for them.

```yaml
solutions:
  - path: "sols/main.cpp"
    outcome: accepted
  - path: "sols/slow.cpp"
    outcome: tle
  - path: "sols/wa.cpp"
    outcome: wa
```

Also, you **have to define** an accepted solution. The first accepted solution in this list will be considered the main solution to generate answers for the testcases.

For a full list of expected outcomes, see [here][rbx.box.schema.ExpectedOutcome].

## Testcase groups

**Field**: `testcases`
**Schema**: `List[`[`TestcaseGroup`][rbx.box.schema.TestcaseGroup]`]`

You can define multiple testgroups for you problem. For each testgroup, you can define tests for it in five (5) different ways:

1. Specifying a sequence of manually defined testcases present in your package's directory with the `testcases` field.

    ```yaml
    testcases:
      - name: "group-1"
        testcases:
          - inputPath: "manual-tests/1.in"
            outputPath: "manual-tests/1.ans"
          - inputPath: "manual-tests/1.in"
    ```

    !!! note
        Notice how the `outputPath` is optional. If it is not defined, the main solution
        will be used to generate an output. This is the recommended approach.
      
2. Specifying a glob of input paths with the `testcaseGlob` field.

    ```yaml
    testcases:
      - name: "group-1"
        testcaseGlob: "tests/*.in" # (1)!
    ```

    1.  Pick all files ending in `.in` inside the `tests/` folder as test inputs for
        the testgroup. The files are taken in lexicographically increasing order.

3. Specifying a list of generator calls with the `generators` field.

    ```yaml
    testcases:
      - name: "generated"
        generators:
          - name: "gen1"
            args: "1000 30"
          - name: "gen1"
            args: "1000 42"
    ```

4. Specifying a **static** generator script with the `generatorScript` field:

    === "problem.rbx.yml"
        ```yaml
        testcases:
          - name: "generated"
            generatorScript:
              path: "script.txt"
        ```

    === "script.txt"
        ```bash
        gen 1000 30
        gen 1000 42
        # ...other tests
        ```

    !!! note
        The `.txt` extension is necessary for {{rbx}} to identify this is a static
        script.

    !!! success "Recommended"
        This is usually the recommended approach to generate a few pre-defined testcases.
        Prefer this over the `generators` call to keep `problem.rbx.yml` cleaner.

5. Specifying a **dynamic** generator script with the `generatorScript` field:

    === "problem.rbx.yml"
        ```yaml
        testcases:
          - name: "generated"
            generatorScript:
              path: "script.py"
        ```

    === "script.py"
        ```bash
        # Generates 10 different cases with different parameters.
        for i in range(10):
          print(f'gen 1000 {i}')
        ```

    !!! success "Recommended"
        This is usually the recommended approach to generate multiple random testcases.

!!! warning
    If the platform you package the problem for does not support testgroups, tests will be **flattened into a single group**, and the tests will be executed in the order the groups were defined.

### Samples

You can also specify samples to be included in your statement by defining a testgroup named `samples`. This testgroup **has to be the first one defined**, otherwise an error will be raised.

## Validators

**Field**: `validator`, `testcases.validator`
**Schema**: [rbx.box.schema.CodeItem][]

You can specify {{testlib}} validators that check whether both manual and generated testcases are in the correct format.

You can specify validators in two places:

1. In the package definition, through the `validator` field.

    ```yaml
    validator:
      path: "validator.cpp"
    ```

2. In the testgroup definition, through the `validator` field, in which case this validator will be executed only for this group, and the package one will be ignored.

    ```yaml
    validator:
      path: "validator.cpp"
    testcases:
      - name: "group-with-usual-constraints"
        # ...other testgroup definitions
      - name: "group-with-different-constraints"
        # ...other testgroup definitions
        validator:
          path: "validator-alternative.cpp"
    ```

You can pass variables to validators in two different ways.

1. (C++ only) Include the `rbx.h` header and using the `getVar` accessor.

    ```cpp
    #include "testlib.h"
    #include "rbx.h"

    using namespace std;

    int main(int argc, char *argv[]) {
        registerValidation(argc, argv);

        int MAX_N = getVar<int>("MAX_N"); // Read from package vars.

        inf.readInt(1, MAX_N, "N");
        inf.readEoln();
        inf.readEof();
    }
    ```

    This header is automatically generated at your problem's root directory by {{rbx}}.

    !!! success "Recommended"
        This is the recommended approach of passing variables to validators.

1. Read the variables from the command line.

    {{rbx}} passes all the variables defined in the `vars` section to the validator through `--{name}={value}` parameters. You are
    responsible for writing code to parse them.

    ```python
    import sys

    variables = {}

    for arg in sys.argv[1:]:
      if arg.startswith('--') and '=' in arg:
        name, value = arg[2:].split('=', 1)
        variables[name] = value

    # Use variables...
    ```

### Extra validators

You can also specify extra validators to be used in your testcases, both at the problem-level and testgroup-level.

```yaml
validator:
  path: "validator.cpp"
testcases:
  - name: "group-1"
    # ...other testgroup definitions
  - name: "group-2-without-solution"
    # a group whose testcases don't have a solution
    extraValidators:
      - path: "validator-no-solution.cpp"
```

## Stress tests

**Field**: `stresses`
**Schema**: `List[`[`Stress`][rbx.box.schema.Stress]`]`

You can pre-define stress tests with a few applications in mind, such as:

- Finding testcases that break incorrect solutions;
- Ensuring solutions you expect to be correct cannot be broken.

Let's break down each field in the stress test below:

```yaml
stresses:
  - name: "stress1"
    generator:
      name: "gen"
      args: "--MAX_N=[1..1000] @"
    finder: "[sols/wa.cpp] ~ INCORRECT"
```

- `name`: a name for the stress test. Useful when calling this test through `rbx stress [name]`.
- `generator`: a [generator expression](/setters/stress-testing#generator-expression) to be repeatedly evaluated in this stress test.
  - `name`: the name of the generator
  - `args`: args *pattern* to be passed to generator.
    - You can pass a random integer by writing something like `[1..1000]`.
    - You can pass variables defined in the `vars` section with something like `<MAX_N>`.
    - You can pass a random choice by writing something like `(a|b|c)`.
    - You can pass a random hex string by passing `@`.
- `finder`: a [finder expression](/setters/stress-testing#finder-expressions) that, when evaluated to true, consider the given generated test as a match

## Unit tests

**Field**: `unitTests`
**Schema**: [`UnitTests`][rbx.box.schema.UnitTests]


You can specify unit tests for your validator and your checker through the `unitTests` field.

```yaml
unitTests:
  validator:
    - glob: "unit/validator/valid_*.in"  # (1)!
      outcome: VALID
    - glob: "unit/validator/invalid_*.in"  # (2)!
      outcome: INVALID
  checker: 
    - glob: "unit/checker/ac*"  # (3)!
      outcome: ACCEPTED
    - glob: "unit/checker/wa*"
      outcome: WRONG_ANSWER
```

1. Specify a glob to match manually crafted input files that when validated should be considered valid.

2. Specify a glob to match manually crafted input files that when validated should be considered INVALID.

3. Specify a glob to match files named `unit/checker/ac*(.in|.out|.ans)` that when checked should be considered ACCEPTED.

Validator globs are really simple: they should match `.in` files relative to the problem root directory. Those files will be passed
to the validator program and validated.

Checker globs are a bit more complex, since they accept three different parameters:

- A `.in` file, the input for the testcase;
- A `.out` file, the output of the participant's program;
- A `.ans` file, the output of the main solution.

Thus, to test a checker, you should provide a subset of these three (3) files. The checker unit test definition expects a glob that matches the names of these three files. Thus, the glob `unit/checker/ac*` will match, for instance, `unit/checker/ac.in`, `unit/checker/ac.out` and `unit/checker/ac.ans`.

Not all three files must exist, only those required by the checker.
