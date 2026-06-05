# Promote = move (script line → manual test) — design

**Status:** approved 2026-06-04. Refines the `rbx testcases promote` command from #442.

## Problem

The first cut of `rbx testcases promote` (see
`2026-06-03-promote-tests-to-manual-design.md`) **copied** a test's input into a manual
group, listing *every* generated test as a candidate. That's wrong in two ways:

1. It offered tests that already come from a file (manual `testcaseGlob`/`inputPath` groups,
   and `@copy` lines in a generator script). Promoting those is meaningless — they're
   already static files.
2. It left the original generator-script line in place, so the promoted input would be
   regenerated on the next build *in addition to* the new static copy — a duplicate.

## What changes

`rbx testcases promote` becomes a **move**, restricted to tests that originate from an
**`rbx`-format generator script** and are not `@copy`:

- The candidate list (and accepted selectors) only includes promotable tests.
- Promoting a test now **writes the static `.in`** into the chosen manual group **and
  deletes the originating statement** from its generator script — including any contiguous
  comment lines directly above it.

The stress "save finding as manual test" route is **unaffected** (a finding has no source
script line to remove).

## Promotable filter

A `GenerationTestcaseEntry` is promotable iff **all** hold:

- `metadata.generator_script is not None` — it came from a generator script.
- `metadata.copied_from is None` — it is not a `@copy` (which already points at a file).
- Its source group's `generatorScript.format == 'rbx'` — box-format scripts are excluded,
  forever.

This naturally excludes: manual `testcaseGlob`/`inputPath` groups (no `generator_script`),
yml-level `generators:` calls (no `generator_script`), `@copy` lines, and box-format
scripts.

Every script-derived test already carries `metadata.generator_script`
(`GeneratorScriptEntry{path, line}`) and one of `generator_call` / `content` plus the
existing `metadata.full_repr()` for display (renders the generator call, or the
`path:line`).

## Move semantics

For the set of selected tests, do all non-destructive work first, then the destructive
edits, so a generation failure aborts before anything is deleted:

1. For each selected test: generate its input via
   `_generate_input_for_editing(entry, output=False)` (works for generator calls and
   `@input`/content), then write it to the chosen manual group via the existing
   `promotion.promote_input_to_group(...)` (input-only, unchanged). Record
   `(metadata.generator_script.path, metadata.generator_script.line)`.
2. After all writes succeed, remove the source statements: group recorded removals by
   `script_path`; for each script, run `RbxGeneratorScriptHandler.remove(start_lines)`
   once, deleting **bottom-up** (descending start line) so earlier line numbers stay valid;
   save each modified script; clear the package cache.

Confirmation wording changes from "promoted" to "moved … (removed from <script>:<line>)".

## Removal mechanics

### Parser helper (`stressing/generator_script_parser.py`)
Add `statement_spans(script) -> List[StatementSpan]` where `StatementSpan` carries
`start_line`, `end_line`, and `kind` (generator_call / inline_input / copy_test /
testgroup). Built from Lark's already-enabled `propagate_positions` (`meta.line` /
`meta.end_line`), walking top-level and nested-`@testgroup` statement nodes. This avoids
round-tripping the AST back to text (which would lose formatting and comments).

### Handler (`generator_script_handlers.py`)
- Base `GeneratorScriptHandler` gains an abstract `remove(start_lines: Set[int]) -> None`.
- `RbxGeneratorScriptHandler.remove`:
  1. Parse spans; for each target `start_line`, locate its span and mark
     `[start_line, end_line]` for deletion.
  2. Extend each deletion upward over **contiguous comment lines** (`//` or `#`), stopping
     at the first blank or code line (a blank line between a comment and the statement
     breaks the association — the comment is kept).
  3. Delete the marked line ranges from `self.script`.
  4. Normalize: collapse any resulting double blank line, trim leading/trailing blank
     lines.
- `BoxGeneratorScriptHandler.remove` raises (unreachable because the filter excludes box
  format, but explicit for safety).

### Driver (`promotion.py`)
- Add a promotable predicate (operating on a `GenerationTestcaseEntry` + its source group's
  `GeneratorScript`).
- Add `remove_script_entries(entries)` that groups by script path, instantiates the rbx
  handler per script, calls `remove(...)` bottom-up, writes the file, and clears the
  package cache.

## Components touched

- `rbx/box/stressing/generator_script_parser.py` — `statement_spans` + capture `end_line`.
- `rbx/box/generator_script_handlers.py` — `remove()` on base + rbx handler; box raises.
- `rbx/box/promotion.py` — promotable predicate + `remove_script_entries`.
- `rbx/box/testcases/main.py` — `promote` (interactive + non-interactive): filter
  candidates, drive removal after writes, updated wording.
- `docs/setters/stress-testing-walkthrough.md` (and the `rbx testcases promote` mention) —
  clarify it *moves* rbx-script-derived tests.

## Edge cases

- Removing the last statement in a `@testgroup`/script leaves an empty block/file — left
  as-is (still parses, yields no tests).
- A source script that no longer parses as rbx → error before any write.
- Two manual-group globs sharing a folder — pre-existing config footgun, unchanged.

## Testing

- **Parser** `statement_spans`: single-line call, `@input` string, `@input { }` block,
  nested `@testgroup`.
- **Handler `remove`**: delete a generator call; delete an `@input { }` block; strip
  contiguous comments above; keep a comment separated by a blank (no-blank-gap rule);
  collapse double-blank; multi-remove bottom-up within one script.
- **Promotable predicate**: rbx generator call ✓, `@input` ✓, `@copy` ✗, manual/glob ✗,
  box-format ✗, yml `generators:` ✗.
- **Command**: non-interactive move deletes the source line, writes the file, and leaves
  sibling lines intact; selector to a non-promotable test errors; interactive list excludes
  non-promotable tests; update existing promote tests that assumed copy semantics.
- **Docs**: build (non-strict) with no new warnings.

## Out of scope

- box-format removal (excluded forever).
- Auto-deleting now-empty `@testgroup` blocks or scripts.
- Any change to the stress manual route.
