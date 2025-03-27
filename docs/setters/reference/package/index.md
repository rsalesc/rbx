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

## Checker

**Field**: `checker`
**Schema**: [rbx.box.schema.CodeItem][]

Checkers are also a very important part of your problem package, and define how the output of a solution will be judged.

The checker is controlled through the top-level parameter `checker`, and is optional. In the case it is not specified, {{rbx}} falls back to {{testlib}}'s [wcmp.cpp](https://github.com/MikeMirzayanov/testlib/blob/master/checkers/wcmp.cpp), which is a token-based checker that compares the output of the solution with the expected answer.

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
        This is usually the recommended solution when building a custom checker.

3. A custom checker (not necessarily using {{testlib}}). It can even be in other language, in which case we suggest specifying the `language` property.

    ```yaml
    checker:
      path: "my-custom-checker.py"
      language: "python"
    ```

    !!! note
        Although this is not a {{testlib}}-based checker, we still expect checker programs to follow the same command line structure as {{testlib}}, which is
        receiving and reading three file paths from the command line.
        
        Thus, your checker program will be called as `<program> <input-file> <output-file> <expected-answer-file>`.

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

## Variables

**Field**: `vars`
**Schema**: `#!python Dict[str, Union[str, int, float, bool]]`

In the package definition you can define variables that can be referenced in statements, validators and stress tests.

This is useful to maintain consistency when changing constraints of your problem. A common mistake this field tries to solve is changing constraints in the statement, but not updating them in the validator.

```yaml
vars:
  MAX_N: 10000
  MAX_A: 100000
  MOD: py`10**9+7` # Backticks force the var to be evaluated as a Python expression.
```

!!! note
    Variable names should be valid Python identifiers.

!!! tip
    You can see how to include these variables in each of the possible assets in the
    sections below.

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

You can pass variables to validators by calling {{testlib}}'s `prepareOpts` function and by using its provided `opt` accessor.

```cpp
#include "testlib.h"

using namespace std;

int main(int argc, char *argv[]) {
    registerValidation(argc, argv);
    prepareOpts(argc, argv);

    int MAX_N = opt<int>("MAX_N"); // Read from package vars.

    inf.readInt(1, MAX_N, "N");
    inf.readEoln();
    inf.readEof();
}
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
- `generator`: a generator to be repeatedly called in this stress test.
  - `name`: the name of the generator
  - `args`: args *pattern* to be passed to generator.
    - You can pass a random integer by writing something like `[1..1000]`.
    - You can pass variables defined in the `vars` section with something like `<MAX_N>`.
    - You can pass a random choice by writing something like `(a|b|c)`.
    - You can pass a random hex string by passing `@`.
- `finder`: a finder expression that, when evaluated to true, consider the given generated test as a match

### Finder expressions

Finder expressions are domain-specific expressions evaluated by rbx that helps you finding tests that meet
certain conditions.

Below, we list a few finder expressions, with an explanation on what they do. They should give a rough understanding
of how this feature works.

```sh
# Find a test for which `sols/wa.cpp` returns any verdict considered incorrect.
[sols/wa.cpp] ~ INCORRECT

# Find a test that fails one incorrect solution and a TLE solution at the same time.
[sols/wa.cpp] ~ INCORRECT && [sols/tle.cpp] ~ TLE

# Find a test that fails one incorrect solution, but do not TLE other solution at the same time.
[sols/wa.cpp] ~ INCORRECT && [sols/tle.cpp] !~ TLE
[sols/wa.cpp] ~ INCORRECT && !([sols/tle.cpp] ~ TLE)

# Find a test that fails one or the other.
[sols/wa.cpp] ~ INCORRECT || [sols/wa2.cpp] ~ INCORRECT

# Find a test where solutions give different verdicts.
[sols/sol1.cpp] != [sols/sol2.cpp]

# By using the ON syntax, specifies a custom checker to be used (instead of the main one).
[sols/wa.cpp ON custom-checker.cpp] ~ INCORRECT

# Use no checker whatsoever. Useful when you don't have a checker yet.
[sols/tle.cpp ON :nil] ~ TLE

# Use a 2-way checker. This checker will only require the input and the
# output generated by the stressed program. In place of the output of the
# main solution, an empty file will be passed.
#
# Useful if you don't have a main solution yet.
[sols/wa.cpp ON 2:my_checker.cpp] ~ INCORRECT

# Special operators:
# Find a test that breaks the main solution (here, specified by a $).
[$] ~ INCORRECT

# Find a test that breaks the main solution, using the main checker in
# a 2-way fashion.
[$ ON 2:$] ~ INCORRECT
```

Finder expressions are really powerful, and can even be used to test your checkers, instead of solutions themselves.

```sh
# Find a test where the checker returns something different than WA,
# even though the given solution always WA.
[sols/always-wa.cpp ON custom-checker.cpp] != WA

# Compare two checkers to see if they're misbehaving.
[sols/sol.cpp ON custom-checker.cpp] != [sols/sol.cpp ON brute-force-checker.cpp]
```
