import pathlib
import re
from typing import Dict, Iterable, Mapping


def _sanitize(name: str) -> str:
    return re.sub(r'[^A-Za-z0-9._]', '_', name)


def _mangle(path: pathlib.Path) -> str:
    return _sanitize('__'.join(path.parts))


def assign_flat_names(
    paths: Iterable[pathlib.Path],
    *,
    reserved: Mapping[pathlib.Path, str] = {},
    enforce_stem_unique: bool = False,
) -> Dict[pathlib.Path, str]:
    """Assign a unique flat name to every path in ``paths``.

    A path whose basename (and stem, when ``enforce_stem_unique``) is globally
    unique and does not clash a reserved name keeps its bare basename, so flat
    packages stay byte-identical. Colliding paths get a ``__``-joined, sanitized
    rendering of their package-relative path, with a deterministic ``__<n>``
    counter fallback for residual collisions. Deterministic and order-independent.

    Only paths present in ``paths`` are assigned; ``reserved`` keys absent from
    ``paths`` are ignored. ``reserved`` values must be mutually distinct (they
    bypass collision handling), otherwise a :class:`ValueError` is raised.
    """
    if len(set(reserved.values())) != len(reserved):
        raise ValueError('reserved flat names must be mutually distinct')
    ordered = sorted(set(paths))
    result: Dict[pathlib.Path, str] = {}
    taken: set = set()
    taken_stems: set = set()

    def _claim(path: pathlib.Path, name: str) -> None:
        result[path] = name
        taken.add(name)
        taken_stems.add(pathlib.Path(name).stem)

    for path in ordered:
        if path in reserved:
            _claim(path, reserved[path])

    basename_counts: Dict[str, int] = {}
    stem_counts: Dict[str, int] = {}
    mangle_counts: Dict[str, int] = {}
    for path in ordered:
        if path in reserved:
            continue
        basename_counts[path.name] = basename_counts.get(path.name, 0) + 1
        stem_counts[path.stem] = stem_counts.get(path.stem, 0) + 1
        mangled = _mangle(path)
        mangle_counts[mangled] = mangle_counts.get(mangled, 0) + 1

    for path in ordered:
        if path in reserved:
            continue
        bare_ok = (
            basename_counts[path.name] == 1
            and mangle_counts[_mangle(path)] == 1
            # bare name must not collide with an already-claimed reserved name
            and path.name not in taken
            and (
                not enforce_stem_unique
                or (stem_counts[path.stem] == 1 and path.stem not in taken_stems)
            )
        )
        candidate = path.name if bare_ok else _mangle(path)
        if candidate in taken or (
            enforce_stem_unique and pathlib.Path(candidate).stem in taken_stems
        ):
            stem = pathlib.Path(candidate).stem
            suffix = pathlib.Path(candidate).suffix
            n = 1
            while f'{stem}__{n}{suffix}' in taken or (
                enforce_stem_unique and f'{stem}__{n}' in taken_stems
            ):
                n += 1
            candidate = f'{stem}__{n}{suffix}'
        _claim(path, candidate)
    return result
