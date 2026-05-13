# `rbx contest add_variant <id>`

**Issue:** [#432](https://github.com/rsalesc/rbx/issues/432) — Add a scaffolding
command for `contest.<id>.rbx.yml` variants. Follow-up from the multi-contest
work ([#431](https://github.com/rsalesc/rbx/issues/431),
[`docs/plans/2026-05-06-multi-contest-design.md`](2026-05-06-multi-contest-design.md)).

## Problem

After turning a contest directory into dispatcher mode (`use_variants: true`),
or when adding extra variants alongside a real `contest.rbx.yml`, users must
hand-author each `contest.<id>.rbx.yml` from scratch. We want a command that
scaffolds one for them, seeded from a preset's contest template.

## Command shape

```
rbx contest add_variant <id> [--preset/-p <name>]
```

Aliased `add_variant, av`, registered in `rbx/box/contest/main.py` next to
`init`/`add`.

- `<id>` — positional, required. Validated against
  `contest_state.VARIANT_ID_PATTERN` (`^[A-Za-z][A-Za-z0-9_-]*$`). Invalid →
  error + exit 1.
- `--preset/-p` — optional preset to scaffold from. When omitted, falls back to
  the active preset in the cwd, then the default preset, via the existing
  `presets.get_preset_fetch_info_with_fallback`. A URI preset is fetched.

## Behavior

### Preconditions / errors

1. **Must be inside a contest directory.** Resolve the contest root with
   `contest_package.find_contest_root()` — *not* `within_contest`, which dies in
   dispatcher mode when there is no canonical selection. `None` → error + exit 1.
2. **No flip required.** Works in both modes. Real-contest mode already supports
   sibling `contest.<id>.rbx.yml` files as additional selectable variants, and
   dispatcher mode obviously does. `contest.rbx.yml` is never modified.
3. **Variant must not already exist.** If `<contest_root>/contest.<id>.rbx.yml`
   exists → error + exit 1.
4. **Preset must define a contest template.** After resolving the preset, if
   `preset.contest is None` → error (same message style as `install_contest`).

### Scaffolding

- Read the preset's contest-template `contest.rbx.yml` via `ruyaml` (preserving
  comments/formatting), applying the same expansions `install_contest` uses
  (`_collect_expansions(preset.expansion.contest)`).
- Override two keys on the loaded mapping:
  - `name: <id>-c`
  - `problems: []` — the scaffold is empty; the user adds problems with
    `rbx contest add` after selecting the variant (`-C <id>`).
- Write to `<contest_root>/contest.<id>.rbx.yml` with `utils.save_ruyaml`.
- Statement templates / assets are **not** re-copied — the variant shares the
  directory's existing files (created when the contest dir was first set up). If
  the chosen preset references assets absent from the dir, that is a documented
  limitation; `add_variant` does not try to reconcile it.
- Validate the result parses as a `Contest` (`load_yaml_model`). On failure,
  remove the half-written file and error.
- `contest_utils.clear_all_caches()` and `find_contest_yaml.cache_clear()`
  afterwards. Print a success message pointing at the new file and reminding the
  user to select it with `-C <id>`.

### Refactor

Factor a small helper in `rbx/box/presets/__init__.py` — e.g.
`read_contest_template_yaml(preset, preset_path) -> (ruyaml.YAML, mapping)` —
so `add_variant` reuses the preset-template lookup + expansion logic instead of
duplicating `install_contest`'s internals. `install_contest` itself is unchanged
(it installs the whole dir; `add_variant` only wants the yaml).

## Out of scope

- `rbx contest remove_variant <id>` — tracked separately, pairs naturally.
- YAML inheritance / `extends:` between variants — still deferred (see the
  multi-contest design's follow-ups).
- `--from <existing-id>` copying — superseded by the preset-driven scaffold.

## Testing

### Unit — `tests/rbx/box/contest/test_contest_main.py`

Invoked via Typer's `CliRunner`, using the contest fixtures in
`tests/rbx/box/conftest.py`.

1. Invalid id (`"bad id"`, `1abc`) → exit 1, no file written.
2. Existing variant (`add_variant div1` in a dispatcher fixture that has
   `contest.div1.rbx.yml`) → exit 1, original file untouched.
3. Not inside a contest dir → exit 1.
4. Successful scaffold in dispatcher mode → `contest.div3.rbx.yml` exists, parses
   as `Contest`, `name == 'div3-c'`, `problems == []`.
5. Successful scaffold in real-contest mode → canonical `contest.rbx.yml`
   unchanged, new sibling discoverable via `discover_contest_variants`.
6. `--preset <name>` honored → scaffold reflects that preset's contest template
   (e.g. its statements config), still with `name`/`problems` overridden.

### e2e — `tests/e2e/testdata/multi-contest/e2e.rbx.yml`

Piggybacks on the existing `multi-contest/` fixture (dispatcher mode). Relies on
the default bundled preset having a contest template, like `rbx contest create`.

- `add-variant-scaffolds-sibling`: `contest add_variant div3` →
  `files_exist: [contest.div3.rbx.yml]`; then `contest list` →
  `stdout_contains: [div3]`; then `-C div3 contest summary` →
  `stdout_contains: [div3-c]`.
- `add-variant-existing-rejected`: `contest add_variant div1` → `expect_exit: 1`.
- `add-variant-invalid-id-rejected`: `contest add_variant "bad id"` →
  `expect_exit: 1`.

## Acceptance (from the issue)

- New command under `rbx/box/contest/main.py`. ✔
- Unit tests cover id validation, refusal on existing variant, successful
  scaffold, preset handling. ✔ (refusal on single-contest mode dropped — that
  mode is supported, per the multi-contest design.)
- e2e fixture `tests/e2e/testdata/multi-contest/` gains an `add_variant`
  scenario. ✔
