import functools
import importlib
import importlib.resources
import json
import pathlib
from typing import Callable, Dict, List, NamedTuple, Type

from rbx.box import package
from rbx.box.fields import Primitive, Vars

# Emitted only when some group declares `vars`. rbx::getGroup() returns "" on
# platforms where the command line is not reachable, which would silently
# validate against package-level constraints; a compile error is preferable.
_GROUP_GUARD = """#if !defined(__linux__) && !defined(__APPLE__) && !defined(_WIN32)
#error "rbx: per-group vars need command-line access on this platform"
#endif"""


@functools.cache
def get_header() -> pathlib.Path:
    generate_header()

    return pathlib.Path('rbx.h')


def generate_header():
    override_header = pathlib.Path('rbx.override.h')
    if override_header.is_file():
        pathlib.Path('rbx.h').write_bytes(override_header.read_bytes())
        return

    with importlib.resources.as_file(
        importlib.resources.files('rbx') / 'resources' / 'templates' / 'rbx.h'
    ) as file:
        with file.open('r') as f:
            header = f.read()

    with pathlib.Path('rbx.h').open('w') as f:
        f.write(_preprocess_header(header))


def _string_repr(s):
    return json.dumps(s)


def check_int_bounds(x: int) -> None:
    if x >= 2**64:
        raise ValueError(
            f'Some variable you defined (value: {x}) is too large to fit in a C++ 64-bit integer (signed or unsigned)'
        )
    if x < -(2**63):
        raise ValueError(
            f'Some variable you defined (value: {x}) is too small to fit in a C++ 64-bit signed integer (int64_t)'
        )


def _int_repr(x: Primitive) -> str:
    if isinstance(x, bool):
        return f'static_cast<int64_t>({int(x)})'
    check_int_bounds(int(x))
    return f'static_cast<int64_t>({x})'


class _VarType(NamedTuple):
    """One of the four typed accessors rbx.h exposes."""

    # Prefix of the `//<rbx::{name}_var>` / `//<rbx::{name}_var_groups>` sentinels.
    name: str
    # Python type whose values this accessor serves. The int accessor also
    # serves bools, since `isinstance(True, int)`; `_int_repr` renders them.
    type: Type
    # Renders a value as the C++ literal the accessor returns.
    render: Callable[[Primitive], str]


_VAR_TYPES: List[_VarType] = [
    _VarType('string', str, _string_repr),
    _VarType('int', int, _int_repr),
    _VarType('float', float, lambda x: f'{x}'),
    _VarType('bool', bool, lambda x: 'true' if x else 'false'),
]


def _preprocess_header(header: str) -> str:
    # Sentinels are replaced together with their own newline, so a block that
    # comes out empty leaves no blank line behind.
    header = header.replace('//<rbx::group_guard>\n', _get_group_guard())
    for var_type in _VAR_TYPES:
        header = header.replace(
            f'//<rbx::{var_type.name}_var_groups>\n', _get_group_block(var_type)
        ).replace(f'//<rbx::{var_type.name}_var>\n', _get_package_block(var_type))
    return header


def _get_groups_with_vars() -> List[str]:
    """Names of the groups that declare `vars` overrides, in a fixed order."""
    pkg = package.find_problem_package_or_die()
    return sorted(group.name for group in pkg.testcases if group.vars)


def _get_group_guard() -> str:
    if not _get_groups_with_vars():
        return ''
    return _GROUP_GUARD + '\n\n'


def _get_package_block(var_type: _VarType) -> str:
    pkg = package.find_problem_package_or_die()
    return _get_var_block(_get_vars_of_type(pkg.expanded_vars, var_type))


def _get_group_block(var_type: _VarType) -> str:
    entries = []
    for group_name in _get_groups_with_vars():
        vars = package.get_expanded_vars_for_group(group_name)
        # An arm holds the group's whole resolved var set, not just its
        # overrides, and answers on its own: it never falls through to the
        # package-level block below. Otherwise an override that changes a var's
        # type -- package `x: 1`, group `x: "one"` -- would leave the group's
        # int lookup finding the stale package value instead of nothing. For
        # the same reason an arm is emitted even when it holds no var of this
        # type: it must still shadow the package's vars of that type.
        block = _get_var_block(_get_vars_of_type(vars, var_type), indent=4)
        entries.append(
            f'  if (group == "{group_name}") {{\n{block}    return std::nullopt;\n  }}\n'
        )
    return ''.join(entries)


def _get_vars_of_type(vars: Vars, var_type: _VarType) -> Dict[str, str]:
    return {
        name: var_type.render(value)
        for name, value in vars.items()
        if isinstance(value, var_type.type)
    }


def _get_var_block(mappings: Dict[str, str], indent: int = 2) -> str:
    entries = []
    pad = ' ' * indent
    # Iterate over sorted keys to ensure a deterministic order.
    for name in sorted(mappings):
        value = mappings[name]
        entry = f'{pad}if (name == "{name}") {{\n{pad}  return {value};\n{pad}}}\n'
        entries.append(entry)
    return ''.join(entries)
