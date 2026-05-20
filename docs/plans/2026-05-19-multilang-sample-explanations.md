# Multi-language Sample Explanations Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Support per-sample `<sample>.rbx.tex` / `.rbx.md` explanation files containing language-keyed JinjaTeX blocks, selecting the block matching the statement's language.

**Architecture:** Explanation-path resolution in `testcase_sample_utils.py` learns to prefer a `.rbx<suffix>` "blocks" file over the plain `<suffix>` file (erroring if both exist) and records `explanationFromBlocks` on the sample. The per-sample rendering loop in `builders.get_rbxtex_blocks` branches on that flag: blocks files are rendered via the existing `render_jinja_blocks` and the block matching `context.lang` is selected (warning if absent). The default preset and docs are updated to make `.rbx.tex` the demonstrated default.

**Tech Stack:** Python 3.10+, Pydantic v2, Jinja2 (LaTeX/Markdown flavored), Typer, pytest.

---

### Task 1: Resolve `.rbx.tex` blocks file in sample explanation lookup

**Files:**
- Modify: `rbx/box/testcase_sample_utils.py` (`StatementSample` model ~line 36; `_get_statement_sample_from_entry` ~lines 68-164)
- Test: `tests/rbx/box/test_testcase_sample_utils.py`

**Step 1: Write failing tests**

Add to `tests/rbx/box/test_testcase_sample_utils.py`:

```python
@pytest.mark.asyncio
async def test_get_statement_samples_explanation_prefers_blocks(
    tmp_path, mock_extract_generation_testcases_from_groups
):
    """A .rbx.<suffix> blocks file is preferred and flagged as from-blocks."""
    dest_input = tmp_path / 'dest.in'
    blocks_expl = tmp_path / 'dest.rbx.desc'
    blocks_expl.touch()

    entry = create_entry(
        TestcaseEntry(group='samples', index=0),
        copied_to_input=dest_input,
    )
    mock_extract_generation_testcases_from_groups.return_value = [entry]

    samples = await testcase_sample_utils.get_statement_samples(
        explanation_suffix='.desc'
    )
    sample = list(samples)[0]
    assert sample.explanationPath.resolve() == blocks_expl.resolve()
    assert sample.explanationFromBlocks is True


@pytest.mark.asyncio
async def test_get_statement_samples_explanation_plain_fallback(
    tmp_path, mock_extract_generation_testcases_from_groups
):
    """With only the plain file, it is used and not flagged as from-blocks."""
    dest_input = tmp_path / 'dest.in'
    plain_expl = tmp_path / 'dest.desc'
    plain_expl.touch()

    entry = create_entry(
        TestcaseEntry(group='samples', index=0),
        copied_to_input=dest_input,
    )
    mock_extract_generation_testcases_from_groups.return_value = [entry]

    samples = await testcase_sample_utils.get_statement_samples(
        explanation_suffix='.desc'
    )
    sample = list(samples)[0]
    assert sample.explanationPath.resolve() == plain_expl.resolve()
    assert sample.explanationFromBlocks is False


@pytest.mark.asyncio
async def test_get_statement_samples_explanation_conflict_errors(
    tmp_path, mock_extract_generation_testcases_from_groups
):
    """Both a blocks and a plain explanation file is an error."""
    dest_input = tmp_path / 'dest.in'
    (tmp_path / 'dest.desc').touch()
    (tmp_path / 'dest.rbx.desc').touch()

    entry = create_entry(
        TestcaseEntry(group='samples', index=0),
        copied_to_input=dest_input,
    )
    mock_extract_generation_testcases_from_groups.return_value = [entry]

    import typer

    with pytest.raises(typer.Exit):
        await testcase_sample_utils.get_statement_samples(explanation_suffix='.desc')
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rbx/box/test_testcase_sample_utils.py -k "prefers_blocks or plain_fallback or conflict_errors" -v`
Expected: FAIL (`explanationFromBlocks` attribute missing; conflict not raised).

**Step 3: Implement**

In `rbx/box/testcase_sample_utils.py`, add the field to `StatementSample`:

```python
class StatementSample(BaseModel):
    entry: GenerationTestcaseEntry
    inputPath: pathlib.Path
    outputPath: pathlib.Path
    answerPath: Optional[pathlib.Path] = None
    explanationPath: Optional[pathlib.Path] = None
    explanationFromBlocks: bool = False
    hasOutput: bool = True
    checkOutput: bool = False
    interaction: Optional[SampleTestcaseInteraction] = None
```

Add a module-level helper (above `_get_statement_sample_from_entry`):

```python
def _resolve_explanation_path(
    input_path: pathlib.Path, explanation_suffix: Optional[str]
) -> Tuple[Optional[pathlib.Path], bool]:
    """Resolve the explanation file for a sample input.

    Prefers a language-block `.rbx<suffix>` file over the plain `<suffix>` file,
    returning whether the resolved file is a blocks file. Errors if both exist.
    """
    if explanation_suffix is None:
        return None, False
    plain_path = input_path.with_suffix(explanation_suffix)
    blocks_path = input_path.with_suffix('.rbx' + explanation_suffix)
    plain_exists = plain_path.is_file()
    blocks_exists = blocks_path.is_file()
    if plain_exists and blocks_exists:
        console.console.print(
            f'[error]Both [item]{utils.relcwd(blocks_path)}[/item] and '
            f'[item]{utils.relcwd(plain_path)}[/item] exist for the same sample.[/error]'
        )
        console.console.print(
            f'[error]Use either the language-specific [item].rbx{explanation_suffix}[/item] '
            f'explanation or the language-agnostic [item]{explanation_suffix}[/item] '
            'explanation, but not both.[/error]'
        )
        raise typer.Exit(1)
    if blocks_exists:
        return blocks_path, True
    if plain_exists:
        return plain_path, False
    return None, False
```

Add `Tuple` to the `typing` import at the top:
`from typing import List, Optional, Tuple`

In `_get_statement_sample_from_entry`, add `explanation_from_blocks: bool = False`
next to the other locals (~line 74), and replace the explanation block inside
`process_additional_files` (~lines 97-100):

```python
    def process_additional_files(testcase: Testcase):
        nonlocal input_path, output_path, explanation_path
        nonlocal explanation_from_blocks, interaction
        explanation_path, explanation_from_blocks = _resolve_explanation_path(
            testcase.inputPath, explanation_suffix
        )
        ...  # pin_path / pout_path / interaction logic unchanged
```

Finally pass the flag into the returned model (~line 153):

```python
    return StatementSample(
        entry=entry,
        inputPath=input_path,
        outputPath=output_path,
        answerPath=answer_path,
        hasOutput=output_path is not None,
        checkOutput=should_check_output,
        interaction=_build_sample_interaction(entry, interaction)
        if interaction is not None
        else None,
        explanationPath=explanation_path,
        explanationFromBlocks=explanation_from_blocks,
    )
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rbx/box/test_testcase_sample_utils.py -v`
Expected: PASS (new tests + existing explanation tests still green).

**Step 5: Commit**

```bash
git add rbx/box/testcase_sample_utils.py tests/rbx/box/test_testcase_sample_utils.py
git commit -m "feat(statements): resolve per-sample .rbx.tex blocks explanations"
```

---

### Task 2: Select the language block when rendering blocks explanations

**Files:**
- Modify: `rbx/box/statements/builders.py` (`get_rbxtex_blocks` per-sample loop ~lines 296-311)
- Test: `tests/rbx/box/statements/test_builders.py`

**Step 1: Write failing tests**

Add to `tests/rbx/box/statements/test_builders.py` inside `class TestGetRbxTexBlocks`:

```python
    def test_get_rbxtex_blocks_selects_language_block(self, context, tmp_path):
        """A from-blocks explanation selects the block for context.lang."""
        package = Package(name='test-problem', timeLimit=1000, memoryLimit=256)
        statement = Statement(
            name='statement', path=pathlib.Path('stmt.tex'), type=StatementType.JinjaTeX
        )
        limits = LimitsProfile(timeLimit=1000, memoryLimit=256)

        explanation_file = tmp_path / '1.rbx.tex'
        explanation_file.write_text(
            'Ignored preamble.\n'
            '%- block en\nEnglish explanation.\n%- endblock\n'
            '%- block pt\nPortuguese explanation.\n%- endblock\n'
        )

        samples = [
            StatementSample(
                entry=create_dummy_entry(),
                inputPath=tmp_path / '1.in',
                outputPath=tmp_path / '1.out',
                explanationPath=explanation_file,
                explanationFromBlocks=True,
            )
        ]
        problem = StatementBuilderProblem(
            package=package, statement=statement, limits=limits, samples=samples
        )

        _, kwargs = get_rbxtex_blocks(b'', context, problem)
        explanation = kwargs['problem']['samples'][0].explanation
        assert 'English explanation.' in explanation
        assert 'Portuguese' not in explanation
        assert 'Ignored preamble' not in explanation

    def test_get_rbxtex_blocks_missing_language_block_warns(
        self, context, tmp_path, capsys
    ):
        """A from-blocks explanation without the language block yields no explanation."""
        package = Package(name='test-problem', timeLimit=1000, memoryLimit=256)
        statement = Statement(
            name='statement', path=pathlib.Path('stmt.tex'), type=StatementType.JinjaTeX
        )
        limits = LimitsProfile(timeLimit=1000, memoryLimit=256)

        explanation_file = tmp_path / '1.rbx.tex'
        explanation_file.write_text('%- block pt\nSó português.\n%- endblock\n')

        samples = [
            StatementSample(
                entry=create_dummy_entry(),
                inputPath=tmp_path / '1.in',
                outputPath=tmp_path / '1.out',
                explanationPath=explanation_file,
                explanationFromBlocks=True,
            )
        ]
        problem = StatementBuilderProblem(
            package=package, statement=statement, limits=limits, samples=samples
        )

        # context.lang == 'en', file only has 'pt'
        _, kwargs = get_rbxtex_blocks(b'', context, problem)
        assert kwargs['problem']['samples'][0].explanation is None
```

Note: the existing `test_get_rbxtex_blocks_block_overrides_explanation_path`
uses a plain (non-blocks) explanation file and must remain green — it verifies
the statement-level `explanation_0` block still wins over a per-sample file.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rbx/box/statements/test_builders.py -k "selects_language_block or missing_language_block" -v`
Expected: FAIL (the whole `.rbx.tex` body is rendered verbatim instead of the `en` block).

**Step 3: Implement**

In `rbx/box/statements/builders.py`, inside `get_rbxtex_blocks`, replace the
per-sample loop body (~lines 297-311) so it branches on the flag:

```python
        for i, sample in enumerate(item_kwargs['problem']['samples']):
            if i in statement_blocks.explanations:
                # Sample will come from a block, not from the file.
                sample.explanation = statement_blocks.explanations[i]
                continue
            if sample.explanation is None:
                # No explanation provided.
                continue
            if sample.explanationFromBlocks:
                # Language-specific explanation: render blocks and pick the one
                # matching the statement language. Content outside blocks is
                # ignored. Receives the same Jinja kwargs as a plain explanation.
                sample_blocks = render_jinja_blocks(
                    context.root,
                    sample.explanation.encode(),
                    mode=mode,
                    **item.build_inner_jinja_kwargs(),
                )
                selected = sample_blocks.blocks.get(context.lang)
                if selected is None:
                    console.console.print(
                        f'[warning]Sample explanation for testcase [item]{i}[/item] '
                        f'has no block for language [item]{context.lang}[/item]; '
                        'no explanation will be shown for this sample.[/warning]'
                    )
                sample.explanation = selected
                continue
            # Render samples.
            sample.explanation = render_jinja(
                context.root,
                sample.explanation.encode(),
                mode=mode,
                **item.build_inner_jinja_kwargs(),
            ).decode()
```

(`render_jinja_blocks` and `console` are already imported in this module.)

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/rbx/box/statements/test_builders.py -v`
Expected: PASS (new tests + existing explanation/externalize tests green).

**Step 5: Commit**

```bash
git add rbx/box/statements/builders.py tests/rbx/box/statements/test_builders.py
git commit -m "feat(statements): select language block for .rbx.tex sample explanations"
```

---

### Task 3: Make `.rbx.tex` the default explanation in the default preset

**Files:**
- Create: `rbx/resources/presets/default/problem/manual_tests/samples/000.rbx.tex`

**Step 1: Create the explanation file**

`rbx/resources/presets/default/problem/manual_tests/samples/000.rbx.tex`:

```latex
%- block en
The sum of the two integers in the first sample is $\VAR{1 + 2}$.
%- endblock
```

(The default preset's only statement language is `en`; see
`problem.rbx.yml` `statements[0].language`. Use a literal explanation if the
arithmetic VAR feels too cute — the goal is simply to demonstrate the
`%- block <lang>` format.)

**Step 2: Verify it builds**

Run (from a throwaway copy of the preset, or rely on the e2e/preset tests in
Task 5):
`uv run pytest tests/rbx/box -k "preset" -v` (sanity that nothing breaks).
Expected: PASS / no new failures.

**Step 3: Commit**

```bash
git add rbx/resources/presets/default/problem/manual_tests/samples/000.rbx.tex
git commit -m "feat(preset): demonstrate .rbx.tex sample explanation in default preset"
```

---

### Task 4: Document per-sample language-block explanations

**Files:**
- Modify: `docs/setters/statements/formats/rbxtex.md`

**Step 1: Add a "Sample explanations" section**

After the "Default blocks" section (after line ~123), add documentation covering
the three explanation options in priority order:

1. Statement-level `%- block explanation_N` (language-specific, in the statement file).
2. Per-sample `<sample>.rbx.tex` (recommended; language-specific blocks alongside the `.in`):

   ```latex
   %- block en
   This is the english explanation.
   %- endblock

   %- block pt
   Esta é a explicação em português.
   %- endblock
   ```

   - Content outside blocks is ignored.
   - Receives the same Jinja variables as the rest of the statement.
   - For Markdown statements the file is `<sample>.rbx.md`.
3. Per-sample `<sample>.tex` (language-agnostic, the same text for every language).

Note the rules: `.rbx.tex` is the recommended/default method; a sample may not
have both a `.rbx.tex` and a `.tex` file (it is an error); a `.rbx.tex` with no
block for the statement's language renders no explanation for that language.

**Step 2: Verify docs reference is consistent**

Run: `grep -n "explanation" docs/setters/statements/formats/rbxtex.md`
Expected: new section present, existing `explanation_N` table row intact.

**Step 3: Commit**

```bash
git add docs/setters/statements/formats/rbxtex.md
git commit -m "docs(statements): document per-sample language-block explanations"
```

---

### Task 5: Full verification

**Step 1: Run the affected test suites**

Run:
```bash
uv run pytest tests/rbx/box/test_testcase_sample_utils.py tests/rbx/box/statements -v
```
Expected: all PASS.

**Step 2: Lint & format**

Run:
```bash
uv run ruff check rbx/box/testcase_sample_utils.py rbx/box/statements/builders.py
uv run ruff format --check rbx/box/testcase_sample_utils.py rbx/box/statements/builders.py
```
Expected: clean (run `ruff format` if needed and amend via a new commit).

**Step 3: Broad sanity run**

Run: `uv run pytest --ignore=tests/rbx/box/cli -n auto -q`
Expected: no new failures relative to `main`.
