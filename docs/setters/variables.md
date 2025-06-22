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
  MAX_N: 100000
  MAX_M: 200000
```

They're defined as key-value pairs. The keys should be valid Python identifiers
and the values should be a `bool`, a `string`, an `int` or a `float`, all conforming
to the YAML specification.

Besides that, it's possible to use Python expressions that evaluate to one of these
types, using the ``py`...` `` syntax. 

```yaml title="problem.rbx.yml"
# ...
vars:
  MAX_N: py`10**5`
  MAX_M: py`2*10**5`
```

## Using variables

Variables can be used within **validators**, **checkers** and **statements**.

In this section, we go through the different ways to use variables in each of these.

### Validators and checkers (C++)

{{rbx}} automatically generates a `rbx.h` header file that contains the variables
that were defined in the `problem.rbx.yml` file, right at the root of your package.

This header exposes a function `getVar<T>(name)` that can be used to get the value
of a variable as a `T`-typed object. There are 4 overloads for this function:
`getVar<bool>(name)`, `getVar<int>(name)`, `getVar<float>(name)` and `getVar<std::string>(name)`.

This header can be directly included in your validator/checker files.

=== "validator.cpp"

    ```cpp hl_lines="2 7-8" linenums="1"
    #include "testlib.h"
    #include "rbx.h"

    int main(int argc, char* argv[]) {
        registerValidation(argc, argv);

        int n = getVar<int>("MAX_N");
        int m = getVar<int>("MAX_M");
      
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

        int n = getVar<int>("MAX_N");
        int m = getVar<int>("MAX_M");
        
        // ...
    }
    ```

### Validators (other languages)

Validators also receive the variables as command-line arguments. This means that
for the `problem.rbx.yml` above, your validator would be called roughly as follows:

```bash
./validator.exe --MAX_N=100000 --MAX_M=200000
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
You're given a graph with \VAR{vars.MAX_N} vertices and \VAR{vars.MAX_M} edges.
% ...
```

Variables can also be used within any {{rbxtex}} statements, including loops and
conditionals.

```latex title="statement.rbx.tex"
% ...
%- if vars.MAX_N < 1000:
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
You're given a graph with \VAR{vars.MAX_N | sci} vertices
and \VAR{vars.MAX_M | sci} edges.
% ...
```

The `sci` builtin will make `MAX_N` and `MAX_M` be rendered as something like
`10^5` and `2 x 10^5` respectively.

### Stress tests

Variables can also be used in [generator expressions](/setters/stress-testing/#generator-expression) in stress tests with the `<variable>` notation.

```
rbx stress -g "gen [1..<MAX_N>]" -f "[sols/wa.cpp] ~ INCORRECT"
```

