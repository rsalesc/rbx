# First steps

`rbx` is the CLI tool {{rbx}} provides for setters to prepare contests and problems.

This document focus on a very specific and simple user journey to highlight the most
common features of {{rbx}}. Feel free to explore the rest of the documentation on the sidebar
to get more information about the other features.

We'll focus on how to create a problem from a pre-initialized template, how to write its main
components and how to test it.

You can start creating a new problem from a pre-initialized template by running `rbx create [name]`.

<!--termynal-->
```bash
$ rbx create test
# This will create a `test` directory under the current
# working directory with a pre-initialized problem template.
```

This is how the directory structure of the pre-initialized problem template will look like:

```bash
test
├── sols  # (1)!
│   ├── main.cpp
│   ├── slow.cpp
│   └── wa.cpp
├── statement  # (2)!
│   ├── olymp.sty
│   ├── projecao.png
│   ├── statement.rbx.tex
│   └── template.rbx.tex
├── tests  # (3)!
│   └── samples
│       ├── 000.in
│       └── 001.in
├── gen.cpp # (4)!
├── problem.rbx.yml # (5)!
├── random.txt # (6)!
├── random.py # (7)!
├── validator.cpp # (8)!
└── wcmp.cpp # (9)!
```

1.  All solutions for the problem: the correct and the incorrect ones.
2.  All statement-related assets, including the legend of the problem itself
    but also the tex templates and imported graphics.
3.  Manually defined tests of the problem.

    !!! note
        Automatically generated tests are not defined by explicit input and output files, but are rather defined by generator entries in the problem configuration.

4.  An example of a {{testlib}} generator. In this case, the generator is used to
    generate testcases for two testgroups: `random` and `program-random`.

    !!! note
        A problem can have multiple generators. This one is just an example.

5.  The {{YAML}} configuration file for this problem.
6.  A generator script for the problem.

    Each line of a generator script describes one call to a generator, and a generator script groups all these calls together.

    Example:

    ```
    gen 123
    gen 456
    ```

    Calls the generator named `gen` (here in this problem, implemented through `gen.cpp`) twice, thus generating two testcases.

    In this problem, this script is used to generate the testcase group `random`.

7.  A program that outputs a generator script. Pretty similar to `random.txt`
    above, except that this is a program that prints to the **stdout** a
    generator script, and thus provides more flexibility to the setter.

    Example:

    ```python
    #! /usr/bin/python3
    for i in range(10):
        print(f'gen {i}')
    ```

    This program outputs a generator script that creates 10 testcases with increasing
    parameter `i`.

    In this problem, this program is used to generate the testcase group `program-random`.

8.  A {{testlib}} validator that checks whether the generated tests are
    in the correct format.

9.  A built-in {{testlib}} checker that compares tokens of the participant's output
    and the judge's output.

## Build

Let's skip the configuration of the problem for a second, and just build and run it. You can build a problem with `rbx build`. This will populate a `build` folder inside your problem's folder with all the testcases generated for the problem.

```{.bash .no-copy}
$ rbx build
$ ls build
build
│   └── tests
│       ├── program-random
│       │   └── ...
│       ├── random
│       │   └── ...
│       └── samples
│           └── ...
```

You can notice it created several folders inside a `tests` directory, each of which contains the tests for a specific testgroup. For this template in particular, we have three testsets: `random`, `program-random` and `samples`.

If you want, you can explore these folders manually, but {{rbx}} also provides a TUI (terminal UI) to explore the testcases.
You can run `rbx ui` and select the first option to explore the built testcases.

## Run

Now, let's execute `rbx run`. This command **builds** all testcases and **executes** each solution against them, evaluating whether each solution had the expected outcome.

```bash
$ rbx run
```

{{ asciinema("x8NJUtmob4uSHUUFppxUn64Kn") }}

You can see this command prints a full run report: it shows for each testcase of each testgroup whether a certain solution passed or not. There are also links for the outputs of each problem.

!!! tip
    You can notice when you call `rbx run` again, the testcases were built really fast.
    That's because {{rbx}} caches certain calls based on the hash tree of your package
    (similar to Makefile). You can explicitly clear this cache by calling `rbx clean`.

## Modifying the package

As you can see from the solutions and the statement, the pre-initialized template simply implements a problem where you have to add up two numbers `A` and `B`. Let's modify the problem to _compute the sum of N numbers_.

### Rewrite solutions

Let's start rewriting the solutions. We can probably drop the slow solution since we're just naively summing numbers anyway.

We can develop the following {{tags.accepted}} and {{tags.wrong_answer}} solutions.

=== "sols/main.cpp"
    ```c++
    #include <bits/stdc++.h>

    int32_t main() {
        int n;
        cin >> n;

        int64_t ans = 0;
        for(int i = 0; i < n; i++) {
            int x;
            cin >> x;
            ans += x;
        }

        cout << ans << endl;
    }
    ```

=== "sols/wa.cpp"
    ```c++
    #include <bits/stdc++.h>

    int32_t main() {
        int n;
        cin >> n;

        int32_t ans = 0; // int32 overflows!!
        for(int i = 0; i < n; i++) {
            int x;
            cin >> x;
            ans += x;
        }

        cout << ans << endl;
    }
    ```

To delete the `slow.cpp` solution from our package, we can just delete the file and the reference to it in `problem.rbx.yml`. The reference is located in the `solutions` section, which will look like this after the deletion:

```yaml
solutions:
  - path: 'sols/main.cpp'
    outcome: ACCEPTED
  - path: 'sols/wa.cpp'
    outcome: WRONG_ANSWER
```

You can find the full list of expected outcomes [here][rbx.box.schema.ExpectedOutcome].

### Write the validator

The {{testlib}} validator is implemented by `validator.cpp` and will look like this:


=== "validator.cpp"
    ```c++
    #include "testlib.h"
    #include "rbx.h"

    using namespace std;

    int main(int argc, char *argv[]) {
        registerValidation(argc, argv);

        int MAX_N = getVar<int>("MAX_N"); // (1)!
        int MAX_A = getVar<int>("MAX_A");

        for (int i = 0; i < n; i++) {
            if (i) inf.readSpace();
            inf.readInt(1, MAX_A, "A_i");
        }
        inf.readEoln();
        inf.readEof();
    }
    ```

    1.  `MAX_N` is a variable defined in `problem.rbx.yaml` that is accessible
        in the validator. It allows you to change the constraints of the problem,
        and instantly replicate the change in validators and statements.

### Generating random testcases

Now, let's rewrite our random generator to generate `N` numbers instead of only two.

We have to actually call this generator and generate testcases into some of the testgroups.

Let's delete the existing test groups in `problem.rbx.yml`, except for the `samples` one, and create a new `main_tests` group. Let's generate 10 random tests for this group by using a generator script. We can either use a static generator script
(represented in the example below as `random.txt`) or a dynamic generator script (represented in the example below as `random.py`).

=== "gen.cpp"
    ```c++
    #include "testlib.h"

    using namespace std;

    int main(int argc, char *argv[]) {
        registerGen(argc, argv, 1); // (1)!

        int n = rnd.next(1, opt<int>(1));

        for (int i = 0; i < n; i++) {
            if (i) cout << " ";
            cout << rnd.next(1, opt<int>(2));
        }
        cout << endl;
    }
    ```

    1.  The generator now receive two parameters `MAX_N` (accessed through `#!c++ opt<int>(1)`) and `MAX_A` (accessed through `#!c++ opt<int>(2)`).

=== "random.txt (static)"
    ```
    gen 1000 1000000000 1
    gen 1000 1000000000 2
    gen 1000 1000000000 3
    gen 1000 1000000000 4
    gen 1000 1000000000 5
    gen 1000 1000000000 6
    gen 1000 1000000000 7
    gen 1000 1000000000 8
    gen 1000 1000000000 9
    gen 1000 1000000000 10
    ```

=== "random.py (dynamic)"
    ```python
    for i in range(10):
        print(f'gen 1000 1000000000 {i}') # (1)!
    ```

    1.  This line defines 10 random calls to the generator `gen`, 
        which will in turn generate testcases with `N` randomly varying
        from 1 to 1000 and the numbers to be added varying from 1 to `1e9`.

        !!! tip
            Notice the trailing `{i}` being printed in every generator script line.
            That's because {{testlib}} rng seed is initialized from the `argv` given to
            the generator.
            
            Thus generators are reproducible: if we called `gen 1000 1000000000` 10 times, we
            would always get the same result. By appending an extra variable `{i}`,
            we introduce randomness to the tests.

=== "problem.rbx.yml"
    ```yaml
    # Testcases section would look like:

    testcases:
    - name: 'samples'
        testcaseGlob: 'tests/samples/*.in'
    - name: 'main_tests'  # (1)!
        generatorScript:
            path: 'random.txt'  # or 'random.py', in case you want to use a dynamic generator
    ```
    
    1.  Here, `main_tests` would contain the 10 tests defined in `random.txt` or `random.py`.

Our newly defined generator `gen.cpp` will receive two positional arguments, `N` and `A`, and generate
a list of `N` integers, each of which is at most `A`.

Then, our generator script will can this generator 10 times to generate 10 different tests with
`N` integers ranging from 1 to `A`.

Now, if we run `rbx build`, we'd get our brand new generated tests.

### Update the statement

Of course, last but not least, we have to update the statement of our problem. {{rbx}}
has its own statement format, called {{rbxTeX}}. The format itself is simple, but the ecosystem
behind it is complex and provides a lot of flexibility for setters.

For now, you just need to know the body and meat of the statement is written at `statement/statement.rbx.tex`.
If you open it, you will find something like the following:


=== "statement/statement.rbx.tex"
    ```tex
    %- block legend
    Dado dois números inteiros $A$ e $B$, determine o valor de $A + B$.

    \includegraphics[width=6cm]{projecao.png}
    %- endblock

    %- block input
    A entrada é composta por uma única linha contendo dois números
    inteiros $A$ e $B$ ($1 \leq A, B \leq \VAR{vars.MAX_N | sci}$). % (1)!
    %- endblock

    %- block output
    A saída deve conter somente um único inteiro, a soma de $A$ e $B$.
    %- endblock

    %- block notes
    Sem muitas notas pra este problema.
    %- endblock
    ```

    1.  Notice the use of `\VAR` here, which is a command {{rbxTeX}} exposes for
        you to access variables defined in `problem.rbx.yml`, similar to how you
        accessed these in the {{testlib}} validator.

        The template engine used to expand `\VAR{...}` is Jinja2. This means we can also
        use filters. Here in particular, we're using a pre-defined filter implemented
        by {{rbxTeX}} called `sci`. This filter converts numbers with lots of zeroes (for instance, 100000), into their scientific notations (`10^5`).

As you can see, similar to {{polygon}}, you write a few blocks of LaTeX. Here, the `%` delimits those pre-defined blocks.
Your statement needs at least a _legend_, an _input_ and an _output_. When the time comes to build this statement,
these blocks will be pieced together to form the final statement.

Let's change each corresponding block to match our new problem description.

=== "statement/statement.rbx.tex"
    ```tex
    %- block legend
    Given $N$ integers, print their sum.
    %- endblock

    %- block input
    The input has a single line containing $N$ 
    ($1 \leq N \leq \VAR{vars.MAX_N | sci}$) numbers. 
    These numbers range from 1 to $\VAR{vars.MAX_A | sci}$.
    %- endblock

    %- block output
    Print the sum of the integers.
    %- endblock

    %- block notes
    No notes.
    %- endblock
    ```

## Advanced configuration

If you want to do more advanced changes to the package, you can continue reading our Reference section on the sidebar.

## Package the problem

To build you problem, you can use the `rbx package [platform]` command.

Here, we'll build a {{polygon}} package with our statement, and as such we'll need LaTeX dependencies installed to compile it to a PDF. You can read more about a few recommendations we have to install pdfLaTeX and other common dependencies [here](pdflatex.md).

!!! note
    Packages usually require a statement to be built.
    
    You can try running `rbx package [platform] --no-statement`, but an error might be raised in case such platform does not support packages without statements.

```bash
$ rbx package polygon
```

A {{polygon}} package will be built. This package can be directly uploaded to the [Codeforces Gym](https://codeforces.com/gyms) through FTP.
