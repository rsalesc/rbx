<!--
  The MOJ backend contract, shared by every command that can reach the judge:
  `rbx run --runner moj` (setters/running/remote.md) and `rbx time --runner moj`
  (setters/profiling/remote.md).

  It lives here because both pages need all of it and neither owns it. What
  genuinely differs between the two commands -- which throwaway problem each
  uploads to, and how many uploads a run costs -- stays in the page that owns
  the command, not in this file.
-->

You must be logged in to the [`moj` CLI](https://github.com/cd-moj/moj-cli) — {{rbx}} reuses
its session and never handles your credentials.

{{rbx}} uploads a **throwaway problem** of its own, derived from the id recorded in a committed
`.moj-id`, so two setters on the same package reach the same one. It never touches a problem it
did not create: a package already bound to a real MOJ problem is refused by name rather than
overwritten.

A judge reports **less** than the local sandbox does. It hands back a verdict, not the bytes
your solution wrote, so some of what a local run shows you has no counterpart at all:

- **No memory usage**, no `.out`/`.err` artifacts, and a verdict code rather than the checker's
  own message.
- `--runs` greater than one, a sanitizer, and interactive (`communication`) problems are
  **refused by name** before anything is uploaded — each would produce a report answering a
  different question than the one you asked.

{{rbx}} refuses whatever it cannot answer honestly on a given backend, rather than quietly
reporting less than you asked for.
