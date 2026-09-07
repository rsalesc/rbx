# Crash reports

Every once in a while, {{rbx}} will crash on you: not a "your validator rejected this test"
error, but an actual traceback, the kind that means {{rbx}} itself has a bug.

When that happens, the useful part is always the same -- the traceback, the command you ran, and
the directory you ran it in -- and it's always in the worst possible place: your terminal
scrollback. By the time you get around to looking into it, you've scrolled past it, or closed the
window, and all you remember is that "something broke during `rbx build`".

So {{rbx}} writes it down. After a crash, you'll see a line like this:

```
Crash report written to /Users/you/Library/Application Support/rbx/crashes/20260905T094952Z-86725.md
```

That file has everything the terminal had, and it isn't going anywhere.

## What's in it

The report is a Markdown file that opens with a block of context and then shows the full
traceback:

```markdown
---
rbx_version: "1.4.2"
timestamp: "2026-09-05T09:49:52.248804+00:00"
command: "rbx build"
cwd: "/Users/you/contest/problem-a"
package: "/Users/you/contest/problem-a"
exception: "RuntimeError"
message: "synthetic crash"
python: "3.14.3"
platform: "darwin"
pid: 86725
argv: ["rbx", "build"]
---

# rbx crash

`rbx build` in `/Users/you/contest/problem-a`

## Traceback

...
```

The two fields worth knowing about are `command` -- the exact invocation, quoted so you can paste
it straight back into a shell -- and `cwd`, the directory it ran in. Those are the two things
you'd otherwise have to remember, and the two things anyone looking at the crash will ask you for
first.

The block at the top is valid YAML, so the whole file is as easy to read for a program as it is
for you.

## Where to find it

Reports live in the `crashes` folder of your {{rbx}} app directory: `~/Library/Application
Support/rbx` on MacOS, `~/.config/rbx` on Linux. Only the newest 20 are kept, since old crashes
stop being interesting once the bug behind them is fixed, and {{rbx}} would rather clean up after
itself than have you do it. A `latest.md` symlink beside them always points at the most recent
one:

```
<app dir>/crashes/
├── 20260905T094952Z-86725.md
├── 20260904T171203Z-47110.md
└── latest.md -> 20260905T094952Z-86725.md
```

If the crash happened inside a problem or contest package, you'll also find a `last-crash.md`
symlink inside that package's `.rbx` cache folder, pointing at the same report. It's just a
shortcut for finding the crash that belongs to the package you're working on. It's a cache
folder, so the shortcut disappears whenever the cache is cleared, and it's gitignored -- it will
never end up in a commit.

!!! note
    Only real crashes are reported. Interrupting {{rbx}} with ++ctrl+c++, and the ordinary errors
    {{rbx}} raises to tell you that something in your package is wrong, are not bugs, and they
    don't produce a report.
