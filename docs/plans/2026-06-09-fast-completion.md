# Fast Shell Completion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `rbx <tab>` shell completion fast (~50ms instead of ~741ms) by serving completions from a precomputed static spec instead of importing the whole CLI, with clean hooks for adding new completers.

**Architecture:** Typer stays the source of truth for execution. A generator introspects the live Click tree and serializes a static `SPEC` (committed Python literal, shipped in the wheel). At `<tab>` time `main.py` intercepts the `_RBX_COMPLETE` env var *before any heavy import* and runs our own resolver over `SPEC`, reusing Click's per-shell output formatters. We never fall back to the slow Typer path: unknown/path positions emit a `file` directive so the shell does its own completion. Correctness is guaranteed at CI time by a differential test (ours vs real Typer) and an import-firewall test.

**Tech Stack:** Python 3.10+, Typer 0.21.x, Click 8.3.x, pytest (`asyncio_mode=auto`, files named `*_test.py`), mise tasks, uv.

**Design doc:** `docs/plans/2026-06-09-fast-completion-design.md`

---

## Conventions for this plan

- Tests live under `tests/rbx/box/completion/` named `*_test.py`; test functions are `def test_*`.
- Run a single test: `uv run pytest tests/rbx/box/completion/<file>_test.py::test_name -v`.
- Run the completion suite: `uv run pytest tests/rbx/box/completion -v`.
- Lint/format before each commit: `uv run ruff check --fix . && uv run ruff format .`.
- Use the `/commit` skill workflow (`.claude/skills/commit.md`): conventional commits, co-author trailer, never `git add -A`, never `--amend`.
- New `@functools.cache` on module-level functions in `rbx/box/` MUST be registered in `rbx.testing_utils.clear_all_functools_cache` (see `rbx/box/CLAUDE.md` "Test isolation rule").

---

## Phase 0 — Harness first (measure before changing)

Goal: build the measuring tools and the "golden" reference (real Typer completion) so every later phase is verified against numbers and against Typer's own output.

### Task 0.1: Completion test package + golden Typer-completion helper

**Files:**
- Create: `tests/rbx/box/completion/__init__.py` (empty)
- Create: `tests/rbx/box/completion/golden.py`
- Test: `tests/rbx/box/completion/golden_test.py`

**Step 1: Write the failing test**

```python
# tests/rbx/box/completion/golden_test.py
from tests.rbx.box.completion.golden import typer_completions


def test_root_command_names_include_known_commands():
    items = typer_completions(args=[], incomplete='')
    values = {i.value for i in items}
    assert 'build' in values
    assert 'run' in values
    assert 'package' in values  # canonical name of the `package, pkg` group


def test_language_option_completes_from_config():
    items = typer_completions(args=['run', '--lang'], incomplete='')
    values = {i.value for i in items}
    # default env ships at least cpp; exact set comes from get_config()
    assert any(v for v in values), 'expected at least one language completion'
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/rbx/box/completion/golden_test.py -v`
Expected: FAIL — `golden.py` / `typer_completions` does not exist.

**Step 3: Write the golden helper**

This builds the *real* Typer app once and asks Click for completions in-process. It is the reference oracle the differential test will compare against. It is intentionally allowed to be slow (it imports the whole app); it never runs on the hot path.

```python
# tests/rbx/box/completion/golden.py
"""Reference completion via the real Typer app (slow, correct). Test-only oracle."""
import functools
from typing import List

import click
import typer.main
from click.shell_completion import CompletionItem


@functools.lru_cache(maxsize=1)
def _real_cli() -> click.Command:
    from rbx.box.cli import app  # heavy import — fine in tests

    return typer.main.get_command(app)


def typer_completions(args: List[str], incomplete: str) -> List[CompletionItem]:
    """Run Click's native completion resolution against the real app."""
    cli = _real_cli()
    ctx_args = {'prog_name': 'rbx'}
    from click.shell_completion import ShellComplete

    comp = ShellComplete(cli, ctx_args, 'rbx', '_RBX_COMPLETE')
    return comp.get_completions(list(args), incomplete)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/rbx/box/completion/golden_test.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
uv run ruff check --fix tests/rbx/box/completion && uv run ruff format tests/rbx/box/completion
git add tests/rbx/box/completion/__init__.py tests/rbx/box/completion/golden.py tests/rbx/box/completion/golden_test.py
git commit -m "test(completion): add golden Typer-completion oracle for #333"
```

---

### Task 0.2: Latency benchmark script + mise task + recorded baseline

**Files:**
- Create: `scripts/bench_completion.py`
- Modify: `mise.toml` (add `[tasks.bench-completion]`)

**Step 1: Write the benchmark script**

Times cold subprocess completion for representative cursor positions using the same env protocol the shell uses. No pytest — it prints a table.

```python
# scripts/bench_completion.py
"""Benchmark cold completion latency. Run: `mise run bench-completion`."""
import os
import subprocess
import sys
import time

# (label, args-before-incomplete, incomplete)
SCENARIOS = [
    ('rbx <tab>', '', ''),
    ('rbx ru<tab>', '', 'ru'),
    ('rbx run <tab>', 'run', ''),
    ('rbx run --<tab>', 'run', '--'),
    ('rbx run --lang <tab>', 'run --lang', ''),
    ('rbx package <tab>', 'package', ''),
]


def _one(comp_words: str, cword: int, n: int = 5) -> float:
    env = dict(os.environ)
    env['_RBX_COMPLETE'] = 'complete_bash'
    env['_TYPER_COMPLETE_ARGS'] = comp_words
    env['COMP_WORDS'] = comp_words
    env['COMP_CWORD'] = str(cword)
    best = float('inf')
    for _ in range(n):
        t = time.perf_counter()
        subprocess.run(['rbx'], env=env, capture_output=True)
        best = min(best, time.perf_counter() - t)
    return best * 1000


def main() -> None:
    print(f'{"scenario":24s} {"ms (best of 5)":>16s}')
    for label, before, inc in SCENARIOS:
        comp_words = ('rbx ' + before + ' ' + inc).replace('  ', ' ').rstrip()
        cword = len(comp_words.split())
        print(f'{label:24s} {_one(comp_words, cword):16.1f}')


if __name__ == '__main__':
    sys.exit(main())
```

**Step 2: Add the mise task**

Add to `mise.toml`:

```toml
[tasks.bench-completion]
description = "Benchmark shell completion latency"
run = "python scripts/bench_completion.py"
```

**Step 3: Run it and record the baseline**

Run: `uv run mise run bench-completion` (or `uv run python scripts/bench_completion.py`)
Expected: every scenario ~700–1000ms (this is the bug). **Copy the table into the commit body** as the baseline.

**Step 4: Commit**

```bash
uv run ruff check --fix scripts && uv run ruff format scripts
git add scripts/bench_completion.py mise.toml
git commit  # body: paste the baseline table (~741ms)
# message: "test(completion): add completion latency benchmark + baseline (#333)"
```

---

### Task 0.3: Import-firewall test (xfail until Phase 3)

**Files:**
- Create: `tests/rbx/box/completion/firewall_test.py`

**Step 1: Write the test (expected to fail today)**

It runs a real completion in a subprocess and asserts none of the heavy modules were imported. Today it FAILS (the whole CLI loads), so mark it `xfail(strict=True)` — it documents the target and will flip to PASS in Phase 3.

```python
# tests/rbx/box/completion/firewall_test.py
import os
import subprocess
import sys

import pytest

DENYLIST = [
    'textual', 'mechanize', 'bs4', 'lxml', 'git', 'agents',
    'prompt_toolkit', 'questionary',
    'rbx.box.cli', 'rbx.box.solutions', 'rbx.box.packaging',
]

# Prints imported module names after performing a completion.
_PROBE = (
    'import os,sys;'
    "os.environ['_RBX_COMPLETE']='complete_bash';"
    "os.environ['_TYPER_COMPLETE_ARGS']='rbx ';"
    "os.environ['COMP_WORDS']='rbx ';os.environ['COMP_CWORD']='1';"
    'from rbx.box import main;'
    'main.app() if False else None;'  # replaced in Phase 3 by the real entry call
    "print(chr(10).join(sorted(sys.modules)))"
)


def _modules_after_completion() -> set:
    out = subprocess.run([sys.executable, '-c', _PROBE], capture_output=True, text=True)
    return set(out.stdout.splitlines())


@pytest.mark.xfail(strict=True, reason='completion still imports the full CLI until Phase 3')
def test_completion_path_imports_nothing_heavy():
    mods = _modules_after_completion()
    leaked = [m for m in DENYLIST if any(x == m or x.startswith(m + '.') for x in mods)]
    assert not leaked, f'completion path imported heavy modules: {leaked}'
```

**Step 2: Run it**

Run: `uv run pytest tests/rbx/box/completion/firewall_test.py -v`
Expected: XFAIL (the test fails as designed; xfail makes the suite green).

**Step 3: Commit**

```bash
git add tests/rbx/box/completion/firewall_test.py
git commit -m "test(completion): add import-firewall guard (xfail until engine lands) (#333)"
```

---

## Phase 1 — Completer registry + completers

Goal: a clean hook for dynamic completers, with the 3 existing ones migrated and `problem` re-enabled. No runtime behavior change yet (Typer still drives completion).

### Task 1.1: The registry

**Files:**
- Create: `rbx/box/completion/__init__.py` (empty)
- Create: `rbx/box/completion/registry.py`
- Test: `tests/rbx/box/completion/registry_test.py`

**Step 1: Write the failing test**

```python
# tests/rbx/box/completion/registry_test.py
import sys

from click.shell_completion import CompletionItem

from rbx.box.completion import registry


def test_register_and_load_roundtrip():
    @registry.register_completer('dummy_xyz')
    def _c(ctx, incomplete):
        return [CompletionItem('hello')]

    loaded = registry.load_completer('dummy_xyz')
    items = loaded(registry.CompletionContext(args=[], command=(), option_values={}, package_root=None), '')
    assert [i.value for i in items] == ['hello']


def test_reverse_lookup_by_function():
    @registry.register_completer('dummy_rev')
    def _c(ctx, incomplete):
        return []

    assert registry.key_for_function(_c) == 'dummy_rev'


def test_load_completer_is_lazy():
    # Registering by dotted path must NOT import the target module eagerly.
    registry.register_completer_path('lazy_demo', 'rbx.box.completion._never_imported:fn')
    assert 'rbx.box.completion._never_imported' not in sys.modules
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/rbx/box/completion/registry_test.py -v`
Expected: FAIL — module missing.

**Step 3: Implement**

```python
# rbx/box/completion/registry.py
import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from click.shell_completion import CompletionItem


@dataclass
class CompletionContext:
    args: List[str]
    command: Tuple[str, ...]
    option_values: Dict[str, str]
    package_root: Optional[Path]


Completer = Callable[[CompletionContext, str], List[CompletionItem]]

# key -> dotted path 'module:function' (string => lazy)
_PATHS: Dict[str, str] = {}
# id(function) -> key, for the generator's reverse lookup
_REVERSE: Dict[int, str] = {}


def register_completer_path(key: str, dotted: str) -> None:
    _PATHS[key] = dotted


def register_completer(key: str) -> Callable[[Completer], Completer]:
    def deco(fn: Completer) -> Completer:
        _PATHS[key] = f'{fn.__module__}:{fn.__qualname__}'
        _REVERSE[id(fn)] = key
        return fn

    return deco


def key_for_function(fn: Completer) -> Optional[str]:
    return _REVERSE.get(id(fn))


def load_completer(key: str) -> Completer:
    dotted = _PATHS[key]
    module_name, _, qualname = dotted.partition(':')
    module = importlib.import_module(module_name)
    obj = module
    for part in qualname.split('.'):
        obj = getattr(obj, part)
    return obj  # type: ignore[return-value]
```

**Step 4: Run to verify pass**

Run: `uv run pytest tests/rbx/box/completion/registry_test.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
uv run ruff check --fix rbx/box/completion tests/rbx/box/completion && uv run ruff format rbx/box/completion tests/rbx/box/completion
git add rbx/box/completion/__init__.py rbx/box/completion/registry.py tests/rbx/box/completion/registry_test.py
git commit -m "feat(completion): add lazy completer registry + CompletionContext (#333)"
```

---

### Task 1.2: The completers (language, checker, problem) + cheap package peek

**Files:**
- Create: `rbx/box/completion/completers.py`
- Create: `rbx/box/completion/peek.py`
- Test: `tests/rbx/box/completion/completers_test.py`

**Step 1: Write the failing tests**

```python
# tests/rbx/box/completion/completers_test.py
from rbx.box.completion import completers, registry


def _ctx(**kw):
    base = dict(args=[], command=(), option_values={}, package_root=None)
    base.update(kw)
    return registry.CompletionContext(**base)


def test_language_completer_returns_config_languages():
    items = completers.complete_language(_ctx(), '')
    assert any(i.value for i in items)


def test_checker_completer_lists_bundled_checkers_without_boilerplate():
    values = {i.value for i in completers.complete_checker(_ctx(), '')}
    assert 'boilerplate.cpp' not in values
    assert any(v.endswith('.cpp') for v in values)


def test_problem_completer_reads_contest_problems(tmp_path):
    # package peek must not require pydantic; a minimal yaml is enough
    (tmp_path / 'contest.rbx.yml').write_text('problems:\n  - short_name: A\n  - short_name: B\n')
    values = {i.value for i in completers.complete_problem(_ctx(package_root=tmp_path), '')}
    assert {'A', 'B'} <= values
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/rbx/box/completion/completers_test.py -v`
Expected: FAIL — modules missing.

**Step 3: Implement the cheap peek + completers**

```python
# rbx/box/completion/peek.py
"""Cheap, tolerant reads of package YAML for completion. No pydantic, no full load."""
import functools
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


def _read_yaml(path: Path) -> Dict[str, Any]:
    try:
        with path.open() as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


@functools.lru_cache(maxsize=64)
def _peek_cached(path_str: str, mtime: float) -> Dict[str, Any]:
    return _read_yaml(Path(path_str))


def peek(path: Path) -> Dict[str, Any]:
    """mtime-keyed cache so repeated tabs are instant."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    return _peek_cached(str(path), mtime)
```

```python
# rbx/box/completion/completers.py
"""Dynamic completers. MUST stay light — do not import the heavy app here."""
import importlib.resources
from pathlib import Path
from typing import List

from click.shell_completion import CompletionItem

from rbx.box.completion import peek
from rbx.box.completion.registry import CompletionContext, register_completer


def _items(values) -> List[CompletionItem]:
    return [CompletionItem(v) for v in sorted(values)]


@register_completer('language')
def complete_language(ctx: CompletionContext, incomplete: str) -> List[CompletionItem]:
    from rbx.config import get_config  # local import keeps module light

    return _items(get_config().languages.keys())


@register_completer('checker')
def complete_checker(ctx: CompletionContext, incomplete: str) -> List[CompletionItem]:
    from rbx import config

    names = set()
    with importlib.resources.as_file(
        importlib.resources.files('rbx') / 'resources' / 'checkers'
    ) as d:
        names.update(p.name for p in d.iterdir() if p.is_file())
    app_checkers = config.get_app_path() / 'checkers'
    if app_checkers.is_dir():
        names.update(p.name for p in app_checkers.iterdir() if p.is_file())
    names.discard('boilerplate.cpp')
    return _items(names)


@register_completer('problem')
def complete_problem(ctx: CompletionContext, incomplete: str) -> List[CompletionItem]:
    root = ctx.package_root
    if root is None:
        return []
    data = peek.peek(Path(root) / 'contest.rbx.yml')
    shorts = {p.get('short_name') for p in data.get('problems', []) if isinstance(p, dict)}
    return _items(s for s in shorts if s)
```

Register the cache in `rbx/testing_utils.py:clear_all_functools_cache` — add `from rbx.box.completion import peek; peek._peek_cached.cache_clear()` (follow the existing pattern in that function).

**Step 4: Run to verify pass**

Run: `uv run pytest tests/rbx/box/completion/completers_test.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
uv run ruff check --fix rbx/box/completion tests/rbx/box/completion && uv run ruff format rbx/box/completion tests/rbx/box/completion
git add rbx/box/completion/completers.py rbx/box/completion/peek.py rbx/testing_utils.py tests/rbx/box/completion/completers_test.py
git commit -m "feat(completion): add language/checker/problem completers + cheap yaml peek (#333)"
```

---

### Task 1.3: Point `annotations.py` at the registry (lazily)

**Files:**
- Modify: `rbx/annotations.py:21-119`
- Test: `tests/rbx/box/completion/annotations_light_test.py`

**Step 1: Write the failing test**

Importing `rbx.annotations` must not eagerly import `rbx.config` (the old 88ms cost), and the annotation completers must still resolve.

```python
# tests/rbx/box/completion/annotations_light_test.py
import subprocess
import sys


def test_importing_annotations_does_not_import_config():
    code = 'import rbx.annotations, sys; print("rbx.config" in sys.modules)'
    out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert out.stdout.strip() == 'False', out.stdout + out.stderr
```

**Step 2: Run to verify failure**

Run: `uv run pytest tests/rbx/box/completion/annotations_light_test.py -v`
Expected: FAIL (annotations imports `from rbx.config import get_config` at top).

**Step 3: Implement**

In `rbx/annotations.py`: remove the top-level `from rbx.config import get_config` and the `import rbx.config` if only used by completers. Replace the three local completer functions (`_get_language_options`, `_get_problem_options`, `_get_checker_options`) with lazy adapters that call the registry, and move `_get_language_default` to a local import:

```python
# rbx/annotations.py  (completer wiring)
from rbx.box.completion.registry import load_completer, CompletionContext

def _adapt(key):
    """Typer autocompletion callback adapter -> registry completer."""
    def _cb(incomplete: str = ''):
        ctx = CompletionContext(args=[], command=(), option_values={}, package_root=None)
        return [i.value for i in load_completer(key)(ctx, incomplete)]
    return _cb

# usage in the Annotated types:
#   autocompletion=_adapt('language')
#   autocompletion=_adapt('checker')
#   autocompletion=_adapt('problem')   # re-enabled
```

For `_get_language_default`, keep it but import `get_config` inside the function body. Keep `register_completer` import side effects working: ensure `rbx.box.completion.completers` is imported somewhere so the keys are registered when needed — the generator (Phase 2) and the adapter's `load_completer` import it lazily, so no eager cost.

> Note: the generator in Phase 2 needs the function→key mapping. Because `annotations.py` now uses `_adapt('language')` (a closure), the generator will read the spec completer key from a marker on the closure. Set it: `_cb._completer_key = key` inside `_adapt`, and have the generator read `getattr(fn, '_completer_key', None)` first, falling back to `registry.key_for_function`.

**Step 4: Run to verify pass + no regressions**

Run: `uv run pytest tests/rbx/box/completion/annotations_light_test.py -v`
Expected: PASS.
Run: `uv run pytest tests/rbx/box -k "annotation or cli" -q` and a smoke `uv run rbx --help` to confirm the CLI still builds.
Expected: PASS / help renders.

**Step 5: Commit**

```bash
uv run ruff check --fix rbx/annotations.py tests/rbx/box/completion && uv run ruff format rbx/annotations.py tests/rbx/box/completion
git add rbx/annotations.py tests/rbx/box/completion/annotations_light_test.py
git commit -m "refactor(completion): route annotations completers through the registry (#333)"
```

---

## Phase 2 — Generator + committed spec

### Task 2.1: Spec generator (walk the Click tree)

**Files:**
- Create: `rbx/box/completion/generate.py`
- Test: `tests/rbx/box/completion/generate_test.py`

**Step 1: Write the failing test** (use a small synthetic Typer app, not the real one, for speed & determinism)

```python
# tests/rbx/box/completion/generate_test.py
import typer
import typer.main
from typing_extensions import Annotated

from rbx.box.completion import generate, registry


def _build_app():
    app = typer.Typer()

    @app.command()
    def hello(
        name: Annotated[str, typer.Argument()] = 'x',
        lang: Annotated[str, typer.Option(autocompletion=_lang)] = 'cpp',
    ):
        ...

    return app


@registry.register_completer('gen_lang')
def _lang(incomplete: str = ''):
    return []


def test_generate_captures_command_and_param_and_completer():
    spec = generate.build_spec(typer.main.get_command(_build_app()))
    hello = spec['children']['hello']
    assert hello['is_group'] is False
    names = {tuple(p['names']) or ('<arg>',) for p in hello['params']}
    assert ('--lang',) in {tuple(p['names']) for p in hello['params'] if p['names']}
    lang = next(p for p in hello['params'] if p['names'] == ['--lang'])
    assert lang['value']['completer'] == 'gen_lang'


def test_generate_rejects_unregistered_completer():
    def _unreg(incomplete: str = ''):
        return []

    app = typer.Typer()

    @app.command()
    def cmd(x: str = typer.Option('a', autocompletion=_unreg)):
        ...

    import pytest

    with pytest.raises(generate.UnregisteredCompleterError):
        generate.build_spec(typer.main.get_command(app))
```

Adjust `_lang` registration so its function identity is what the param holds (the synthetic app passes `_lang` directly, so `registry.key_for_function` resolves it).

**Step 2: Run to verify failure**

Run: `uv run pytest tests/rbx/box/completion/generate_test.py -v`
Expected: FAIL — module missing.

**Step 3: Implement** (core walker; mirror the spec schema in the design doc)

```python
# rbx/box/completion/generate.py
import re
from typing import Any, Dict, List, Optional

import click

from rbx.box.completion import registry

_CMD_SPLIT = re.compile(r', ?')


class UnregisteredCompleterError(RuntimeError):
    pass


def _completer_key(param: click.Parameter) -> Optional[str]:
    fn = getattr(param, '_custom_shell_complete', None) or getattr(param, 'shell_complete', None)
    # Typer stores the autocompletion callable; unwrap our adapter marker first.
    raw = getattr(param, 'autocompletion', None) or fn
    if raw is None:
        return None
    key = getattr(raw, '_completer_key', None) or registry.key_for_function(raw)
    if key is None:
        raise UnregisteredCompleterError(f'completer for {param.name!r} is not registered')
    return key


def _value_spec(param: click.Parameter) -> Dict[str, Any]:
    key = _completer_key(param)
    if key is not None:
        return {'kind': 'completer', 'completer': key}
    t = param.type
    choices = getattr(t, 'choices', None)
    if choices:
        return {'kind': 'choice', 'choices': list(choices)}
    if isinstance(t, (click.Path, click.File)):
        is_dir = bool(getattr(t, 'dir_okay', False) and not getattr(t, 'file_okay', True))
        return {'kind': 'path', 'path': 'dir' if is_dir else 'file'}
    return {'kind': 'none'}


def _param_spec(param: click.Parameter) -> Dict[str, Any]:
    is_opt = isinstance(param, click.Option)
    return {
        'kind': 'option' if is_opt else 'argument',
        'names': list(param.opts) if is_opt else [],
        'takes_value': not getattr(param, 'is_flag', False),
        'multiple': bool(getattr(param, 'multiple', False)),
        'help': getattr(param, 'help', None) if is_opt else None,
        'value': _value_spec(param) if not getattr(param, 'is_flag', False) else {'kind': 'none'},
    }


def _names_and_aliases(name: Optional[str]) -> (str, List[str]):
    parts = _CMD_SPLIT.split(name) if name else ['']
    return parts[0], parts[1:]


def build_spec(cmd: click.Command, name: Optional[str] = None) -> Dict[str, Any]:
    canonical, aliases = _names_and_aliases(name if name is not None else cmd.name)
    node: Dict[str, Any] = {
        'name': canonical,
        'aliases': aliases,
        'help': cmd.get_short_help_str() or None,
        'panel': getattr(cmd, 'rich_help_panel', None),
        'is_group': isinstance(cmd, click.Group),
        'params': [_param_spec(p) for p in cmd.params if not _is_hidden(p)],
    }
    if isinstance(cmd, click.Group):
        children: Dict[str, Any] = {}
        for sub_name in cmd.list_commands(_ctx(cmd)):
            sub = cmd.get_command(_ctx(cmd), sub_name)
            child = build_spec(sub, name=sub.name or sub_name)
            children[child['name']] = child
        node['children'] = children
    return node


def _ctx(cmd: click.Command) -> click.Context:
    return click.Context(cmd, info_name='rbx', resilient_parsing=True)


def _is_hidden(param: click.Parameter) -> bool:
    return bool(getattr(param, 'hidden', False))
```

> The exact attribute Typer uses to store `autocompletion` may differ by version; pin it during implementation by inspecting one real param (`uv run python -c "..."`) and adjust `_completer_key`. The `generate_test.py` synthetic app is the fast feedback loop.

**Step 4: Run to verify pass**

Run: `uv run pytest tests/rbx/box/completion/generate_test.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
uv run ruff check --fix rbx/box/completion tests/rbx/box/completion && uv run ruff format rbx/box/completion tests/rbx/box/completion
git add rbx/box/completion/generate.py tests/rbx/box/completion/generate_test.py
git commit -m "feat(completion): generate static spec from the Typer tree (#333)"
```

---

### Task 2.2: Serialize + commit `_spec.py` + mise task

**Files:**
- Create: `rbx/box/completion/serialize.py` (renders `build_spec` output to a Python literal)
- Create (generated): `rbx/box/completion/_spec.py`
- Modify: `mise.toml` (add `[tasks.gen-completion-spec]`)

**Step 1: Implement the serializer + a `__main__`**

```python
# rbx/box/completion/serialize.py
import pprint
from pathlib import Path

_HEADER = '# GENERATED by `mise run gen-completion-spec` — do not edit by hand.\n# Source of truth: the Typer app in rbx/box/cli.py.\n\nSPEC = '


def render(spec: dict) -> str:
    return _HEADER + pprint.pformat(spec, width=100, sort_dicts=True) + '\n'


def write_spec(out: Path) -> None:
    import typer.main

    from rbx.box.cli import app
    from rbx.box.completion import completers  # noqa: F401  (register keys)
    from rbx.box.completion.generate import build_spec

    spec = build_spec(typer.main.get_command(app), name='rbx')
    out.write_text(render(spec))


if __name__ == '__main__':
    write_spec(Path(__file__).with_name('_spec.py'))
```

**Step 2: Add the mise task**

```toml
[tasks.gen-completion-spec]
description = "Regenerate the committed completion spec from the Typer app"
run = "python -m rbx.box.completion.serialize"
```

**Step 3: Generate and inspect**

Run: `uv run mise run gen-completion-spec`
Then: `uv run ruff format rbx/box/completion/_spec.py`
Expected: `rbx/box/completion/_spec.py` exists with a big `SPEC = {...}`; eyeball that `build`, `run`, `package`(+alias `pkg`), `--lang` completer key etc. are present.

**Step 4: Sanity test the committed spec loads fast**

Run: `uv run python -c "from rbx.box.completion import _spec; print(_spec.SPEC['children'].keys())"`
Expected: prints command names; quick.

**Step 5: Commit**

```bash
git add rbx/box/completion/serialize.py rbx/box/completion/_spec.py mise.toml
git commit -m "feat(completion): commit generated static completion spec (#333)"
```

---

### Task 2.3: Drift test

**Files:**
- Create: `tests/rbx/box/completion/drift_test.py`

**Step 1: Write the test**

```python
# tests/rbx/box/completion/drift_test.py
import typer.main

from rbx.box.cli import app
from rbx.box.completion import _spec, completers, serialize  # noqa: F401
from rbx.box.completion.generate import build_spec


def test_committed_spec_matches_generated():
    fresh = build_spec(typer.main.get_command(app), name='rbx')
    assert fresh == _spec.SPEC, 'run `mise run gen-completion-spec` and commit the result'
```

**Step 2: Run**

Run: `uv run pytest tests/rbx/box/completion/drift_test.py -v`
Expected: PASS (it was just generated).

**Step 3: Commit**

```bash
git add tests/rbx/box/completion/drift_test.py
git commit -m "test(completion): fail CI when committed spec drifts from Typer (#333)"
```

---

## Phase 3 — Engine + fast-path entry

### Task 3.1: The static resolver

**Files:**
- Create: `rbx/box/completion/engine.py`
- Test: `tests/rbx/box/completion/engine_test.py`

Build the resolver incrementally — one behavior per sub-step, each with its own failing test first. Use a small hand-written `SPEC` fixture in the test plus the real `_spec.SPEC`.

**Behaviors to drive (each = test → implement → run):**

1. **Group command names**: `resolve(SPEC, [], '')` → child names; `resolve(SPEC, [], 'ru')` → names starting with `ru`. Types are `plain`, help carried.
2. **Aliases resolve on descent**: `resolve(SPEC, ['pkg'], '')` behaves like `['package']`.
3. **Option names**: `resolve(SPEC, ['run'], '--')` → run's option names; prefix filter on `--la`.
4. **Choice value**: an option/arg with `value.kind == 'choice'` after `--opt ` → filtered choices.
5. **Completer value (lazy)**: `value.kind == 'completer'` → `load_completer(key)(ctx, incomplete)`; assert the completer module is imported only now (spy on `sys.modules`).
6. **Path / none / unknown → file directive**: returns `[CompletionItem('', type='file')]`.
7. **`--opt=val` form** and **`--` end-of-options**.

**Reference implementation** (resolver core; flesh out branch-by-branch under TDD):

```python
# rbx/box/completion/engine.py
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from click.shell_completion import CompletionItem

from rbx.box.completion.registry import CompletionContext, load_completer

FILE = [CompletionItem('', type='file')]


def _find_problem_root() -> Optional[Path]:
    cur = Path.cwd()
    for d in [cur, *cur.parents]:
        if (d / 'problem.rbx.yml').exists() or (d / 'contest.rbx.yml').exists():
            return d
    return None


def _match_child(node: Dict[str, Any], token: str) -> Optional[Dict[str, Any]]:
    for child in node.get('children', {}).values():
        if token == child['name'] or token in child['aliases']:
            return child
    return None


def _option(node: Dict[str, Any], token: str) -> Optional[Dict[str, Any]]:
    name = token.split('=', 1)[0]
    for p in node['params']:
        if p['kind'] == 'option' and name in p['names']:
            return p
    return None


def _walk(spec, args) -> Tuple[Dict[str, Any], Dict[str, str], List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    node = spec
    option_values: Dict[str, str] = {}
    positionals_filled = 0
    pending_value_for: Optional[Dict[str, Any]] = None
    no_more_opts = False
    i = 0
    while i < len(args):
        tok = args[i]
        if pending_value_for is not None:
            option_values[pending_value_for['names'][0]] = tok
            pending_value_for = None
            i += 1
            continue
        if tok == '--' and not no_more_opts:
            no_more_opts = True
            i += 1
            continue
        if not no_more_opts and tok.startswith('-'):
            opt = _option(node, tok)
            if opt and opt['takes_value'] and '=' not in tok:
                pending_value_for = opt
            elif opt and opt['takes_value']:
                option_values[opt['names'][0]] = tok.split('=', 1)[1]
            i += 1
            continue
        child = _match_child(node, tok) if node.get('is_group') else None
        if child is not None:
            node = child
        else:
            positionals_filled += 1
        i += 1
    args_meta = [p for p in node['params'] if p['kind'] == 'argument']
    next_arg = args_meta[positionals_filled] if positionals_filled < len(args_meta) else None
    return node, option_values, [next_arg] if next_arg else [], pending_value_for


def _value_items(value: Dict[str, Any], ctx: CompletionContext, incomplete: str) -> List[CompletionItem]:
    kind = value['kind']
    if kind == 'choice':
        return [CompletionItem(c) for c in value['choices'] if c.startswith(incomplete)]
    if kind == 'completer':
        return load_completer(value['completer'])(ctx, incomplete)
    return FILE  # 'path' / 'none'


def resolve(spec: Dict[str, Any], args: List[str], incomplete: str) -> List[CompletionItem]:
    try:
        node, option_values, next_args, pending = _walk(spec, args)
        ctx = CompletionContext(
            args=list(args),
            command=(node['name'],),
            option_values=option_values,
            package_root=_find_problem_root(),
        )
        if pending is not None:  # completing the value of a value-taking option
            return _value_items(pending['value'], ctx, incomplete)
        if incomplete.startswith('-'):
            out = []
            for p in node['params']:
                if p['kind'] != 'option':
                    continue
                out += [CompletionItem(n, help=p.get('help')) for n in p['names'] if n.startswith(incomplete)]
            return out
        if node.get('is_group'):
            out = []
            for child in node['children'].values():
                names = [child['name'], *child['aliases']]
                out += [CompletionItem(n, help=child.get('help')) for n in names if n.startswith(incomplete)]
            return out
        if next_args:
            return _value_items(next_args[0]['value'], ctx, incomplete)
        return FILE
    except Exception:
        return FILE
```

**Commit** after the resolver's tests are green:

```bash
git add rbx/box/completion/engine.py tests/rbx/box/completion/engine_test.py
git commit -m "feat(completion): add static-spec resolver (#333)"
```

---

### Task 3.2: `FastComplete` + output via Click formatters

**Files:**
- Modify: `rbx/box/completion/engine.py` (add `complete_to_string`)
- Test: `tests/rbx/box/completion/engine_output_test.py`

**Step 1: Failing test** — output string equals Click's format for the same items.

```python
# tests/rbx/box/completion/engine_output_test.py
import os

from rbx.box.completion import _spec, engine


def test_bash_output_lists_commands(monkeypatch):
    monkeypatch.setenv('_TYPER_COMPLETE_ARGS', 'rbx ')
    monkeypatch.setenv('COMP_WORDS', 'rbx ')
    monkeypatch.setenv('COMP_CWORD', '1')
    out = engine.complete_to_string('bash', _spec.SPEC)
    # bash format is "plain,<value>" per line
    assert 'plain,run' in out.splitlines()
```

**Step 2: Implement**

```python
# add to engine.py
import click
from click.shell_completion import get_completion_class


def complete_to_string(shell: str, spec) -> str:
    base = get_completion_class(shell)
    if base is None:
        return 'file,'  # best-effort: let the shell do file completion

    class _Fast(base):  # type: ignore[misc, valid-type]
        def get_completions(self, args, incomplete):
            return resolve(spec, args, incomplete)

    comp = _Fast(click.Command('rbx'), {}, 'rbx', '_RBX_COMPLETE')
    return comp.complete()
```

**Step 3: Run / pass / commit**

Run: `uv run pytest tests/rbx/box/completion/engine_output_test.py -v` → PASS.

```bash
git add rbx/box/completion/engine.py tests/rbx/box/completion/engine_output_test.py
git commit -m "feat(completion): render completions via Click per-shell formatters (#333)"
```

---

### Task 3.3: The entry point (detect, dispatch, fallback)

**Files:**
- Create: `rbx/box/completion/entry.py`
- Test: `tests/rbx/box/completion/entry_test.py`

**Step 1: Failing test**

```python
# tests/rbx/box/completion/entry_test.py
from rbx.box.completion import entry


def test_handle_returns_false_when_not_completing(monkeypatch):
    monkeypatch.delenv('_RBX_COMPLETE', raising=False)
    assert entry.handle_completion() is False


def test_handle_complete_prints_and_returns_true(monkeypatch, capsys):
    monkeypatch.setenv('_RBX_COMPLETE', 'complete_bash')
    monkeypatch.setenv('_TYPER_COMPLETE_ARGS', 'rbx ')
    monkeypatch.setenv('COMP_WORDS', 'rbx ')
    monkeypatch.setenv('COMP_CWORD', '1')
    assert entry.handle_completion() is True
    assert 'plain,run' in capsys.readouterr().out.splitlines()
```

**Step 2: Implement**

```python
# rbx/box/completion/entry.py
import os
import sys

COMPLETE_VAR = '_RBX_COMPLETE'


def handle_completion() -> bool:
    """If this is a completion request, serve it and return True. Imports nothing heavy."""
    instruction = os.environ.get(COMPLETE_VAR)
    if not instruction:
        return False
    try:
        kind, _, shell = instruction.partition('_')
        from rbx.box.completion import _spec, engine

        if kind == 'complete':
            sys.stdout.write(engine.complete_to_string(shell, _spec.SPEC))
            return True
        if kind == 'source':
            from click.shell_completion import get_completion_class

            cls = get_completion_class(shell)
            if cls is not None:
                import click

                comp = cls(click.Command('rbx'), {}, 'rbx', COMPLETE_VAR)
                sys.stdout.write(comp.source())
            return True
    except Exception:
        sys.stdout.write('file,\n')  # never crash the shell; let it default-complete
        return True
    return True
```

**Step 3: Run / pass / commit**

Run: `uv run pytest tests/rbx/box/completion/entry_test.py -v` → PASS.

```bash
git add rbx/box/completion/entry.py tests/rbx/box/completion/entry_test.py
git commit -m "feat(completion): add completion entry point with shell-default fallback (#333)"
```

---

### Task 3.4: Wire `main.py` to intercept before heavy imports

**Files:**
- Modify: `rbx/box/main.py:75-93` (the `app()` function)

**Step 1: Implement** — at the very top of `app()`, before the symlink check and handler installs:

```python
def app():
    from rbx.box.completion import entry  # light: only stdlib + click + spec

    if entry.handle_completion():
        return
    # ... existing body unchanged (symlink check, handlers, run_app_cli) ...
```

Also re-enable Typer completion machinery so the env var is honored: confirm `rbx/box/cli.py:58` `add_completion=False` does not strip the `_RBX_COMPLETE` handling we now own — it doesn't, because we intercept in `main.py` before Typer runs. Leave `add_completion=False`.

**Step 2: End-to-end subprocess check**

Run:
```bash
env _RBX_COMPLETE=complete_bash _TYPER_COMPLETE_ARGS='rbx ' COMP_WORDS='rbx ' COMP_CWORD=1 uv run rbx
```
Expected: prints `plain,build`, `plain,run`, … and exits fast.

**Step 3: Commit**

```bash
git add rbx/box/main.py
git commit -m "perf(completion): serve completions before importing the CLI (#333)"
```

---

### Task 3.5: Flip the firewall test to PASS + turn on the differential test + re-bench

**Files:**
- Modify: `tests/rbx/box/completion/firewall_test.py` (use the real entry; drop `xfail`)
- Create: `tests/rbx/box/completion/differential_test.py`

**Step 1: Update the firewall probe** to call the real entry and drop `@pytest.mark.xfail`:

```python
_PROBE = (
    'import os,sys;'
    "os.environ['_RBX_COMPLETE']='complete_bash';"
    "os.environ['_TYPER_COMPLETE_ARGS']='rbx ';"
    "os.environ['COMP_WORDS']='rbx ';os.environ['COMP_CWORD']='1';"
    'from rbx.box.completion import entry; entry.handle_completion();'
    'print(chr(10).join(sorted(sys.modules)))'
)
# remove the xfail marker
```

**Step 2: Differential test** — ours vs golden Typer across a spec-derived corpus:

```python
# tests/rbx/box/completion/differential_test.py
import pytest

from rbx.box.completion import _spec, engine
from tests.rbx.box.completion.corpus import command_lines  # see Task 4.1
from tests.rbx.box.completion.golden import typer_completions


@pytest.mark.parametrize('args,incomplete', command_lines(_spec.SPEC))
def test_matches_typer(args, incomplete):
    ours = engine.resolve(_spec.SPEC, args, incomplete)
    gold = typer_completions(args, incomplete)
    assert sorted((i.value, i.type) for i in ours) == sorted((i.value, i.type) for i in gold)
```

> A minimal `corpus.command_lines` can start as a few hand-written cases; Task 4.1 expands it to walk the whole spec. Fix any resolver divergences the differential test surfaces (this is the point of the oracle).

**Step 3: Run the gates**

Run: `uv run pytest tests/rbx/box/completion -v`
Expected: firewall PASS, differential PASS.
Run: `uv run mise run bench-completion`
Expected: `rbx <tab>` ~40–80ms (down from ~741ms). **Paste the new table in the commit body.**

**Step 4: Commit**

```bash
git add tests/rbx/box/completion/firewall_test.py tests/rbx/box/completion/differential_test.py
git commit  # body: new benchmark table
# message: "test(completion): enforce import firewall + Typer parity (#333)"
```

---

## Phase 4 — Hardening + docs

### Task 4.1: Full spec-derived corpus + fix divergences

**Files:**
- Create: `tests/rbx/box/completion/corpus.py`
- Test: extends `differential_test.py` (already parametrized on `command_lines`)

**Step 1:** Implement `command_lines(spec)` to yield, by recursively walking the spec: for each group → `(path, '')` and `(path, <prefix>)`; for each leaf → `(path, '--')`, each option value position `(path+[opt], '')`, each positional position, alias variants, and `--opt=` / `--` edge cases.

**Step 2:** Run `uv run pytest tests/rbx/box/completion/differential_test.py -v`. For every mismatch, adjust `engine.resolve` until parity holds. Commit once green.

```bash
git add tests/rbx/box/completion/corpus.py rbx/box/completion/engine.py
git commit -m "test(completion): exhaustive Typer-parity corpus + resolver fixes (#333)"
```

---

### Task 4.2: Robustness tests

**Files:**
- Create: `tests/rbx/box/completion/robustness_test.py`

Cover: engine exception → `file,` + exit 0 + empty stderr; unknown shell → graceful; `source_bash` renders a script and (subprocess) imports nothing heavy; malformed `_TYPER_COMPLETE_ARGS` → no crash. Implement, run, commit:

```bash
git add tests/rbx/box/completion/robustness_test.py
git commit -m "test(completion): cover fallback, unknown shell, source, malformed args (#333)"
```

---

### Task 4.3: Docs + "how to add a completer"

**Files:**
- Create/modify: `docs/setters/` completion page (follow existing docs structure) + `rbx/box/completion/CLAUDE.md` (module guide)
- Modify: `docs/` install/completion instructions if present

Document: how completion works now (spec + engine + fallback), and the 3-line recipe to add a completer (write fn, `@register_completer('key')`, set the param's `autocompletion` to the adapter, `mise run gen-completion-spec`, commit). Verify docs build (non-strict, per the mkdocs memory): `uv run mkdocs build` (ignore the ~9 pre-existing strict warnings).

```bash
git add docs rbx/box/completion/CLAUDE.md
git commit -m "docs(completion): explain fast completion + how to add a completer (#333)"
```

---

### Task 4.4: Wire everything into CI / final verification

**Files:**
- Verify `mise run test` includes `tests/rbx/box/completion` (it does via `testpaths = tests`).
- Confirm CI runs `gen-completion-spec` drift implicitly via `drift_test.py`.

**Final verification (run all, paste results in the PR):**

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest tests/rbx/box/completion -v
uv run pytest --ignore=tests/rbx/box/cli -q     # full suite, no regressions
uv run mise run bench-completion                # final table
```

Open the PR referencing #333 with: before/after benchmark table, the firewall guarantee, and the differential-test parity claim.

---

## Definition of done

- `rbx <tab>` ~40–80ms (was ~741ms); benchmark table in the PR.
- Import-firewall test green (no heavy module on the completion path).
- Differential test green (engine output == real Typer across the full spec corpus).
- Drift test green (committed spec == generated).
- `problem` completer re-enabled; adding a new completer is a documented 3-line change.
- Full suite passes; no regressions.
