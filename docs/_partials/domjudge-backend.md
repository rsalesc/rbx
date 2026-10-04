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
`domjudge` team. A plain jury account can't do any of these.

Before uploading, {{rbx}} checks the instance and stops with an error if:

- `verification_required` is on, since it hides every judgement until a human verifies it.
- No judgehost is enabled, or none has asked for work recently.

Solutions are submitted one at a time. A judgehost judges one submission at a time anyway, and
two in flight on a multi-judgehost instance could be judged on different machines, whose timings
aren't comparable.
