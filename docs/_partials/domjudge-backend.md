<!--
  The DOMjudge backend contract, shared by every command that can reach the
  judge: `rbx run --runner domjudge` (setters/running/remote.md) and
  `rbx time --runner domjudge` (setters/profiling/remote.md).

  Mirrors _partials/moj-backend.md, and for the same reason: both pages need all
  of it and neither owns it. What genuinely differs between the two commands --
  which throwaway problem each uploads to -- stays in the page that owns the
  command.
-->

{{rbx}} talks to DOMjudge's REST API directly, so there is no CLI to install. Point it at the
instance with three environment variables:

```bash
export RBX_DOMJUDGE_SERVER=https://judge.example.edu/
export RBX_DOMJUDGE_USERNAME=your-admin-user
export RBX_DOMJUDGE_PASSWORD=...
```

They are environment variables rather than package settings on purpose: which DOMjudge you can
reach is a property of your machine, and committing one setter's server would break the package
for everyone else.

The account needs **admin** rights. {{rbx}} creates a private `rbx-timing` contest the first
time it runs, uploads a throwaway `rbxt-…` problem into it, and submits as the built-in
`domjudge` team — none of which a plain jury account may do. The problem is named from the slug
in `.rbx-id` at the package root — the one identity your package has on any remote judge, shared
with the MOJ backend — so it stays the same problem as
your testset grows, rather than leaving a trail of abandoned ones behind. The contest has no scoreboard
anyone reads, and nothing {{rbx}} does there touches a real contest.

Before uploading anything, {{rbx}} checks the instance and **refuses by name** what cannot
work, rather than leaving you watching a run that will never finish:

- **`verification_required` turned on.** It hides every judgement and run until a human
  verifies it, so a timing run would poll an empty list until it gave up.
- **No enabled judgehost**, or one that is enabled but has not asked for work recently. Either
  way submissions would be stored and never judged — but the fix differs, so the two are
  reported differently.

A judge reports **less** than the local sandbox does. It hands back a verdict, not the bytes
your solution wrote:

- **No memory usage**, no `.out`/`.err` artifacts, and a verdict rather than the checker's own
  message. DOMjudge has no memory-limit verdict at all, so a solution that runs out of memory
  comes back as a runtime error.
- **Times are CPU time**, not wall clock. A solution killed for exceeding the limit reports the
  CPU it actually burned, which for a sleeping or I/O-bound solution is close to zero. The
  verdict is what says it was too slow.
- `--runs` greater than one and sanitizers are **refused by name** before anything is
  uploaded — each would produce a report answering a different question than the one you asked.

Interactive (`communication`) problems **do** work. DOMjudge runs the interactor rbx ships as
the problem's run script, so the verdict comes from the same program that judges locally — and
a legacy interactor paired with a checker is chained so that both still run.

Solutions are submitted one at a time. A judgehost judges one submission at a time anyway, and
two in flight on a multi-judgehost instance would land on different machines — whose timings are
not comparable, which is the whole point of measuring remotely.
