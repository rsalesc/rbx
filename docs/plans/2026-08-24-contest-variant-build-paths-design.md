# Variant-scoped contest build paths

**Issue:** [#753](https://github.com/rsalesc/rbx/issues/753) tracks the deferred
problem-level half. This design covers the contest-level half.

## Problem

Contest variants share one physical directory by design (see
[multi-contest design](2026-05-06-multi-contest-design.md)). `contest.rbx.yml`
and its `contest.<id>.rbx.yml` siblings all resolve to the same contest root, and
`get_contest_build_path()` is `find_contest() / environment.get_build_dir()`.
Nothing in any output path carries the variant id, so every variant writes its
artifacts on top of the previous one's.

Three contest-level artifacts collide:

| Artifact | Path | Site |
|---|---|---|
| Contest statements and documents | `build/<name>[-<profile>].pdf` | `build_contest_statements.py:121` |
| Statement scratch overlay | `build/statements/<name>/` | `build_contest_statements.py:474` |
| Contest packages | `build/<packager-filename>.zip` | `packager.py:202` via `contest_main.py:83` |

The overlay case is the sharpest: `_fresh_dir` wipes the directory on every
build, so interleaved builds of two variants destroy each other's scratch state
rather than merely overwriting a final file.

Note this bites a plain real contest with siblings too, not only dispatcher
mode: the canonical and its siblings share the same `build/`.

## Scope

In: the three contest-level artifacts above, and `rbx clean`.

Out: problem-level artifacts. `problems/A/build/statement-<lang>.pdf` (built with
contest chrome) and `problems/A/build/<packager>.zip` are equally
variant-dependent in content and variant-agnostic in path, but fixing them needs
a split between variant-invariant work (generated tests, compiled solutions,
caches — expensive, must stay shared) and variant-dependent output. Deferred to
[#753](https://github.com/rsalesc/rbx/issues/753); the docs carry a warning until
it lands.

## Layout

Non-default variants nest under the contest build root; the canonical keeps
today's paths exactly.

```
contest/
  contest.rbx.yml          # canonical (real contest)
  contest.div2.rbx.yml
  build/
    statements/            # canonical scratch
    statement-en.pdf       # canonical output
    contest-boca.zip
    variants/
      div2/
        statements/
        statement-en.pdf
        contest-boca.zip
```

In dispatcher mode there is no canonical, so nothing lands at the `build/` root
and every variant lives under `build/variants/<id>/`.

Nesting rather than a sibling `build-<id>/` root keeps preset `.gitignore`
entries for `build/` working unchanged, keeps `rbx clean` able to wipe
everything by removing one directory, and puts variant subtrees behind a
`variants/` container so a variant id can never clash with `build/statements/`.

Keeping the canonical at the bare `build/` was chosen over a symmetric
`build/_default/` because the overwhelming majority of packages are
single-contest, and moving their output path would break scripts, docs and
habits for a problem those packages do not have.

## Mechanism

One choke point does the work. All three collision sites already read through
`get_contest_build_path`, directly or via the derived
`get_contest_statements_build_path`, so none of them are touched.

`rbx/box/contest/contest_package.py` gains:

```python
def get_selected_variant_id(root=pathlib.Path()) -> Optional[str]:
    """The id of the resolved contest variant, or None for the canonical."""
```

It resolves the yaml through `find_contest_yaml` — the same resolution the rest
of the codebase uses, so there is no second path to drift — and reads the id off
the resolved filename: `contest.rbx.yml` yields `None`, `contest.<id>.rbx.yml`
yields `<id>`. Validity is already enforced at discovery
(`discover_contest_variants`), so no re-validation here.

`get_contest_root_build_path(root)` is today's `get_contest_build_path` body
under a new name — the *unscoped* accessor. `get_contest_build_path` becomes:

```python
@functools.cache
def get_contest_build_path(root=pathlib.Path()) -> pathlib.Path:
    build = get_contest_root_build_path(root)
    vid = get_selected_variant_id(root)
    return build if vid is None else build / 'variants' / vid
```

`get_contest_statements_build_path` is unchanged; it derives from the above.

## `rbx clean`

`_clean_build_dirs` (`cli.py:1737`) switches to `get_contest_root_build_path`,
so a clean wipes `build/` including every `build/variants/*` regardless of
selection. Clean stays variant-agnostic: its blast radius should not depend on
an easy-to-forget flag.

That accessor resolves through `find_contest_root`, which needs no selection,
rather than `find_contest`, and no-ops when there is no contest root. This also
drops a pre-existing wart: today `rbx clean` hard-errors in dispatcher mode with
no `-C`, because `get_contest_build_path` dies without a selection.

## Reporting

`rbx contest statements build` prints its results under a
`console.rule(title=f'Built {kind.value}')` (`contest/statements.py:212`). The
rule title gains the resolved variant when there is one — `Built statements
(variant: div2)` — so it is obvious from the output which subtree the artifacts
landed in. The canonical keeps the current title unchanged.

## Edge cases

- **Custom `buildDir`.** Respected; the variant component is appended beneath
  whatever `environment.get_build_dir()` returns.
- **A variant named `variants`.** Nests to `build/variants/variants/`. Harmless.
- **Cache key.** `get_contest_build_path` is `@functools.cache`d on `root` alone
  while now depending on the selection contextvar, exactly the caveat
  `find_contest_yaml` already documents. Production resolves the selection once
  at the CLI callback boundary; tests clear the cache, and `contest_package` is
  already module-registered in `rbx.testing_utils.clear_all_functools_cache`.
- **Pre-change artifacts.** A variant that previously wrote to `build/` leaves
  stale files there. No migration; they are inert leftovers. Worth a changelog
  line.

## Testing

Unit tests in `tests/rbx/box/contest/test_contest_package.py`, which already
exercises these accessors with `cache_clear`:

- canonical selection resolves to `build/`;
- a sibling variant selected on a real contest resolves to `build/variants/div2`;
- dispatcher mode with `-C div2` resolves to `build/variants/div2`;
- a custom `buildDir` resolves to `out/variants/div2`;
- `get_contest_statements_build_path` derives correctly in each case;
- `get_contest_root_build_path` ignores the selection.

Plus a clean test asserting it targets the root build dir and succeeds in
dispatcher mode with no selection, and an e2e that builds statements for two
variants and asserts both PDFs coexist.

## Docs

`docs/setters/statements/contest.md:123` documents the output as
`build/<statement-name>[-<profile>].pdf` and needs the variant qualifier;
`docs/setters/cheatsheet.md` mentions variants and should be checked. Both get
the warning that problem-level artifacts are still overwritten across variants
until [#753](https://github.com/rsalesc/rbx/issues/753) lands.
