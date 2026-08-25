# Extra compiler flags for `rbx compile`

Design for [#767](https://github.com/rsalesc/rbx/issues/767).

## Problem

`rbx compile` builds an asset with exactly the command `env.rbx.yml` declares for its
language, plus whatever `--sanitized` and `--warnings` inject. There is no way to add a
one-off flag. Two things suffer:

- **Debugging one-offs.** Reproducing a bug under `-DLOCAL -g -O0` or a sanitizer the
  tool does not wire up means editing `env.rbx.yml`, compiling, then reverting it.
- **Trying a flag before adopting it.** Deciding whether the package's C++ command
  should carry a new flag requires the same edit-and-revert dance.

Neither is a scripting or CI need, so the feature stays a convenience on the
interactive path.

## CLI surface

```
rbx compile [PATH] [-s] [-w] [-a] [-- EXTRA...]
```

`compile_command` takes a variadic `extra` argument and sets
`ignore_unknown_options`, so everything after `--` reaches the compiler verbatim --
including tokens that collide with rbx's own options. `rbx compile sol.cpp -- -s`
passes `-s` to the compiler; `rbx compile -s sol.cpp -- -O0` sanitizes *and* adds
`-O0`.

Click fills positional arguments in order and does not tell us where `--` was, so
`rbx compile -- -O0` would bind `-O0` to `PATH`. A leading-dash `PATH` is never a real
path, so it is shifted to the front of `extra` and the command falls through to the
usual interactive prompt.

Under `--all` the flags apply to every asset compiled.

## Where the flags land

A language may compile in several steps. Java is the awkward one:

```yaml
compilation:
  commands:
    - "javac -Xlint -encoding UTF-8 {compilable}"
    - "jar cvf {executable} @glob:*.class"
```

`-DFOO` belongs on `javac`, not on `jar`. The rule, mirroring how sanitizer and
warning flags are already placed:

> Append the flags to every command whose `command_kinds()` intersects the language's
> kinds. If no command matches, append to the first command.

`javac` reports `{JAVA, JVM}` and takes the flags; `jar` reports nothing and is left
alone. C, C++ and Kotlin are single-command and match directly. A language whose
compiler `command_kinds()` does not recognise -- `rustc`, `fpc`, `ghc` -- falls back
to the first command, which is the only command such a language has.

The flags are appended after the sanitizer and warning flags, so the user's flags come
last on the command line and win.

## Interpreted languages

Python declares no `compilation.commands`, so `compile_item` returns the source
unchanged and the flags can do nothing. Silently dropping them is the worst outcome
for a debugging one-off, so rbx warns, names the language, and continues to the
passthrough artifact. It stays a warning rather than an error because `--all` on a
package that mixes Python and C++ solutions is legitimate.

## Precompiled headers

`compile_item` precompiles the headers in `__internal__/`. GCC rejects a PCH built
under different `-D` flags than the translation unit that includes it, so extra flags
would either fail the build or silently skip the PCH. When extra flags are present,
precompilation is disabled. That costs time only on the debugging path.

## Caching

`steps_with_caching.compile` keys its cache on the command list, so a different set of
extra flags is a different cache entry with no extra work.

## Scope

`rbx compile` only. `rbx run`, `rbx build` and the packaging commands are untouched.
