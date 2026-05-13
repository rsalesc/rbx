# `rbx irun -t` Honors Per-Testcase Validators — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `generate_standalone()` validate generated input against the validators of the specific `GenerationTestcaseEntry` being generated (so `rbx irun -t <group>/<i>` uses that test's group-level validator), instead of always using the package-level validators.

**Architecture:** Add an optional `entry: Optional[GenerationTestcaseEntry] = None` parameter to `generators.generate_standalone()`. When `entry` is given, the validators are `([entry.validator] if set else []) + entry.extra_validators` (an empty list ⇒ no input validation); when `entry` is `None`, behavior is unchanged (`package.get_all_validators()`). `solutions._generate_testcase_interactively()` forwards the extracted entry into `generate_standalone()` only on the `-t` path. Output validators and the `rbx stress` path are out of scope. See `docs/plans/2026-05-12-irun-honor-testcase-validators-design.md`.

**Tech Stack:** Python, Pydantic v2, Typer, pytest (async via `anyio`/`pytest`), `uv run pytest`.

**Background reading the implementer should skim first:**
- `rbx/box/generators.py:348-448` — `generate_standalone()` (the function to change).
- `rbx/box/generation_schema.py:69-116` — `GenerationTestcaseEntry` (`validator`, `extra_validators`, `output_validators`, `group_entry`, `make_interactive`).
- `rbx/box/testcase_extractors.py:174-388` — how an entry's `validator`/`extra_validators` are derived (package → group override; package + group + subgroup `extraValidators` accumulate).
- `rbx/box/validators.py:175-207` (`validate_one_off`), `:231-242` (`compile_validators_for_entries`), `:257-342` (`validate_testcases` — the existing per-entry-aware path we are mirroring).
- `rbx/box/solutions.py:607-743` — `_generate_testcase_interactively()` (the `-t` branch is `elif testcase_entry is not None:` around line 626).
- `tests/rbx/box/generators_test.py:337-493` — existing `generate_standalone` tests + `testing_pkg` usage patterns.
- `rbx/box/testing/testing_package.py` — `set_validator()`, `add_testgroup_from_glob(name, glob, validator=..., extra_validators=...)`, `add_file()`.
- Test validator sources already in the repo: `validators/int-validator.cpp` (accepts a single integer line — accepts `123\n`, rejects `123 456\n`) and `validators/extra-validator-odd.cpp` (requires the integer to be odd — accepts `123\n`, rejects `100\n`).

---

### Task 1: Add `entry` parameter to `generate_standalone()` (input validators from the entry)

**Files:**
- Modify: `rbx/box/generators.py` — `generate_standalone()` signature (~line 348-355) and the validation block (~line 412-431).
- Test: `tests/rbx/box/generators_test.py`

**Step 1: Write the failing tests**

Add these tests to `tests/rbx/box/generators_test.py` (near the other `generate_standalone` tests). Add any missing imports at the top of the file: `from rbx.box.generation_schema import GenerationTestcaseEntry` and `from rbx.box.testcase_extractors import extract_generation_testcases_from_groups`. (`GenerationMetadata`, `Testcase`, `CodeItem`, `ValidationError` are already imported.)

```python
async def test_generate_standalone_entry_validator_overrides_package(
    testing_pkg: testing_package.TestingPackage,
):
    # Package validator: any single integer is fine.
    testing_pkg.set_validator('validator.cpp', src='validators/int-validator.cpp')
    # Group "strict" replaces the package validator with an "odd integer" validator.
    testing_pkg.add_from_testdata(
        'extra-validator-odd.cpp', src='validators/extra-validator-odd.cpp'
    )
    even_in = testing_pkg.add_file('tests/strict/000.in')
    even_in.write_text('100\n')
    testing_pkg.add_testgroup_from_glob(
        'strict', 'tests/strict/*.in', validator='extra-validator-odd.cpp'
    )

    [entry] = await extract_generation_testcases_from_groups({'strict'})

    # Sanity: the extracted entry carries the group-level validator.
    assert entry.validator is not None
    assert entry.validator.path == pathlib.Path('extra-validator-odd.cpp')

    with pytest.raises(ValidationError):
        await generate_standalone(entry.metadata, entry=entry)


async def test_generate_standalone_entry_validator_inherits_package(
    testing_pkg: testing_package.TestingPackage,
):
    # Package validator: any single integer is fine.
    testing_pkg.set_validator('validator.cpp', src='validators/int-validator.cpp')
    # Group with no validator of its own -> inherits the package validator.
    loose_in = testing_pkg.add_file('tests/loose/000.in')
    loose_in.write_text('100\n')
    testing_pkg.add_testgroup_from_glob('loose', 'tests/loose/*.in')

    [entry] = await extract_generation_testcases_from_groups({'loose'})

    # '100\n' is a valid single integer -> no ValidationError.
    await generate_standalone(entry.metadata, entry=entry)


async def test_generate_standalone_entry_with_no_validators_skips_validation(
    testing_pkg: testing_package.TestingPackage,
):
    # Package has a validator that would reject this input...
    testing_pkg.set_validator('validator.cpp', src='validators/int-validator.cpp')

    input_file = testing_pkg.add_file('manual_tests/000.in')
    input_file.write_text('not an int\n')

    tmpd = testing_pkg.mkdtemp()
    entry = GenerationTestcaseEntry.make_interactive(
        copied_to=Testcase(inputPath=tmpd / '000.in')
    )
    entry.metadata.copied_from = Testcase(inputPath=input_file)
    assert entry.validator is None and entry.extra_validators == []

    # ...but the entry declares no validators, so generate_standalone runs none.
    await generate_standalone(entry.metadata, entry=entry)

    # Whereas without an entry it falls back to the package validator and fails.
    with pytest.raises(ValidationError):
        await generate_standalone(entry.metadata)
```

**Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/rbx/box/generators_test.py -k "entry_validator or entry_with_no_validators" -v`
Expected: FAIL — `generate_standalone()` does not accept an `entry` keyword argument (`TypeError: ... unexpected keyword argument 'entry'`).

**Step 3: Implement**

In `rbx/box/generators.py`, update the signature of `generate_standalone()`:

```python
async def generate_standalone(
    spec: GenerationMetadata,
    validate: bool = True,
    group_entry: Optional[TestcaseEntry] = None,
    entry: Optional[GenerationTestcaseEntry] = None,
    generator_digest: Optional[str] = None,
    validators_digests: Optional[Dict[str, str]] = None,
    progress: Optional[StatusProgress] = None,
):
```

Right after the function's docstring/`_print_error_header` definition (before `if spec.generator_call is not None:`), normalize `group_entry` from `entry` when not given explicitly:

```python
    if group_entry is None and entry is not None:
        group_entry = entry.group_entry
```

Then replace the line `all_validators = package.get_all_validators()` (around line 412) with:

```python
    if entry is not None:
        all_validators = ([entry.validator] if entry.validator is not None else []) + list(
            entry.extra_validators
        )
    else:
        all_validators = package.get_all_validators()
```

Leave the rest of the validation block (`if validate and all_validators:` … compile loop … `validate_one_off(...)` … `ValidationError`) exactly as is. Note: when `entry` is provided with no validators, `all_validators` is `[]`, so the `if validate and all_validators:` guard short-circuits and nothing runs — that is the intended "no input validation" behavior.

`GenerationTestcaseEntry` is already imported in `generators.py` (`from rbx.box.generation_schema import GenerationMetadata, GenerationTestcaseEntry`).

**Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/rbx/box/generators_test.py -k "entry_validator or entry_with_no_validators" -v`
Expected: PASS (3 tests).

Then run the full `generate_standalone` regression set:

Run: `uv run pytest tests/rbx/box/generators_test.py -k "generate_standalone" -v`
Expected: PASS (all, including the pre-existing package-level / `validators_digests` cache tests).

**Step 5: Commit**

```bash
git add rbx/box/generators.py tests/rbx/box/generators_test.py
git commit -m "feat(generators): generate_standalone honors testcase entry validators (#405)"
```

(Use the `/commit` skill per `CLAUDE.md` if available; the message above already follows the conventional-commits format the pre-commit hook enforces.)

---

### Task 2: Forward the extracted entry into `generate_standalone()` from `rbx irun -t`

**Files:**
- Modify: `rbx/box/solutions.py` — `_generate_testcase_interactively()` (the `await generate_standalone(...)` call around line 661, inside `if interactive_entry.metadata is not None:`).

**Step 1: Make the change**

In `rbx/box/solutions.py`, inside `_generate_testcase_interactively()`, the `elif testcase_entry is not None:` branch already does `interactive_entry = extracted_entry.model_copy(deep=True)`. We want to pass that entry to `generate_standalone` **only when it came from extraction** (the `-t` path) — not for the `make_interactive()` cases (typed-at-prompt or `-g` generator call), which must keep falling back to package-level validators.

The simplest robust way: track whether the entry is "real". Just before the `if generator is not None:` chain, the entry is `interactive_entry = GenerationTestcaseEntry.make_interactive(copied_to=testcase)`. In the `elif testcase_entry is not None:` branch (right after `interactive_entry = extracted_entry.model_copy(deep=True)` and `interactive_entry.metadata.copied_to = testcase`), set a local flag:

```python
        extracted_entry = extracted[0]
        interactive_entry = extracted_entry.model_copy(deep=True)
        # Replace destination with the irun testcase we're using.
        interactive_entry.metadata.copied_to = testcase
        entry_for_validation = interactive_entry
```

Initialize `entry_for_validation: Optional[GenerationTestcaseEntry] = None` near the top of the function (next to `interactive_entry = ...`). Then change the generation call:

```python
    # 1. Generate testcase.
    should_print_testcase = False
    if interactive_entry.metadata is not None:
        await generate_standalone(
            interactive_entry.metadata,
            entry=entry_for_validation,
            progress=progress,
            validate=validate,
        )
```

(Do not change the `generator is not None` branch or the prompt branch — `entry_for_validation` stays `None` there.)

**Step 2: Run a quick smoke check that nothing obvious broke**

Run: `uv run pytest tests/rbx/box/solutions_test.py -q`
Expected: PASS (this change is a no-op for non-`-t` flows and `solutions_test.py` doesn't exercise `-t`; it just confirms imports/signature still line up).

**Step 3: Commit**

```bash
git add rbx/box/solutions.py
git commit -m "fix(irun): validate -t testcase with its own validators (#405)"
```

---

### Task 3: Full verification

**Step 1: Run the box test suite (excluding the slow CLI tests, per CLAUDE.md)**

Run: `uv run pytest tests/rbx/box -n auto -q --ignore=tests/rbx/box/cli`
Expected: PASS / no new failures. (If pre-existing unrelated failures appear, note them — don't fix here.)

**Step 2: Lint & format**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: clean. If `ruff format --check` complains, run `uv run ruff format .` and re-commit.

**Step 3: Manual sanity (optional, if a quick fixture is handy)**

In a problem package that has a group with a stricter `validator:` than the package validator, run `uv run rbx irun -t <strict-group>/0 --no-check` with input that violates the group validator and confirm it now reports the group validator failing (previously it would have used the package validator). Not required if Task 1's tests cover it.

**Step 4: Final commit (only if Step 2 produced formatting changes)**

```bash
git add -A
git commit -m "style: ruff format"
```

---

## Notes / non-goals

- `entry.output_validators` is intentionally **not** wired here — `generate_standalone()` does input validation only, and irun's output handling is a separate path. If desired later, that's a follow-up.
- `rbx stress` (`stresses.py`) still uses package-level validators because it generates from a `GenerationMetadata` with no associated entry — unchanged on purpose.
- Entry validator paths are used as-is (not glob-expanded), mirroring the existing `validators.validate_testcases()` / `compile_validators_for_entries()` behavior. If a glob in a per-group `validator:`/`extraValidators:` is ever needed, fix it there too — out of scope here.
