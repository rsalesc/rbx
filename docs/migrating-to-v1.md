# Migrating to v1

{{rbx}} v1 removed a few {{boca}} configuration fields from `env.rbx.yml`. An environment that
still sets one fails to load, with an error that points to the replacement. A `languages` list
without a `template` also fails to load. Each section below shows the old form and the new one.

If you rely on the bundled `default` preset, there's nothing to do: it has already
been migrated. You only need to act if you maintain a **custom `env.rbx.yml`**
(`rbx environment` prints where the one in use lives, usually `.local.rbx/env.rbx.yml`).

## `bocaLanguage` → `languages`

The singular per-language `bocaLanguage` was replaced by the plural `languages` list.
The first entry is the canonical ({{rbx}} → BOCA) mapping; every entry is emitted as a
separate per-language script in the package.

```yaml title="Before"
languages:
  - name: "cpp"
    # ...
    extensions:
      boca:
        bocaLanguage: "cc"
```

```yaml title="After"
languages:
  - name: "cpp"
    # ...
    extensions:
      boca:
        languages: ["cc"]   # or ["cc", "cpp"] to emit both
```

## Env-level `languages` allowlist → per-language `languages`

The top-level `extensions.boca.languages` list (an allowlist of BOCA languages to
emit) was removed. In v1 the emitted set is the **union** of every {{rbx}} language's own
`languages`. Move each entry into the `languages` of the {{rbx}} language it belongs
to, and delete the env-level list.

```yaml title="Before"
extensions:
  boca:
    languages: ["cc", "cpp", "c", "py3"]   # env-level allowlist
```

```yaml title="After"
languages:
  - name: "cpp"
    extensions:
      boca: { languages: ["cc", "cpp"], template: "cc" }
  - name: "c"
    extensions:
      boca: { languages: ["c"], template: "c" }
  - name: "py"
    extensions:
      boca: { languages: ["py3"], template: "py3" }
# (env-level `extensions.boca.languages` removed)
```

!!! warning
    Both fields are named `languages` but live at different levels: the **per-language**
    one (under each language's `extensions.boca`) is the replacement; the **env-level**
    one (at the top of `env.rbx.yml`) is the one being removed.

## `template` is now required

When an {{rbx}} language declares `languages`, the `template` field becomes **required** —
the old fallback to the first `languages` entry is gone. Set it explicitly to one of
the on-disk template dirs: `c`, `cc`, `cpp`, `java`, `kt`, `py2`, `py3`.

```yaml title="Before"
extensions:
  boca:
    languages: ["cc", "cpp"]   # template inferred from "cc"
```

```yaml title="After"
extensions:
  boca:
    languages: ["cc", "cpp"]
    template: "cc"             # required, names the template dir to source scripts from
```

## Also removed: `maximumTimeError`

The env-level `extensions.boca.maximumTimeError` had been ignored since {{rbx}} started
emitting exact fractional time limits, and was removed in v1. If you used it to widen
the per-solution time budget, use `minRunningTime` instead (see
[Packaging: BOCA](setters/packaging/boca.md#minimum-running-time)).

```yaml title="Before"
extensions:
  boca:
    maximumTimeError: 1.5
```

```yaml title="After"
extensions:
  boca:
    minRunningTime: 1000   # milliseconds
```
