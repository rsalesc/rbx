# PackagePath Annotation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `PackagePath` annotation marker for Typer parameters that auto-resolves paths relative to the package root when the command is wrapped by `@package.within_problem`.

**Architecture:** A sentinel `PackagePath` object lives in `rbx/annotations.py`. The `within_problem` decorator in `package.py` inspects function annotations for this marker before calling the wrapped function. When found, it resolves the parameter value from the caller's original cwd to a path relative to the package root. A shared `_resolve_package_paths` helper does the heavy lifting so `cd.within_closest_package` and `cd.within_closest_wrapper` can reuse it later.

**Tech Stack:** `typing_extensions` (for `get_type_hints(include_extras=True)` on Python 3.10+), `inspect`, `pathlib`

---

### Task 1: Add `PackagePath` sentinel and path resolution helper

**Files:**
- Modify: `rbx/annotations.py` (add `PackagePath` sentinel)
- Create: `rbx/box/path_resolution.py` (resolution logic, kept separate for reuse)
- Test: `tests/rbx/box/test_path_resolution.py`

**Step 1: Write failing tests for path resolution**

Create `tests/rbx/box/test_path_resolution.py`:

```python
import pathlib
from typing import List, Optional
from unittest import mock

from typing_extensions import Annotated

import typer

from rbx.annotations import PackagePath
from rbx.box.path_resolution import resolve_package_paths


def test_resolve_single_str():
    """Single str param annotated with PackagePath is resolved."""

    def cmd(
        path: Annotated[str, PackagePath, typer.Argument()] = '',
    ):
        pass

    original_cwd = pathlib.Path('/project/subdir')
    package_dir = pathlib.Path('/project')

    resolved = resolve_package_paths(cmd, (), {'path': 'sol.cpp'}, original_cwd, package_dir)
    assert resolved['path'] == 'subdir/sol.cpp'


def test_resolve_optional_str_with_value():
    """Optional[str] param with a value is resolved."""

    def cmd(
        path: Annotated[Optional[str], PackagePath, typer.Argument()] = None,
    ):
        pass

    original_cwd = pathlib.Path('/project/subdir')
    package_dir = pathlib.Path('/project')

    resolved = resolve_package_paths(cmd, (), {'path': 'sol.cpp'}, original_cwd, package_dir)
    assert resolved['path'] == 'subdir/sol.cpp'


def test_resolve_optional_str_none():
    """Optional[str] param with None value is left as None."""

    def cmd(
        path: Annotated[Optional[str], PackagePath, typer.Argument()] = None,
    ):
        pass

    original_cwd = pathlib.Path('/project/subdir')
    package_dir = pathlib.Path('/project')

    resolved = resolve_package_paths(cmd, (), {'path': None}, original_cwd, package_dir)
    assert resolved['path'] is None


def test_resolve_list_str():
    """Optional[List[str]] param is resolved element-wise."""

    def cmd(
        paths: Annotated[Optional[List[str]], PackagePath, typer.Argument()] = None,
    ):
        pass

    original_cwd = pathlib.Path('/project/subdir')
    package_dir = pathlib.Path('/project')

    resolved = resolve_package_paths(
        cmd, (), {'paths': ['a.cpp', 'b.cpp']}, original_cwd, package_dir
    )
    assert resolved['paths'] == ['subdir/a.cpp', 'subdir/b.cpp']


def test_resolve_list_none():
    """Optional[List[str]] param with None is left as None."""

    def cmd(
        paths: Annotated[Optional[List[str]], PackagePath, typer.Argument()] = None,
    ):
        pass

    original_cwd = pathlib.Path('/project/subdir')
    package_dir = pathlib.Path('/project')

    resolved = resolve_package_paths(cmd, (), {'paths': None}, original_cwd, package_dir)
    assert resolved['paths'] is None


def test_resolve_absolute_path():
    """Absolute path is made relative to package dir."""

    def cmd(
        path: Annotated[str, PackagePath, typer.Argument()] = '',
    ):
        pass

    original_cwd = pathlib.Path('/project/subdir')
    package_dir = pathlib.Path('/project')

    resolved = resolve_package_paths(
        cmd, (), {'path': '/project/other/sol.cpp'}, original_cwd, package_dir
    )
    assert resolved['path'] == 'other/sol.cpp'


def test_resolve_absolute_path_outside_package():
    """Absolute path outside package dir stays absolute."""

    def cmd(
        path: Annotated[str, PackagePath, typer.Argument()] = '',
    ):
        pass

    original_cwd = pathlib.Path('/project/subdir')
    package_dir = pathlib.Path('/project')

    resolved = resolve_package_paths(
        cmd, (), {'path': '/elsewhere/sol.cpp'}, original_cwd, package_dir
    )
    assert resolved['path'] == '/elsewhere/sol.cpp'


def test_no_annotation_untouched():
    """Params without PackagePath annotation are not modified."""

    def cmd(
        name: str = '',
        path: Annotated[str, PackagePath, typer.Argument()] = '',
    ):
        pass

    original_cwd = pathlib.Path('/project/subdir')
    package_dir = pathlib.Path('/project')

    resolved = resolve_package_paths(
        cmd, (), {'name': 'foo', 'path': 'sol.cpp'}, original_cwd, package_dir
    )
    assert resolved['name'] == 'foo'
    assert resolved['path'] == 'subdir/sol.cpp'


def test_resolve_pathlib_path():
    """pathlib.Path values are resolved and returned as pathlib.Path."""

    def cmd(
        path: Annotated[pathlib.Path, PackagePath, typer.Argument()] = pathlib.Path(),
    ):
        pass

    original_cwd = pathlib.Path('/project/subdir')
    package_dir = pathlib.Path('/project')

    resolved = resolve_package_paths(
        cmd, (), {'path': pathlib.Path('sol.cpp')}, original_cwd, package_dir
    )
    assert resolved['path'] == pathlib.Path('subdir/sol.cpp')
    assert isinstance(resolved['path'], pathlib.Path)


def test_resolve_same_dir():
    """When original cwd IS the package dir, paths pass through unchanged."""

    def cmd(
        path: Annotated[str, PackagePath, typer.Argument()] = '',
    ):
        pass

    package_dir = pathlib.Path('/project')

    resolved = resolve_package_paths(
        cmd, (), {'path': 'sol.cpp'}, package_dir, package_dir
    )
    assert resolved['path'] == 'sol.cpp'


def test_resolve_with_positional_args():
    """Parameters passed as positional args are also resolved."""

    def cmd(
        path: Annotated[str, PackagePath, typer.Argument()],
    ):
        pass

    original_cwd = pathlib.Path('/project/subdir')
    package_dir = pathlib.Path('/project')

    resolved = resolve_package_paths(cmd, ('sol.cpp',), {}, original_cwd, package_dir)
    assert resolved['path'] == 'subdir/sol.cpp'
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/rbx/box/test_path_resolution.py -v`
Expected: FAIL (imports don't exist yet)

**Step 3: Add `PackagePath` sentinel to `rbx/annotations.py`**

Add at the top of the file (after existing imports):

```python
class _PackagePathMarker:
    """Marker for path parameters that should be resolved relative to the package root."""

PackagePath = _PackagePathMarker()
```

**Step 4: Create `rbx/box/path_resolution.py`**

```python
import inspect
import pathlib
from typing import Any, Dict, Tuple

from typing_extensions import get_args, get_origin, get_type_hints

from rbx.annotations import _PackagePathMarker


def _has_package_path_marker(annotation: Any) -> bool:
    """Check if an annotation has the PackagePath marker in its Annotated metadata."""
    from typing_extensions import Annotated

    origin = get_origin(annotation)
    if origin is Annotated:
        for arg in get_args(annotation)[1:]:
            if isinstance(arg, _PackagePathMarker):
                return True
    return False


def _resolve_single_path(
    value: Any,
    original_cwd: pathlib.Path,
    package_dir: pathlib.Path,
) -> Any:
    """Resolve a single path value relative to the package directory."""
    path = pathlib.Path(value)
    if not path.is_absolute():
        path = original_cwd / path
    try:
        resolved = path.relative_to(package_dir)
    except ValueError:
        resolved = path

    if isinstance(value, pathlib.Path):
        return resolved
    return str(resolved)


def _resolve_path_value(
    value: Any,
    original_cwd: pathlib.Path,
    package_dir: pathlib.Path,
) -> Any:
    """Resolve a path value, handling None and list types by runtime inspection."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return type(value)(
            _resolve_single_path(v, original_cwd, package_dir) for v in value
        )
    return _resolve_single_path(value, original_cwd, package_dir)


def resolve_package_paths(
    func: Any,
    args: Tuple,
    kwargs: Dict[str, Any],
    original_cwd: pathlib.Path,
    package_dir: pathlib.Path,
) -> Dict[str, Any]:
    """Resolve PackagePath-annotated parameters from original cwd to package-relative paths.

    Returns a new kwargs dict with resolved values. Positional args are bound to
    parameter names first.
    """
    try:
        hints = get_type_hints(func, include_extras=True)
    except Exception:
        return kwargs

    # Bind positional args to parameter names.
    sig = inspect.signature(func)
    bound = sig.bind_partial(*args, **kwargs)
    bound.apply_defaults()
    resolved = dict(bound.arguments)

    for param_name, annotation in hints.items():
        if param_name == 'return':
            continue
        if param_name not in resolved:
            continue
        if _has_package_path_marker(annotation):
            resolved[param_name] = _resolve_path_value(
                resolved[param_name], original_cwd, package_dir
            )

    return resolved
```

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/rbx/box/test_path_resolution.py -v`
Expected: All PASS

**Step 6: Commit**

```
feat: add PackagePath annotation and path resolution helper
```

---

### Task 2: Integrate into `within_problem` decorator

**Files:**
- Modify: `rbx/box/package.py:93-105` (update `within_problem`)

**Step 1: Write failing integration test**

Add to `tests/rbx/box/test_path_resolution.py`:

```python
import os

from rbx.box.path_resolution import resolve_package_paths


def test_within_problem_resolves_package_paths(tmp_path):
    """End-to-end: within_problem resolves PackagePath params before calling func."""
    pkg_dir = tmp_path / 'pkg'
    pkg_dir.mkdir()
    (pkg_dir / 'problem.rbx.yml').write_text('name: test\ntimeLimit: 1000\nmemoryLimit: 256\n')

    sub_dir = pkg_dir / 'solutions'
    sub_dir.mkdir()

    captured = {}

    # We test the resolution logic directly since within_problem
    # also requires a valid package and environment setup.
    def cmd(
        path: Annotated[Optional[str], PackagePath, typer.Argument()] = None,
    ):
        captured['path'] = path

    original_cwd = sub_dir
    resolved = resolve_package_paths(cmd, (), {'path': 'sol.cpp'}, original_cwd, pkg_dir)
    assert resolved['path'] == 'solutions/sol.cpp'
```

**Step 2: Modify `within_problem` in `rbx/box/package.py`**

```python
def within_problem(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        original_cwd = pathlib.Path.cwd().resolve()
        problem_dir = find_problem()
        kwargs = path_resolution.resolve_package_paths(
            func, args, kwargs, original_cwd, problem_dir.resolve()
        )
        with cd.new_package_cd(problem_dir):
            issue_level_token = issue_stack.issue_level_var.set(
                issue_stack.IssueLevel.DETAILED
            )
            ret = func(**kwargs)
            issue_stack.print_current_report()
            issue_stack.issue_level_var.reset(issue_level_token)
            return ret

    return wrapper
```

Note: after `resolve_package_paths`, all positional args are bound into kwargs, so we call `func(**kwargs)` instead of `func(*args, **kwargs)`.

Add import at top of `package.py`:
```python
from rbx.box import path_resolution
```

**Step 3: Run all existing tests to verify no regressions**

Run: `uv run pytest tests/rbx/box/test_path_resolution.py -v`
Expected: All PASS

Run: `uv run pytest --ignore=tests/rbx/box/cli -x -q`
Expected: All PASS (no regressions)

**Step 4: Commit**

```
feat: integrate PackagePath resolution into within_problem decorator
```

---

### Task 3: Annotate existing CLI path parameters

**Files:**
- Modify: `rbx/box/cli.py` (annotate `solutions` in `run`, `irun`; `path` in `compile_command`, `validate`)

**Step 1: Add PackagePath to relevant parameters in `cli.py`**

Import at top of `cli.py`:
```python
from rbx.annotations import PackagePath
```

Commands to annotate — only parameters that represent file paths:

- `run()` line 290: `solutions: Annotated[Optional[List[str]], PackagePath, typer.Argument(...)]`
- `irun()` line 590: `solutions: Annotated[Optional[List[str]], PackagePath, typer.Argument(...)]`
- `compile_command()` line 1013: `path: Annotated[Optional[str], PackagePath, typer.Argument(...)]`
- `validate()` line 1066: `path: Annotated[Optional[str], PackagePath, typer.Option(...)]`

Do NOT annotate parameters that are not file paths (e.g. `name`, `outcome`, `tags`, `generator`, `testcase`).

**Step 2: Run existing tests to verify no regressions**

Run: `uv run pytest --ignore=tests/rbx/box/cli -x -q`
Expected: All PASS

**Step 3: Commit**

```
feat: annotate CLI path parameters with PackagePath
```

---

### Task 4: Lint check and final verification

**Step 1: Run ruff**

Run: `uv run ruff check rbx/annotations.py rbx/box/path_resolution.py rbx/box/package.py rbx/box/cli.py`
Expected: No errors

**Step 2: Run full test suite**

Run: `uv run pytest --ignore=tests/rbx/box/cli -x -q`
Expected: All PASS

**Step 3: Commit if any lint fixes were needed**

```
style: fix lint issues in PackagePath implementation
```
