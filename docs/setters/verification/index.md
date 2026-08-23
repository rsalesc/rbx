# Verification

{{rbx}} offers several ways to check your testset and the {{testlib}} assets you use. The table
below summarizes them, and the sections that follow cover each one.

+-------------------------------------------+---------------------------------------------------------------+
|                  Feature                  |                          Description                          |
+===========================================+===============================================================+
| [Validators](validators.md)               | Check whether your test inputs are conforming the to the      |
|                                           | format you expect.                                            |
+-------------------------------------------+---------------------------------------------------------------+
| [Unit tests](unit-tests.md)               | Check whether your checker and/or validator are behaving      |
|                                           | as expected against manually defined inputs.                  |
+-------------------------------------------+---------------------------------------------------------------+
| [Stress testing](/setters/stress-testing) | Check whether your validators, checkers and correct solutions |
|                                           | are behaving as expected against randomly generated inputs.   |
+-------------------------------------------+---------------------------------------------------------------+

## Verification Level

A verification level says how strict verification should be when building your testset and
running solutions. You usually specify it on the command itself.

```bash
rbx build -v{0,1}  # defaults to 1
rbx run -v{0,1,2,3,4}  # defaults to 4
rbx package -v{0,1,2,3,4}  # defaults to 4
```

{{ asciinema("verification-levels") }}

The verification level is a non-negative incremental enum, which means that the level
`N+1` will include all the checks of level `N`, plus what is specified in
the table below:

|         Level          |                              Description                              |
| ---------------------- | --------------------------------------------------------------------- |
| `0` / `NONE`           | No verification.                                                      |
| `1` / `VALIDATE`       | Run validators on the generated testset.                              |
| `2` / `FAST_SOLUTIONS` | Run all non-TLE solutions.                                            |
| `3` / `ALL_SOLUTIONS`  | Run all solutions, including TLE.                                     |
| `4` / `FULL`           | Run solutions with twice the TL to check if TLE solutions still pass. |

Prefer a larger value: it confirms more of your expectations. Drop to a smaller one to run
faster, when you already know the skipped checks hold.

## Exit codes

Verification is only useful in a pipeline if a failed check fails the pipeline. The commands
below exit with status `1` when a check they ran did not pass, and `0` otherwise:

| Command                      | Exits `1` when                                                           |
| ---------------------------- | ------------------------------------------------------------------------ |
| `rbx build`                  | A validator rejects a generated test.                                     |
| `rbx run`                    | The build fails, or a solution's verdict does not match its expected one. |
| `rbx time`                   | The build fails.                                                          |
| `rbx package build`          | The build or the verification of the testset fails.                       |
| `rbx contest statements build` | Samples could not be built for some problem.                            |

`rbx contest statements build` still builds every statement it can before failing, so the
report tells you which problems are broken rather than stopping at the first one.

!!! warning "Behavior change"

    Up to and including `1.0.0`, `rbx build` and `rbx run` exited `0` even when they printed a
    failing report. A CI job that is silently green today on a broken package will start failing
    once you upgrade. That is the point, but it may surprise you.

    Use a lower [verification level](#verification-level) (or `--no-validate`) if you deliberately
    want a step that does not check the testset.