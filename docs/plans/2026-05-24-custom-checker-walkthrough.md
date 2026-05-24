# Custom Checker Walkthrough Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add the "Adding a custom checker" walkthrough page (step 2 of the *Authoring a problem* track) and fix a related `checker:` YAML bug in the feature guide.

**Architecture:** A single new Markdown page under `docs/setters/`, wired into `mkdocs.yml` nav. Content is prose + tabbed code blocks in the same style as `first-steps.md`. The "test" for this docs work is a clean `uv run mkdocs build` (catches broken nav/links/macros) plus visual confirmation the new page renders. A second, smaller task corrects the `checker:` list-vs-object documentation bug in `grading/checkers.md`.

**Tech Stack:** MkDocs + Material theme + `mkdocs-macros-plugin` (provides `{{rbx}}`, `{{testlib}}`, `{{tags.*}}`, `asciinema()` macros).

**Design doc:** `docs/plans/2026-05-24-custom-checker-walkthrough-design.md`

---

### Task 1: Create the walkthrough page

**Files:**
- Create: `docs/setters/custom-checker-walkthrough.md`

**Step 1: Write the page content**

Write the file exactly as below.

````markdown
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
````

**Step 2: Verify the page builds**

Run: `uv run mkdocs build 2>&1 | tail -20`
Expected: build finishes with `INFO - Documentation built` and **no** `WARNING` mentioning
`custom-checker-walkthrough.md` (the page is not yet in nav, so MkDocs will warn it's "not
included in the nav" — that warning is expected and resolved in Task 2).

---

### Task 2: Wire the page into the nav

**Files:**
- Modify: `mkdocs.yml` (the `Authoring a problem` block)

**Step 1: Add the nav entry**

Find:
```yaml
      - "Authoring a problem":
          - "First steps": "setters/first-steps.md"
```
Replace with:
```yaml
      - "Authoring a problem":
          - "First steps": "setters/first-steps.md"
          - "Adding a custom checker": "setters/custom-checker-walkthrough.md"
```

**Step 2: Verify the build is clean**

Run: `uv run mkdocs build 2>&1 | tail -20`
Expected: `Documentation built` with **no** warnings about `custom-checker-walkthrough.md`
(neither "not in nav" nor broken-link warnings).

**Step 3: Commit**

```bash
git add docs/setters/custom-checker-walkthrough.md mkdocs.yml
git commit -m "$(cat <<'EOF'
docs(walkthrough): add 'Adding a custom checker' page (#443)

Step 2 of the Authoring a problem track. Mutates the sum-of-N example
into the (a,b) pair variant to motivate a testlib checker, covers
wiring checker: into problem.rbx.yml, the new rbx run output, and a
brief rbx unit intro. asciinema casts left as TODO markers.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Fix the `checker:` list-vs-object bug in the feature guide

The schema is `checker: Optional[Checker]` (a single object; the default preset uses
`checker: {path: "wcmp.cpp"}`), but `grading/checkers.md` documents it as a YAML list in 3
places. Fix all three.

**Files:**
- Modify: `docs/setters/grading/checkers.md` (lines ~28, ~171, ~290)

**Step 1: Fix occurrence 1 (built-in checker example)**

Find:
```yaml
checker:
  - path: "wcmp.cpp"
```
Replace with:
```yaml
checker:
  path: "wcmp.cpp"
```

**Step 2: Fix occurrences 2 and 3 (custom checker examples)**

Both indented blocks read identically. Find (and apply to both, using `replace_all`):
```yaml
    checker:
      - path: "checker.cpp"
```
Replace with:
```yaml
    checker:
      path: "checker.cpp"
```

**Step 3: Verify no list-form occurrences remain**

Run: `grep -n -A1 'checker:' docs/setters/grading/checkers.md`
Expected: each `checker:` is followed by an indented `path:` line, with **no** `- path:`.

**Step 4: Verify the build still passes**

Run: `uv run mkdocs build 2>&1 | tail -5`
Expected: `Documentation built`.

**Step 5: Commit**

```bash
git add docs/setters/grading/checkers.md
git commit -m "$(cat <<'EOF'
docs(checkers): fix checker: YAML to single-object form

The checker field is a single object (checker: {path: ...}), not a
list. Three examples in the feature guide showed the list form.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Final verification

**Step 1: Full build sanity check**

Run: `uv run mkdocs build 2>&1 | tail -20`
Expected: `Documentation built`, no warnings referencing the new page or `checkers.md`.

**Step 2: Confirm the deliverables**

Run: `git log --oneline -3`
Expected: the design-doc commit plus the two commits from Tasks 2 and 3.

**Remaining manual handoff:** record the two asciinema casts (`rbx run`, `rbx unit`), upload
them, and replace the `<!-- TODO(record) -->` markers with `{{ asciinema("<id>") }}` macros.
This cannot be automated.
