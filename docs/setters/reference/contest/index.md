# Contest package

This documentation goes over how each field (or group of fields) in `contest.rbx.yml` works.

## Contest definition

**Schema**: [rbx.box.contest.schema.Contest][]

The only required field of a contest is its `name`.

A barebones package would look something like:

```yaml
name: "my-problem"
```
## Contest problem

**Schema**: `List[`[`ContestProblem`][rbx.box.contest.schema.ContestProblem]`]`

```yaml
name: "my-contest"
problems:
  - short_name: "A"
    path: "A"
    color: "ff0000"
    aliases: ["apple"]   # Optional; refer to this problem as "A" or "apple" in e.g. rbx on <name> run
  - short_name: "B"
    path: "B"
    color: "00ff00"
```

## Selecting problems

Commands that act on part of a contest -- `rbx on` above all -- take a **problem
selector**: a comma-separated list of entries, each naming one or more problems.

An entry can name a problem in four ways, and they're tried in this order:

1. its `short_name` (`A`);
2. the `name` it declares in its own `problem.rbx.yml` (`knapsack`);
3. one of its `aliases` (`apple`);
4. the basename of the folder it lives in (`day1/knapsack` matches `knapsack`).

The order matters when two problems disagree. If `B` is one problem's letter and
another problem's alias, `rbx on B run` runs the first one -- the letter wins, and
the alias is never even looked at.

Matching is case-insensitive, so `rbx on apple` and `rbx on APPLE` are the same
command.

On top of a plain entry, a selector understands ranges, wildcards and exclusions:

| Selector | Selects |
| :--- | :--- |
| `A,C` | problems `A` and `C` |
| `A..C` | every problem from `A` to `C`, in the order they appear in `contest.rbx.yml` |
| `day1-*` | every problem matching the pattern (`*` and `?` are wildcards) |
| `*` | every problem in the contest |
| `*,!C` | every problem but `C` |
| `!C` | the same -- a selector made only of exclusions starts from every problem |

Note that a range is written with **two dots**. A single dash is just a character
like any other, since a problem may well be named `two-sum`.

Your shell will happily expand `*` and `!` before {{rbx}} ever sees them, so quote
any selector that uses them:

```bash
rbx on '*,!C' run
```

Finally, an entry that matches no problem is an error, and the whole command stops
there. A typo in one letter of a list never quietly runs on the rest.