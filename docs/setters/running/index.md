# Running

{{rbx}} provides a range of options to run your solutions. In the sections below,
we'll go through each of them.

## Running solutions on the whole testset

You can use the `rbx run` command to run your solutions on the whole testset.

The command will run all selected solutions (or all declared solutions if none are selected) on all testcases,
providing for each of them the solution outcome, and for the whole testset the timing and memory usage.

{{ asciinema("x8NJUtmob4uSHUUFppxUn64Kn") }}

Below are some examples of how to use the command.

```bash
# Run all solutions on all testcases
rbx run

# Run a single solution (or a list of solutions) on all testcases
rbx run <solution-name> ...

# Run all AC solutions on all testcases
rbx run --outcome AC

# Run all WA solutions on all testcases
rbx run --outcome WA

# Run all solutions, and provide a table-like output instead
# of the default output
rbx run -d

# Interactively pick which solutions to run
rbx run -c
```

One can also set the verification level to be used when running the solutions.

```bash
rbx run -v{0,1,2,3,4}
```

You can read more about each verification level [here](/setters/verification/#verification-level).

By default, {{rbx}} will run solutions with the maximum verification level. This means tests will be built
and verified, and that all solutions will be run with twice the time limit, and a warning will show up if a TLE solution passed in `2*TL`.

The results of a `rbx run` command can be inspected through the `rbx ui` command, as shown in the
animation below.

{{ asciinema("6XYQ11Cv1HZ8TuTiCFXBXXM29") }}

## Running tests with custom inputs

You might want to run your solutions on a testcase that is not part of the testset, or even on a specific
testcase of the testset.

You can do this with the `rbx irun` command. The command will select which solutions to run similar to `rbx run`.
This means you can specify with the following flags:

```bash
# Run a single solution (or a list of solutions) on a specific testcase
rbx irun <solution-name> ...

# Run all AC solutions on a specific testcase
rbx irun --outcome AC

# Interactively pick which solutions to run
rbx irun -c
```

By default, `rbx irun` will prompt you to type a testcase input. After you've finished typing it, you can press
`Ctrl+D` to tell {{rbx}} that you're done.

{{rbx}} will then run the solutions on the testcase you've provided, and print the results into files. You can
also use the `-p` flag to instruct it to print the results into the console instead.

{{ asciinema("OW9JfUpTzwQlvwcXmR3xSnS3q") }}

!!! tip
    By default, the test you've written will be validated, so make sure you've typed it perfectly.

    If you want to disable validation, you can pass the `-v0` flag to set the verification level to 0.

You can also specify a certain testcase of the testset to run using the `-t` flag followed by the *testcase notation*, which
is composed of `<testgroup-name>/<testcase-index>`. For instance, `samples/0` is the first testcase in the `sample` testgroup,
and `secret/10` is the 11th testcase in the `secret` testgroup.

```bash
rbx irun -t sample/0
```

{{ asciinema("1QYrKEMUKGgtFLTEEtrKTFIgn") }}

Last but not least, you can also specify a [generator call](/setters/testset/generators/#generator-call) to be used when generating the testcase.

```bash
rbx irun -g "gen 100 123" -p
```

{{ asciinema("F6BfQ4GKr9FvCTmVD8zuOKJ8r") }}