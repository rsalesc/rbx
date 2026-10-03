# JSON schemas

{{rbx}} config files start with a `# yaml-language-server` comment pointing at
a JSON Schema:

```yaml
---
# yaml-language-server: $schema=https://rsalesc.github.io/rbx-schemas/1.0/Package.json
name: "my-problem"
```

Editors that support the [YAML Language
Server](https://marketplace.visualstudio.com/items?itemName=redhat.vscode-yaml)
read that URL to give you completion, hover documentation and inline
validation. {{rbx}} writes and maintains the comment for you, so you should not
need to touch it.

## Where the schemas are published

Schemas are published per **minor** version at:

```
https://rsalesc.github.io/rbx-schemas/<major>.<minor>/<Model>.json
```

Alongside the version directories there are two conveniences:

| Path | Contents |
| :--- | :--- |
| `latest/<Model>.json` | The newest published minor. |
| `index.json` | The published versions and model names. |

Published models: `Package`, `Contest`, `Preset`, `PresetLock`,
`PresetRegistry`, `Environment`, `Statement`, `LimitsProfile`.

A new directory is published on every release, and a patch release
re-publishes its own minor -- so `1.4` always reflects the newest `1.4.x`.

Schemas are published by `mise run release`, or by `mise run publish-schemas` on its
own. Both call `scripts/publish_schemas.py`, which pushes over SSH. Publishing is
idempotent, so running it twice commits nothing the second time. Prereleases (`rc`)
are skipped, so an `rc` never exposes a schema for a minor nobody can install yet.

The `publish-schemas` job in `release.yml` calls the same script, but that workflow's
tag-push trigger is commented out, so it only runs through a manual `workflow_dispatch`.
It needs a cross-repo token (`GITHUB_TOKEN` cannot write to another repository) and is
skipped when that secret is absent, so it never fails a release on its own.

## Which version your files point at

The pinned version comes from the **`min_version` of the preset your package
was created from** -- the oldest {{rbx}} version that preset claims to support.

This is deliberate: your editor validates against the same compatibility floor
your package promises, so you find out while authoring when you have used a
field that is newer than the floor. Files with no preset in scope (the setter
config, limits profiles, run logs) pin to the version of {{rbx}} that wrote them.

Presets whose floor predates published schemas fall back to the older
unversioned URL, which stays published indefinitely. Existing files keep
working; nothing needs migrating.

## Newer fields, older pins

Published schemas do **not** reject unknown keys, so a field added after your
pinned minor will not be flagged as an error. Enum *values* behave differently.
A value added in a later version, such as a new packaging format, is still
rejected by an older pinned schema, since there is no way to say "and anything
added later" in an enumeration.

If your editor rejects a value your {{rbx}} accepts, raise the `min_version` in
your preset. That is the right fix: the file really does require a newer {{rbx}}
than the preset currently claims.

{{rbx}} itself is always stricter than the schema. Unknown keys are a hard
error at load time, so {{rbx}} catches a typo when you run it, even if your
editor did not flag it.

## Fixing up the header

`rbx fix` normalizes the header of your problem, contest and preset YAMLs,
adding it when missing and re-pointing it when the pin is stale:

```bash
rbx fix
```

It leaves alone any `$schema` that {{rbx}} does not own, so pointing a file at a
local or custom schema is supported, and linting will not complain about it.
