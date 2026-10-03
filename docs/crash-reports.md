# Crash reports

Every once in a while, {{rbx}} will crash on you: not a "your validator rejected this test"
error, but an actual traceback, the kind that means {{rbx}} itself has a bug.

To report it, you need the traceback, the command you ran, and the directory you ran it in.
All of that is in the worst possible place: your terminal scrollback. By the
time you get around to looking into it, you've scrolled past it or closed the window, and you only
remember that something broke during `rbx build`.

So {{rbx}} writes it down. After a crash, you'll see a line like this:

```
Crash report written to /Users/you/Library/Application Support/rbx/crashes/20260905T094952Z-86725.md
```

That file has everything the terminal showed, and it stays on disk after you close the window.

## What's in it

The report is a Markdown file that opens with a block of context and then shows the full
traceback:

```markdown
---
rbx_version: "1.4.2"
timestamp: "2026-09-05T09:49:52.248804+00:00"
command: "/Users/you/.local/bin/rbx build"
cwd: "/Users/you/contest/problem-a"
package: "/Users/you/contest/problem-a"
exception: "RuntimeError"
message: "synthetic crash"
python: "3.14.3"
platform: "darwin"
pid: 86725
argv: ["/Users/you/.local/bin/rbx", "build"]
---

# rbx crash

`/Users/you/.local/bin/rbx build` in `/Users/you/contest/problem-a`

## Traceback

...
```

The fields you'll want most are `command`, the exact invocation (quoted so you can paste it
straight back into a shell), and `cwd`, the directory it ran in. You'd otherwise have to
remember both, and anyone looking at the crash will ask you for them first.

The block at the top is valid YAML, so a script can parse the report too.

## Where to find it

Reports are saved in the `crashes` folder of your {{rbx}} app directory: `~/Library/Application
Support/rbx` on macOS, `~/.config/rbx` on Linux. Only the newest 20 are kept: {{rbx}} deletes
older reports, so the folder doesn't grow without bound. A `latest.md` symlink beside them always
points at the most recent one:

```
<app dir>/crashes/
├── 20260905T094952Z-86725.md
├── 20260904T171203Z-47110.md
└── latest.md -> 20260905T094952Z-86725.md
```

If the crash happened inside a problem or contest package that already has a `.rbx` cache
folder, you'll also find a `last-crash.md` symlink in that folder, pointing at the same report. It's a
shortcut to the crash that belongs to the package you're working on. Because it's in the cache
folder, the shortcut disappears whenever the cache is cleared, and since that folder is gitignored,
it never ends up in a commit.

!!! note
    Only real crashes are reported. Interrupting {{rbx}} with ++ctrl+c++, and the ordinary errors
    {{rbx}} raises to tell you that something in your package is wrong, are not bugs, and they
    don't produce a report.

## Reporting a crash

Attach the report to an issue on our {{repo}}. It already has everything we'll ask you for
first.
