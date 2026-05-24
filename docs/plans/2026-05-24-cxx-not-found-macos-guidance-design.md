# C/C++ compiler-not-found guidance on macOS — Design

Closes #408.

## Problem

When the C/C++ compiler isn't found, `rbx` prints a generic message:

```
FAILED The compiler/interpreter 'g++' was not found while running [...]
Is it installed and on your PATH?
```

(added in #451, which closed #374). Issue #408 asks for more: when the missing
executable is a C/C++ compiler — and especially on macOS — point the user at the
known fix. macOS doesn't bundle GNU GCC, and the common setup is to install it via
Homebrew and configure `command_substitutions` (e.g. `g++ -> g++-14`). If that
version isn't installed, the compile fails with the generic message and no hint.

There is already a docs page describing the whole fix: `docs/cpp-on-macos.md`,
served at <https://rbx.rsalesc.dev/cpp-on-macos/>.

## Design

In the compile path's existing `ProgramNotFoundError` catch block
(`rbx/grading/steps.py`), after the generic lines, add a conditional branch:

```python
if is_cxx_command(e.executable) and sys.platform == 'darwin':
    # print macOS C/C++ guidance + link to the cpp-on-macos doc
```

- `is_cxx_command()` (same module) already detects the C/C++ family
  (`gcc`/`g++`/`clang`/`clang++`).
- Gated on `sys.platform == 'darwin'`: the doc is macOS-specific, so Linux/Windows
  users keep the existing generic message.
- C/C++ "not found" only surfaces at compile time (the run command is the compiled
  binary, not the compiler), so this single site is sufficient.

### Message (macOS + cxx)

```
On macOS the GNU compiler isn't bundled — install it with 'brew install gcc',
then point rbx at the exact version via 'rbx config edit' (command_substitutions).
See https://rbx.rsalesc.dev/cpp-on-macos/ for the full guide.
```

## Scope (YAGNI)

- Compile path only; no change to `ProgramNotFoundError` (keeps the low-level
  grading layer ignorant of cxx/docs concerns).
- No new config and no docs changes — the doc already exists.

## Testing

`tests/rbx/grading/steps_compile_test.py`:

1. cxx executable + `sys.platform` patched to `'darwin'` → message contains the doc
   URL and brew guidance.
2. cxx executable on non-darwin → generic message only, no doc URL.
3. non-cxx executable on darwin → no C/C++ guidance, no doc URL.
