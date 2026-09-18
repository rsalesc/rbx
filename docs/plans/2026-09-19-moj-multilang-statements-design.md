# MOJ: statements in multiple languages

**Date:** 2026-09-19
**Status:** approved

## Problem

MOJ now accepts a problem statement in Portuguese (canonical, required) plus
translations in English and Spanish, and renders each reader the one in their
language. The `moj` packager ships **one** statement -- `--language` picks it,
otherwise the topmost declared -- and drops every other statement the problem
declares. A setter who authored `pt` and `en` statements in rbx reaches MOJ
readers in one language only.

## What MOJ expects

From `moj.naquadah.com.br/docs/PACOTE.html` and mojtools' `statement-langs.sh`
(the single source of truth for language discovery, as of 2026-09-15):

| | pt (canonical, required) | en / es (Markdown only) |
|---|---|---|
| Statement | `docs/enunciado.md` | `docs/enunciado.<lang>.md` |
| Sample note | `docs/notes/<sample>.md` | `docs/notes/<sample>.<lang>.md` |
| Title | `.moj-meta.json` `display_title` | `.moj-meta.json` `titles: {<lang>: ...}` |

- The allowlist is hard-coded `pt en es`; any other suffix is ignored.
- `validate-problem.sh` applies the `## Entrada`/`## Saída` release gate to
  every translation too. It matches `entrada|input` and
  `saída|saida|salida|output`, so a Spanish statement passes with `Entrada`
  and `Salida`.
- A translation without a note for a sample falls back to the Portuguese note,
  with a soft `nota-sem-traducao` warning. A translation without a `titles`
  entry falls back to `display_title`.
- The examples section, its labels (Exemplos/Examples/Ejemplos, ...) and the
  `<html lang>` are MOJ's; the package carries nothing for them.
- The PACOTE page lists `display_title`, `collections` and `languages` as the
  meta fields read from an uploaded tar and does not mention `titles`, but the
  current `moj upload` synthesizes `titles` into the tar's `.moj-meta.json`
  from `.moj-id`, so the server reads it from there. Writing it into the file
  is all rbx has to do.

Editorials (`docs/solucao.<lang>.md`) are out of scope: the packager ships no
editorial today, and that is a separate feature.

## Decisions

1. **The main statement always fills `enunciado.md`, whatever its language.**
   `--language` picks it; without the flag, the `pt` statement is preferred
   and the topmost declared one is the fallback. An English-only problem still
   packages exactly as it does today. The `pt` preference is new: with `en`
   declared first and `pt` second, "first declared" would have put English in
   the canonical slot and Portuguese in `enunciado.pt.md`, which MOJ ignores.
2. **Every other `en`/`es` statement ships as a translation**, at
   `docs/enunciado.<lang>.md`, with its sample notes at
   `docs/notes/<sample>.<lang>.md`. One statement per language: when a language
   has several variants, the topmost wins and the packager says so. A `pt`
   statement that is not the main one is dropped with a warning: MOJ reads
   Portuguese only from the canonical slot.
3. **A statement in a language MOJ does not support is skipped with a
   warning**, not refused and not shipped. Nothing dead travels.
4. **`titles[<lang>]` is emitted only when the translation has a title of its
   own** (`Statement.title`, else `pkg.titles[lang]`) **and it differs from
   `display_title`.** MOJ falls back to `display_title` anyway, so an identical
   entry is noise -- and `naming.get_problem_title`'s last resort, the package
   *name*, is deliberately not taken for a translation: it would replace that
   fallback with a name the setter never meant as a title.
5. Probe packages keep shipping the dummy statement only.

## Design

### Selection (`rbx/box/packaging/moj/statement.py`)

`select_statements(main_language) -> StatementSelection` with `main`,
`translations: Dict[str, Statement]` keyed by MOJ language, and `skipped`.
`get_main_statement` and `get_display_title` keep their signatures (`rbx
tooling moj summary` calls them) and resolve through it. The MOJ language of a
statement is its ISO 639-1 subtag (`pt-br` -> `pt`), the same normalization
`_headings` already applies.

`_HEADINGS` gains `es` (`Entrada`, `Salida`, `Notas`).

`enunciado_path(lang=None)` and `note_path(name, lang=None)` spell the two
file names, so the suffix is written in one place.

### Packager (`_write_statement`)

Runs the existing per-statement sequence -- build bundle, materialize,
rasterize PDF figures, convert body and notes (inlining figures), write,
discard inlined assets -- once for the main statement and once per
translation. Each iteration is independent, so a translation that fails the
MOJ gate names itself. With `INLINE_IMAGES_AS_BASE64 = False` two languages
shipping a figure under the same name would overwrite each other under
`docs/assets`; the default inlines and discards per iteration, so this is
documented rather than solved.

`_write_moj_meta` adds `titles` per decision 4.

### Testing

- Unit: selection prefers `pt`, honors `--language`, skips unsupported
  languages with a warning, dedupes variants, and the Spanish headings.
- Packager: a `pt`+`en`+`es`+`ru` problem yields the three files and the
  translated notes, `titles` carries only the differing titles, `ru` is
  absent and warned about, and an `en`-first problem still puts `pt` in
  `enunciado.md`.
- E2E (`MOJTOOLS_DIR`): `validate-problem.sh` passes the gate for every
  translation, including `## Salida`.
