# `rbx contest add_variant` Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `rbx contest add_variant <id> [--preset/-p <name>]` command that scaffolds a new `contest.<id>.rbx.yml` variant file, seeded from a preset's contest template.

**Architecture:** New Typer command in `rbx/box/contest/main.py`. It validates the id, ensures we're in a contest directory, refuses to overwrite an existing variant, then installs the chosen preset's contest template into a throwaway temp dir (reusing `presets.install_contest`), reads its `contest.rbx.yml`, overrides `name`→`<id>-c` and `problems`→`[]`, and writes it to `<contest_root>/contest.<id>.rbx.yml`. Works in both real-contest and dispatcher modes — `contest.rbx.yml` is never modified.

**Tech Stack:** Python, Typer, Pydantic v2, `ruyaml` (round-trip YAML), `pytest` + `typer.testing.CliRunner`, the e2e YAML DSL under `tests/e2e/`.

**Design doc:** [`docs/plans/2026-05-12-contest-add-variant-design.md`](2026-05-12-contest-add-variant-design.md)

---

## Background notes for the implementer

- The variant id regex lives at `rbx/box/contest/contest_state.py`: `VARIANT_ID_PATTERN` / `is_valid_variant_id(value: str) -> bool`.
- `rbx/box/contest/contest_package.py` has:
  - `find_contest_root(root: pathlib.Path) -> Optional[pathlib.Path]` — walks up to the dir containing `contest.rbx.yml`. **Use this** (NOT `within_contest`, which dies in dispatcher mode when no variant is selected).
  - `VARIANT_GLOB = 'contest.*.rbx.yml'`, `discover_contest_variants(contest_root)`.
  - `find_contest_yaml` is `@functools.cache`d — call `find_contest_yaml.cache_clear()` after writing a new variant file.
  - `load_yaml_model` (re-exported / imported there) is used as `load_yaml_model(path, Contest)`; `Contest` is `rbx.box.contest.schema.Contest`.
- `rbx/box/presets/__init__.py`:
  - `get_preset_fetch_info_with_fallback(uri: Optional[str], local: bool = False) -> Optional[PresetFetchInfo]` — returns `None` when `uri is None` **and** there is an active preset in the cwd (meaning "use the active preset"); otherwise returns fetch info (for the named/URI preset, or the bundled `default` preset).
  - `install_contest(dest_pkg: pathlib.Path, fetch_info: Optional[PresetFetchInfo] = None)` — when `fetch_info` is given, installs the preset into `dest_pkg/.local.rbx` first; then reads the active preset from `dest_pkg` and copies its `preset.contest` dir into `dest_pkg`. When `fetch_info` is `None`, it does **not** install anything and relies on an already-present `.local.rbx` under `dest_pkg`.
  - `install_preset_from_dir(src, dest, ensure_contest=False, ...)` — copies a preset directory tree to `dest`.
  - `get_active_preset_path(root=pathlib.Path()) -> pathlib.Path` — path to the cwd's active preset (`.local.rbx`).
- `rbx/box/contest/contest_utils.py` has `clear_all_caches()`.
- `rbx/utils` has `save_ruyaml(path, yaml_obj, data)` (used in `contest add`/`remove`). For loading raw round-trip YAML, `ruyaml.YAML()` then `.load(text)` (see `presets.get_ruyaml`).
- `rbx/box/contest/main.py` already imports: `pathlib`, `typer`, `console`, `utils`, `presets`, `contest_utils`, `contest_package`. The command file uses the alias style `@app.command('name, alias', help='...')` (see `init, i`, `add, a`).

### Test setup notes

- Existing unit tests live in `tests/rbx/box/contest/test_contest_main.py` and use `CliRunner`, `tmp_path`, `monkeypatch.chdir`, plus local helpers `_write_single_contest` / `_write_dispatcher`. Follow that style.
- To make `add_variant` resolve a preset **without network**, install a local preset into the test dir's `.local.rbx` so it becomes the active preset:
  `presets.install_preset_from_dir(simple_preset_testdata, tmp_path / '.local.rbx')` — see `tests/rbx/box/presets/test_presets.py` (`contest_package_with_preset` fixture, `simple_preset_testdata` fixture pointing at `rbx/testdata/presets/simple-preset`).
  - **Caveat:** `rbx/testdata/presets/simple-preset/contest/contest.rbx.yml` is *not* a valid `Contest` (it has `duration`/`startTime`/`problems[].label`). If the validation step rejects it, build a valid preset in the test instead via `rbx.box.testing.testing_preset.TestingPreset` + `preset.create_contest_package()` (see `preset_with_contest_package` fixture in `test_presets.py`), or write a tiny preset dir by hand with a `contest/contest.rbx.yml` of just `name: x` / `problems: []`. Resolve this when you hit it during TDD.
- For the e2e scenario, `rbx contest add_variant` inside `tests/e2e/testdata/multi-contest/` will need a preset available without network. The runner copies the whole package dir to a tmpdir, so the cleanest fix is to **check a minimal `.local.rbx/` preset into `tests/e2e/testdata/multi-contest/`** (a `preset.rbx.yml` with `contest: contest` + `env: env.rbx.yml` and a `contest/contest.rbx.yml` containing `name: placeholder` / `problems: []`, mirroring an existing tiny preset). Verify it isn't swallowed by a `.gitignore` (`git status` / `git check-ignore`); if it is, add an exception. Confirm `uv run pytest tests/e2e/testdata/multi-contest/ -v` is still offline.

---

## Task 1: Add the `add_variant` command (id validation + contest-dir + existing-file guards)

**Files:**
- Modify: `rbx/box/contest/main.py` (add a new `add_variant` command after `init`)
- Test: `tests/rbx/box/contest/test_contest_main.py`

**Step 1: Write the failing tests**

Add a `TestContestAddVariant` class to `tests/rbx/box/contest/test_contest_main.py`:

```python
class TestContestAddVariant:
    def test_invalid_id_rejected(self, runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_dispatcher(tmp_path)

        result = runner.invoke(contest_main.app, ['add_variant', 'bad id'])

        assert result.exit_code != 0, result.output
        assert not (tmp_path / 'contest.bad id.rbx.yml').exists()

    def test_invalid_id_leading_digit_rejected(self, runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_dispatcher(tmp_path)

        result = runner.invoke(contest_main.app, ['add_variant', '1abc'])

        assert result.exit_code != 0, result.output

    def test_not_in_contest_dir_rejected(self, runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(contest_main.app, ['add_variant', 'div3'])

        assert result.exit_code != 0, result.output

    def test_existing_variant_rejected(self, runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_dispatcher(tmp_path, 'div1')
        original = (tmp_path / 'contest.div1.rbx.yml').read_text()

        result = runner.invoke(contest_main.app, ['add_variant', 'div1'])

        assert result.exit_code != 0, result.output
        assert (tmp_path / 'contest.div1.rbx.yml').read_text() == original
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rbx/box/contest/test_contest_main.py::TestContestAddVariant -v`
Expected: errors / non-zero exit because the `add_variant` command doesn't exist (Typer prints "No such command").

**Step 3: Implement the command skeleton with the three guards**

In `rbx/box/contest/main.py`, add (place after the `init` command; reuse already-imported modules, add `import tempfile` and a `ruyaml` import as needed):

```python
@app.command('add_variant, av', help='Scaffold a new contest variant file.')
def add_variant(
    variant_id: Annotated[
        str,
        typer.Argument(
            help='Id of the new variant. Must match ^[A-Za-z][A-Za-z0-9_-]*$.',
        ),
    ],
    preset: Annotated[
        Optional[str],
        typer.Option(
            '--preset',
            '-p',
            help='Preset to scaffold the variant from. Defaults to the active '
            'preset in the current directory, then the default preset.',
        ),
    ] = None,
):
    from rbx.box.contest.contest_state import is_valid_variant_id

    if not is_valid_variant_id(variant_id):
        console.console.print(
            f'[error]Invalid variant id [item]{variant_id}[/item]. '
            r'Must match ^[A-Za-z][A-Za-z0-9_-]*$.[/error]'
        )
        raise typer.Exit(1)

    contest_root = contest_package.find_contest_root(pathlib.Path())
    if contest_root is None:
        console.console.print(
            '[error]Not inside a contest directory '
            '(no [item]contest.rbx.yml[/item] found).[/error]'
        )
        raise typer.Exit(1)

    dest = contest_root / f'contest.{variant_id}.rbx.yml'
    if dest.exists():
        console.console.print(
            f'[error]Variant file [item]{dest.name}[/item] already exists.[/error]'
        )
        raise typer.Exit(1)

    # (scaffolding implemented in Task 2)
    raise NotImplementedError
```

> Note: `find_contest_root` may currently be module-private or imported under a different name in `contest_package`; if it isn't exported, import it directly (`from rbx.box.contest.contest_package import find_contest_root`). Confirm the symbol exists before relying on it.

**Step 4: Run the tests to verify the guard tests pass**

Run: `uv run pytest tests/rbx/box/contest/test_contest_main.py::TestContestAddVariant -v`
Expected: the four guard tests PASS (they all exit non-zero before reaching `NotImplementedError`). Tests that exercise a successful scaffold come in Task 2.

**Step 5: Commit**

```bash
git add rbx/box/contest/main.py tests/rbx/box/contest/test_contest_main.py
git commit -m "feat(contest): add_variant command skeleton with input guards"
```

(Use the `/commit` skill workflow for the actual commit message — `feat(contest): ...`.)

---

## Task 2: Implement the preset-driven scaffold

**Files:**
- Modify: `rbx/box/contest/main.py`
- Test: `tests/rbx/box/contest/test_contest_main.py`

**Step 1: Write the failing tests**

Add to `TestContestAddVariant` (adjust the preset setup per the "Test setup notes" caveat above — these use the bundled `simple-preset`; swap to a `TestingPreset` or hand-written minimal preset if `Contest` validation rejects it):

```python
    def test_scaffold_in_dispatcher_mode(self, runner, tmp_path, monkeypatch, testdata_path):
        monkeypatch.chdir(tmp_path)
        _write_dispatcher(tmp_path)
        from rbx.box import presets
        presets.install_preset_from_dir(
            testdata_path / 'presets' / 'simple-preset', tmp_path / '.local.rbx'
        )

        result = runner.invoke(contest_main.app, ['add_variant', 'div3'])

        assert result.exit_code == 0, result.output
        dest = tmp_path / 'contest.div3.rbx.yml'
        assert dest.exists()
        from rbx.box.contest.schema import Contest
        from rbx.utils import model_from_yaml  # or whatever the loader is
        contest = model_from_yaml(Contest, dest.read_text())
        assert contest.name == 'div3-c'
        assert contest.problems == []

    def test_scaffold_in_real_contest_mode(self, runner, tmp_path, monkeypatch, testdata_path):
        monkeypatch.chdir(tmp_path)
        _write_single_contest(tmp_path)
        original = (tmp_path / 'contest.rbx.yml').read_text()
        from rbx.box import presets
        presets.install_preset_from_dir(
            testdata_path / 'presets' / 'simple-preset', tmp_path / '.local.rbx'
        )

        result = runner.invoke(contest_main.app, ['add_variant', 'extra'])

        assert result.exit_code == 0, result.output
        assert (tmp_path / 'contest.extra.rbx.yml').exists()
        assert (tmp_path / 'contest.rbx.yml').read_text() == original
        from rbx.box.contest import contest_package
        contest_package.find_contest_yaml.cache_clear()
        variants = contest_package.discover_contest_variants(tmp_path)
        assert 'extra' in variants
```

> Resolve the exact `Contest`-from-YAML loader name during implementation (grep `load_yaml_model` in `rbx/box/contest/contest_package.py`). The `testdata_path` fixture already exists (used in `tests/rbx/box/presets/test_presets.py`); if it isn't visible in `tests/rbx/box/contest/`, add it locally or import from a shared conftest.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rbx/box/contest/test_contest_main.py::TestContestAddVariant -v`
Expected: the two new tests FAIL (currently hit `NotImplementedError` → non-zero exit / no file written).

**Step 3: Implement the scaffold**

Replace the `raise NotImplementedError` in `add_variant` with:

```python
    from rbx.box.contest.contest_package import find_contest_yaml
    from rbx.box.contest.schema import Contest

    fetch_info = presets.get_preset_fetch_info_with_fallback(preset)

    with tempfile.TemporaryDirectory() as tmp:
        scratch = pathlib.Path(tmp)
        if fetch_info is None:
            # `None` means: use the active preset in the cwd. Install it into
            # the scratch dir so `install_contest` can resolve it there.
            presets.install_preset_from_dir(
                presets.get_active_preset_path(),
                scratch / '.local.rbx',
                ensure_contest=True,
            )
        presets.install_contest(scratch, fetch_info)
        template_text = (scratch / 'contest.rbx.yml').read_text()

    ru = ruyaml.YAML()
    data = ru.load(template_text)
    data['name'] = f'{variant_id}-c'
    data['problems'] = []
    utils.save_ruyaml(dest, ru, data)

    # Make sure the result is a valid Contest before declaring success.
    try:
        contest_package.load_yaml_model(dest, Contest)
    except Exception as e:  # noqa: BLE001 - want to surface any validation error
        dest.unlink(missing_ok=True)
        console.console.print(
            f'[error]Scaffolded variant did not validate against the contest '
            f'schema: {e}[/error]'
        )
        raise typer.Exit(1)

    find_contest_yaml.cache_clear()
    contest_utils.clear_all_caches()
    console.console.print(
        f'Created contest variant at [item]{dest}[/item]. '
        f'Select it with [item]-C {variant_id}[/item].'
    )
```

> Adjust import paths to match the codebase (`load_yaml_model` may already be importable from `contest_package`; `ruyaml` import style — `import ruyaml`). `install_contest` prints progress lines and (for some preset sources) may prompt; that's acceptable for the active/local-dir/default cases. If `model_to_yaml`/`save_ruyaml` differs, mirror what `contest add` does in the same file.

**Step 4: Run the tests**

Run: `uv run pytest tests/rbx/box/contest/test_contest_main.py::TestContestAddVariant -v`
Expected: all `TestContestAddVariant` tests PASS.

**Step 5: Run the full contest test module + lint**

Run:
```
uv run pytest tests/rbx/box/contest/ -v
uv run ruff check rbx/box/contest/main.py tests/rbx/box/contest/test_contest_main.py
uv run ruff format rbx/box/contest/main.py tests/rbx/box/contest/test_contest_main.py
```
Expected: all green, no lint errors.

**Step 6: Commit**

```bash
git add rbx/box/contest/main.py tests/rbx/box/contest/test_contest_main.py
git commit -m "feat(contest): scaffold add_variant from preset contest template"
```

---

## Task 3: `--preset` flag explicitly honored (unit coverage)

**Files:**
- Test: `tests/rbx/box/contest/test_contest_main.py`

**Step 1: Write the failing test**

```python
    def test_preset_flag_is_honored(self, runner, tmp_path, monkeypatch, testdata_path):
        monkeypatch.chdir(tmp_path)
        _write_dispatcher(tmp_path)
        # No active preset in cwd; pass one explicitly as a local dir.
        preset_dir = testdata_path / 'presets' / 'simple-preset'

        result = runner.invoke(
            contest_main.app, ['add_variant', 'div3', '--preset', str(preset_dir)]
        )

        assert result.exit_code == 0, result.output
        dest = tmp_path / 'contest.div3.rbx.yml'
        assert dest.exists()
        # Came from the simple-preset's contest template (e.g. it carried a key
        # the bare _write_dispatcher variants don't have), with name overridden.
        text = dest.read_text()
        assert 'div3-c' in text
```

> If `get_preset_fetch_info_with_fallback(str(preset_dir))` doesn't accept a bare local path, use the URI form the preset tests use, or install the preset and rely on the active-preset path. Adapt the assertion to a stable marker from whichever preset template you end up using.

**Step 2: Run it to verify it fails (or passes trivially) — confirm the flag path actually executes**

Run: `uv run pytest tests/rbx/box/contest/test_contest_main.py::TestContestAddVariant::test_preset_flag_is_honored -v`
Expected: PASS once `--preset` resolution works; if it errors on path handling, fix `add_variant` / the test until the explicit-preset path is exercised.

**Step 3: Commit**

```bash
git add tests/rbx/box/contest/test_contest_main.py
git commit -m "test(contest): cover add_variant --preset flag"
```

---

## Task 4: e2e scenarios

**Files:**
- Modify: `tests/e2e/testdata/multi-contest/e2e.rbx.yml`
- Possibly create: `tests/e2e/testdata/multi-contest/.local.rbx/...` (a minimal local preset so `add_variant` works offline — see "Test setup notes")

**Step 1: Make a preset available offline in the fixture**

Add a minimal preset under `tests/e2e/testdata/multi-contest/.local.rbx/`:
- `preset.rbx.yml`: `name: e2e`, `contest: contest`, `env: env.rbx.yml` (mirror the smallest existing preset's required fields — check `rbx/box/presets/schema.py` for what's mandatory; copy from `rbx/testdata/presets/simple-preset` and trim).
- `contest/contest.rbx.yml`: minimal valid `Contest` — `name: placeholder` and `problems: []` (plus `titles`/`statements` only if `Contest` requires them; keep it as small as the schema allows).
- `env.rbx.yml`: copy `rbx/testdata/presets/simple-preset/env.rbx.yml`.

Verify it's tracked by git (`git check-ignore tests/e2e/testdata/multi-contest/.local.rbx/preset.rbx.yml` should print nothing; if it's ignored, add a negation in the nearest `.gitignore`).

Sanity check offline: `uv run pytest tests/e2e/testdata/multi-contest/ -v` still passes with no network.

**Step 2: Add the scenarios to `tests/e2e/testdata/multi-contest/e2e.rbx.yml`**

```yaml
  - name: add-variant-scaffolds-sibling
    description: >-
      `rbx contest add_variant div3` writes contest.div3.rbx.yml; it then
      shows up in `contest list` and loads under `-C div3`.
    steps:
      - cmd: contest add_variant div3
        expect:
          files_exist:
            - contest.div3.rbx.yml
      - cmd: contest list
        expect:
          stdout_contains:
            - div3
      - cmd: -C div3 contest summary
        expect:
          stdout_contains:
            - div3-c

  - name: add-variant-existing-rejected
    description: 'add_variant refuses to overwrite an existing variant file.'
    steps:
      - cmd: contest add_variant div1
        expect_exit: 1

  - name: add-variant-invalid-id-rejected
    description: 'add_variant rejects an id failing the variant id regex.'
    steps:
      - cmd: contest add_variant "bad id"
        expect_exit: 1
```

> If `-C div3 contest summary` is noisy or slow, fall back to asserting on `contest list` only and/or reading the file via `files_exist`. Match the surrounding scenarios' style.

**Step 3: Run the e2e package**

Run: `uv run pytest tests/e2e/testdata/multi-contest/ -v`
Expected: all scenarios (old + new) PASS, offline.

**Step 4: Commit**

```bash
git add tests/e2e/testdata/multi-contest/
git commit -m "test(e2e): add_variant scenarios for multi-contest fixture"
```

---

## Task 5: Final verification

**Step 1: Full relevant test runs**

Run:
```
uv run pytest tests/rbx/box/contest/ -v
uv run pytest tests/e2e/testdata/multi-contest/ -v
uv run ruff check .
uv run ruff format --check .
```
Expected: all green.

**Step 2: Manual smoke (optional)**

In a scratch dir: `mkdir t && cd t && printf 'use_variants: true\n' > contest.rbx.yml && uv run rbx contest add_variant div1` → should create `contest.div1.rbx.yml` with `name: div1-c` / `problems: []`. (This will use the bundled default preset and may hit the network — that's expected for a real run.)

**Step 3: Update the design doc's "Refactor" note if it diverged**

The design proposed factoring a `read_contest_template_yaml` helper in `presets/__init__.py`; this plan instead reuses `install_contest` via a temp dir. If you kept the temp-dir approach, tweak the design doc's "Refactor" section to say so (or note the deviation in the PR description). Commit any doc change.

**Step 4: Open the PR (when ready)**

Per repo convention, branch is already isolated (worktree). Use the `/commit` skill for commits; create the PR with `gh` referencing issue #432.
