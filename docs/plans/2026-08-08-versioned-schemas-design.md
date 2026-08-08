# Versioned JSON schemas

Date: 2026-08-08

## Problem

`rbx` publishes JSON Schemas for its 8 user-facing config models (`Package`,
`Contest`, `Preset`, `PresetLock`, `PresetRegistry`, `Environment`,
`Statement`, `LimitsProfile`). They are generated at docs-build time by
`rbx/box/dump_schemas.py` (an mkdocs `gen-files` script) and referenced from a
single, unversioned URL built by `rbx.utils.uploaded_schema_path`:

```
https://rsalesc.github.io/rbx/schemas/<Model>.json
```

That URL always serves whatever is on `main`. Two consequences:

- A package pinned to an older `rbx` is validated against a schema newer than
  the tool that reads it.
- There is no way to say "this file conforms to the schema as of version X",
  even though presets already declare exactly that contract via `min_version`.

## Goals

1. Publish versioned, publicly fetchable copies of the schemas.
2. Make `rbx` write a version-pinned URL into the `# yaml-language-server`
   header, derived from the active preset's `min_version` — the minimum
   compatibility layer the package promises.

Non-goals: versioning the documentation site, byte-reproducible schema pins,
backfilling schemas for already-released versions.

## Decisions

### Hosting: a dedicated repo with its own Pages site

A new repository `rsalesc/rbx-schemas` serves GitHub Pages, laid out by minor:

```
/1.1/Package.json      /1.1/Contest.json      ... (all 8 models)
/1.2/Package.json      ...
/latest/Package.json   copy of the newest published minor
/index.json            {"versions": ["1.1", ...], "models": [...]}
```

Base URL: `https://rsalesc.github.io/rbx-schemas`, held in a single constant so
a custom domain can be adopted later without touching call sites (adding a
CNAME makes `github.io` redirect, so pins already in the wild keep resolving).

Publishing is a new job in `.github/workflows/release.yml`, triggered on
release tags after `pypi-publish`: check out `rbx` at the tag, generate the
schemas, push `<major>.<minor>/` into the schemas repo. Writes are additive, so
they never interact with the docs `gh-pages` branch, which
`mkdocs gh-deploy --force` fully replaces on every push to `main`.

Rejected alternatives:

- **Versioned dirs on the docs `gh-pages` branch.** Nice URLs on the docs
  domain, but `gh-deploy --force` replaces the branch tree, so anything written
  out-of-band is wiped on the next docs deploy. Surviving that requires either
  committing every snapshot into the repo and re-materializing the archive on
  each build, or migrating the docs to `mike`.
- **`raw.githubusercontent.com` pinned at the tag.** Zero infrastructure and
  immutable by construction, but `text/plain`, shared per-IP rate limits, and
  no backfill path for existing tags.
- **jsDelivr over a `schemas` branch.** Real CDN with no new repo, but a
  third-party dependency, immutable caching that makes a bad publish hard to
  correct, and it is blocked on some networks.

### Granularity: major.minor

The path carries `<major>.<minor>`; a `min_version` of `1.4.2` pins to `/1.4/`.
Roughly 8 directories a year instead of one per release, and a patch release
re-publishes its minor, which is the correction path for a bad schema.

The trade-off: minor URLs are *mutable*, so a pin is a compatibility contract,
not a reproducibility guarantee. A patch that changes a schema retroactively
changes what an existing pin resolves to.

### Forward tolerance: strip `additionalProperties: false`

Every model uses `ConfigDict(extra='forbid')`, so generated schemas reject
unknown keys — under a strict `1.4` pin, a user on `rbx` 1.6 would see editor
errors on fields their tool accepts. Both the release generator and
`dump_schemas.py` therefore recursively strip `additionalProperties: false`
before publishing, for versioned and unversioned URLs alike.

Limits of this, stated plainly:

- Relaxation covers unknown *keys* only. `required`, types, and **enums** are
  still enforced, so a value added to an enum after the pinned minor still
  shows as an editor error. The fix is to raise the preset's `min_version`,
  which is the honest signal.
- In-editor typo detection on keys is lost. `rbx` still hard-errors on unknown
  keys at load time, so typos are caught by the tool rather than the editor.

### Pin resolution

New module `rbx/box/schema_urls.py`. It cannot live in `rbx/utils.py`, which is
imported by `rbx.box.presets` — `model_to_yaml` will import it lazily inside
the function, a pattern that file already uses.

```
schema_url(model, root) ->
    v = min_version of nearest .local.rbx/preset.rbx.yml  (find_local_preset walks up)
        else installed rbx version
    if (major, minor) of v < SCHEMA_PIN_FLOOR:  unversioned URL
    else  f'{BASE}/{major}.{minor}/{model.__name__}.json'
```

- The preset read must **not** go through `get_preset_yaml` /
  `get_active_preset`, which call `_check_preset_compatibility` and can
  `typer.Exit(1)`. Writing a comment line must never abort a command: the
  reader is tolerant (returns `None` on missing/malformed YAML), silent, and
  `functools.cache`d, because `model_to_yaml` runs per test evaluation in
  `rbx/box/tasks.py` and cannot afford a directory walk each call.
- **Floor clamping** guarantees we never emit a URL that 404s — a missing
  schema makes the VSCode YAML extension raise a hard "unable to load schema"
  error. `SCHEMA_PIN_FLOOR` is the first minor this feature ships in (`1.1`);
  anything older, including the current `min_version` default of `0.14.0`,
  falls back to the unversioned URL. Old releases are not backfilled: it would
  mean importing ~20 historical minors under a modern Python in CI.
- Files with no preset in scope — setter config, `LimitsProfile`, eval and run
  logs, the user preset registry, any invocation outside a package — pin to the
  installed `rbx`'s own `major.minor`.
- RC tags (`*rc*`) do not publish; `1.5.0rc1` must not expose a `1.5` schema
  before `1.5.0` is installable.

### Write path

Three surfaces, all normalizing to the same helper:

1. `model_to_yaml` in `rbx/utils.py` — every machine-written YAML.
2. `fix_language_server` in `rbx/box/linting.py`, currently commented out since
   it was added, is enabled so `rbx lint` normalizes headers in problem,
   contest, and preset YAMLs.
3. Preset materialization rewrites the header of copied templates, so
   third-party presets that hardcode a URL are normalized on use.

Rewriting is idempotent and only touches headers pointing at an rbx-owned
schema host; a user pointing at a local or custom schema is left alone.

### Backwards compatibility

`dump_schemas.py` keeps emitting `https://rsalesc.github.io/rbx/schemas/<Model>.json`
on every docs deploy. Every file already in the wild keeps validating; nothing
about this change is breaking for users.

## Repo-side work

- `rbx/resources/presets/**/*.rbx.yml` and `tests/e2e/testdata/**` hardcode the
  unversioned URL and become lint-normalized. The default preset's
  `min_version` must be at or above `SCHEMA_PIN_FLOOR` for pinning to be
  exercised end to end.
- The schemas repo needs a deploy key or fine-grained PAT stored as an `rbx`
  secret; the default `GITHUB_TOKEN` cannot write to another repository.

## Testing

- Pin resolution: preset floor, no preset, below floor, malformed preset YAML,
  preset lookup from a nested problem inside a contest.
- The tolerant preset reader never raises and never prints, even against a
  preset whose `min_version` is incompatible with the installed version.
- `fix_language_server` idempotency, and that it leaves foreign schema URLs
  untouched.
- The `additionalProperties` relaxation transform.
- The set of models published at release time matches `dump_schemas.models`.
