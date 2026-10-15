# Testplan lenses and promote-to-manual (#910, testplans only)

Status: implemented. Scope agreed on 2026-10-15: generator scripts (`.txt`
testplans) only; `problem.rbx.yml` `generators:` entries are a follow-up.

## Goal

Above every statement of a testplan, a CodeLens row
`Generate · Validate · Run · Promote` acts on that one test without building
the testset. Promote moves the test into a manual group as a `.in` file and
deletes its line -- the "promote a generator call from the testplan to a manual
test" request, and the testplan half of #319.

## Addressing a test: `<script>:<line>`

A lens names its test by the testplan and the line its statement starts on
(`tests/plan.txt:12`), never by `group/index`. That needs no built testset,
so it is right the moment the plan is saved; `irun -t` already accepted it.

- `rbx/box/testcases/main.py::_entries_for_selectors` resolves both shapes.
  Script selectors compare *resolved* paths: `GeneratorScriptEntry.__hash__`
  hashes the raw path while `__eq__` uses `samefile`, so the set lookup
  `extract_generation_testcases_from_generic_entries` relies on misses
  `./x.txt` or an absolute spelling.
- A line no statement starts on fails by name. So does a line inside a
  `@testgroup X { ... }` block when the problem has no group `X`: those lines
  generate no test at all (partition semantics), and the lens cannot know that
  cheaply. The error says so.

## CLI

- `rbx testcases generate <sel> [-o/--output] [-v/--validate] [--json]`:
  exactly one test (refuses a selector matching several), via the same helpers
  as `view`. `--validate` runs the entry's own validators
  (`validate_one_off`) and exits 1 if any rejects. JSON:
  `{test, source, call, input, answer, validation: [{validator, ok, message}] | null}`.
- `rbx testcases promote` gains `script:line` selectors, `--new-manual NAME
  --glob GLOB`, `--list-groups [--json]` (manual groups only) and `--json`,
  mirroring `add-finding`. A new group is registered only after every file
  write succeeded. A non-interactive `--name` is now checked by
  `validate_stems`.

## Extension

- `rbx/manifest.ts` marks a `generatorScript` that is a `.txt` in `rbx` format
  as `testplan: true` (group- or package-level).
- `rbx/testplan.ts` (pure): a line scanner mirroring the Lark grammar, argv
  builders, and the `generate --json` parser. `rbx/testplan.cases.json` holds
  scripts with the statement lines rbx's `statement_spans` reports; both
  `testplan.test.ts` and `tests/rbx/box/stressing/testplan_cases_test.py`
  read it, so the two parsers cannot drift.
- `testplanLens.ts`: the lens provider (setting `rbx.testplanCodeLens`) and the
  four commands, also in the editor context menu and palette, where they act on
  the statement under the cursor. Every action saves the plan first.
  - Generate / Validate run `generate --json` headless (D3: read-mostly,
    idempotent) and open the files in the testcase panes
    (`TestcasePanes.openGenerated`) or show the verdict.
  - Run dispatches `rbx irun -t <sel>`; Promote picks a manual group (or
    creates one) and a file name, then dispatches `rbx testcases promote`.
    Both write or run solutions, so both go to a terminal (D3). `@copy` lines
    get no Promote.
- `vscode/demo/apples` gains a `plan` testplan group and a `handmade` manual
  group.

## Follow-ups

- Lenses on `problem.rbx.yml` `generators:` entries, and YAML source spans in
  `testset.yml`.
- Hover showing the built tests of a line; inline decorations for tests that
  failed validation.
- `@testgroup` "Generate group" lens; box-format and dynamic scripts.
- `promotion.create_manual_group` round-trips `problem.rbx.yml` through ruyaml,
  which re-indents block sequences and can strand a trailing comment above the
  new group. Pre-existing; worth fixing separately.
