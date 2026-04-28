# Preset Variable Expansion

## Problem

Preset authors want to define placeholder strings (needles) in their preset files that get replaced with user-provided values when a problem or contest folder is created from the preset.

## Design

### Schema (`presets/schema.py`)

The schema is already defined:

- `VariableExpansion`: `needle`, `replacement` (ReplacementMode), `prompt` (Optional[str]), `glob` (List[str])
- `Expansion`: `problem` and `contest` lists of `VariableExpansion`
- `Preset.expansion`: `Expansion` field

**New**: A Pydantic `model_validator` on `VariableExpansion` that rejects configs where `replacement == PROMPT` but `prompt is None`.

### New functions (`presets/__init__.py`)

#### `_collect_expansions(expansions: List[VariableExpansion]) -> List[Tuple[str, str, List[str]]]`

Iterates over expansions. For each `PROMPT`-mode expansion, calls `questionary.text()` with the expansion's prompt string to collect a replacement value. Returns a list of `(needle, replacement_value, glob_patterns)` tuples. Called once before file copying begins.

#### `_should_expand_file(src: pathlib.Path, content: bytes) -> bool`

Returns `False` if:
- `src` is a symlink
- `content` contains a null byte in the first chunk (binary file)
- `content` exceeds 1024KB

Returns `True` otherwise.

#### `_expand_content(content: bytes, expansions, src_relative: pathlib.Path) -> bytes`

For each expansion, checks if glob patterns match `src_relative` (empty globs = match all). Performs needle-to-value string replacement on content. Returns the modified content.

### Integration into file copy

`_install_package_from_preset()`:
1. Calls `_collect_expansions()` before the file copy loop.
2. Passes collected expansions to `copy_preset_file()`.

`copy_preset_file()`:
1. Reads file content.
2. Calls `_should_expand_file()` — if false, writes as-is.
3. Calls `_expand_content()` to apply replacements.
4. Writes modified content to destination.

### Safety

- Symlinked files are never expanded (they point to shared preset files).
- Binary files (null-byte detection) are skipped.
- Files larger than 1024KB are skipped.

### Flow

```
install_problem / install_contest
  -> _install_package_from_preset()
    -> _collect_expansions()        # prompt user upfront
    -> for each file:
        copy_preset_file(..., expansions)
          -> read content
          -> _should_expand_file()  # skip symlinks, binaries, large files
          -> _expand_content()      # apply needle replacements
          -> write to dest
```
