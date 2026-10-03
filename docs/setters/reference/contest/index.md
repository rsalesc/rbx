# Contest package

This documentation goes over how each field (or group of fields) in `contest.rbx.yml` works.

## Contest definition

**Schema**: [rbx.box.contest.schema.Contest][]

The only required field of a contest is its `name`.

A barebones package would look something like:

```yaml
name: "my-contest"
```

## Contest problems

**Field**: `problems`
**Schema**: `List[`[`ContestProblem`][rbx.box.contest.schema.ContestProblem]`]`

```yaml
name: "my-contest"
problems:
  - short_name: "A"
    path: "A"
    color: "#ff0000"     # a `#rrggbb`/`#rgb` hex or an X11 color name
    aliases: ["apple"]   # optional; `rbx on apple run` now selects A
  - short_name: "B"
    path: "B"
    color: "#00ff00"
```

## Selecting problems

Commands that act on part of a contest, such as `rbx on`, take a **problem
selector**: a comma-separated list of entries, each matching one or more problems.

An entry can match a problem in four ways, tried in this order:

1. its `short_name` (`A`);
2. the `name` it declares in its own `problem.rbx.yml` (`knapsack`);
3. one of its `aliases` (`apple`);
4. the basename of its folder (`day1/knapsack` matches `knapsack`).

The order matters when two problems disagree. If `B` is one problem's letter and
another problem's alias, `rbx on B run` runs the first one, because letters are tried
before aliases.

Matching is case-insensitive, so `rbx on apple` and `rbx on APPLE` are the same
command.

Besides plain entries, a selector supports ranges, wildcards and exclusions:

| Selector | Selects |
| :--- | :--- |
| `A,C` | problems `A` and `C` |
| `A..C` | every problem from `A` to `C`, in the order they appear in `contest.rbx.yml` |
| `day1-*` | every problem matching the pattern (`*` and `?` are wildcards) |
| `*` | every problem in the contest |
| `*,!C` | every problem but `C` |
| `!C` | the same -- a selector made only of exclusions starts from every problem |

A range is written with **two dots**. A single dash is a regular character, since a
problem may be named `two-sum`.

Your shell may expand `*` and `!` before {{rbx}} sees them, so quote
any selector that uses them:

```bash
rbx on '*,!C' run
```

Finally, an entry that matches no problem is an error. One bad entry stops the whole
command: a typo never runs it on just the other problems.