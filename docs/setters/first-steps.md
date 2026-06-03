# First steps

`rbx` is the CLI tool {{rbx}} provides for setters to prepare contests and problems.

This document focus on a very specific and simple user journey to highlight the most
common features of {{rbx}}. Feel free to explore the rest of the documentation on the sidebar
to get more information about the other features.

We'll focus on how to create a problem from a pre-initialized preset, how to write its main
components and how to test it.

You can start creating a new problem from a pre-initialized preset by running `rbx create`.

<!--termynal-->
```bash
$ rbx create
# This will prompt you for the name of the problem, and then create a new problem
# in a folder with that name.
```

This is how the directory structure of the pre-initialized problem preset will look like:

```bash
test
├── problem.rbx.yml # (1)!
├── README.md # (2)!
├── validator.cpp # (3)!
├── wcmp.cpp # (4)!
├── documents # (5)!
│   ├── statement.rbx.tex
│   ├── icpc.sty
│   ├── template.rbx.tex
│   └── samples
│       ├── 000.in
│       ├── 000.rbx.tex
│       └── 001.in
├── tests # (6)!
│   ├── testplan.txt # (7)!
│   └── gen.cpp # (8)!
└── sols
    └── main.cpp # (9)!
```

1.  The {{YAML}} configuration file for this problem.

2.  A short README describing the package layout and pointing you at the docs.

3.  A {{testlib}} validator that checks whether the generated tests are
    in the correct format.

4.  A built-in {{testlib}} checker that compares tokens of the participant's output
    and the judge's output.

5.  All statement-related assets, including the legend of the problem itself
    but also the tex templates, the `icpc.sty` style file and the sample testcases
    (`documents/samples/`). Samples can carry an explanation alongside them
    (e.g. `000.rbx.tex`).

6.  Everything related to generating tests lives here: generator sources (e.g.
    `tests/gen.cpp`) and the generator scripts (testplans) that call them.

7.  A generator script for the problem (a _testplan_).

    Each line of a generator script describes one call to a generator, and a generator script groups all these calls together.

    The preset ships this file fully commented out, just to show you the shape of a call:

    ```
    # tests/gen 1000000000
    # tests/gen 100
    ```

    Uncommenting a line calls the generator named `gen` (here implemented through
    `tests/gen.cpp`) once, thus generating one testcase. In this problem, this
    script backs the testcase group `testplan`.

8.  An example of a {{testlib}} generator.

    !!! note
        A problem can have multiple generators. This one is just an example.

9.  The single solution shipped by the preset: a correct, {{tags.accepted}} solution.

    !!! note
        `problem.rbx.yml` already declares outcome patterns for other prefixes
        (`ac-*`, `wa-*`, `tle-*`, ...), so you can add more solutions later just by
        dropping in a file with the matching prefix.

## Build

Let's skip the configuration of the problem for a second, and just build and run it. You can build a problem with `rbx build`. This will populate a `build` folder inside your problem's folder with all the testcases generated for the problem.

```{.bash .no-copy}
$ rbx build
$ ls build
build
│   └── tests
│       ├── samples
│       │   └── ...
│       └── testplan
│           └── ...
```

You can notice it created several folders inside a `tests` directory, each of which contains the tests for a specific testgroup. For this preset in particular, we have two testsets: `samples` and `testplan`.

!!! note
    The `testplan` group ships empty because `tests/testplan.txt` is fully commented
    out by default. We'll fill it in [further below](#generating-random-testcases).

If you want, you can explore these folders manually, but {{rbx}} also provides a TUI (terminal UI) to explore the testcases.
You can run `rbx ui` and select the first option to explore the built testcases.

{{ asciinema("cqUTWgIRFA1P7VsV39uJTorKC") }}

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

As you can see from the solutions and the statement, the pre-initialized preset simply implements a problem where you have to add up two numbers `A` and `B`. Let's modify the problem to _compute the sum of N numbers_.

### Rewrite solutions

The lean preset ships a single solution, `sols/main.cpp`. Let's start by rewriting it to
sum `N` numbers, and then **add a second, deliberately buggy** solution so we have something
to catch later on.

We can develop the following {{tags.accepted}} solution (rewriting `sols/main.cpp`) and
{{tags.wrong_answer}} solution (a brand new file, `sols/wa-overflow.cpp`):

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

=== "sols/wa-overflow.cpp"
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

Notice that we didn't have to touch `problem.rbx.yml` to register `sols/wa-overflow.cpp`.

By default, the `solutions` section is configured to use the file name to determine the outcome of that solution,
example: if the file name starts with `ac-`, its outcome should be `ACCEPTED`, and if it starts with `wa-`, its outcome
should be `WRONG_ANSWER`, etc. The preset already declares the `sols/wa-*` → {{tags.wrong_answer}} pattern,
so simply creating a file whose name starts with `wa-` is enough for {{rbx}} to pick it up with the
right expected outcome.

If you want to add or delete solutions from our package, you can just make the changes to the files
(matching one of these prefixes), or manually edit the `solutions` section if you want a bespoke setup.

You can find the full list of expected outcomes [here][rbx.box.schema.ExpectedOutcome].

### Write the validator

The new input limits have to be updated in the `problems.rbx.yml`. The `vars` sections should look like this:

=== "validator.cpp"
    ```yaml
    vars:
      N:
        min: 1
        max: 1000000000
      A:
        min: 1
        max: 1000000000
    ```

The {{testlib}} validator is implemented by `validator.cpp` and will look like this:


=== "validator.cpp"
    ```c++
    #include "rbx.h"
    #include "testlib.h"

    using namespace std;

    int main(int argc, char *argv[]) {
      registerValidation(argc, argv);
      prepareOpts(argc, argv);

      // Read from package vars. // (1)!
      int MIN_N = getVar<int>("N.min");
      int MAX_N = getVar<int>("N.max");
      int MIN_A = getVar<int>("A.min");
      int MAX_A = getVar<int>("A.max");

      int n = inf.readInt(1, MAX_N, "N");
      inf.readEoln();
      for (int i = 0; i < n; i++) {
        if (i) inf.readSpace();
        inf.readInt(MIN_A, MAX_A, "A_i");
      }
      inf.readEoln();
      inf.readEof();
    }
    ```

    1.  `getVar` reads a variable defined in `problem.rbx.yaml` that is accessible
        in the validator. It allows you to change the constraints of the problem,
        and instantly replicate the change in validators and statements.

### Generating random testcases

Now, let's rewrite our random generator to generate `N` numbers instead of only two.

We have to actually call this generator and generate testcases into the `testplan` testgroup.

The preset already declares a `testplan` group backed by `tests/testplan.txt`, but that file
ships fully commented out, so the group starts empty. Let's fill it in with 10 random tests by
uncommenting/adding calls to the generator. We can either spell the calls out by hand in a
static generator script (`tests/testplan.txt`) or have a program print them for us as a
dynamic generator script (here shown as `tests/testplan.py`).

=== "tests/gen.cpp"
    ```c++
    #include "testlib.h"

    using namespace std;

    int main(int argc, char *argv[]) {
        registerGen(argc, argv, 1); // (1)!

        int n = rnd.next(1, opt<int>(1));
        cout << endl;
        for (int i = 0; i < n; i++) {
            if (i) cout << " ";
            cout << rnd.next(1, opt<int>(2));
        }
        cout << endl;
    }
    ```

    1.  The generator now receive two parameters `N.max` (accessed through `#!c++ opt<int>(1)`) and `A.max` (accessed through `#!c++ opt<int>(2)`).

=== "tests/testplan.txt (static)"
    ```
    tests/gen 1000 1000000000 1
    tests/gen 1000 1000000000 2
    tests/gen 1000 1000000000 3
    tests/gen 1000 1000000000 4
    tests/gen 1000 1000000000 5
    tests/gen 1000 1000000000 6
    tests/gen 1000 1000000000 7
    tests/gen 1000 1000000000 8
    tests/gen 1000 1000000000 9
    tests/gen 1000 1000000000 10
    ```

=== "tests/testplan.py (dynamic)"
    ```python
    for i in range(10):
        print(f'tests/gen 1000 1000000000 {i}') # (1)!
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
        testcaseGlob: 'documents/samples/*.in'
    - name: 'testplan'  # (1)!
        generatorScript:
            path: 'tests/testplan.txt'  # or 'tests/testplan.py', in case you want to use a dynamic generator
    ```
    
    1.  Here, `testplan` would contain the 10 tests defined in `tests/testplan.txt` or `tests/testplan.py`.

Our newly defined generator `gen.cpp` will receive two positional arguments, `N` and `A`, and generate
a list of `N` integers, each of which is at most `A`.

Then, our generator script will call this generator 10 times to generate 10 different tests with
`N` integers ranging from 1 to `A`.

Now, if we run `rbx build`, we'd get our brand new generated tests.

### Update the statement

Of course, last but not least, we have to update the statement of our problem. {{rbx}}
has its own statement format, called {{rbxTeX}}. The format itself is simple, but the ecosystem
behind it is complex and provides a lot of flexibility for setters.

For now, you just need to know the body and meat of the statement is written at `documents/statement.rbx.tex`.
If you open it, you will find something like the following:


=== "documents/statement.rbx.tex"
    ```tex
    %- block legend
    Given two integers $A$ and $B$, determine the value of $A + B$.
    %- endblock

    %- block input
    The input is a single line containing two integers $A$ and $B$
    ($1 \leq A, B \leq \VAR{N.max | sci}$). % (1)!
    %- endblock

    %- block output
    The output must contain only one integer, the sum of $A$ and $B$.
    %- endblock

    %- block notes
    No notes.
    %- endblock
    ```

    1.  Notice the use of `\VAR` here, which is a command {{rbxTeX}} exposes for
        you to access variables defined in `problem.rbx.yml`, similar to how you
        accessed these in the {{testlib}} validator.

        The template engine used to expand `\VAR{...}` is Jinja2. This means we can also
        use filters. Here in particular, we're using a pre-defined filter implemented
        by {{rbxTeX}} called `sci`. This filter converts numbers with lots of zeroes (for instance, 100000), into their scientific notations (`10^5`).

As you can see, similar to {{polygon}}, you write a few blocks of LaTeX. Here, the `%-` delimits those pre-defined blocks.
Your statement needs at least a _legend_, an _input_ and an _output_. When the time comes to build this statement,
these blocks will be pieced together to form the final statement.

Let's change each corresponding block to match our new problem description.

=== "documents/statement.rbx.tex"
    ```tex
    %- block legend
    Given $N$ integers, print their sum.
    %- endblock

    %- block input
    The input has a single line containing $N$ 
    ($1 \leq N \leq \VAR{N.max | sci}$) numbers. 
    These numbers range from 1 to $\VAR{A.max | sci}$.
    %- endblock

    %- block output
    Print the sum of the integers.
    %- endblock

    %- block notes
    No notes.
    %- endblock
    ```

## Next steps

If you want to customize the problem even more, you can continue reading our Reference
section on the sidebar.

<div class="grid cards" markdown>

-   :fontawesome-solid-not-equal: **Add a custom checker**

    ---

    Want to grade solutions without comparing tokens? Check out our guide on how to add a custom checker.

    [:octicons-arrow-right-24: Checkers](/setters/grading/checkers)

-   :fontawesome-solid-rocket: **Package and ship your problem**

    ---

    Want to package your problem for a judge? Check out our guide on how to package your problem.

    [:octicons-arrow-right-24: Packaging](/setters/packaging)

-   :fontawesome-solid-shuffle: **Stress test**

    ---

    Walk through finding a tiny counterexample for a buggy solution and locking it into your testset.

    [:octicons-arrow-right-24: Stress-testing your solutions](/setters/stress-testing-walkthrough)

-   :fontawesome-solid-gear: **Configure further**

    ---

    Want to learn all you can do in `problem.rbx.yml`? Check out our reference on how to configure your problem.

    [:octicons-arrow-right-24: `problem.rbx.yml`](/setters/reference/package)

</div>
