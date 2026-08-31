# Variables

Variables are a way to define the constraints of your problem in a
single place and reference them everywhere else.

The motivation for having variables are simple: imagine you've decided
to change the constraints of your problem. Without variables, you'd have
to change this constraint in the validator, (potentially) in the checker
and in the statements. It's super easy to forget about these changes, increasing the
likelihood of introducing a disastrous bug in your problem.

## Defining variables

Variables are defined in the `vars` section of your `problem.rbx.yml` file.

```yaml title="problem.rbx.yml"
# ...
vars:
  N:
    min: 1
    max: 100000
  M:
    min: 1
    max: 200000
```

They're defined as key-value pairs. The keys should be valid Python identifiers
and the values should be a `bool`, a `string`, an `int` or a `float`, all conforming
to the YAML specification.

Besides that, it's possible to use Python expressions that evaluate to one of these
types, using the ``py`...` `` syntax. 

```yaml title="problem.rbx.yml"
# ...
vars:
  N:
    max: py`10**5`
  M:
    max: py`2*10**5`
```

## Using variables

Variables can be used within **validators**, **checkers** and **statements**.

In this section, we go through the different ways to use variables in each of these.

### Validators and checkers (C++)

{{rbx}} automatically generates a `rbx.h` header file that contains the variables
that were defined in the `problem.rbx.yml` file, right at the root of your package.

This header exposes a function `getVar<T>(name)` that can be used to get the value
of a variable as a `T`-typed object. `T` can be `bool`, `std::string`, any
floating-point type (`float`, `double`) or any integer type.

Nested variables can be addressed either by their full dotted name, or by passing
one segment per argument -- the two calls below are equivalent:

```cpp
int n = getVar<int>("N.max");
int n = getVar<int>("N", "max");
```

This header can be directly included in your validator/checker files.

=== "validator.cpp"

    ```cpp hl_lines="2 7-8" linenums="1"
    #include "testlib.h"
    #include "rbx.h"

    int main(int argc, char* argv[]) {
        registerValidation(argc, argv);

        int n = getVar<int>("N.max");
        int m = getVar<int>("M.max");
      
        // Single line with two numbers.
        inf.readInt(1, n, "n");
        inf.readSpace();
        inf.readInt(1, m, "m");
        inf.readEoln();
        inf.readEof();
    }
    ```

=== "checker.cpp"

    ```cpp hl_lines="2 7-8" linenums="1"
    #include "testlib.h"
    #include "rbx.h"

    int main(int argc, char* argv[]) {
        registerTestlibCmd(argc, argv);

        int n = getVar<int>("N.max");
        int m = getVar<int>("M.max");
        
        // ...
    }
    ```

### Validators (other languages)

Validators also receive the variables as command-line arguments. This means that
for the `problem.rbx.yml` above, your validator would be called roughly as follows:

```bash
./validator.exe --N.max=100000 --M.max=200000
```

You can freely parse those arguments in your language of choice.

!!! danger "Checkers"

    Checkers do not receive the variables as command-line arguments, as
    doing so is not compatible with any judging platforms.

    If you want to use variables in your checkers, they must be in C++ and
    you have to follow the approach outlined in the [previous section](#validators-and-checkers-c).

### Statements

{{rbxtex}} statements can also use variables. This is done by using the `\VAR` command with
the `vars.` prefix.

```latex title="statement.rbx.tex"
% ...
You're given a graph with \VAR{N.max} vertices and \VAR{M.max} edges.
% ...
```

Variables can also be used within any {{rbxtex}} statements, including loops and
conditionals.

```latex title="statement.rbx.tex"
% ...
%- if vars.N.max < 1000:
This problem is easy.
%- else:
This problem is hard.
%- endif
% ...
```

Also, {{rbx}} exposes a few transform builtins that can be used to change
how a variable is rendered. One of them is the `sci` builtin, which formats
a number with many trailing zeroes in scientific notation.

```latex title="statement.rbx.tex"
% ...
You're given a graph with \VAR{N.max | sci} vertices
and \VAR{M.max | sci} edges.
% ...
```

The `sci` builtin will make `N.max` and `M.max` be rendered as something like
`10^5` and `2 x 10^5` respectively.

### Stress tests

Variables can also be used in [generator expressions](/setters/stress-testing/#generator-expression) in stress tests with the `<variable>` notation.

```
rbx stress -g "gen [1..<N.max>]" -f "[sols/wa.cpp] ~ INCORRECT"
```

## Seeing the expanded values

The value you write is not always the value {{rbx}} ends up using: a
``py`...` `` expression has to be evaluated, and one variable can be defined in
terms of another. `rbx vars` prints what is left after all of that -- the very
same values your validators, checkers and statements see. On the
``py`...` `` package from [Defining variables](#defining-variables), it prints:

<!--termynal-->

```bash
$ rbx vars
M.max = 200000
N.max = 100000
```

Pass `--json` and you get the same map as a JSON object, keyed by dotted name.
Every value crosses as a **string**, never as a JSON number, so that a bound
like ``py`10**18 + 7` `` survives a JSON parser exactly instead of being
quietly rounded to the nearest float.

```bash
$ rbx vars --json
{"N.max": "100000", "M.max": "200000"}
```

A value and what a statement *shows* for it are two different things, though --
that is exactly what a filter like `sci` sits in the middle of. `--render`
answers the second question: it reads statement expressions from stdin, one per
line, and prints a JSON object mapping each one to the text it renders to.

```bash
$ printf 'N.max\nM.max | sci\n' | rbx vars --render
{"N.max": "100000", "M.max | sci": "2×10⁵"}
```

`--target` picks the spelling of that text, never the rules the filter follows:

| Target | What `sci` spells `M.max` as |
| ------ | ---------------------------- |
| `text` (the default) | `2×10⁵` -- plain text, for somewhere that cannot typeset maths |
| `latex` | `2 \times 10^{5}` -- what a {{rbxTeX}} statement puts in the PDF |
| `markdown` | the same as `latex`, since a Markdown statement writes its constraints inside `$...$` |

An expression {{rbx}} cannot render -- an unknown filter, a name no variable
answers to -- is left out of the map instead of guessed at, and named on
`stderr`. The command still exits 0, so one bad expression does not cost you
the rest.

A test group may override a variable for its own testcases, and `--groups`
shows what each group ends up with. Each group's set is the *resolved* one --
the package values with that group's overrides applied -- so a variable the
group does not override still appears, holding what it inherits:

```bash
$ rbx vars --groups
M.max = 200000
N.max = 100000
groups.sub1
  M.max = 200000
  N.max = 1000
```

With `--json` alongside it, the flat map moves under `vars` and the groups
arrive beside it:

```bash
$ rbx vars --json --groups
{"vars": {"N.max": "100000"}, "groups": {"sub1": {"N.max": "1000"}}}
```

`--render` takes the group per expression instead, ahead of a tab, since one
run may need to render against several. A line without a tab is a package-level
expression, and every key comes back exactly as you wrote it:

```bash
$ printf 'N.max | sci\nsub1\tN.max\n' | rbx vars --render
{"N.max | sci": "10⁵", "sub1\tN.max": "1000"}
```

!!! tip "Right there in your statement"

    The [VS Code extension](../tools/vscode.md#variables-in-a-statement) reads
    both of these to show you what each `\VAR{...}` in a statement expands to,
    beside the reference itself -- `--json` for a bare reference, `--render`
    for a filtered one.
