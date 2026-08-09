# JSON schemas

Every rbx config file starts with a `# yaml-language-server` comment pointing at
a JSON Schema:

```yaml
---
# yaml-language-server: $schema=https://rsalesc.github.io/rbx-schemas/1.0/Package.json
name: "my-problem"
```

Editors that support the [YAML Language
Server](https://marketplace.visualstudio.com/items?itemName=redhat.vscode-yaml)
read that URL to give you completion, hover documentation and inline
validation. rbx writes and maintains the comment for you -- you should not need
to touch it.

## Where the schemas live

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

Schemas are published by the release itself, from either entrypoint:

| Entrypoint | How |
| :--- | :--- |
| Manual release | `mise run release` (bump + PyPI + schemas), or `mise run publish-schemas` on its own |
| Tag pushed to GitHub | the `publish-schemas` job in `release.yml` |

Both call `scripts/publish_schemas.py`, and publishing is idempotent -- whichever
runs second commits nothing. Prereleases (`rc`) are skipped, so an `rc` never
exposes a schema for a minor nobody can install yet.

The manual path is the primary one and pushes over SSH. The CI job is a
backstop that needs a cross-repo token (`GITHUB_TOKEN` cannot write to another
repository) and skips quietly when that secret is absent, so it never fails a
release on its own.

## Which version your files point at

The pinned version comes from the **`min_version` of the preset your package
was created from** -- the oldest rbx that preset claims to support.

That is a deliberate choice: it means your editor validates against the same
compatibility floor your package promises, so you find out at authoring time
when you have used a field that is newer than the floor. Files with no preset
in scope (the setter config, limits profiles, run logs) pin to the version of
rbx that wrote them.

Presets whose floor predates published schemas fall back to the older
unversioned URL, which stays published indefinitely. Existing files keep
working; nothing needs migrating.

## Newer fields, older pins

Published schemas do **not** reject unknown keys, so a field added after your
pinned minor will not be flagged as an error. Enum *values* are a different
story: a value added in a later version -- a new packaging format, say -- is
still rejected by an older pinned schema, because there is no way to express
"and anything added later" for an enumeration.

If your editor rejects a value your rbx accepts, raise the `min_version` in
your preset. That is the honest fix: the file really does require a newer rbx
than the preset currently claims.

Note that rbx itself is always stricter than the schema. Unknown keys are a
hard error at load time, so a typo is caught when you run rbx even if your
editor stayed quiet about it.

## Fixing up the header

`rbx fix` normalizes the header of your problem, contest and preset YAMLs,
adding it when missing and re-pointing it when the pin is stale:

```bash
rbx fix
```

It leaves a `$schema` that rbx does not own alone, so pointing a file at a local
or custom schema is a supported thing to do -- linting will not fight you over
it.
