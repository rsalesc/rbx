# Crash reports

Every once in a while, {{rbx}} will crash on you: not a report error,
but an actual traceback, the kind that means {{rbx}} itself has a bug.

When that happens, the traceback, the command you ran, and
the directory you ran it in are useful pieces to debug, but are always in the worst possible place: your terminal
scrollback. By the time you get around to looking into it, you've scrolled past it, or closed the
window, and all you remember is that "something broke during `rbx build`".

So {{rbx}} writes it down. After a crash, you'll see a line like this:

```
Crash report written to /Users/you/Library/Application Support/rbx/crashes/20260905T094952Z-86725.md
```

That file has everything the terminal had.

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
## Where to find it

Reports live in the `crashes` folder of your {{rbx}} app directory: `~/Library/Application
Support/rbx` on MacOS, `~/.config/rbx` on Linux. Only the newest 20 are kept, since old crashes
stop being interesting once the bug behind them is fixed. A `latest.md` symlink beside them always
points at the most recent one:

```
<app dir>/crashes/
├── 20260905T094952Z-86725.md
├── 20260904T171203Z-47110.md
└── latest.md -> 20260905T094952Z-86725.md
```

If the crash happened inside a problem or contest package, you'll also find a `last-crash.md`
symlink inside that package's `.rbx` cache folder, pointing at the same report. It's just a
shortcut for finding the crash that belongs to the package you're working on. It's a cache
folder, so the shortcut disappears whenever the cache is cleared.

!!! note
    Only real crashes are reported. Interrupting {{rbx}} with ++ctrl+c++, and the ordinary errors
    {{rbx}} raises to tell you that something in your package is wrong, are not bugs, and they
    don't produce a report.
