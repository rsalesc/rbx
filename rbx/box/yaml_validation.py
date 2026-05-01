"""Pretty-rendered YAML loading and validation for user-authored configs.

Loads a YAML file with ruyaml (round-trip mode, so every node carries its
source line/column) and validates it against a Pydantic model. On either a
YAML syntax error or a Pydantic validation error, raises a typed
RbxException whose ``str(exc)`` is a rust-style caret diagnostic showing
file, line, snippet, caret, and message.

The single public entry point is :func:`load_yaml_model`.
"""

from __future__ import annotations

import pathlib
from typing import Type, TypeVar

import pydantic

from rbx.box.exception import RbxException

T = TypeVar('T', bound=pydantic.BaseModel)

PYDANTIC_INTERNAL_LOC_SEGMENTS = frozenset({'union_tag', 'tagged-union'})


class YamlSyntaxError(RbxException):
    """Raised when a YAML file cannot be parsed."""


class YamlValidationError(RbxException):
    """Raised when a YAML file parses but fails Pydantic schema validation."""


def load_yaml_model(path: pathlib.Path, model: Type[T]) -> T:
    """Load a YAML file and validate it against a Pydantic model.

    Args:
        path: Path to a YAML file. Must exist; ``FileNotFoundError`` from
            ``read_text`` propagates unchanged.
        model: A ``pydantic.BaseModel`` subclass to validate the loaded
            data against.

    Returns:
        An instance of ``model`` populated from the YAML file.

    Raises:
        YamlSyntaxError: The file is not valid YAML.
        YamlValidationError: The file parses but does not match ``model``.
        FileNotFoundError: The file does not exist.
    """
    raise NotImplementedError
