# `rbx vscode install` Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship the VS Code extension inside the `rbx-cp` wheel and add `rbx vscode install` to sideload it into VS Code / Cursor / Windsurf / VSCodium, plus a silent-by-default nudge when the installed extension is older than the bundled one.

**Architecture:** A new `rbx/box/vscode/` package holds pure, testable logic (editor detection from the environment, reading the editor's `extensions.json`, locating the bundled `.vsix`) and a thin Typer app that shells out to the editor CLI. `mise run vscode:vsix` builds the `.vsix` into `rbx/resources/vscode/`, and hatchling is told explicitly to ship it. See `docs/plans/2026-08-23-rbx-vscode-install-design.md`.

**Tech Stack:** Python 3.10+, Typer, Rich, pytest, hatchling, `@vscode/vsce`, mise.

---

## Background the implementer needs

- `TERM_PROGRAM=vscode` is set by VS Code **and every fork** in their integrated
  terminals. It says "we are in an integrated terminal", never *which* editor.
- `VSCODE_GIT_ASKPASS_NODE` / `VSCODE_GIT_ASKPASS_MAIN` are absolute paths into
  the running app bundle (`/Applications/Cursor.app/...`,
  `/usr/share/cursor/resources/app/...`). Matching a lowercased substring against
  them is how we tell the forks apart. Order matters: `cursor`, `windsurf`,
  `codium`, `code - insiders` must be tried **before** the generic `code`,
  because those paths contain `code` somewhere too.
- Each editor keeps its extensions in its own home directory: `~/.vscode`,
  `~/.vscode-insiders`, `~/.cursor`, `~/.windsurf`, `~/.vscode-oss`. Over SSH or
  in a devcontainer it is the `*-server` variant.
- `<root>/extensions/extensions.json` is a JSON **list**; each entry has
  `identifier.id` (e.g. `rsalesc.rbx-vscode`) and `version`. The extensions
  *directory* can hold several versions of one extension at once, so the
  directory listing is not authoritative -- `extensions.json` is.
- `rbx.config.get_resources_dir` raises `FileNotFoundError` when the directory is
  missing. An absent vsix is a normal state in a dev checkout, so resolve the
  vsix directory with `importlib.resources` directly instead.
- Existing helper to reuse, do NOT reimplement:
  `rbx.utils.check_version_compatibility_between(installed, required)` returns
  `SemVerCompatibility.OUTDATED` exactly when `installed < required`.
  `rbx.utils.is_valid_semver` and `rbx.utils.get_semver` are there too.
- Console theme keys: `item` (bold blue), `warning`, `error`, `success`, `info`.

---

### Task 1: Locate the bundled `.vsix`

**Files:**
- Create: `rbx/box/vscode/__init__.py` (empty)
- Create: `rbx/box/vscode/extension.py`
- Test: `tests/rbx/box/vscode/extension_test.py`

**Step 1: Write the failing test** — cover: absent directory returns `None`; a
single `rbx-vscode-0.2.0.vsix` yields version `0.2.0` and its path; with both
`0.2.0` and `0.10.0` present the newest wins (semver, not lexicographic); a
`.vsix` whose name does not parse is ignored.

**Step 2:** `uv run pytest tests/rbx/box/vscode/extension_test.py -v` →
FAIL, `ModuleNotFoundError: No module named 'rbx.box.vscode'`.

**Step 3: Implement**

```python
EXTENSION_ID = 'rsalesc.rbx-vscode'
_VSIX_NAME = re.compile(r'^rbx-vscode-(?P<version>.+)\.vsix$')


@dataclasses.dataclass(frozen=True)
class BundledVsix:
    path: pathlib.Path
    version: str


def vsix_dir() -> pathlib.Path:
    return pathlib.Path(str(importlib.resources.files('rbx'))) / 'resources' / 'vscode'


def bundled_vsix(directory: Optional[pathlib.Path] = None) -> Optional[BundledVsix]:
    directory = directory if directory is not None else vsix_dir()
    if not directory.is_dir():
        return None
    candidates = []
    for entry in directory.glob('*.vsix'):
        matched = _VSIX_NAME.match(entry.name)
        if matched is None:
            continue
        version = matched.group('version')
        if not utils.is_valid_semver(version):
            continue
        candidates.append(BundledVsix(path=entry, version=version))
    if not candidates:
        return None
    return max(candidates, key=lambda c: utils.get_semver(c.version))
```

**Step 4:** rerun → PASS. **Step 5:** commit
`feat(vscode): locate the bundled extension vsix`.

---

### Task 2: Detect which editor we are running inside

**Files:** modify `rbx/box/vscode/extension.py`, `tests/rbx/box/vscode/extension_test.py`

Every test passes an explicit `env` dict — never read or monkeypatch
`os.environ` here.

**Step 1: Write the failing test** — `{}` and `{'TERM_PROGRAM': 'iTerm.app'}`
give `None`; `{'TERM_PROGRAM': 'vscode'}` alone gives `code`; and each of these
app paths maps to its editor:

| `VSCODE_GIT_ASKPASS_NODE` | key |
|---|---|
| `/Applications/Cursor.app/Contents/Resources/app/out/node` | `cursor` |
| `/Applications/Windsurf.app/Contents/Resources/app/out/node` | `windsurf` |
| `/usr/share/codium/resources/app/out/node` | `codium` |
| `/Applications/Visual Studio Code - Insiders.app/.../node` | `code-insiders` |
| `/Applications/Visual Studio Code.app/.../node` | `code` |

Plus `editor_by_key('cursor').binary == 'cursor'` and `editor_by_key('nope') is None`.

**Step 2:** rerun → FAIL, no attribute `detect_editor`.

**Step 3: Implement**

```python
@dataclasses.dataclass(frozen=True)
class Editor:
    key: str
    label: str
    binary: str
    # Substring looked for in the running app's path. Checked in EDITORS order,
    # so the forks must come before plain 'code' -- their paths contain it too.
    marker: str
    # Home directories, most specific first. A remote (SSH, devcontainer) keeps
    # its extensions under the *-server variant.
    homes: Tuple[str, ...]


EDITORS = (
    Editor('cursor', 'Cursor', 'cursor', 'cursor', ('.cursor-server', '.cursor')),
    Editor('windsurf', 'Windsurf', 'windsurf', 'windsurf',
           ('.windsurf-server', '.windsurf')),
    Editor('codium', 'VSCodium', 'codium', 'codium', ('.vscode-oss',)),
    Editor('code-insiders', 'VS Code Insiders', 'code-insiders', 'code - insiders',
           ('.vscode-server-insiders', '.vscode-insiders')),
    Editor('code', 'VS Code', 'code', 'code', ('.vscode-server', '.vscode')),
)


def editor_by_key(key: str) -> Optional[Editor]: ...


def detect_editor(env) -> Optional[Editor]:
    if env.get('TERM_PROGRAM') != 'vscode':
        return None
    app_path = (
        env.get('VSCODE_GIT_ASKPASS_NODE') or env.get('VSCODE_GIT_ASKPASS_MAIN') or ''
    ).lower()
    for editor in EDITORS:
        if editor.marker in app_path:
            return editor
    # An integrated terminal that told us nothing else is VS Code by default.
    return editor_by_key('code')
```

**Step 4:** rerun → PASS. **Step 5:** commit
`feat(vscode): detect the editor from the integrated terminal env`.

---

### Task 3: Read the installed extension's version

**Files:** modify `rbx/box/vscode/extension.py`, `tests/rbx/box/vscode/extension_test.py`

**Step 1: Write the failing test** — with a helper writing
`<root>/extensions/extensions.json`: missing file → `None`; a list containing our
id → its version; a list without it → `None`; malformed JSON (`'{not json'`) →
`None` (a half-written file must never break `rbx run`); id matched
case-insensitively.

**Step 2:** rerun → FAIL, no attribute `installed_version`.

**Step 3: Implement**

```python
def editor_home(editor: Editor, home: Optional[pathlib.Path] = None) -> Optional[pathlib.Path]:
    home = home if home is not None else pathlib.Path.home()
    for candidate in editor.homes:
        root = home / candidate
        if root.is_dir():
            return root
    return None


def installed_version(root: pathlib.Path) -> Optional[str]:
    path = root / 'extensions' / 'extensions.json'
    try:
        entries = json.loads(path.read_text())
    except (OSError, ValueError):
        # A missing, unreadable or half-written extensions.json is not an error
        # worth surfacing -- it just means we cannot tell, so we say nothing.
        return None
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        identifier = entry.get('identifier') or {}
        if not isinstance(identifier, dict):
            continue
        if str(identifier.get('id', '')).lower() != EXTENSION_ID.lower():
            continue
        version = entry.get('version')
        if isinstance(version, str) and utils.is_valid_semver(version):
            return version
    return None
```

**Step 4:** rerun → PASS. **Step 5:** commit
`feat(vscode): read the installed extension version`.

---

### Task 4: Compose the nudge

**Files:** modify `rbx/box/vscode/extension.py`, `tests/rbx/box/vscode/extension_test.py`

The nudge is a pure function returning `Optional[str]`; the caller prints it.
That makes every silence rule testable without capturing console output.

**Step 1: Write the failing test** — `outdated_hint(env=..., home=...,
vsix_directory=...)` returns a string naming both versions and
`rbx vscode install` when installed `0.1.0` < bundled `0.2.0`, and `None` for:
`TERM_PROGRAM=iTerm.app`; nothing installed (never nag someone who has not opted
in); installed `0.9.0` newer than bundled (a marketplace copy is a fine state);
no vsix bundled at all.

**Step 2:** rerun → FAIL, no attribute `outdated_hint`.

**Step 3: Implement**

```python
def outdated_hint(env=None, home=None, vsix_directory=None) -> Optional[str]:
    """One line telling the user their editor extension lags the bundled one.

    None -- stay silent -- for every other state: not in an editor, nothing
    installed, already current, or anything unreadable.
    """
    env = env if env is not None else os.environ
    editor = detect_editor(env)
    if editor is None:
        return None
    bundled = bundled_vsix(vsix_directory)
    if bundled is None:
        return None
    root = editor_home(editor, home)
    if root is None:
        return None
    installed = installed_version(root)
    if installed is None:
        return None
    if (
        utils.check_version_compatibility_between(installed, bundled.version)
        is not utils.SemVerCompatibility.OUTDATED
    ):
        return None
    return (
        f'[info]The rbx {editor.label} extension is outdated '
        f'({installed} < {bundled.version}). Run [item]rbx vscode install[/item] '
        f'to re-sync it.[/info]'
    )
```

**Step 4:** rerun → PASS. **Step 5:** commit
`feat(vscode): compose the outdated-extension hint`.

---

### Task 5: The `rbx vscode install` command

**Files:**
- Create: `rbx/box/vscode/main.py`
- Modify: `rbx/box/cli.py` (imports; `add_typer` block ends ~line 126)
- Test: `tests/rbx/box/vscode/install_test.py`

Use `typer.testing.CliRunner` against `rbx.box.vscode.main.app`. Mock only
`subprocess.run`.

**Step 1: Write the failing test** — with `vsix_dir` monkeypatched to a tmp dir
holding `rbx-vscode-0.2.0.vsix` and `TERM_PROGRAM=vscode`: the command invokes
`['code', '--install-extension', <vsix>, '--force']` and exits 0;
`--editor cursor` uses `cursor` and needs no `TERM_PROGRAM`; with no bundled vsix
it exits 1 mentioning `mise run vscode:vsix`; outside an editor it exits 1
mentioning `--editor`; a `returncode=1, stderr='boom'` surfaces `boom` and exits 1.

**Step 2:** `uv run pytest tests/rbx/box/vscode/install_test.py -v` → FAIL,
`ModuleNotFoundError: No module named 'rbx.box.vscode.main'`.

**Step 3: Implement** `rbx/box/vscode/main.py` with a single `install` command:

1. `--editor` given → `editor_by_key`, unknown key exits 1.
2. otherwise `detect_editor(os.environ)`; `None` exits 1 telling the user to run
   it from the integrated terminal or pass `--editor`.
3. `bundled_vsix()`; `None` exits 1 pointing at `mise run vscode:vsix`.
4. `shutil.which(editor.binary)`; `None` exits 1 with the editor's
   "Shell Command: Install '<binary>' command in PATH" hint plus the literal
   command to run by hand.
5. `subprocess.run([editor.binary, '--install-extension', str(bundled.path),
   '--force'], capture_output=True, text=True)`; non-zero exits 1 printing
   `stderr or stdout`.
6. success prints the installed version and, on its own line, the reload hint —
   a freshly installed extension does not reliably activate in windows that are
   already open, so do not pretend it is live.

Register in `rbx/box/cli.py` after the `tooling.app` block:

```python
app.add_typer(
    vscode.app,
    name='vscode',
    cls=annotations.AliasGroup,
    help='Manage the rbx editor extension (sub-command).',
    rich_help_panel='Misc',
)
```

**Step 4:** `uv run pytest tests/rbx/box/vscode/ -v` and `uv run rbx vscode --help`
→ PASS, help lists `install`. **Step 5:** commit `feat(vscode): add rbx vscode install`.

---

### Task 6: Print the nudge after `rbx run` and `rbx ui`

**Files:** modify `rbx/box/cli.py` (`run` ends ~line 581; `ui` at 266-271),
`rbx/box/vscode/extension.py`

**Step 1: Write the failing test** — the hint logic is already covered by Task 4,
so test only that the print seam exists and is silent by default:
`print_outdated_hint(env={'TERM_PROGRAM': 'iTerm.app'})` writes nothing.

**Step 2:** rerun → FAIL, no attribute `print_outdated_hint`.

**Step 3: Implement**

```python
def print_outdated_hint(**kwargs) -> None:
    hint = outdated_hint(**kwargs)
    if hint is not None:
        console.console.print(hint)
```

In `run`, call it immediately before `if not ok:`. In `ui`, call it **after**
`ui_pkg.start()` returns — a fullscreen TUI wipes anything printed before it, so
the hint has to land when the UI exits. (This departs from the design doc's
"at `rbx ui` startup"; startup output is not visible.)

**Step 4:** rerun → PASS. **Step 5:** commit
`feat(vscode): nudge when the installed extension lags rbx`.

---

### Task 7: Build and ship the `.vsix`

**Files:** `vscode/package.json`, `mise.toml` (`build` task ~line 64),
`pyproject.toml` (`[tool.hatch.build.targets.wheel]` ~line 111), `.gitignore`

**Step 1:** add `"@vscode/vsce": "^3.0.0"` to `vscode/devDependencies` and a
script `"vsix": "vsce package --no-dependencies --out ../rbx/resources/vscode/"`.
`--no-dependencies` because esbuild already bundles everything into
`dist/extension.js`; without it vsce tries to resolve the npm tree.

**Step 2:** add the mise task and make the Python build depend on it:

```toml
[tasks."vscode:vsix"]
description = "Build the extension .vsix that ships inside the wheel"
dir = "vscode"
run = "npm run package && npm run vsix"

[tasks.build]
run = ["rm -rf dist/ rbx/resources/vscode/", "mise run vscode:vsix", "uv build"]
```

**Step 3: the step that fails invisibly.** The `.vsix` is a build output and
therefore gitignored, and hatchling excludes VCS-ignored files from wheels by
default. Without this the wheel builds cleanly, every test passes, and
`rbx vscode install` is broken for real users only:

```toml
[tool.hatch.build.targets.wheel]
packages = ["rbx"]
exclude = ["rbx/testdata", "docs"]
artifacts = ["rbx/resources/vscode/*.vsix"]
```

Add `rbx/resources/vscode/` to `.gitignore`.

**Step 4: verify the wheel actually contains it**

```bash
mise run vscode:vsix && uv build
python -c "
import zipfile, glob
names = zipfile.ZipFile(glob.glob('dist/*.whl')[0]).namelist()
hits = [n for n in names if n.endswith('.vsix')]
print(hits); assert hits, 'the wheel does not ship the vsix'
"
```

If `npm`/`vsce` is unavailable, stop and report rather than skipping this — it is
the whole point of the task.

**Step 5:** commit `build(vscode): ship the extension vsix inside the wheel`.

---

### Task 8: Docs and completion spec

**Step 1:** the drift test fails on any new CLI command, and
`mise run gen-completion-spec` is a no-op inside a worktree, so run it directly:

```bash
uv run python -m rbx.box.completion.serialize
uv run ruff format rbx/box/completion/_spec.py
```

**Step 2:** add an "Installing" section to `vscode/README.md`: run
`rbx vscode install` from the integrated terminal; it sideloads the `.vsix`
bundled with your `rbx` so the extension matches the CLI that produced the runs
it reads; reload the window afterwards; Cursor/Windsurf/VSCodium work the same
way, pass `--editor` if autodetection guesses wrong; it is on no marketplace.
Check `docs/` and `mkdocs.yml` for a page that should mention it.

**Step 3:**

```bash
uv run pytest tests/rbx/box/vscode/ tests/rbx/box/completion -v
uv run ruff check . && uv run ruff format --check .
```

**Step 4:** commit `docs(vscode): document rbx vscode install`.

---

## Final verification

```bash
uv run pytest --ignore=tests/rbx/box/cli -n auto
```

Expected: no new failures. Pre-existing local failures (C++/sandbox/docker) are
documented and are not caused by this change.
