# Verification

{{rbx}} provides a range of solutions to improve the quality and correctness of your testset and
the {{testlib}} assets you use. You can see a quick summary of the features in the table below,
and then read more about each one in the following sections.

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

{{rbx}} also has the concept of a verification level. This is a way to specify how strict the verification
should be when building your testset and running solutions.

The verification level will usually be specified along your {{rbx}} command.

```bash
rbx build -v{0,1}  # defaults to 1
rbx run -v{0,1,2,3,4}  # defaults to 4
rbx package -v{0,1,2,3,4}  # defaults to 4
```

{{ asciinema("141SSzM2QsLqznBknzMdojOHj") }}

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

Setting a larger value is usually the recommended approach to ensure all your expectations are being met.

Setting a smaller value is usually useful when you want to run the commands faster, and you are sure that
the checks you are running are not being violated.