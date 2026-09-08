<!--
  The MOJ backend contract, shared by every command that can reach the judge:
  `rbx run --runner moj` (setters/running/remote.md) and `rbx time --runner moj`
  (setters/profiling/remote.md).

  It lives here because both pages need all of it and neither owns it. What
  genuinely differs between the two commands -- which throwaway problem each
  uploads to, and how many uploads a run costs -- stays in the page that owns
  the command, not in this file.

  Pulled in by mkdocs-macros' own include (via its `include_dir`) rather than
  by pymdownx.snippets: snippets inline the file during Markdown rendering,
  long after macros have run, so the project macros used below would reach the
  page as literal text.
-->

You must be logged in to the [`moj` CLI](https://github.com/cd-moj/moj-cli) — {{rbx}} reuses
its session and never handles your credentials. On macOS the CLI also needs a bash newer than
the one the system ships; if it refuses to start, see
[The MOJ CLI needs bash 4 or newer](/setters/packaging/moj#the-moj-cli-needs-bash-4-or-newer).

{{rbx}} uploads a **throwaway problem** of its own, named `<your login>#rbxt-<slug>` from the
slug in `.rbx-id` at the package root — the one identity your package has on any remote judge,
shared with the DOMjudge backend. The slug is
minted once and then kept, so every later run reuses the same problem instead of orphaning one;
commit `.rbx-id` if you want a co-setter to reach that problem too. The id is also written to
`.moj-id`, which is what the `moj` CLI itself reads.

It never touches a problem it did not create: a package already bound to a real MOJ problem is
refused by name rather than overwritten.

A judge reports **less** than the local sandbox does. It hands back a verdict, not the bytes
your solution wrote, so some of what a local run shows you has no counterpart at all:

- **No memory usage**, no `.out`/`.err` artifacts, and a verdict code rather than the checker's
  own message.
- `--runs` greater than one, a sanitizer, and interactive (`communication`) problems are
  **refused by name** before anything is uploaded — each would produce a report answering a
  different question than the one you asked.

{{rbx}} refuses whatever it cannot answer honestly on a given backend, rather than quietly
reporting less than you asked for.
