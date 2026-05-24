# Adding a custom checker

!!! note "Prerequisite"
    This page continues the story from [First steps](first-steps.md). If you haven't gone
    through it yet, start there — we pick up right where it left off.

In [First steps](first-steps.md) we built a problem that asks for the **sum of `N` integers**.
That problem has a single correct answer, so {{rbx}}'s default checker — `wcmp`, which simply
compares the participant's output token-by-token against the model answer — works perfectly.

But not every problem has a unique answer. Let's mutate our problem into one that doesn't, and
see why we need a **checker**.

## A problem with many answers

Let's change the problem to:

> Given an integer `N` (`2 ≤ N ≤ 10^9`), print **any** two integers `a` and `b` such that
> `a + b = N` and `1 ≤ a, b`.

Now there are many correct answers. For `N = 10`, both `1 9` and `5 5` are valid. This breaks
token comparison: if your solution prints `1 9` but the model solution printed `5 5`, `wcmp`
would wrongly flag a {{tags.wrong_answer}} even though `1 9` is perfectly correct.

We need a checker that *verifies the property* (`a + b = N`) instead of comparing strings.

### The solutions

Here's an {{tags.accepted}} solution and a {{tags.wrong_answer}} solution. As in step 1, the
filename prefix (`wa-`) tells {{rbx}} the expected outcome.

=== "sols/main.cpp"
    ```c++
    #include <bits/stdc++.h>
    using namespace std;

    int32_t main() {
        int64_t n;
        cin >> n;
        cout << 1 << " " << n - 1 << endl; // 1 + (n - 1) = n
    }
    ```

=== "sols/wa-offbyone.cpp"
    ```c++
    #include <bits/stdc++.h>
    using namespace std;

    int32_t main() {
        int64_t n;
        cin >> n;
        cout << 2 << " " << n - 1 << endl; // bug: 2 + (n - 1) = n + 1
    }
    ```

!!! note "What about the validator, generator and statement?"
    Switching problems also means updating the input validator, the generator and the
    statement. The mechanics are exactly what you learned in
    [First steps](first-steps.md) — the input is now a single integer `N` — so we won't
    re-walk them here and will keep the spotlight on the checker.

## Writing the checker

A {{testlib}} checker is a small program that receives three files:

```bash
./checker <input_file> <output_file> <answer_file>
```

- `<input_file>` — the test input (here, the integer `N`).
- `<output_file>` — the participant's output (here, the pair `a b`).
- `<answer_file>` — the model solution's output.

{{testlib}} exposes these as the streams `inf`, `ouf` and `ans` respectively. For our problem,
we only need `inf` and `ouf`: any pair that sums to `N` is correct, so we never have to look at
the model answer.

=== "checker.cpp"
    ```cpp linenums="1"
    #include "testlib.h"

    int main(int argc, char* argv[]) {
        registerTestlibCmd(argc, argv); // (1)!

        // Read the input: the target sum N.
        int n = inf.readInt();

        // Read the participant's two integers, enforcing 1 <= a, b <= n - 1.
        int a = ouf.readInt(1, n - 1, "a"); // (2)!
        int b = ouf.readInt(1, n - 1, "b");

        // The pair must sum to exactly N.
        if (a + b != n) {
            quitf(_wa, "a + b = %d, expected %d", a + b, n); // (3)!
        }

        quitf(_ok, "%d + %d = %d", a, b, n); // (4)!
    }
    ```

    1.  `registerTestlibCmd` wires up the three streams (`inf`, `ouf`, `ans`) from the command
        line arguments. Every checker starts with this call.

    2.  Reading with bounds is your first line of defense. `ouf.readInt(1, n - 1, "a")` reads an
        integer named `a` and **automatically** fails with a {{tags.wrong_answer}} if it is
        missing or outside `[1, n - 1]` — no extra code needed.

    3.  `quitf(_wa, ...)` ends the checker with a {{tags.wrong_answer}} and a **custom message**.
        Notice you can use `printf`-style format specifiers, so the report tells the setter
        exactly what went wrong.

    4.  `quitf(_ok, ...)` ends the checker with an {{tags.accepted}} verdict.

!!! tip "When you *do* need the model answer"
    Some problems (e.g. "find the **shortest** path") can only be checked by comparing against
    the jury's solution via the `ans` stream. That's a more advanced pattern — see the
    [Checkers](grading/checkers.md) feature guide for the full *output + answer* example.

### Wiring it into `problem.rbx.yml`

The pre-initialized preset uses the built-in `wcmp` checker. Point the `checker` field at our
new file instead:

=== "problem.rbx.yml"
    ```yaml
    # ... rest of the problem.rbx.yml ...
    checker:
      path: "checker.cpp"
    ```

## Running it

Now run `rbx run` again. Two things change compared to step 1:

- Your `main.cpp` passes on every test, even when it prints a different pair than the model
  solution — the checker verifies the *property*, not the exact tokens.
- `wa-offbyone.cpp` fails, and instead of an opaque token diff you get the checker's custom
  message, e.g. `a + b = 11, expected 10`.

<!-- TODO(record): rbx run cast showing the custom WA message goes here -->

## Testing the checker with `rbx unit`

A buggy checker can silently let wrong solutions through (or reject correct ones). {{rbx}} lets
you **unit test** your checker so you can trust it.

Declare the expected outcomes in `problem.rbx.yml`:

=== "problem.rbx.yml"
    ```yaml
    unitTests:
      checker:
        - glob: unit/checker/ac*
          outcome: ACCEPTED
        - glob: unit/checker/wa*
          outcome: WRONG_ANSWER
    ```

Each unit test is a triple of files sharing a name prefix: `<name>.in` (input), `<name>.out`
(participant output) and an optional `<name>.ans` (model answer). Our checker ignores the
answer, so we only provide `.in` and `.out`.

=== "unit/checker/ac_BASIC.in"
    ```title="unit/checker/ac_BASIC.in"
    10
    ```

=== "unit/checker/ac_BASIC.out"
    ```title="unit/checker/ac_BASIC.out"
    4 6
    ```

=== "unit/checker/wa_BAD_SUM.in"
    ```title="unit/checker/wa_BAD_SUM.in"
    10
    ```

=== "unit/checker/wa_BAD_SUM.out"
    ```title="unit/checker/wa_BAD_SUM.out"
    2 9
    ```

`ac_BASIC` should be {{tags.accepted}} (`4 + 6 = 10`) and `wa_BAD_SUM` should be
{{tags.wrong_answer}} (`2 + 9 = 11 ≠ 10`). Run them with:

```bash
rbx unit
```

<!-- TODO(record): short rbx unit cast goes here -->

For many small cases you can avoid one-file-per-test with **test plans** — see the
[Unit tests](verification/unit-tests.md) feature guide.

## Next steps

<div class="grid cards" markdown>

-   :fontawesome-solid-shuffle: **Stress-test your solutions**

    ---

    Continue the track: hunt for inputs that break a solution your checker would otherwise pass.

    [:octicons-arrow-right-24: Stress testing](/setters/stress-testing)

-   :fontawesome-solid-not-equal: **Checker reference**

    ---

    The full {{testlib}} checker guide: built-in checkers, the `ans` stream, and `JUDGE_FAILED`.

    [:octicons-arrow-right-24: Checkers](/setters/grading/checkers)

</div>
