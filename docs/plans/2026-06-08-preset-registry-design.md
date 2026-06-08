# Design: Registry of presets (#535)

Status: approved (2026-06-08)

## Problem

`rbx` commands that need a preset (`rbx create`, `rbx contest create`,
`rbx contest` problem creation, `rbx presets create`) currently resolve the
preset via `get_preset_fetch_info_with_fallback`, which:

1. uses the active `.local.rbx` preset if one exists, otherwise
2. **silently falls back to the hardcoded `default`** bundled preset.

The issue asks rbx to instead keep a *registry* of presets, show that list to
the user when a preset must be chosen (and can't be inferred from a
`.local.rbx` folder), and require every preset to carry a description. The
registry must accept all sorts of fetch infos (remote URL, git repo, local rbx
folder, etc.) — which `PresetFetchInfo` / `get_preset_fetch_info` already
support.

## Decisions (from brainstorming)

- **Registry = merge** of a built-in registry file shipped in rbx resources
  (per installed version) and a user-local registry file in the app dir
  (initially empty).
- **Description lives in the preset** (`preset.rbx.yml`) as the canonical,
  author-defined home, AND is also stored (denormalized) in each registry
  entry so the picker can display it without resolving/fetching presets.
- **Add flow:** explicit `rbx presets registry add <uri>` command PLUS
  auto-offer to register when a new `-p <uri>` is used interactively.
- **Non-interactive (no TTY) with no `-p` and no active preset → error**
  requiring an explicit `--preset`. (Behavior change from today's silent
  default.)

## 1. Registry model & storage

Two YAML files, merged at runtime:

- **Built-in:** `rbx/resources/presets/registry.yml`
  (via `get_default_app_path() / 'presets' / 'registry.yml'`). Lists rbx's own
  presets — initially just `default`. Versioned with the installed rbx.
- **User-local:** `get_app_path() / 'presets' / 'registry.yml'` (Typer app
  dir). Absent → treated as empty.

**Merge semantics:** union by `name`; built-ins first, then user-only entries.
On a name collision the user entry wins (lets a user re-point a name). `default`
becomes a normal registry entry; it is no longer a hardcoded silent fallback.

## 2. Schemas

New `rbx/box/presets/registry_schema.py`:

```python
class RegistryPreset(BaseModel):
    name: str = NameField()
    uri: str
    description: str = ''

class PresetRegistry(BaseModel):
    presets: List[RegistryPreset] = []
```

Add `description: str = Field(default='')` to `Preset` in
`rbx/box/presets/schema.py`. The bundled `default` preset's `preset.rbx.yml`
and the built-in `registry.yml` both get a real description.

## 3. Resolution / picker

New resolution helper (`resolve_preset_choice(uri, local, *, interactive)`)
replacing the silent-default branch of `get_preset_fetch_info_with_fallback`:

- `uri` given → resolve via existing `get_preset_fetch_info`; if not already in
  the merged registry **and** TTY → offer to register it (auto-on-use).
- `uri` None **and** active `.local.rbx` preset → return `None` (use active —
  unchanged).
- `uri` None **and** no active preset:
  - **TTY** → `questionary.select` over the merged registry
    (`name — description`, `default` pre-highlighted) → resolve chosen entry's
    `uri`.
  - **No TTY** → error: "No preset selected; pass `--preset`."

TTY detection via `sys.stdin.isatty() and sys.stdout.isatty()`.

## 4. CLI commands

New `registry` sub-Typer under `presets`:

- `rbx presets registry ls` — table of merged entries (name, description, uri,
  source: built-in/user).
- `rbx presets registry add <uri>` — resolve fetch info, peek `preset.rbx.yml`
  (shallow fetch for remote / direct read for local) to capture name +
  description, write the entry to the user file.
- `rbx presets registry rm <name>` — remove from the user file (refuses/warns
  for built-ins).

## 5. Call sites updated

Everywhere `get_preset_fetch_info_with_fallback(None)` feeds creation:
`creation.create` (problem), `contest/main.py` (contest create, add/create
problem), `presets create` (`--preset` base). Auto-on-use registration prompt
fires post-install when a `-p <uri>` was not already registered.

## 6. Testing

- Registry load/merge precedence (built-in + user, name collision).
- `registry add/rm/ls` with mocked fetch.
- Resolution: no-TTY + no-preset + no `-p` → error; `-p` given → resolves;
  active preset → `None`; picker selection (mock `questionary.select`).
- Update `tests/rbx/box/presets/test_presets_additions_test.py` for the new
  no-fallback behavior.

## 7. Side effects to handle

- Regenerate dumped JSON schemas (new `Preset.description` field) via
  `dump_schemas.py`.
- Docs: presets page gets the `description` field + `registry` commands.

## Tradeoff flagged

The "error in non-interactive" choice is a real behavior change — anything that
today relies on the silent `default` (CI scripts, `rbx create foo` in a
pipeline) must now pass `-p default`. We keep `default` trivially selectable and
document the migration. A fallback-with-warning variant is a one-line change if
this proves too sharp.
