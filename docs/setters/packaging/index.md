# Packaging

{{rbx}} supports exporting problem/contest packages into a few formats. You can see
in the table below which formats are supported, and what are its supported features
and limitations:

+-----------------------+---------------------+-----------------------------------------------------------+
|        Format         |   Target Systems    |                         Supports                          |
+=======================+=====================+===========================================================+
| ICPC                  | DOMjudge, Kattis    |                                                           |
| (coming soon)         |                     | :white_check_mark: Interactive problems (without checker) |
|                       |                     | :white_check_mark: Batch problems                         |
|                       |                     | :white_check_mark: Test grouping                          |
|                       |                     | :white_check_mark: Limits per language                    |
|                       |                     | :white_check_mark: Solution verification                  |
|                       |                     | :white_check_mark: Package upload                         |
+-----------------------+---------------------+-----------------------------------------------------------+
| [BOCA](boca.md)       | BOCA                |                                                           |
|                       |                     | :white_check_mark: Interactive problems (with checker)    |
|                       |                     | :white_check_mark: Batch problems                         |
|                       |                     | :white_check_mark: Limits per language                    |
|                       |                     | :white_check_mark: Package upload                         |
|                       |                     | :x: Test grouping                                         |
|                       |                     | :x: Solution verification                                 |
+-----------------------+---------------------+-----------------------------------------------------------+
| [MOJ](moj.md)         | MOJ                 |                                                           |
|                       |                     | :white_check_mark: Batch problems                         |
|                       |                     | :white_check_mark: Test grouping                          |
|                       |                     | :white_check_mark: Limits per language                    |
|                       |                     | :white_check_mark: Solution verification                  |
|                       |                     | :white_check_mark: Package upload                         |
|                       |                     | :x: Interactive problems                                  |
+-----------------------+---------------------+-----------------------------------------------------------+
| [Polygon](polygon.md) | Codeforces, Polygon |                                                           |
|                       |                     | :white_check_mark: Interactive problems (with checker)    |
|                       |                     | :white_check_mark: Batch problems                         |
|                       |                     | :white_check_mark: Limits per language                    |
|                       |                     | :warning: Package upload (with limitations)               |
|                       |                     | :x: Solution verification                                 |
|                       |                     | :x: Test grouping                                         |
+-----------------------+---------------------+-----------------------------------------------------------+

## `rbx package`

{{rbx}} provides an umbrella `rbx package <format>` command group that contains commands for each
of the formats supported by it.

All these formats support a `-v` flag, that sets the verification level for building the package.

By default, packages will be built with the `-v` flag set to `4` (the maximum value), which means that tests will be
built, validated and all solutions will be run against them, and their expected outcomes will be verified.

You can change this by setting the `-v` flag to a different value, with the following meanings:

- `0`: Tests will be built, no validation will be done.
- `1`: Tests will be built and validated.
- `2`: Tests will be built, validated and accepted solutions will be run against them, and their expected outcomes will be verified.
- `3`: Tests will be built, validated and non-TLE solutions will be run against them, and their expected outcomes will be verified.
- `4`: Tests will be built, validated and all solutions will be run against them, and their expected outcomes will be verified.

The example below shows how to build an ICPC package by only generating tests and validating them.

```bash
rbx package icpc -v1
```

The flag changes how much work happens before the package is written, not what the package
contains. Below, the same problem is packaged twice for [BOCA](boca.md) — first with `-v1`,
which stops once the tests are built and validated, and then with the default `-v4`, which
also runs every declared solution and checks it against its expected outcome:

{{ asciinema("package-verification") }}

Both produce the same `.zip`. The second one just refuses to produce it if a solution
disagrees with the outcome you declared for it.

See each one of the sections dedicated to each of the avilable formats on the sidebar.
