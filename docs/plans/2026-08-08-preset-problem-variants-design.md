# Problem template variants in presets

**Issue:** [#264](https://github.com/rsalesc/rbx/issues/264) — Add variants for problem
templates in presets.

## Problem

A preset declares exactly one problem template and one contest template:

```yaml
problem: "problem"
contest: "contest"
```

Every problem created from the preset is a copy of that single directory. One
contest template is usually enough, but one problem template is not: a contest
routinely mixes batch problems, interactive problems, and subtask-scored
problems, and those differ in ways a single template cannot express.

The differences are structural, not cosmetic, and the package schema enforces
them as mutually exclusive:

- **Interactive (communication) tasks** set `type: communication` and declare an
  `interactor:`. `Package.check_checker_and_interactor_for_task_type` rejects an
  interactor on a batch problem and rejects a checker on a communication problem
  unless the interactor is legacy. The template also needs an `interactor.cpp`,
  an interaction-loop `sols/main.cpp`, a statement with an Interaction section,
  and a validator written against the interactor's input file rather than the
  solution's stdin.
- **Points (IOI-style) tasks** set `scoring: points` and carry `score:` and
  `dependencies:` on test groups plus expected `score:` ranges on solutions.
  `Package.check_scoring_fields` rejects all three when scoring is binary.

So a setter starting an interactive problem today copies the batch template and
then deletes and rewrites half of it. That is exactly the work a preset exists to
remove.

## Scope

In:

- Multiple named problem templates ("variants") per preset, each a complete
  template directory.
- The same mechanism for contest templates, for symmetry (unused by the bundled
  preset).
- Variant selection at creation time, recorded in the package lock so
  `rbx presets sync` tracks the right template.
- An `interactive` variant in the bundled `default` preset.

Out (deferred):

- Switching a package's variant after creation. Batch to interactive is a
  semantic rewrite (checker versus interactor, statement, solutions) that no
  file copy performs safely; a partial migration that looks complete is worse
  than none. Hand-editing `.preset-lock.yml` remains the escape hatch.
- Overlay or inheritance between variants. Each variant is a full directory.
  Presets that want to share files can use plain copies or in-preset symlinks
  (both already supported — see "Sharing files between variants").
- A `points` variant in the bundled preset. The mechanism supports it; shipping
  it is a separate call once `interactive` has proven the design.

## Why full directories

Three shapes were considered.

**Sibling template directories** (chosen). Each variant is a complete problem
template: `problem/`, `problem-interactive/`. Each stays a runnable package, so a
preset author can `cd` into it and run `rbx build` to test it — the workflow the
preset docs already recommend. Install, tracking, and sync only need to point at
a different directory; no new copy machinery. The cost is duplication of files
shared with the canonical template.

**Base plus overlay directories** were rejected. An overlay directory is not a
valid package, so it cannot be tested in place. Removing a base file (interactive
must not ship `wcmp.cpp`) needs a tombstone convention. Sync becomes ambiguous
about which layer a tracked asset came from, and the symlink rewriting in
`copy_preset_file` would have to reason across layers.

**One template with conditionals** (Jinja, or a `--interactive` flag) was
rejected for the same testability reason, plus unreadable branching in
`problem.rbx.yml`.

## Schema

`rbx/box/presets/schema.py` gains one model, reused for both package kinds:

```python
class PackageVariant(BaseModel):
    # Identifier of the variant, used in `--variant` and recorded in the lock.
    id: str  # ^[a-zA-Z][a-zA-Z0-9_-]*$, 'default' reserved for the canonical

    # Path of the template directory, relative to the preset directory.
    path: pathlib.Path

    # Human-readable description, shown in the variant picker.
    description: str = ''

    # Merged over the shared tracking/libraries/expansion for this kind.
    tracking: List[TrackedAsset] = []
    libraries: List[Library] = []
    expansion: List[VariableExpansion] = []
```

`Preset` gains `problemVariants: List[PackageVariant] = []` and
`contestVariants: List[PackageVariant] = []`.

Validation: ids are unique within a kind; `default` is rejected as an id; a
declared `path` must exist and be a directory when the preset is read from disk.

Merge semantics, shared config as the base:

- `tracking`: concatenate variant-first, then dedup by `path` via the existing
  `dedup_tracked_assets` (which keeps the first occurrence), so a variant entry
  overrides a shared one for the same path.
- `expansion`: same, dedup by `needle`.
- `libraries`: merge by `name`, variant wins. A variant can add a library or
  re-pin an existing one without restating the shared list.

A preset may declare variants with no canonical (`problem:` omitted). Then
`--variant` is mandatory: the picker appears on a TTY, and a non-TTY run errors
out. This mirrors the dispatcher mode of multi-contest packages, where no
contest is the default.

Both fields are additive, so published `Preset.json` consumers stay
forward-compatible.

## Resolution choke point

Three call sites reach for `preset.problem` / `preset.contest` independently
today — `install_problem` / `install_contest`, `_get_active_preset_package_path`,
and `get_preset_tracked_assets` — and `_copy_updated_assets` re-derives tracked
assets by passing the template directory back in as a root, which re-resolves the
preset from there. Variants would multiply that drift, so resolution collapses
into one function:

```python
@dataclasses.dataclass
class ResolvedTemplate:
    variant_id: Optional[str]     # None == canonical
    path: pathlib.Path            # absolute path to the template directory
    tracking: List[TrackedAsset]
    libraries: List[Library]
    expansion: List[VariableExpansion]

def resolve_template(
    preset: Preset,
    preset_path: pathlib.Path,
    *,
    is_contest: bool,
    variant: Optional[str],
) -> ResolvedTemplate: ...
```

`install_problem`, `install_contest`, `_get_active_preset_package_path`,
`get_preset_tracked_assets`, and `materialize_libraries` take a
`ResolvedTemplate` instead of a `Preset` plus an `is_contest` flag. An unknown
variant id raises with the available ids and their descriptions listed.

## Lock and sync

`PresetLock` gains `variant: Optional[str] = None`, where `None` means the
canonical template. Existing `.preset-lock.yml` files keep working unchanged.

`generate_lock` records the variant used at creation. `rbx presets sync` resolves
the template from the recorded variant, so tracked-asset diffs are taken against
the directory the package actually came from.

If a preset update removes a variant a package is locked to, sync fails with an
error naming the missing variant and pointing at `.preset-lock.yml`. It does not
fall back to the canonical template, which would overwrite an interactive
problem's tracked assets with batch ones.

## CLI

- `rbx create <name> -v/--variant <id>`
- `rbx contest add ... -v/--variant <id>`
- `rbx contest create ... -v/--variant <id>` (contest variants)

When the flag is omitted and the preset declares variants:

- On a TTY, a questionary picker lists `default` (preselected, when a canonical
  exists) plus each variant id and description.
- Off a TTY, the canonical is used silently, or the command errors if the preset
  has no canonical.

Presets with no variants behave exactly as today; no prompt appears and no
existing script changes behavior.

`rbx presets ls` lists the declared variants and marks the one the current
package is locked to.

## Sharing files between variants

Both approaches are supported for third-party presets and documented:

- **Plain copies.** The variant directory carries its own copy of every file.
  Self-contained and buildable in place.
- **In-preset symlinks.** A variant file may symlink to a shared directory
  elsewhere in the preset. `copy_preset_file` already handles this: a symlink
  whose target lies inside the preset but outside the template directory is
  rewritten, at install time, into a relative symlink into the installed
  package's `.local.rbx/`. Single source of truth, at the cost of the installed
  package containing symlinked files.

The bundled preset uses plain copies, so each variant stays self-contained, with
a test that diffs the files shared with the canonical template to catch drift.

## The bundled `interactive` variant

`rbx/resources/presets/default/problem-interactive/`, declared as:

```yaml
problem: "problem"
problemVariants:
  - id: interactive
    path: "problem-interactive"
    description: "Communication task with a testlib interactor"
```

Contents follow the guessing-game task already written up in
`docs/setters/grading/interactors.md`:

- `problem.rbx.yml` with `type: communication`, `interactor: {path: interactor.cpp}`,
  and no `checker`.
- `interactor.cpp` reading `N S` from the input file and answering `<`, `>`, `=`.
- `sols/main.cpp` running the interaction loop.
- `validator.cpp` validating the `N S` input file.
- `tests/gen.cpp` and `tests/testplan.txt` producing those pairs.
- `statement/statement.rbx.tex` with an Interaction section.
- `rbx.h` and `.gitignore`, copied from the canonical template.

The shared `tracking.problem` entry for `.gitignore` applies to the variant
automatically; no per-variant tracking is needed.

## Existing behaviors that must change

Two are load-bearing and would silently break:

- `install_preset_from_dir` cleans build artifacts from `preset.problem` and
  `preset.contest` only. It must clean every declared variant directory too;
  otherwise `rbx presets create -p <other-preset>` carries `build/` and `.box/`
  junk into the new preset's variant directories.
- Nested presets: running rbx inside a template directory is supported
  (`find_nested_preset` walks up to the preset root) and the preset docs
  encourage it, but the template is then resolved as `preset.problem`
  regardless of which directory you are standing in. With variants,
  `resolve_template` must map the nested working directory to its variant by
  longest-matching declared path, falling back to the canonical, so that syncing
  from inside `problem-interactive/` does not diff against `problem/`.

## Testing

- Schema: duplicate ids, the reserved `default` id, a nonexistent path, and the
  merge semantics for `tracking`, `libraries`, and `expansion`.
- `resolve_template`: canonical, named variant, unknown variant, and the
  no-canonical preset.
- Install and sync: a variant added to `rbx/testdata/presets/simple-preset`,
  covering install from the variant, the variant recorded in the lock, and sync
  diffing against the variant's tracked assets.
- Back-compat: a preset declaring no variants, and a lock file with no `variant:`
  key, both behaving exactly as before.
- Bundled preset: an e2e run where `rbx create -p default -v interactive` builds
  and runs green, alongside the existing `default-preset` e2e fixture.
- Drift: the files shared between `problem/` and `problem-interactive/` are
  identical.

## Documentation

- A "Problem template variants" section in `docs/setters/presets/index.md`:
  declaring variants, per-variant tracking and libraries, and both file-sharing
  approaches.
- A note in `docs/setters/grading/interactors.md` that the default preset ships
  an interactive variant, with the `rbx create -v interactive` invocation.
