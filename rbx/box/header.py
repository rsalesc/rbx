import functools
import importlib
import importlib.resources
import json
import pathlib
from typing import Callable, Dict, Type

from rbx.box import package
from rbx.box.fields import Primitive


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


def _preprocess_header(header: str) -> str:
    return (
        header.replace('//<rbx::string_var>', _get_string_var_block())
        .replace('//<rbx::int_var>', _get_int_var_block())
        .replace('//<rbx::float_var>', _get_float_var_block())
        .replace('//<rbx::bool_var>', _get_bool_var_block())
    )


def _string_repr(s):
    return json.dumps(s)


def _get_string_var_block() -> str:
    return _get_var_block(_get_vars_of_type(str, _string_repr))


def check_int_bounds(x: int) -> None:
    if x >= 2**64:
        raise ValueError(
            f'Some variable you defined (value: {x}) is too large to fit in a C++ 64-bit integer (signed or unsigned)'
        )
    if x < -(2**63):
        raise ValueError(
            f'Some variable you defined (value: {x}) is too small to fit in a C++ 64-bit signed integer (int64_t)'
        )


def _get_int_var_block() -> str:
    def _transform(x: Primitive) -> str:
        if isinstance(x, bool):
            return f'static_cast<int64_t>({int(x)})'
        check_int_bounds(int(x))
        return f'static_cast<int64_t>({x})'

    # Get both int and bool variables for the int block
    pkg = package.find_problem_package_or_die()
    vars = pkg.expanded_vars
    int_vars = {
        name: _transform(value)
        for name, value in vars.items()
        if isinstance(value, (int, bool))
    }
    return _get_var_block(int_vars)


def _get_float_var_block() -> str:
    return _get_var_block(_get_vars_of_type(float, lambda x: f'{x}'))


def _get_bool_var_block() -> str:
    return _get_var_block(_get_vars_of_type(bool, lambda x: 'true' if x else 'false'))


def _get_vars_of_type(t: Type, transform: Callable[[Primitive], str]) -> Dict[str, str]:
    pkg = package.find_problem_package_or_die()
    vars = pkg.expanded_vars
    return {
        name: transform(value) for name, value in vars.items() if isinstance(value, t)
    }


def _get_var_block(mappings: Dict[str, str]) -> str:
    entries = []
    # Iterate over sorted keys to ensure a deterministic order.
    for name in sorted(mappings):
        value = mappings[name]
        entry = f'  if (name == "{name}") {{\n    return {value};\n  }}\n'
        entries.append(entry)
    return ''.join(entries)
