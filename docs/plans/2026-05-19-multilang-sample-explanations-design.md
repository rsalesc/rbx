# Multi-language sample explanations — design

## Problem

Sample explanations exist in two flavors today:

1. **Statement-level blocks** — `%- block explanation_N` inside the statement
   `.rbx.tex`. These are inherently language-specific because each statement is
   built per language.
2. **Per-sample files** — a plain `<sample>.tex` (or `<sample>.md` for Markdown
   statements) living alongside the sample `.in`. These are language-agnostic:
   nothing ties the file to a language, so the same text is used for every
   language.

We want a third option that keeps the convenience of per-sample files but is
language-aware: a `<sample>.rbx.tex` file alongside the `.in` that contains
language-keyed JinjaTeX blocks.

## Desired file format

```latex
%- block en
This is the english explanation.
%- endblock

%- block pt
Esta é a explicação em português.
%- endblock
```

- Content **outside** any block is ignored.
- The file receives all the same Jinja parameters the existing `.tex` file
  receives.
- Generalizes to Markdown statements via `<sample>.rbx.md`.

## Resolution & priority

For a given sample, the explanation is resolved as:

1. Statement-level `explanation_N` block — highest priority (unchanged).
2. Per-sample `<sample>.rbx.<ext>` — new, language-specific.
3. Per-sample `<sample>.<ext>` — existing, language-agnostic.

Where `<ext>` is the builder's plain explanation suffix (`.tex` for the
rbxTeX/JinjaTeX/TeX2PDF builders, `.md` for the rbxMarkdownToTeX builder), and
the blocks file suffix is `.rbx` + that suffix.

Edge cases:

- If **both** `<sample>.rbx.<ext>` and `<sample>.<ext>` exist → **error**,
  asking the setter to remove one of the two (avoids silent ambiguity).
- If the `.rbx.<ext>` file exists but has **no block for the statement's
  language** → **warn and render no explanation** for that sample/language.

## Implementation

### `rbx/box/testcase_sample_utils.py`

- Add `explanationFromBlocks: bool = False` to `StatementSample`.
- Replace the inline explanation lookup inside `_get_statement_sample_from_entry`
  with a helper that, given an input path and the plain suffix, returns
  `(explanation_path, from_blocks)`:
  - Prefers `<input>.rbx<suffix>` (sets `from_blocks=True`).
  - Falls back to `<input><suffix>`.
  - Raises `typer.Exit(1)` with a clear message if both exist.
- The public `get_statement_samples(explanation_suffix=...)` signature is
  unchanged — `explanation_suffix` remains the *plain* suffix and the blocks
  suffix is derived, so `.rbx.md` support comes for free.

### `rbx/box/statements/builders.py`

- `ExplainedStatementSample` inherits the new field; no change to
  `from_statement_sample` (it still reads the raw file text).
- In `get_rbxtex_blocks`, the per-sample loop branches on
  `sample.explanationFromBlocks`:
  - If set: render the raw text via `render_jinja_blocks` (same kwargs as the
    plain path, passing the statement language) and pick
    `blocks.get(context.lang)`. If missing, print a warning and clear the
    explanation.
  - Otherwise: the existing `render_jinja` path.

### Default preset

Add `manual_tests/samples/000.rbx.tex` containing an `en` block, and reference
it so the default preset demonstrates `.rbx.tex` as the default explanation
method.

### Docs

Update `docs/setters/statements/formats/rbxtex.md` to document per-sample
`.rbx.tex` / `.rbx.md` language-block explanations as the recommended method,
alongside the existing `explanation_N` block and plain `.tex` options.

## Testing

- `tests/rbx/box/test_testcase_sample_utils.py`:
  - resolution prefers `.rbx.tex` over `.tex`;
  - falls back to `.tex` when only it exists;
  - errors when both exist.
- `tests/rbx/box/statements/test_builders.py`:
  - `get_rbxtex_blocks` selects the block matching the statement language;
  - a missing language block warns and yields no explanation;
  - statement-level `explanation_N` block still overrides the per-sample file.
