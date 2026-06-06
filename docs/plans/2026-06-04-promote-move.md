# Promote = Move (script line → manual test) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `rbx testcases promote` a *move* — restrict candidates to tests originating from an `rbx`-format generator script (excluding `@copy`/file-backed), and on promotion both write the static `.in` AND delete the source statement (plus its contiguous leading comments) from the script.

**Architecture:** A new parser helper exposes each statement's line span; the `rbx` script handler gains a `remove()` that deletes spans + leading comments; `promotion.py` gains a promotable predicate and a per-script removal driver; the `promote` command filters candidates and runs removal after the writes succeed. The stress route is untouched.

**Tech Stack:** Python 3, Lark (generator-script grammar, `propagate_positions` already on), Typer, questionary, pytest.

**Design doc:** `docs/plans/2026-06-04-promote-move-design.md`

---

## Background facts the implementer needs

- **Generation metadata.** Each `GenerationTestcaseEntry` (`rbx/box/generation_schema.py:69`) has `.metadata` (a `GenerationMetadata`) carrying `generator_script: Optional[GeneratorScriptEntry]` (`{path, line}`, `line` = 1-indexed start line), `generator_call`, `content`, `copied_from`, and helpers `repr()` / `full_repr()`. Script-derived tests always have `generator_script` set; `@copy` also sets `copied_from`; manual/glob tests and yml-level `generators:` have `generator_script is None`.
- **Script format.** `GeneratorScript` (`rbx/box/schema.py:320`) has `format: Literal['rbx','box']` (default `'rbx'`) and `root`. Resolve a script's format by building a map from `get_test_groups_by_name().values()`: for each subgroup with `generatorScript is not None`, map `gs.path` → `gs.format`. Keys in `package.get_test_groups_by_name()` are `name` and `f'{group}.{subgroup}'` (`rbx/box/package.py:509`).
- **Parser.** `rbx/box/stressing/generator_script_parser.py` uses Lark with `propagate_positions=True` (so `meta.line`/`meta.end_line` are populated). Statements: `comment`, `copy_test`, `inline_input` (string or `{ }` block), `testgroup` (nested), `generator_call`. The transformer currently captures only `meta.line`.
- **Handler.** `rbx/box/generator_script_handlers.py`: `GeneratorScriptHandler` (abstract `parse`, `append`), concrete `RbxGeneratorScriptHandler` / `BoxGeneratorScriptHandler`, `get_generator_script_handler(script, GeneratorScriptHandlerParams(script_entry, group))`. Get a group's `GeneratorScript` from `subgroup.generatorScript`.
- **Promote command.** `rbx/box/testcases/main.py` — `promote` (Tasks 2-3 of the prior plan): non-interactive resolves selectors via `extract_generation_testcases_from_patterns`; interactive enumerates via `extract_generation_testcases_from_groups()`; both get input through `_generate_input_for_editing(entry, output=False, ...)` and write via `promotion.promote_input_to_group`. Existing tests: `tests/rbx/box/testcases/test_promote.py`.
- **Existing tests to mirror for style:** `tests/rbx/box/stressing/test_generator_script_parser.py`, `tests/rbx/box/test_generator_script_handlers.py`.
- Conventions: single quotes, absolute imports, `uv run ruff format . && uv run ruff check --fix .` before commit, conventional commits (commitizen) ending with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`, stage files by name.

---

## Task 1: Parser — `statement_spans`

**Files:**
- Modify: `rbx/box/stressing/generator_script_parser.py`
- Test: `tests/rbx/box/stressing/test_generator_script_parser.py`

**Step 1: Write failing tests**

```python
from rbx.box.stressing import generator_script_parser as gsp

def test_statement_spans_single_line_call():
    script = 'gens/gen --n=5\n'
    spans = gsp.statement_spans(script)
    assert len(spans) == 1
    assert (spans[0].start_line, spans[0].end_line) == (1, 1)
    assert spans[0].kind == 'generator_call'

def test_statement_spans_input_block_multiline():
    script = '@input {\n1 2 3\n4 5 6\n}\n'
    spans = gsp.statement_spans(script)
    assert len(spans) == 1
    assert spans[0].start_line == 1
    assert spans[0].end_line == 4  # closing brace line
    assert spans[0].kind == 'inline_input'

def test_statement_spans_skips_comments_and_blanks():
    script = '// a comment\n\ngens/gen 1\n'
    spans = gsp.statement_spans(script)
    assert [(s.start_line, s.kind) for s in spans] == [(3, 'generator_call')]

def test_statement_spans_nested_testgroup():
    script = '@testgroup g {\ngens/a 1\n@input "x"\n}\n'
    spans = gsp.statement_spans(script)
    kinds = [s.kind for s in spans]
    # the two inner statements are reported (testgroup children)
    assert 'generator_call' in kinds and 'inline_input' in kinds
```

(Adjust expected `end_line` values to whatever Lark actually reports — RUN the test and read the
failure to learn the real numbers, then lock them in. Do not assume; verify.)

**Step 2: Run, verify fail**

Run: `uv run pytest tests/rbx/box/stressing/test_generator_script_parser.py -v -k statement_spans`
Expected: FAIL (`statement_spans` not defined).

**Step 3: Implement**

Add a dataclass and a tree walk that reads `propagate_positions` metadata. The transformer
discards positions, so walk the raw parse tree instead.

```python
import dataclasses

@dataclasses.dataclass
class StatementSpan:
    start_line: int
    end_line: int
    kind: str


_STATEMENT_RULES = {'generator_call', 'copy_test', 'inline_input', 'testgroup'}


def statement_spans(script: str) -> List['StatementSpan']:
    """Line spans (1-indexed, inclusive) of each leaf statement in an rbx script.

    Comments are not statements. A `@testgroup` is descended into: its child
    statements are reported (not the group wrapper), since each child is one test.
    """
    tree = parse(script)
    spans: List[StatementSpan] = []

    def walk(node):
        for child in node.children:
            if not isinstance(child, lark.Tree):
                continue
            rule = child.data
            if rule == 'testgroup':
                walk(child)  # report inner statements, not the wrapper
            elif rule in _STATEMENT_RULES:
                meta = child.meta
                spans.append(
                    StatementSpan(
                        start_line=meta.line,
                        end_line=meta.end_line,
                        kind=rule,
                    )
                )

    walk(tree)
    spans.sort(key=lambda s: s.start_line)
    return spans
```

(If `child.meta.end_line` is missing/empty for some node, confirm `propagate_positions` covers it;
the grammar already sets `propagate_positions=True` on `LARK_PARSER`. For a `testgroup`, descend so
each child test is individually removable.)

**Step 4: Run, verify pass**

Run: `uv run pytest tests/rbx/box/stressing/test_generator_script_parser.py -v -k statement_spans`
Expected: PASS.

**Step 5: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add rbx/box/stressing/generator_script_parser.py tests/rbx/box/stressing/test_generator_script_parser.py
git commit  # feat(generators): expose statement line spans in rbx script parser
```

---

## Task 2: Handler — `RbxGeneratorScriptHandler.remove`

**Files:**
- Modify: `rbx/box/generator_script_handlers.py`
- Test: `tests/rbx/box/test_generator_script_handlers.py`

**Step 1: Write failing tests**

```python
from rbx.box.generator_script_handlers import get_generator_script_handler, GeneratorScriptHandlerParams
from rbx.box.schema import GeneratorScript

def _rbx_handler(script):
    return get_generator_script_handler(
        script, GeneratorScriptHandlerParams(GeneratorScript(path=__import__('pathlib').Path('s.txt'), format='rbx'))
    )

def test_remove_single_generator_call():
    script = 'gens/a 1\ngens/b 2\ngens/c 3\n'
    h = _rbx_handler(script)
    h.remove({2})
    assert h.script.splitlines() == ['gens/a 1', 'gens/c 3']

def test_remove_input_block():
    script = 'gens/a 1\n@input {\n1\n2\n}\ngens/c 3\n'
    h = _rbx_handler(script)
    h.remove({2})  # start line of the @input block
    assert 'input' not in h.script
    assert h.script.splitlines() == ['gens/a 1', 'gens/c 3']

def test_remove_strips_contiguous_comment_above():
    script = '// makes a big case\ngens/a 1\ngens/b 2\n'
    h = _rbx_handler(script)
    h.remove({2})
    assert h.script.splitlines() == ['gens/b 2']  # comment gone too

def test_remove_keeps_comment_separated_by_blank():
    script = '// header\n\ngens/a 1\n'
    h = _rbx_handler(script)
    h.remove({3})
    assert '// header' in h.script  # blank gap breaks association

def test_remove_multiple_bottom_up():
    script = 'gens/a 1\ngens/b 2\ngens/c 3\n'
    h = _rbx_handler(script)
    h.remove({1, 3})
    assert h.script.splitlines() == ['gens/b 2']
```

**Step 2: Run, verify fail**

Run: `uv run pytest tests/rbx/box/test_generator_script_handlers.py -v -k remove`
Expected: FAIL (`remove` not defined / abstract).

**Step 3: Implement**

- Add abstract `def remove(self, start_lines: Set[int]) -> None: ...` to `GeneratorScriptHandler`.
- `BoxGeneratorScriptHandler.remove` raises (unreachable via the promote filter):

```python
def remove(self, start_lines: Set[int]) -> None:
    raise NotImplementedError('Removing tests is only supported for rbx-format scripts.')
```

- `RbxGeneratorScriptHandler.remove`:

```python
def remove(self, start_lines: Set[int]) -> None:
    from rbx.box.stressing import generator_script_parser

    spans = {s.start_line: s for s in generator_script_parser.statement_spans(self.script)}
    lines = self.script.splitlines()  # 0-indexed list; line N is lines[N-1]

    # Collect 1-indexed line numbers to drop.
    drop = set()
    for start in start_lines:
        span = spans.get(start)
        if span is None:
            continue  # nothing matches that start line; ignore defensively
        for ln in range(span.start_line, span.end_line + 1):
            drop.add(ln)
        # Walk upward over contiguous comment lines (no blank gap).
        prev = span.start_line - 1
        while prev >= 1:
            stripped = lines[prev - 1].strip()
            if stripped.startswith('//') or stripped.startswith('#'):
                drop.add(prev)
                prev -= 1
            else:
                break

    kept = [line for i, line in enumerate(lines, start=1) if i not in drop]
    self.script = _normalize_blank_lines('\n'.join(kept))
```

Add a small module-level helper:

```python
def _normalize_blank_lines(text: str) -> str:
    out = []
    for line in text.splitlines():
        if not line.strip() and out and not out[-1].strip():
            continue  # collapse consecutive blanks
        out.append(line)
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return '\n'.join(out)
```

Import `Set` from typing if not already imported.

**Step 4: Run, verify pass**

Run: `uv run pytest tests/rbx/box/test_generator_script_handlers.py -v -k remove`
Expected: PASS.

**Step 5: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add rbx/box/generator_script_handlers.py tests/rbx/box/test_generator_script_handlers.py
git commit  # feat(generators): support removing statements from rbx scripts
```

---

## Task 3: `promotion.py` — promotable predicate + removal driver

**Files:**
- Modify: `rbx/box/promotion.py`
- Test: `tests/rbx/box/promotion_test.py`

**Step 1: Write failing tests**

Unit-test the pure predicate against a script-format map and a `GenerationTestcaseEntry`-like
input. Build small `GenerationTestcaseEntry` objects (import from `rbx.box.generation_schema`) with
metadata variants and a `script_formats` dict:

```python
import pathlib
from rbx.box import promotion
from rbx.box.generation_schema import GenerationTestcaseEntry, GenerationMetadata, GeneratorScriptEntry
from rbx.box.schema import GeneratorCall, Testcase
from rbx.box.testcase_schema import TestcaseEntry

def _entry(metadata):
    return GenerationTestcaseEntry(
        group_entry=TestcaseEntry(group='g', index=0),
        subgroup_entry=TestcaseEntry(group='g', index=0),
        metadata=metadata,
    )

def _md(**kw):
    return GenerationMetadata(copied_to=Testcase(inputPath=pathlib.Path('x.in')), **kw)

SCRIPT = pathlib.Path('tests/plan.txt')
FORMATS = {SCRIPT: 'rbx'}

def test_promotable_rbx_generator_call():
    md = _md(generator_call=GeneratorCall(name='g'), generator_script=GeneratorScriptEntry(path=SCRIPT, line=1))
    assert promotion.is_promotable(_entry(md), FORMATS) is True

def test_promotable_input_content():
    md = _md(content='1 2 3', generator_script=GeneratorScriptEntry(path=SCRIPT, line=1))
    assert promotion.is_promotable(_entry(md), FORMATS) is True

def test_not_promotable_copy():
    md = _md(copied_from=Testcase(inputPath=pathlib.Path('a.in')), generator_script=GeneratorScriptEntry(path=SCRIPT, line=1))
    assert promotion.is_promotable(_entry(md), FORMATS) is False

def test_not_promotable_no_script():
    md = _md(generator_call=GeneratorCall(name='g'))
    assert promotion.is_promotable(_entry(md), FORMATS) is False

def test_not_promotable_box_format():
    md = _md(generator_call=GeneratorCall(name='g'), generator_script=GeneratorScriptEntry(path=SCRIPT, line=1))
    assert promotion.is_promotable(_entry(md), {SCRIPT: 'box'}) is False
```

(Verify the real `GenerationMetadata` constructor args by reading `generation_schema.py:65`; it
requires `copied_to`. Adjust kwargs to match.)

**Step 2: Run, verify fail.**

Run: `uv run pytest tests/rbx/box/promotion_test.py -v -k promotable`
Expected: FAIL (`is_promotable` not defined).

**Step 3: Implement**

```python
def script_format_by_path() -> Dict[pathlib.Path, str]:
    """Map each generator-script path in the package to its format ('rbx'/'box')."""
    res = {}
    for group in package.get_test_groups_by_name().values():
        gs = group.generatorScript
        if gs is not None:
            res[gs.path] = gs.format
    return res


def is_promotable(entry, script_formats: Dict[pathlib.Path, str]) -> bool:
    """True iff entry came from an rbx generator script and is not a @copy."""
    md = entry.metadata
    if md.generator_script is None or md.copied_from is not None:
        return False
    return script_formats.get(md.generator_script.path) == 'rbx'
```

Add the removal driver (groups recorded removals by script path, removes bottom-up, writes, clears
cache):

```python
def remove_script_entries(entries) -> None:
    """Delete each entry's originating statement from its rbx generator script."""
    from rbx.box import generator_script_handlers as gsh

    by_path: Dict[pathlib.Path, Set[int]] = {}
    for entry in entries:
        gse = entry.metadata.generator_script
        assert gse is not None
        by_path.setdefault(gse.path, set()).add(gse.line)

    groups = package.get_test_groups_by_name()
    script_entry_by_path = {
        g.generatorScript.path: g.generatorScript
        for g in groups.values()
        if g.generatorScript is not None
    }

    for path, start_lines in by_path.items():
        script_entry = script_entry_by_path[path]
        handler = gsh.get_generator_script_handler(
            path.read_text(),
            gsh.GeneratorScriptHandlerParams(script_entry),
        )
        handler.remove(start_lines)
        path.write_text(handler.script if handler.script.endswith('\n') else handler.script + '\n')

    package_utils.clear_package_cache()
```

(Confirm `package_utils` is the same import already used in this module for `clear_package_cache`.)

**Step 4: Run, verify pass.**

Run: `uv run pytest tests/rbx/box/promotion_test.py -v -k promotable`
Expected: PASS.

**Step 5: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add rbx/box/promotion.py tests/rbx/box/promotion_test.py
git commit  # feat(promotion): add promotable predicate and script-removal driver
```

---

## Task 4: Wire move semantics into `rbx testcases promote`

**Files:**
- Modify: `rbx/box/testcases/main.py`
- Test: `tests/rbx/box/testcases/test_promote.py`

**Step 1: Write failing tests**

Use the existing `testing_pkg` + CliRunner harness in this file. Set up a package with an **rbx
generator script** group (e.g. a `tests/plan.txt` with two generator-call lines registered as a
group with `generatorScript: {path: tests/plan.txt}`) plus a manual glob group `corner`. Look at how
`_setup_pkg_with_two_generated_tests` / `add_testgroup_with_generators` work and whether a helper to
add a **generatorScript** group exists (search `testing_package.py` for `generatorScript`/`add_testgroup`);
if not, write the `problem.rbx.yml` group + the `.txt` file directly in the test.

Required tests:
1. **Move deletes the source line:** `promote plan/0 --group corner` writes `tests/manual/corner/000.in` AND the first line is gone from `tests/plan.txt` (the second line remains).
2. **Non-promotable selector errors:** a selector pointing at a `@copy` line, a manual/glob test, or a box-format script → non-zero exit with an explanatory message; assert no file written and the script unchanged.
3. **Interactive list excludes non-promotable:** drive the interactive path (mock questionary) on a package mixing an rbx-script group and a manual group; assert the checkbox `choices` only contain the rbx-script tests. (Capture the `choices=` passed to the mocked `questionary.checkbox`.)
4. Update the prior copy-semantics tests in this file: after promotion the source test no longer regenerates (the line is gone). Adjust assertions that assumed the source still exists.

**Step 2: Run, verify fail.**

Run: `uv run pytest tests/rbx/box/testcases/test_promote.py -v`
Expected: FAIL on the new move/filter assertions.

**Step 3: Implement**

In `promote` (both paths):
- Compute `script_formats = promotion.script_format_by_path()` once.
- **Non-interactive:** after resolving `entries`, filter/validate: any selected entry where
  `not promotion.is_promotable(entry, script_formats)` → print an error naming the selector and the
  reason (`@copy`/file-backed/box-format/not-from-script) and `raise typer.Exit(1)` (fail the whole
  command before writing anything).
- **Interactive (`_promote_interactive`):** when enumerating `all_entries`, keep only
  `promotion.is_promotable(e, script_formats)`. If the filtered list is empty, print a message
  ('No promotable tests — only tests generated by an rbx generator script can be promoted.') and
  return. Build checkbox labels from `str(e.group_entry)` + ` (` + `e.metadata.full_repr()` + `)` so
  the source metadata shows.
- **After all writes succeed** (in both paths), call `promotion.remove_script_entries(written_entries)`
  where `written_entries` is the list of entries actually promoted. Keep generation+write first, then
  removal (matches the design's all-or-nothing ordering).
- Update confirmation wording to e.g. `Moved {group_entry} to {written} (removed from {gse.path}:{gse.line}).`

**Step 4: Run, verify pass.**

Run: `uv run pytest tests/rbx/box/testcases/test_promote.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
uv run ruff format . && uv run ruff check --fix .
git add rbx/box/testcases/main.py tests/rbx/box/testcases/test_promote.py
git commit  # feat(testcases): make promote a move limited to rbx-script tests
```

---

## Task 5: Docs

**Files:**
- Modify: `docs/setters/stress-testing-walkthrough.md` (the `rbx testcases promote` cross-link/blurb)

**Step 1:** Update the `rbx testcases promote` mention to say it **moves** a test generated by an
**rbx generator script** into a manual group (writes the static `.in` and removes the originating
script line + its leading comments). Make clear it does not apply to `@copy`, file-backed, or
box-format tests.

**Step 2: Verify docs build** (non-strict; ~9 pre-existing unrelated warnings):

Run: `uv run mkdocs build 2>&1 | tail -20`
Expected: builds; no new warnings referencing the edited page. (Discard any generated `site/` /
autogenerated `cli.md` artifacts; commit only the doc source.)

**Step 3: Commit** — `docs(promote): document promote-as-move semantics`

---

## Final verification

- `uv run pytest tests/rbx/box/stressing/test_generator_script_parser.py tests/rbx/box/test_generator_script_handlers.py tests/rbx/box/promotion_test.py tests/rbx/box/testcases/test_promote.py -v`
- `uv run pytest tests/rbx/box --collect-only -q` (no import errors)
- `uv run ruff check rbx/box && uv run ruff format --check rbx/box`
- Manual smoke: in a package with an rbx `tests/plan.txt` group, `rbx build`, then
  `rbx testcases promote plan/0 --group corner`; confirm `tests/manual/corner/000.in` appears and the
  line vanished from `tests/plan.txt`; `rbx build` still succeeds.
