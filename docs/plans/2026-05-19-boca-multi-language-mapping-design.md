# BOCA multi-language mapping (cc/cpp aliasing)

Design doc for issue #453: BOCA changed the default C++20 language code from `cc` to
`cpp`. The rbx default preset still emits `cc`, which works on older BOCA installs but
breaks on newer ones. We need a way for a single rbx language to target multiple BOCA
languages so a single package works on both, and we want to retire two legacy schema
fields along the way.

## Goals

- A single rbx language can target multiple BOCA languages (forward `cc`+`cpp` from rbx
  `cpp`), with one canonical primary.
- The default preset produces a BOCA package that works on both old and new BOCA out of
  the box.
- New mapping is the forward-looking shape; legacy fields (`bocaLanguage`,
  `BocaExtension.languages`, `template` fallback) keep working for back-compat but
  are scheduled for removal in a follow-up issue.

## Non-goals

- Removing the legacy fields in this change (tracked in a separate issue).
- Changing BOCA server-side behavior or any non-BOCA packager.

## Mechanics today (recap)

- `rbx/box/packaging/boca/extension.py` defines `BocaLanguageExtension.bocaLanguage:
  Optional[str]` and `BocaExtension.languages: List[BocaLanguage]` (defaults to every
  literal in the `BocaLanguage` union).
- `boca_language_utils.get_boca_language_from_rbx_language` reads
  `bocaLanguage`; `get_rbx_language_from_boca_language` reverse-maps by equality.
- `packager.py` iterates `BocaExtension.languages` and, for each entry `L`, sources the
  per-language scripts from `rbx/resources/packagers/boca/{compile,run,interactive}/L`.
  `limits`, `compare`, `tests` are generated or shared and not per-template.
- The default preset maps rbx `cpp` → BOCA `cc` and lists
  `languages: ["c", "cc", "java", "py3", "kt"]`.

## Design

### Schema: `languages` and `template`

`BocaLanguageExtension` (`rbx/box/packaging/boca/extension.py`) becomes:

```python
class BocaLanguageExtension(BaseModel):
    bocaLanguage: Optional[str] = Field(
        default=None,
        deprecated='Use `languages` instead.',
    )
    languages: Optional[List[str]] = None
    template: Optional[str] = None

    @property
    def resolved_languages(self) -> List[str]:
        if self.languages:
            return self.languages
        if self.bocaLanguage:
            return [self.bocaLanguage]
        return []

    @property
    def primary_language(self) -> Optional[str]:
        langs = self.resolved_languages
        return langs[0] if langs else None

    @property
    def resolved_template(self) -> Optional[str]:
        # Deprecated fallback: primary languages entry. To be removed
        # alongside the other legacy fields; see follow-up issue.
        return self.template or self.primary_language
```

The first entry of `resolved_languages` is canonical/primary, used for the rbx→BOCA
forward map. `bocaLanguage` continues to work; the Pydantic `deprecated=` flag surfaces
in schema/docs.

### Mapping logic (`boca_language_utils.py`)

- `get_boca_language_from_rbx_language` reads `primary_language` (then the existing
  env-level fallback and rbx-name fallback).
- `get_rbx_language_from_boca_language` matches by **membership** in
  `resolved_languages`, so both `cc` and `cpp` resolve back to rbx `cpp`.

### Emitted set: union with name-fallback

`BocaExtension.languages` default changes from `list(typing.get_args(BocaLanguage))` to
`[]`. The packager computes the emitted BOCA-language set as the union of:

1. Explicit `extensions.boca.languages` (back-compat for users who set it).
2. `resolved_languages` across every enabled rbx language.
3. Name-fallback: every enabled rbx language whose `name` is itself a valid
   `BocaLanguage` literal and which declared no explicit boca extension is treated as
   contributing `[name]`. Preserves the previous "no boca config" behavior for users
   without needing them to migrate immediately.

### Template sourcing

Today the packager sources `compile/<L>`, `run/<L>`, `interactive/<L>` from the template
dir whose name equals the emitted BOCA language `L`. With multiple `languages` per
rbx language, the per-emit content would silently diverge (e.g. `compile/cpp` would pull
the `cpp` template rather than the `cc` one), defeating the aliasing intent.

Change: when emitting BOCA language `L` for rbx language `R`, source the per-language
template scripts from `resolved_template(R)` rather than from `L`. `limits`,
`compare`, `tests` are generated or shared and remain unaffected. Per-language time
limit lookups continue to resolve via the reverse map from `L` to `R`.

### Default preset (`rbx/resources/presets/default/env.rbx.yml`)

Each language declares its own BOCA targets and template explicitly; the env-level
`languages` list is removed. `flags`, `preferContestLetter`, `usePypy` are kept.

| rbx lang | `languages`    | `template` |
| -------- | ------------------ | -------------- |
| `cpp`    | `["cc", "cpp"]`    | `cc`           |
| `c`      | `["c"]`            | `c`            |
| `py`     | `["py3"]`          | `py3`          |
| `java`   | `["java"]`         | `java`         |
| `kt`     | `["kt"]`           | `kt`           |

Emitted set becomes `{cc, cpp, c, py3, java, kt}` (the old set plus `cpp`). Both
`compile/cc` and `compile/cpp` are sourced from the `cc` template — true aliasing.

## Back-compat and deprecation

This change is additive at the schema/runtime level:

- `bocaLanguage` still works (read into `resolved_languages`).
- `BocaExtension.languages`, if set, still contributes to the emitted set.
- `template`, if unset, falls back to `primary_language`.
- Name-fallback safety net covers zero-config users.

Three deprecations are tracked as a single follow-up issue (see below):

1. `BocaLanguageExtension.bocaLanguage` → use `languages`.
2. `BocaExtension.languages` → declare `languages` per language.
3. `template` fallback → require explicit `template` whenever an rbx language
   declares `languages`.

## Testing

- Unit: `resolved_languages`, `primary_language`, `resolved_template`
  across all three input states (plural set, only singular, neither; with/without
  explicit template).
- Mapping: reverse map resolves both `cc` and `cpp` → rbx `cpp`; forward map returns
  `cc`. Name-fallback still resolves bare-name configs.
- Packager/integration: BOCA package built from the updated default preset contains
  `compile/cc` and `compile/cpp` with **identical** content (both sourced from the `cc`
  template); parallel `run/`, `limits/`, `compare/`, `tests/` dirs are present for every
  emitted language.
- Regression: existing BOCA packaging tests pass unchanged for single-target languages
  and for configs that still set `bocaLanguage` and/or env-level `languages`.

## Follow-up issue (full deprecation)

A single GitHub issue tracks removing all three legacy behaviors after a deprecation
window. Plan: warn (release N) → migrate bundled fixtures/docs (release N) → remove
(release N+1 or N+2). At removal, `BocaExtension.languages` is dropped, the
`template` fallback is removed (validation requires `template` whenever
`languages` is set), and the union logic collapses to `resolved_languages` plus
the name-fallback safety net.
