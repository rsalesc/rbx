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