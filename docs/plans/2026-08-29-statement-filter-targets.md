# Target-aware statement filters Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the statement filters render per target, so the VS Code var hints can honour `| sci`, `| rsci` and every other filter without a second implementation.

**Architecture:** `add_builtin_filters(env, target)` selects a formatter, never the rules. `rbx vars --render --target text` renders whole expressions through the real Jinja environment, reading them from stdin. The extension keeps its bulk var map for unfiltered references and asks rbx only about filtered ones, caching every answer — including failures — per `(package root, expression)`.

**Tech Stack:** Python 3 / Jinja2 / Typer / pytest; TypeScript / VS Code API / `node --test`.

**Design:** `docs/plans/2026-08-29-statement-filter-targets-design.md`. Read it first.

---

## The constraint that outranks everything

**LaTeX output must not move.** These filters render statements people ship. The
current behaviour, captured from the installed code, is the golden table:

| value | `sci` | `rsci` |
| --- | --- | --- |
| `0` | `0` | `0` |
| `1` | `1` | `1` |
| `10` | `10` | `10` |
| `532` | `532` | `532` |
| `9999` | `9999` | `9999` |
| `10000` | `10^{4}` | `10^{4}` |
| `100000` | `10^{5}` | `10^{5}` |
| `100007` | `100007` | `10^{5} + 7` |
| `200000` | `2 \times 10^{5}` | `2 \times 10^{5}` |
| `250000` | `250000` | `250000` |
| `1000000007` | `1000000007` | `10^{9} + 7` |
| `10**18 + 7` | `1000000000000000007` | `10^{18} + 7` |
| `-100000` | `-10^{5}` | `-10^{5}` |
| `10**21` | `10^{21}` | `10^{21}` |

Note `250000` and `100007` **decline** under `sci` — the rules refuse an
abbreviation that is not shorter or not clean. Those two rows are the ones a
careless refactor breaks.

---

## Task 1: Target-aware filters

**Files:**
- Modify: `rbx/box/statements/latex_jinja.py`
- Test: `tests/rbx/box/statements/filter_targets_test.py` (check whether a statements test dir already exists: `ls tests/rbx/box/statements/`; if not, create it with an `__init__.py` if its siblings have one)

**Step 1: Pin today's behaviour before changing anything**

Write the golden table above as a parametrised test against the CURRENT
functions, and run it. It must pass before you touch the implementation — that
is what makes it a regression test rather than a description of whatever you
end up writing.

```python
import pytest

from rbx.box.statements.latex_jinja import (
    rest_scientific_notation,
    scientific_notation,
)

GOLDEN = [
    (0, '0', '0'),
    (1, '1', '1'),
    (10, '10', '10'),
    (532, '532', '532'),
    (9999, '9999', '9999'),
    (10000, '10^{4}', '10^{4}'),
    (100000, '10^{5}', '10^{5}'),
    (100007, '100007', '10^{5} + 7'),
    (200000, r'2 \times 10^{5}', r'2 \times 10^{5}'),
    (250000, '250000', '250000'),
    (1000000007, '1000000007', '10^{9} + 7'),
    (10**18 + 7, '1000000000000000007', '10^{18} + 7'),
    (-100000, '-10^{5}', '-10^{5}'),
    (10**21, '10^{21}', '10^{21}'),
]


@pytest.mark.parametrize(('value', 'sci', 'rsci'), GOLDEN)
def test_latex_scientific_notation_is_unchanged(value, sci, rsci):
    assert scientific_notation(value) == sci
    assert rest_scientific_notation(value) == rsci
```

Run: `uv run pytest tests/rbx/box/statements/filter_targets_test.py -v`
Expected: PASS, before any change.

**Step 2: Introduce the target**

Add to `latex_jinja.py`:

```python
class FilterTarget(enum.Enum):
    """What a filter is formatting for.

    The *rules* a filter applies -- when `sci` abbreviates, when it declines --
    are a property of the value and never vary. Only the spelling does: a PDF
    wants `2 \\times 10^{5}`, a VS Code inlay hint wants `2×10⁵` because it
    cannot typeset maths.

    MARKDOWN maps to the LaTeX formatter and is not redundant: a Markdown
    statement puts its constraints in `$...$` math, so LaTeX is correct there.
    Naming it separately means the day it stops being correct is a one-line
    change rather than an archaeology exercise.
    """

    LATEX = 'latex'
    MARKDOWN = 'markdown'
    TEXT = 'text'
```

**Step 3: Split formatting out of the rules**

`scientific_notation` currently decides and formats in one pass. Keep ONE copy
of the decisions and give it a formatter. The shape to aim for:

- a helper that returns the decision — declined, or `(mult, exp, rem)`;
- per-target formatting of that decision.

Do not restructure more than that. In particular keep `_process_zeroes`, the
`zeroes` threshold, the two "decline" branches and the negative-number
recursion exactly as they behave now. The Step 1 test is your proof.

Superscript mapping for TEXT: `0123456789` → `⁰¹²³⁴⁵⁶⁷⁸⁹`, `\times` → `×`, and
no braces. `10^{18} + 7` becomes `10¹⁸ + 7` — the ` + 7` keeps its spaces.

**Step 4: Extend the golden test to the TEXT target**

Add the expected TEXT column and assert it. Every row where LaTeX declines must
also decline in TEXT — that is the invariant the design calls out, so assert it
directly rather than only via the table:

```python
@pytest.mark.parametrize(('value', 'sci', 'rsci'), GOLDEN)
def test_text_and_latex_agree_on_whether_to_abbreviate(value, sci, rsci):
    """The rules are the value's; only the spelling is the medium's."""
    latex_declined = sci == str(value)
    text_declined = scientific_notation(value, target=FilterTarget.TEXT) == str(value)
    assert latex_declined == text_declined
```

**Step 5: Make `escape` target-aware and install by target**

`escape_latex_str_if_str` under TEXT is the identity — a badge is not a
document. `parent`/`stem` do not vary.

Change the signature to `add_builtin_filters(j2_env, target=FilterTarget.LATEX)`
and pass the target explicitly at all three call sites in this file: `LATEX`,
`LATEX`, and `MARKDOWN` for `render_markdown_template_blocks`. Defaulting the
parameter keeps any out-of-tree caller working; grep first to confirm there are
none: `grep -rn "add_builtin_filters" --include="*.py" . | grep -v .venv`.

**Step 6: Verify nothing downstream moved**

```bash
uv run pytest tests/rbx/box/statements/ -v
```
Expected: PASS. If a statement test fails, the refactor changed LaTeX output — fix the refactor, not the test.

**Step 7: Lint and commit**

```bash
uv run ruff check --fix . && uv run ruff format .
git add rbx/box/statements/latex_jinja.py tests/rbx/box/statements/filter_targets_test.py
git commit -m "feat(statements): render builtin filters per target"
```

---

## Task 2: `rbx vars --render`

**Files:**
- Modify: `rbx/box/cli/commands/vars_cmd.py`
- Modify: `rbx/box/cli/__init__.py` only if the `ENTRIES` help text changes (it should not)
- Test: `tests/rbx/box/vars_cmd_test.py`

**Step 1: Write the failing tests**

Add to the existing test file. Expressions arrive on stdin, one per line;
output is a JSON object keyed by the expression. Use `CliRunner(input=...)`.

```python
@pytest.mark.test_pkg('problems/interactive')
def test_render_evaluates_filters_for_the_text_target(pkg_from_testdata):
    result = runner.invoke(
        app, ['vars', '--render', '--target', 'text'], input='N.max | sci\nN.max\n'
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        'N.max | sci': '10⁶',
        'N.max': '1000000',
    }


@pytest.mark.test_pkg('problems/interactive')
def test_render_omits_an_expression_it_cannot_evaluate(pkg_from_testdata):
    """Absent, not an error: the extension draws no badge and moves on."""
    result = runner.invoke(
        app,
        ['vars', '--render', '--target', 'text'],
        input='N.max | nosuchfilter\nN.typo\nN.max\n',
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {'N.max': '1000000'}


@pytest.mark.test_pkg('problems/interactive')
def test_render_with_no_expressions_is_an_empty_object(pkg_from_testdata):
    result = runner.invoke(app, ['vars', '--render'], input='')

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {}
```

**VERIFY the expected values first** — `problems/interactive` has `N.min: 1`,
`N.max: 1000000`, so `sci` gives `10^{6}` → `10⁶`. Confirm with:
`cd rbx/testdata/problems/interactive && uv run rbx vars --json`

**Step 2:** Run them; expect FAIL (no `--render` option).

**Step 3: Implement**

- `--render` (bool) and `--target` (an enum-typed option defaulting to `text`; Typer renders a Python enum as a choice).
- With `--render`: read stdin, strip, drop blank lines, de-duplicate while preserving order.
- Build a Jinja environment the same way the statement renderer does, with `add_builtin_filters(env, target)`, and render each expression as `{{ <expr> }}` against the package's expanded vars.
- Collect successes; on ANY per-expression exception, skip that expression. Do not let one bad expression fail the command.
- Emit `json.dumps(rendered)` — note the values here are already strings.

Reuse rather than reinvent: look at how `latex_jinja` builds its environment
(`J2_ARGS`, `StrictChainableUndefined`) and match it, since the whole point is
that the badge agrees with the statement.

Keep the existing `--json` behaviour untouched.

**Step 4:** Run the tests; expect PASS. Then the full file plus the lazy-CLI and drift tests:

```bash
uv run pytest tests/rbx/box/vars_cmd_test.py tests/rbx/box/lazy_cli_test.py tests/rbx/box/completion/drift_test.py -v
```

Adding options changes the completion spec — regenerate it exactly as the
existing `rbx vars` entry was:
`uv run python -m rbx.box.completion.serialize && uv run ruff format rbx/box/completion/_spec.py`
and confirm the diff is only this command's new options.

**Step 5: Verify by hand**

```bash
cd rbx/testdata/problems/interactive
printf 'N.max | sci\nN.max\nN.max | nosuchfilter\n' | uv run rbx vars --render --target text
printf 'N.max | sci\n' | uv run rbx vars --render --target latex
```
Expected: `10⁶` for text, `10^{6}` for latex, the bad filter absent, exit 0 both times.

**Step 6: Lint and commit** — `feat(cli): render statement expressions with rbx vars --render`

---

## Task 3: The scanner keeps pipelines

**Files:**
- Modify: `vscode/src/rbx/statementVars.ts`
- Test: `vscode/src/rbx/statementVars.test.ts`

Today `scanStatementVars` matches a plain dotted name plus an optional pipeline
and **discards** the pipeline, returning `{end, text}`. It must now report the
expression so the caller can decide whether it needs rendering.

**Step 1: Write the failing tests.** The return type gains the expression and
whether it is filtered. Suggested shape — adapt if you find better:

```typescript
{ end: number; text?: string; expression: string; filtered: boolean }
```

Cover: an unfiltered reference still resolves from the map with no expression
to render; a filtered one reports the full normalised expression; the `vars.`
prefix is stripped in the expression sent to rbx (or NOT — decide, and pin it
with a test, since rbx accepts both and the cache key should be stable);
whitespace around the pipe is normalised so `N.max|sci` and `N.max | sci` share
one cache entry; and every existing rejection (foreign scope, non-name
expression, comment, escape) still yields nothing.

**Step 2-4:** Fail, implement, pass. Run `cd vscode && npm test`.

**Step 5: Commit** — `feat(vscode): report the filter pipeline of a var reference`

---

## Task 4: Rendering cache and provider wiring

**Files:**
- Modify: `vscode/src/statementVarsIndex.ts` (or a sibling — your call, argue it)
- Modify: `vscode/src/statementVarHints.ts`
- Test: extend `vscode/src/rbx/varsPayload.test.ts` for the render map

**What it must do:**

- `renderedFor(root, expressions): Promise<Map<string, string>>` — answers from cache, spawns once for the unknown remainder, writes stdin.
- **Cache failures.** An expression rbx omitted is cached as "no value". Typing `\VAR{N.max | sc` must ask once, not once per keystroke. Say in a comment why.
- One spawn per batch, not per expression.
- The manifest watcher already drops the per-root entry; make sure it drops rendered expressions too — a changed `vars` block changes what they render to.
- The provider renders known hints immediately and fires `onDidChangeInlayHints` when a batch lands. It must not block the whole document's hints on one slow spawn.

**Reuse:** `rbxProcess.run` takes `(command, args, cwd, timeoutMs)` — check whether it can write stdin; if not, extend it minimally and say so.

Verify: `cd vscode && npm run typecheck && npm test`.

**Commit** — `feat(vscode): honour statement filters in the var hints`

---

## Task 5: Documentation

**Files:** `docs/tools/vscode.md`, `docs/setters/variables.md`, `docs/setters/reference/cli.md`

The vscode page currently states the badge shows the raw value under a filter —
that becomes false. Fix it, and show the `10⁵` form. Document
`rbx vars --render` on the variables page beside `rbx vars --json`.

`mkdocs build` regenerates the CLI reference and the checked-in copy is badly
stale — hand-insert only this command's new options, exactly as the `rbx vars`
entry was added. Verify with `uv run mkdocs build` (not `--strict`; the ~6
warnings are pre-existing).

**Commit** — `docs: document filter-aware statement var hints`

---

## Final verification

```bash
uv run pytest tests/rbx/box/statements/ tests/rbx/box/vars_cmd_test.py tests/rbx/box/lazy_cli_test.py tests/rbx/box/completion/drift_test.py -v
cd vscode && npm run typecheck && npm test
```

Do NOT run the full Python suite. Then push to the existing PR #803 branch.
