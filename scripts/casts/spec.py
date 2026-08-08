"""Parsing for docs recording specs (``casts/*.yml``)."""

import pathlib
from typing import Any, List, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field


class Tagged:
    """A YAML tagged scalar/mapping preserved verbatim for autocast.

    autocast's instruction schema is a tagged union (``!Command``, ``!Wait``, ...).
    We never interpret those tags -- we round-trip them so the spec files stay
    valid autocast input if the wrapper is ever replaced.
    """

    def __init__(self, tag: str, value: Any):
        self.tag = tag
        self.value = value

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Tagged)
            and self.tag == other.tag
            and self.value == other.value
        )

    def __repr__(self) -> str:
        return f'Tagged({self.tag!r}, {self.value!r})'


class _SpecLoader(yaml.SafeLoader):
    pass


def _construct_tagged(loader: yaml.Loader, tag_suffix: str, node: yaml.Node) -> Tagged:
    if isinstance(node, yaml.MappingNode):
        value: Any = loader.construct_mapping(node, deep=True)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_scalar(node)
    return Tagged(tag_suffix, value)


_SpecLoader.add_multi_constructor('!', _construct_tagged)


class _TaggedDumper(yaml.SafeDumper):
    pass


def _represent_tagged(dumper: yaml.Dumper, data: Tagged) -> yaml.Node:
    if isinstance(data.value, dict):
        return dumper.represent_mapping(f'!{data.tag}', data.value)
    if isinstance(data.value, list):
        return dumper.represent_sequence(f'!{data.tag}', data.value)
    return dumper.represent_scalar(f'!{data.tag}', str(data.value))


_TaggedDumper.add_representer(Tagged, _represent_tagged)


class RecordingSpec(BaseModel):
    model_config = ConfigDict(extra='forbid', arbitrary_types_allowed=True)

    # Filled in by `load_spec` from the filename; not present in the YAML.
    name: str = ''

    fixture: str
    title: Optional[str] = None
    width: int = 100
    height: int = 30
    type_speed: str = '60ms'
    timeout: str = '120s'
    # Casts autoplay on a loop, so without a trailing hold the final frame --
    # usually the whole point of the recording -- flashes past. Set '0s' to
    # opt out.
    end_pause: str = '3s'
    setup: List[str] = Field(default_factory=list)
    instructions: List[Any] = Field(min_length=1)
    expect_contains: List[str] = Field(default_factory=list)


def load_spec(path: pathlib.Path) -> RecordingSpec:
    data = yaml.load(path.read_text(), Loader=_SpecLoader)
    if not isinstance(data, dict):
        raise ValueError(f'{path}: expected a YAML mapping at the top level')
    if 'name' in data:
        raise ValueError(f'{path}: `name` is derived from the filename, remove it')
    return RecordingSpec(name=path.stem, **data)


def dump_autocast_yaml(data: Any) -> str:
    """Serialize a dict that may contain `Tagged` values back to YAML."""
    return yaml.dump(
        data, Dumper=_TaggedDumper, sort_keys=False, default_flow_style=False
    )
