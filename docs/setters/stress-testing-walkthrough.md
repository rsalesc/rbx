# Stress-testing your solutions

!!! note
    This page picks up the sum-of-N-integers problem from [First steps](first-steps.md),
    where `sols/main.cpp` is correct and `sols/wa-overflow.cpp` accumulates the sum into
    an `int32_t` that silently overflows.

Our goal here is simple: ask {{rbx}} to find a **tiny** input that breaks `sols/wa-overflow.cpp`.

## Describing the search

A stress test is described by two expressions:

- a **generator expression**, which tells {{rbx}} how to keep producing random testcases, and
- a **finder expression**, which describes the condition that makes a testcase a *match*.

See [Stress testing](stress-testing.md) for the complete operator reference. Here we only
need a couple of operators.

Our generator expression is:

```
tests/gen [1..5] <A.max> @
```

- `[1..5]` keeps the count of integers tiny — at most five numbers per test.
- `<A.max>` pulls the upper bound straight from the `vars` defined in `problem.rbx.yml`,
  so it tracks the problem's real constraints.
- `@` is replaced by a fresh random string on every evaluation, so each run produces a
  different testcase.

Why is such a small range enough? An `int32_t` overflows once the sum passes ~2.1×10⁹.
With `A.max` up at ~10⁹, just a handful of large numbers already pushes the true sum past
that line — which is exactly *why* the counterexample {{rbx}} finds comes out tiny.

Our finder expression is:

```
[sols/wa-overflow.cpp] ~ INCORRECT
```

This matches any testcase for which `sols/wa-overflow.cpp` produces a verdict considered
incorrect. As a convenience, `sols/wa-overflow.cpp` on its own is shorthand for the same
thing.

## Running the stress

```bash
rbx stress -g "tests/gen [1..5] <A.max> @" -f "sols/wa-overflow.cpp"
```

<!-- TODO(#437): record the rbx stress run (kickoff -> counterexample) and replace REPLACE_ME_CAST_ID. -->
{{ asciinema("REPLACE_ME_CAST_ID") }}

By default the stress runs for about 10 seconds and stops as soon as it finds the first
match. You can tune both the number of findings and the timeout with `-n` and `-t` — see
[Stress testing](stress-testing.md) for the details.

## Inspecting the counterexample

When a match is found, `rbx stress` prints a report and shows the exact generator call
that produced the failing testcase, along with the input itself.

It's a small input — just a few large numbers whose sum overflows `int32_t`, so
`sols/wa-overflow.cpp` prints the wrong value while `sols/main.cpp` gets it right. That's
the divergence {{rbx}} flagged as `INCORRECT`.

## Making it stick

A counterexample is only useful if it survives into your testset. Right after a match,
`rbx stress` asks:

> Do you want to add the tests that were found to a test group?

Answer **yes**. {{rbx}} then lists every test group backed by a `.txt` generator script,
plus two extra options: `(create new script)` and `(skip)`. Choose `(create new script)`
and name it `tests/corner.txt`.

{{rbx}} appends the found generator call to that script — prefixed with a
`# Obtained by running rbx stress ...` comment so you know where it came from — and adds a
new `corner` test group to `problem.rbx.yml`:

=== "problem.rbx.yml"
    ```yaml
    # Testcases section would now look like:

    testcases:
    - name: 'samples'
        testcaseGlob: 'documents/samples/*.in'
    - name: 'testplan'
        generatorScript:
            path: 'tests/testplan.txt'
    - name: 'corner'  # (1)!
        generatorScript:
            path: 'tests/corner.txt'  # (2)!
    ```

    1.  The new group `corner` is backed by the freshly created `tests/corner.txt`.
    2.  The `path` is relative to the testplan root, so bare `corner.txt` here and the `tests/corner.txt` you typed are the same file.

=== "tests/corner.txt"
    ```
    # Obtained by running `rbx stress -g 'tests/gen [1..5] <A.max> @' -f sols/wa-overflow.cpp`
    tests/gen 3 1000000000 a1b2c3d4
    ```

Now run `rbx build`, and the counterexample is regenerated as a permanent test in the
`corner` group.

!!! tip
    Because {{testlib}} seeds its RNG from the `argv` passed to the generator, the saved
    generator call reproduces the **exact same** input on every build. The randomized `@`
    has already been resolved to a concrete string, so the test is fully deterministic from
    here on.

The same picker also lists every **manual** test group (those backed by a glob, like
`tests/manual/*.in`), plus a `(create new manual group)` option. Choosing a manual group
saves each finding's **actual failing input** as a static `.in` file rather than appending a
generator call — `rbx build` regenerates the matching `.out` for you. Picking
`(create new manual group)` prompts for a group name and a glob path (e.g.
`tests/manual/corner/*.in`) and wires it into `problem.rbx.yml`.

!!! note
    Use the manual-group route when you want the *input itself* frozen in your testset (no
    generator needed to reproduce it); use the generator-script route above when you'd rather
    keep the reproducing generator call. Either way the counterexample becomes a permanent
    test ([issue #442](https://github.com/rsalesc/rbx/issues/442)).

!!! tip
    To promote tests you *already* have — rather than fresh stress findings — into a manual
    group, use [`rbx testcases promote`](/setters/reference/cli), which copies existing
    testcase inputs into a glob-backed manual group as static `.in` files.

## Next steps

<div class="grid cards" markdown>

-   :fontawesome-solid-shuffle: **Stress testing reference**

    ---

    Want fuzzing, `--slowest`, or saved `stresses:` blocks? The reference page covers the full operator set and every flag.

    [:octicons-arrow-right-24: Stress testing](/setters/stress-testing)

-   :fontawesome-solid-dice: **Generators**

    ---

    Want to write smarter generators for your stress tests? Check out our guide on generators.

    [:octicons-arrow-right-24: Generators](/setters/testset/generators)

-   :fontawesome-solid-gear: **Configure further**

    ---

    Want to learn all you can do in `problem.rbx.yml`? Check out our reference on how to configure your problem.

    [:octicons-arrow-right-24: `problem.rbx.yml`](/setters/reference/package)

</div>
