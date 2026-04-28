# Preset Variable Expansion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable preset authors to define placeholder strings that get replaced with user-provided values when creating problem/contest folders from presets.

**Architecture:** Add a Pydantic validator to enforce prompt requirement, three new functions for expansion logic (`_collect_expansions`, `_should_expand_file`, `_expand_content`), and wire them into the existing `_install_package_from_preset` / `copy_preset_file` flow.

**Tech Stack:** Pydantic v2, questionary, pathlib, fnmatch

---

### Task 1: Add Pydantic validator to VariableExpansion

**Files:**
- Modify: `rbx/box/presets/schema.py:44-56`
- Test: `tests/rbx/box/presets/test_schema_validation.py` (create)

**Step 1: Write the failing test**

Create `tests/rbx/box/presets/test_schema_validation.py`:

```python
import pytest
from pydantic import ValidationError

from rbx.box.presets.schema import ReplacementMode, VariableExpansion


class TestVariableExpansionValidation:
    def test_prompt_mode_requires_prompt_field(self):
        with pytest.raises(ValidationError):
            VariableExpansion(
                needle='__NAME__',
                replacement=ReplacementMode.PROMPT,
                prompt=None,
            )

    def test_prompt_mode_accepts_prompt_field(self):
        ve = VariableExpansion(
            needle='__NAME__',
            replacement=ReplacementMode.PROMPT,
            prompt='Enter the problem name:',
        )
        assert ve.prompt == 'Enter the problem name:'

    def test_prompt_mode_is_default(self):
        ve = VariableExpansion(
            needle='__NAME__',
            prompt='Enter name:',
        )
        assert ve.replacement == ReplacementMode.PROMPT
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/presets/test_schema_validation.py -v`
Expected: `test_prompt_mode_requires_prompt_field` FAILS (no validator yet)

**Step 3: Write the validator**

In `rbx/box/presets/schema.py`, add a `model_validator` to `VariableExpansion`:

```python
from pydantic import BaseModel, Field, field_validator, model_validator

class VariableExpansion(BaseModel):
    # The needle to be replaced.
    needle: str

    # The mode to use for the replacement.
    replacement: ReplacementMode = Field(default=ReplacementMode.PROMPT)

    # The prompt to use for the replacement.
    # Only used when the replacement mode is PROMPT.
    prompt: Optional[str] = Field(default=None)

    # A glob pattern for the files to be expanded. If left empty, expand all files.
    glob: List[str] = Field(default=[])

    @model_validator(mode='after')
    def validate_prompt_required(self) -> 'VariableExpansion':
        if self.replacement == ReplacementMode.PROMPT and self.prompt is None:
            raise ValueError(
                'prompt is required when replacement mode is PROMPT'
            )
        return self
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/presets/test_schema_validation.py -v`
Expected: All 3 PASS

**Step 5: Commit**

```
feat(presets): add validation for VariableExpansion prompt requirement
```

---

### Task 2: Implement `_should_expand_file`

**Files:**
- Modify: `rbx/box/presets/__init__.py`
- Test: `tests/rbx/box/presets/test_expansion.py` (create)

**Step 1: Write the failing tests**

Create `tests/rbx/box/presets/test_expansion.py`:

```python
import pathlib

import pytest

from rbx.box.presets import _should_expand_file


class TestShouldExpandFile:
    def test_regular_text_file(self, tmp_path):
        f = tmp_path / 'hello.txt'
        f.write_text('hello world')
        content = f.read_bytes()
        assert _should_expand_file(f, content) is True

    def test_symlink_excluded(self, tmp_path):
        target = tmp_path / 'target.txt'
        target.write_text('hello')
        link = tmp_path / 'link.txt'
        link.symlink_to(target)
        content = target.read_bytes()
        assert _should_expand_file(link, content) is False

    def test_binary_file_excluded(self, tmp_path):
        f = tmp_path / 'binary.bin'
        f.write_bytes(b'hello\x00world')
        content = f.read_bytes()
        assert _should_expand_file(f, content) is False

    def test_large_file_excluded(self, tmp_path):
        f = tmp_path / 'large.txt'
        content = b'a' * (1024 * 1024 + 1)
        f.write_bytes(content)
        assert _should_expand_file(f, content) is False

    def test_exactly_1024kb_included(self, tmp_path):
        f = tmp_path / 'exact.txt'
        content = b'a' * (1024 * 1024)
        f.write_bytes(content)
        assert _should_expand_file(f, content) is True
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/presets/test_expansion.py::TestShouldExpandFile -v`
Expected: FAIL with ImportError

**Step 3: Implement `_should_expand_file`**

In `rbx/box/presets/__init__.py`, add:

```python
_MAX_EXPAND_SIZE = 1024 * 1024  # 1024 KB


def _should_expand_file(src: pathlib.Path, content: bytes) -> bool:
    """Check whether a preset file should undergo variable expansion."""
    if src.is_symlink():
        return False
    if len(content) > _MAX_EXPAND_SIZE:
        return False
    if b'\x00' in content:
        return False
    return True
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/presets/test_expansion.py::TestShouldExpandFile -v`
Expected: All 5 PASS

**Step 5: Commit**

```
feat(presets): add _should_expand_file for expansion safety checks
```

---

### Task 3: Implement `_expand_content`

**Files:**
- Modify: `rbx/box/presets/__init__.py`
- Modify: `tests/rbx/box/presets/test_expansion.py`

**Step 1: Write the failing tests**

Append to `tests/rbx/box/presets/test_expansion.py`:

```python
import pathlib

from rbx.box.presets import _expand_content


class TestExpandContent:
    def test_simple_replacement(self):
        content = b'Hello __NAME__, welcome!'
        expansions = [('__NAME__', 'Alice', [])]
        result = _expand_content(content, expansions, pathlib.PurePosixPath('file.txt'))
        assert result == b'Hello Alice, welcome!'

    def test_multiple_replacements(self):
        content = b'__A__ and __B__'
        expansions = [('__A__', 'X', []), ('__B__', 'Y', [])]
        result = _expand_content(content, expansions, pathlib.PurePosixPath('file.txt'))
        assert result == b'X and Y'

    def test_glob_match_applies(self):
        content = b'Hello __NAME__!'
        expansions = [('__NAME__', 'Alice', ['*.txt'])]
        result = _expand_content(content, expansions, pathlib.PurePosixPath('readme.txt'))
        assert result == b'Hello Alice!'

    def test_glob_no_match_skips(self):
        content = b'Hello __NAME__!'
        expansions = [('__NAME__', 'Alice', ['*.py'])]
        result = _expand_content(content, expansions, pathlib.PurePosixPath('readme.txt'))
        assert result == b'Hello __NAME__!'

    def test_empty_glob_matches_all(self):
        content = b'Hello __NAME__!'
        expansions = [('__NAME__', 'Alice', [])]
        result = _expand_content(content, expansions, pathlib.PurePosixPath('any/path/file.xyz'))
        assert result == b'Hello Alice!'

    def test_multiple_occurrences_replaced(self):
        content = b'__X__ is __X__'
        expansions = [('__X__', 'Y', [])]
        result = _expand_content(content, expansions, pathlib.PurePosixPath('f.txt'))
        assert result == b'Y is Y'

    def test_nested_path_glob(self):
        content = b'__NAME__'
        expansions = [('__NAME__', 'val', ['subdir/*.tex'])]
        result = _expand_content(content, expansions, pathlib.PurePosixPath('subdir/main.tex'))
        assert result == b'val'
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/presets/test_expansion.py::TestExpandContent -v`
Expected: FAIL with ImportError

**Step 3: Implement `_expand_content`**

In `rbx/box/presets/__init__.py`, add:

```python
import fnmatch

def _expand_content(
    content: bytes,
    expansions: List[Tuple[str, str, List[str]]],
    src_relative: pathlib.PurePosixPath,
) -> bytes:
    """Apply variable expansions to file content."""
    for needle, value, globs in expansions:
        if globs and not any(
            fnmatch.fnmatch(str(src_relative), g) for g in globs
        ):
            continue
        content = content.replace(needle.encode(), value.encode())
    return content
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/presets/test_expansion.py::TestExpandContent -v`
Expected: All 7 PASS

**Step 5: Commit**

```
feat(presets): add _expand_content for needle replacement in preset files
```

---

### Task 4: Implement `_collect_expansions`

**Files:**
- Modify: `rbx/box/presets/__init__.py`
- Modify: `tests/rbx/box/presets/test_expansion.py`

**Step 1: Write the failing tests**

Append to `tests/rbx/box/presets/test_expansion.py`:

```python
from unittest import mock

from rbx.box.presets import _collect_expansions
from rbx.box.presets.schema import ReplacementMode, VariableExpansion


class TestCollectExpansions:
    def test_prompt_mode_asks_user(self):
        expansions = [
            VariableExpansion(
                needle='__NAME__',
                replacement=ReplacementMode.PROMPT,
                prompt='Enter the problem name:',
            ),
        ]
        with mock.patch('rbx.box.presets.questionary') as mock_q:
            mock_q.text.return_value.ask.return_value = 'my-problem'
            result = _collect_expansions(expansions)

        assert result == [('__NAME__', 'my-problem', [])]
        mock_q.text.assert_called_once_with('Enter the problem name:')

    def test_multiple_expansions(self):
        expansions = [
            VariableExpansion(
                needle='__A__', prompt='A?', glob=['*.txt'],
            ),
            VariableExpansion(
                needle='__B__', prompt='B?',
            ),
        ]
        with mock.patch('rbx.box.presets.questionary') as mock_q:
            mock_q.text.return_value.ask.side_effect = ['val_a', 'val_b']
            result = _collect_expansions(expansions)

        assert result == [
            ('__A__', 'val_a', ['*.txt']),
            ('__B__', 'val_b', []),
        ]

    def test_empty_expansions(self):
        result = _collect_expansions([])
        assert result == []
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/presets/test_expansion.py::TestCollectExpansions -v`
Expected: FAIL with ImportError

**Step 3: Implement `_collect_expansions`**

In `rbx/box/presets/__init__.py`, add:

```python
from rbx.box.presets.schema import VariableExpansion

def _collect_expansions(
    expansions: List[VariableExpansion],
) -> List[Tuple[str, str, List[str]]]:
    """Prompt the user for expansion values and return (needle, value, globs) tuples."""
    result: List[Tuple[str, str, List[str]]] = []
    for exp in expansions:
        if exp.replacement == ReplacementMode.PROMPT:
            assert exp.prompt is not None
            value = questionary.text(exp.prompt).ask()
            result.append((exp.needle, value, exp.glob))
    return result
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/presets/test_expansion.py::TestCollectExpansions -v`
Expected: All 3 PASS

**Step 5: Commit**

```
feat(presets): add _collect_expansions for user-prompted replacements
```

---

### Task 5: Wire expansion into `_install_package_from_preset` and `copy_preset_file`

**Files:**
- Modify: `rbx/box/presets/__init__.py:359-406` (`copy_preset_file`)
- Modify: `rbx/box/presets/__init__.py:832-868` (`_install_package_from_preset`)
- Modify: `rbx/box/presets/__init__.py:871-922` (`install_contest`, `install_problem`)
- Modify: `tests/rbx/box/presets/test_expansion.py`

**Step 1: Write the failing integration test**

Append to `tests/rbx/box/presets/test_expansion.py`:

```python
from rbx.box.presets import copy_preset_file


class TestCopyPresetFileExpansion:
    def test_expansion_applied_to_regular_file(self, tmp_path):
        preset_dir = tmp_path / 'preset'
        preset_dir.mkdir()
        src = preset_dir / 'hello.txt'
        src.write_text('Hello __NAME__!')

        dest = tmp_path / 'dest' / 'hello.txt'
        expansions = [('__NAME__', 'World', [])]

        copy_preset_file(src, dest, preset_dir, tmp_path, expansions=expansions)

        assert dest.read_text() == 'Hello World!'

    def test_no_expansion_on_symlink(self, tmp_path):
        preset_dir = tmp_path / 'preset'
        preset_dir.mkdir()
        target = preset_dir / 'target.txt'
        target.write_text('Hello __NAME__!')
        src = preset_dir / 'link.txt'
        src.symlink_to(target)

        dest = tmp_path / 'dest' / 'link.txt'
        expansions = [('__NAME__', 'World', [])]

        copy_preset_file(src, dest, preset_dir, tmp_path, expansions=expansions)

        # Symlink should be copied as symlink, content not expanded
        assert dest.is_symlink()

    def test_no_expansion_when_empty(self, tmp_path):
        preset_dir = tmp_path / 'preset'
        preset_dir.mkdir()
        src = preset_dir / 'hello.txt'
        src.write_text('Hello __NAME__!')

        dest = tmp_path / 'dest' / 'hello.txt'

        copy_preset_file(src, dest, preset_dir, tmp_path)

        assert dest.read_text() == 'Hello __NAME__!'
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/presets/test_expansion.py::TestCopyPresetFileExpansion -v`
Expected: FAIL (copy_preset_file doesn't accept `expansions` yet)

**Step 3: Modify `copy_preset_file`**

Update `copy_preset_file` in `rbx/box/presets/__init__.py`:

```python
def copy_preset_file(
    src: pathlib.Path,
    dst: pathlib.Path,
    preset_package_path: pathlib.Path,
    preset_path: pathlib.Path,
    force_symlink: bool = False,
    expansions: Optional[List[Tuple[str, str, List[str]]]] = None,
):
    if dst.is_file() or dst.is_symlink():
        dst.unlink(missing_ok=True)
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not src.is_symlink() and not force_symlink:
        content = src.read_bytes()
        if expansions and _should_expand_file(src, content):
            relative = pathlib.PurePosixPath(src.relative_to(preset_package_path))
            content = _expand_content(content, expansions, relative)
        dst.write_bytes(content)
        return

    # ... rest of symlink handling unchanged ...
```

**Step 4: Modify `_install_package_from_preset`**

Add `expansions` parameter and pass it through:

```python
def _install_package_from_preset(
    preset_path: pathlib.Path,
    preset_package_inner_path: pathlib.Path,
    dest_pkg: pathlib.Path,
    tracked_assets: List[TrackedAsset],
    expansions: Optional[List[Tuple[str, str, List[str]]]] = None,
):
    preset_package_path = preset_path / preset_package_inner_path
    if not preset_package_path.is_dir():
        # ... unchanged error handling ...
        raise typer.Exit(1)

    for file in _glob_while_ignoring(preset_package_path, '*', recursive=True):
        if not file.is_file():
            continue
        copy_preset_file(
            file,
            dest_pkg / file.relative_to(preset_package_path),
            preset_package_path,
            preset_path,
            expansions=expansions,
        )

    for asset in tracked_assets:
        if not asset.symlink:
            continue
        copy_preset_file(
            preset_package_path / asset.path,
            dest_pkg / asset.path,
            preset_package_path,
            preset_path,
            force_symlink=True,
        )
```

**Step 5: Modify `install_problem` and `install_contest`**

In `install_problem`, after getting the preset, collect and pass expansions:

```python
def install_problem(
    dest_pkg: pathlib.Path, fetch_info: Optional[PresetFetchInfo] = None
):
    # ... existing fetch logic unchanged ...
    preset = get_active_preset(dest_pkg)
    preset_path = find_local_preset(dest_pkg)
    # ... existing validation unchanged ...

    expansions = _collect_expansions(preset.expansion.problem)

    console.console.print(...)
    _install_package_from_preset(
        preset_path, preset.problem, dest_pkg, preset.tracking.problem,
        expansions=expansions,
    )
    clean_copied_problem_dir(dest_pkg)
```

Same pattern for `install_contest` using `preset.expansion.contest`.

**Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/rbx/box/presets/test_expansion.py -v`
Expected: All PASS

**Step 7: Run full preset test suite**

Run: `uv run pytest tests/rbx/box/presets/ -v`
Expected: All PASS (no regressions)

**Step 8: Commit**

```
feat(presets): wire variable expansion into preset installation
```

---

### Task 6: Lint and final verification

**Step 1: Run linter**

Run: `uv run ruff check rbx/box/presets/ tests/rbx/box/presets/`

**Step 2: Fix any lint issues**

**Step 3: Run formatter**

Run: `uv run ruff format rbx/box/presets/ tests/rbx/box/presets/`

**Step 4: Run full test suite**

Run: `uv run pytest tests/rbx/box/presets/ -v`
Expected: All PASS

**Step 5: Commit if any fixes**

```
style(presets): lint and format variable expansion code
```
