# CLAUDE.md — BocaNext packager

This guide covers **BocaNext**, a NEW, separate BOCA packager. It does not touch
the existing bash-based `BocaPackager` in `rbx/box/packaging/boca/`, which
remains the default and is left untouched.

## Two layers

BocaNext is split into two independent layers:

- **Layer 1** — the rbx-side bundler: env-config → `LanguageSpec` resolution,
  `.pyz` assembly, directory layout, and the `rbx package boca-next` CLI wiring.
  **NOT yet implemented**; tracked in GitHub issue **#489**.
- **Layer 2** — the judge-side runtime library `rbx_boca`. **IMPLEMENTED** at
  `rbx/resources/packagers/boca_next/runtime/rbx_boca/`.

## `rbx_boca` runtime

`rbx_boca` is **stdlib-only** and targets **Python 3.8+** (the interpreter found
on BOCA judges). It is authored as a normal Python package, and is intended to be
zipapp-bundled (by the future Layer 1) into each of the BOCA scripts
(`compile` / `run` / `compare` / `limits` / `tests`) as a `.pyz`.

The five BOCA scripts dispatch into `rbx_boca` via its `__main__` / entrypoints
based on the invoked command and the argv contract from `autojudging.php`.

### Importability in tests

`rbx_boca` is importable in tests via
`tests/rbx/box/packaging/boca_next/conftest.py`, which inserts the runtime
directory on `sys.path`, so `import rbx_boca` works exactly as it does on the
judge (where the package lives inside the `.pyz`).

## Module map

- `manifest.py` — config dataclasses (parsed from bundled manifests).
- `languages.py` — the kind engine (compiled_static / jvm_jar / interpreted).
- `sandbox.py` — safeexec argv construction and per-phase/per-language profiles.
- `assets.py` — `NativeAsset` compile cache.
- `verdicts.py` — pure exit-code → verdict logic.
- `interactor_launcher.py` — re-entrant interactor wrapper (fd inheritance,
  watchdog, best-effort RLIMIT).
- `tasks.py` — Batch / Interactive task orchestration (`BaseTask` shares the
  compile/compare logic).
- `entrypoints.py` + `__main__.py` — command dispatch.

## Design + plan

- Design doc: `docs/plans/2026-05-29-boca-next-python-packager-design.md`
  (see the **Implementation corrections (as-built)** section for deviations
  discovered during implementation).
- Implementation plan: `docs/plans/2026-05-29-boca-next-layer2-runtime.md`.

## Running tests

```bash
uv run pytest tests/rbx/box/packaging/boca_next/
```

The 2 slow launcher tests can be skipped with `-m "not slow"`.
