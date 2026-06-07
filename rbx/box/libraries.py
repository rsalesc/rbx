import functools
import pathlib
from typing import List

from rbx.box.presets.schema import Library
from rbx.grading import steps


@functools.cache
def get_declared_libraries() -> List[Library]:
    """Libraries declared by the active preset for the current package kind.

    Returns an empty list when the package was not created from a preset.
    Cwd-dependent and cached, so it is registered in
    `rbx.testing_utils.clear_all_functools_cache`.
    """
    from rbx.box import presets

    preset = presets.get_active_preset_or_null()
    if preset is None:
        return []
    libs = (
        preset.libraries.contest if presets.is_contest() else preset.libraries.problem
    )
    return list(libs)


def get_always_include_libraries() -> List[Library]:
    return [lib for lib in get_declared_libraries() if lib.always_include]


def add_always_include_libraries(artifacts: steps.GradingArtifacts) -> bool:
    """Inject always_include libraries into __internal__/. Returns True if any
    were appended (so the caller knows to add -I__internal__)."""
    existing = {input.dest for input in artifacts.inputs}
    added = False
    root = pathlib.Path()
    for lib in get_always_include_libraries():
        include_as = lib.include_as or pathlib.Path((lib.path or lib.dest).name)
        dest = steps.INTERNAL_DIR / include_as
        if dest in existing:
            continue
        src = root / lib.dest
        if not src.is_file():
            # Not materialized (e.g. needs `rbx presets sync`); skip silently.
            continue
        artifacts.inputs.append(steps.GradingFileInput(src=src, dest=dest))
        existing.add(dest)
        added = True
    return added
