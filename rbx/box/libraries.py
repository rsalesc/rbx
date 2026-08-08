import functools
import pathlib
from typing import List, Optional

from rbx import console
from rbx.box.presets.schema import Library
from rbx.grading import steps

# A package without a preset still gets testlib: it is the de-facto builtin,
# declared as an always_include library by every bundled preset, and rbx's own
# builtin checkers (`wcmp.cpp` and friends) include it. Those checkers live
# outside the package root, where the dependency scanner deliberately does not
# reach, so this injection is the only thing that can resolve their include.
BUILTIN_TESTLIB = Library(
    name='testlib',
    source='MikeMirzayanov/testlib',
    path=pathlib.Path('testlib.h'),
    version='latest',
    dest=pathlib.Path('testlib.h'),
    always_include=True,
)


@functools.cache
def get_declared_libraries() -> List[Library]:
    """Libraries declared by the active preset for the current package kind.

    Falls back to just [[BUILTIN_TESTLIB]] when the package was not created from
    a preset. Cwd-dependent and cached, so it is registered in
    `rbx.testing_utils.clear_all_functools_cache`.
    """
    from rbx.box import presets

    preset = presets.get_active_preset_or_null()
    if preset is None:
        return [BUILTIN_TESTLIB]
    libs = (
        preset.libraries.contest if presets.is_contest() else preset.libraries.problem
    )
    return list(libs)


def _builtin_fallback(lib: Library) -> Optional[pathlib.Path]:
    """Where an implicitly declared library comes from when the package has none.

    Only the builtin testlib has one: a package with no preset never
    materialized it, so fall back to the copy rbx keeps in its app dir, which
    ships predownloaded. A preset-declared library deliberately has no fallback
    -- there, a missing file means the package is out of sync with its preset,
    and saying so is more useful than silently compiling against something the
    setter did not choose.
    """
    if lib is not BUILTIN_TESTLIB:
        return None

    from rbx.config import get_testlib

    path = get_testlib()
    return path if path.is_file() else None


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
            fallback = _builtin_fallback(lib)
            if fallback is None:
                # Declared but not materialized — turn a later cryptic "file not
                # found" compile error into an actionable hint.
                console.console.print(
                    f'[warning]Library [item]{lib.name}[/item] is declared but not '
                    f'materialized at [item]{lib.dest}[/item]; run '
                    '[item]rbx presets sync[/item] (or [item]rbx download '
                    f'{lib.name}[/item]).[/warning]'
                )
                continue
            src = fallback
        artifacts.inputs.append(steps.GradingFileInput(src=src, dest=dest))
        existing.add(dest)
        added = True
    return added
