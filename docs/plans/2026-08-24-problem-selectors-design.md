# `rbx on` problem selectors — design

Issue: [#718](https://github.com/rsalesc/rbx/issues/718).

`rbx on <PROBLEMS>` used to accept a wildcard, a `A-C` range over short names, and a
comma-separated list matched against short names and aliases. This design extends the
selector to problem names and folder basenames, gives the identifier kinds a priority
order, and makes a mistyped selector fail loudly.

## Grammar

```
selector := token (',' token)*
token    := ['!'] atom
atom     := '*' | range | pattern
range    := <short-name> '..' <short-name>
```

- `*` selects every problem in the contest.
- `A..C` is an inclusive range. Both endpoints are resolved as short names, and the
  result is the contiguous slice of `contest.problems` **by position in the file** —
  not by string comparison, so `A1..A3` and non-alphabetical orderings behave. An
  unknown endpoint, or a start that comes after the end, is an error.
- `-` is never a range separator. `two-sum` and `prob-a` are ordinary tokens. When a
  token `X-Y` matches nothing and both halves name a problem, the error suggests the
  range form `X..Y`.
- `!token` excludes. Exclusions apply after the union of the includes, and a selector
  made only of exclusions implies `*` as its base: `rbx on '!C'` means "all but C".

Both `*` and `!` are shell metacharacters, so selectors that use them need quoting.

## Priority ladder

Each token resolves independently through four tiers, stopping at the first tier that
matches anything:

1. `short_name`
2. `name`, from that problem's `problem.rbx.yml`
3. `aliases`
4. basename of the problem's folder

Matching is case-insensitive. A token containing `*` or `?` is `fnmatch`ed at every
tier, in the same order, so `day1-*` falls through tiers 1–3 and lands on folder
basenames.

Resolution is per token and stops at the first non-empty tier. A token that is B's
short name therefore never also drags in C merely because C carries the alias `B`.

Tier 2 needs each problem's declared name, which lives in its own package file. The
selector reads it through the tolerant `peek` helper (`rbx/box/completion/peek.py`)
rather than a full pydantic load, and only when tier 1 has already missed. A malformed
problem package degrades to "no name" instead of crashing the selector.

## Errors

Every token that resolves to nothing is an error. The message names the offending
token, lists the available short names, and adds the range hint when the token looks
like an attempted `X-Y` range. Exclusion tokens are held to the same rule, so `!Z`
catches the typo instead of silently excluding nothing.

## Code shape

The resolver lives in `rbx/box/contest/problem_selector.py` as pure functions over a
list of `ContestProblem` plus a name lookup, so its tests need no filesystem.
`contest_utils.get_problems_of_interest` supplies the lookup and delegates.
`match_problem` — a per-problem boolean — is gone: priority is a property of the whole
selector, not of one problem in isolation.

`complete_problem` in `rbx/box/completion/completers.py` offers names and folder
basenames alongside short names and aliases.
