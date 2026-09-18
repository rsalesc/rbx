# Per-language BOCA compilation flags

## Problem

BOCA compilation flags live at the environment level, in `extensions.boca.flags`, as a
dict keyed by BOCA language id (`c`, `cc`, `cpp`). Every other per-language BOCA
setting (`languages`, `template`) already lives under each rbx language's
`extensions.boca`, and MOJ keeps its `flags` there too. The env-level dict is the odd
one out and forces the setter to know BOCA's ids instead of their own language names.

## Design

- `BocaLanguageExtension` gains `flags: Optional[str]`, mirroring `MojLanguageExtension`.
- The built-in defaults move out of `BocaExtension.flags_with_defaults()` into a
  `DEFAULT_FLAGS` dict in the BOCA packager, keyed by **template** (`c`, `cc`, `cpp`),
  like MOJ's.
- A new `get_boca_flags(boca_language)` helper in `boca_language_utils.py` resolves,
  in order:
  1. the `flags` of the rbx language that emits `boca_language`;
  2. the legacy env-level `extensions.boca.flags[boca_language]`;
  3. `DEFAULT_FLAGS[template]`, or `''` when the template has none.
- `_replace_common` uses the helper for every emitted language. `checker.sh` and
  `interactor_compile.sh` keep asking for `cc`, so they follow the C++ language's flags.
- The env-level `extensions.boca.flags` stays accepted as a silent fallback: no
  warning, no removal, just undocumented.
- The default preset moves its flags onto the `c` and `cpp` languages.

## Out of scope

`extensions.boca.usePypy` has the same shape problem but stays where it is.
