# Unit tests

{{rbx}} provides a way for you to unit test your **validators** and your **checker**.

You can define unit tests in the `unitTests` field in your `problem.rbx.yml` file.

```yaml title="problem.rbx.yml"
unitTests:
  validator:
    - glob: unit/validator/valid_*.in
      outcome: VALID
    - glob: unit/validator/invalid_*.in
      outcome: INVALID
  checker:
    - glob: unit/checker/ac*
      outcome: ACCEPTED
    - glob: unit/checker/wa*
      outcome: WRONG_ANSWER
```

The unit tests can be run with the following command:

```bash
rbx unit
```

{{ asciinema("51w76V3tB3zirJkucufFVD4hs") }}

In the next sections, we'll go through what each of these fields mean, and how to define
the actual test inputs.

## Testing validators

Let's say we have a validator that checks if the input contains a connected graph in the format.

```
N M
u_1 v_1
u_2 v_2
...
u_M v_M
```

We'll omit the actual validator code here for simplicity, but you can see an example
at the [Validators](validators.md) section.

We can create positive (valid) and negative (invalid) unit tests for the problem by
defining the following in our `problem.rbx.yml` file:

```yaml title="problem.rbx.yml"
unitTests:
  validator:
    - glob: unit/validator/valid_*.in
      outcome: VALID
    - glob: unit/validator/invalid_*.in
      outcome: INVALID
```

Now, every input file matching the glob `unit/validator/valid_*.in` will be considered a valid input
and every input file matching the glob `unit/validator/invalid_*.in` will be considered an invalid input.

To check the tests are working properly, let's create the following files in the `unit/validator` directory:

=== "valid_CONNECTED.in"
    ```title="unit/validator/valid_CONNECTED.in"
    3 3
    1 2
    2 3
    1 3
    ```

=== "invalid_NOT_CONNECTED.in"
    ```title="unit/validator/invalid_NOT_CONNECTED.in"
    3 1
    1 2
    ```

=== "invalid_VERTEX_OUT_OF_BOUNDS.in"
    ```title="unit/validator/invalid_VERTEX_OUT_OF_BOUNDS.in"
    3 3
    1 2
    2 3
    2 4
    ```

Now, when you run `rbx unit`, you should see all the three tests passing if the validator
is implemented correctly, and we should see failures if the validator does not behave as expected.

{{ asciinema("Q31OAPd4qfzHM5oGcqjeos904") }}

## Testing checkers

Now, let's say we have a checker that checks whether the output of the participant is a path
between two vertices 1 and `N` in a graph with `N` vertices and `M` edges.

Let's say we have a checker that expects a number `K` in the first line, and then `K` numbers
on the second line, which are the vertices on the path.

**The checker code is omitted for simplicity. You can check the complete code in the [Checkers](../grading/checkers.md) section.**

We can create unit tests for this checker by defining the following in our `problem.rbx.yml` file:

```yaml title="problem.rbx.yml"
unitTests:
  checker:
    - glob: unit/checker/ac*
      outcome: ACCEPTED
    - glob: unit/checker/wa*
      outcome: WRONG_ANSWER
```

These will define the general skeleton of our checker unit tests. Remember that checkers
are a bit more complex than validators, and accept three different files as input:

- `<file>.in`: The input file for this testcase.
- `<file>.out`: The output file of the participant for this testcase.
- `<file>.ans`: The answer file (output of the model solution) for this testcase.

The glob pattern `unit/checker/ac*` will match any file that starts with `ac` in its name, and
ends with `.in`, `.out`, or `.ans`. Then, these three files will be passed to the checker for
testing. If some of them are missing, the checker will simply receive an empty file in their place.

Let's say we have the following files in the `unit/checker` directory:

=== "ac_VALID_PATH.in"
    ```title="unit/checker/ac_VALID_PATH.in"
    3 2
    1 2
    2 3
    ```

=== "ac_VALID_PATH.out"
    ```title="unit/checker/ac_VALID_PATH.out"
    3
    1 2 3
    ```

Here, we don't even set a `.ans` file, because the aforementioned checker will simply ignore it
anyways. If you run `rbx unit`, this test should pass, because the checker will indeed return {{tags.accepted}} for this output.

Let's test now that the checker fails when the output is not a valid path on the output.

=== "wa_NON_EXISTING_EDGE.in"
    ```title="unit/checker/wa_NON_EXISTING_EDGE.in"
    3 2
    1 3
    1 2
    ```

=== "wa_NON_EXISTING_EDGE.out"
    ```title="unit/checker/wa_NON_EXISTING_EDGE.out"
    3
    1 2 3
    ```

If you run `rbx unit`, this test should also pass, because the checker will indeed return {{tags.wrong_answer}}
for this output, since the participant's output uses an edge that does not exist in the input.

In problems where the model solution output is consumed by the checker, we can additionally
define the `.ans` file as well, and the checker will consume it.

## Testing extra validators

You can test extra validators in the same way as the main validator by simply specifying the validator that should be testedin the `unitTests` field. By default, the main validator will be tested.

```yaml title="problem.rbx.yml" hl_lines="9 12"
unitTests:
  validator:
    - glob: unit/validator/valid_*.in
      outcome: VALID
    - glob: unit/validator/invalid_*.in
      outcome: INVALID
    - glob: unit/extra-validator/valid_*.in
      outcome: VALID
      validator: extra-validator.cpp
    - glob: unit/extra-validator/invalid_*.in
      outcome: INVALID
      validator: extra-validator.cpp
```

## Using test plans

While defining tests using glob patterns is simple and works well for file-based tests, it can be cumbersome if you have many small unit tests and don't want to create a separate file for each one. For this use case, {{rbx}} supports **test plans**.

A test plan is a single file that contains multiple unit tests defined using a special syntax. You can define test plans in your `problem.rbx.yml` file:

```yaml title="problem.rbx.yml"
unitTests:
  validator:
    - testplan: unit/validator/tests.txt
  checker:
    - testplan: unit/checker/tests.txt
```

### Syntax reference

Test plans use a simple DSL to define tests. You can define tests using the `@test` block or the simplified `@input` syntax.

#### The `@test` block

The `@test` block is the most general way to define a test. It allows you to specify the input, output, and answer for a test case.

```
@test name EXPECTATION {
    @input {
        ... input content ...
    }
    @output {
        ... output content ...
    }
    @answer {
        ... answer content ...
    }
}
```

- `name` (optional): The name of the test case.
- `EXPECTATION`: The expected outcome (e.g., `VALID`, `INVALID` for validators; `ACCEPTED`, `WRONG_ANSWER`, etc. for checkers).

#### Simplified `@input` syntax

For simple tests where you only need to specify the input (common in validator tests), you can use the simplified `@input` syntax:

```
@input name EXPECTATION {
    ... input content ...
}
```

or for one-liners:

```
@input name EXPECTATION "input content"
```

#### When to use what?

- **Use the simplified `@input` syntax** when you only need to provide the input file. This is most common for **validator tests**, where you only care about whether the input is valid or not.
- **Use the `@test` block** when you need to specify more than just the input, such as the `output` (participant's output) or `answer` (model answer), or when you prefer a more structured format for complex multi-line inputs. This is often needed for **checker tests**.

### Examples

=== "Validator test plan"
    ```title="unit/validator/tests.txt"
    // You can use comments starting with // or #

    @input valid_1 VALID {
        3 3
        1 2
        2 3
        3 1
    }

    @input invalid_n_negative INVALID "-1 3"

    @input INVALID {
        3 1
        1 2
    }
    ```

=== "Checker test plan"
    ```title="unit/checker/tests.txt"
    @test valid_path ACCEPTED {
        @input {
            3 2
            1 2
            2 3
        }
        @output {
            3
            1 2 3
        }
    }

    @test wrong_path WRONG_ANSWER {
        @input {
            3 2
            1 2
            2 3
        }
        @output {
            2
            1 2
        }
    }
    ```
