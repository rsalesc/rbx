import functools
import importlib
import importlib.resources
import pathlib
from typing import Callable, Dict, Type

from rbx.box import package
from rbx.box.schema import Primitive


@functools.cache
def get_header() -> pathlib.Path:
    generate_header()

    return pathlib.Path('rbx.h')


def generate_header():
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


def _get_string_var_block() -> str:
    return _get_var_block(_get_vars_of_type(str, lambda x: f'{x:!r}'))


def _get_int_var_block() -> str:
    return _get_var_block(_get_vars_of_type(int, lambda x: str(x)))


def _get_float_var_block() -> str:
    return _get_var_block(_get_vars_of_type(float, lambda x: f'{x}'))


def _get_bool_var_block() -> str:
    return _get_var_block(_get_vars_of_type(bool, lambda x: 'true' if x else 'false'))


def _get_vars_of_type(
    type: Type, transform: Callable[[Primitive], str]
) -> Dict[str, str]:
    pkg = package.find_problem_package_or_die()
    vars = pkg.expanded_vars
    return {
        name: transform(value)
        for name, value in vars.items()
        if isinstance(value, type)
    }


def _get_var_block(mappings: Dict[str, str]) -> str:
    entries = []
    # Iterate over sorted keys to ensure a deterministic order.
    for name in sorted(mappings):
        value = mappings[name]
        entry = f'  if (name == "{name}") {{\n    return {value};\n  }}\n'
        entries.append(entry)
    return ''.join(entries)
