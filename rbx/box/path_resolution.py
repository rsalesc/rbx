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
    if str(value).startswith('@'):
        return value
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
