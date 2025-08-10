from typing import TYPE_CHECKING, Dict, TypeVar, Union

from deepmerge import always_merger
from pydantic import BaseModel, Field
from typing_extensions import TypeAliasType


def NameField(**kwargs):
    return Field(
        pattern=r'^[a-zA-Z0-9][a-zA-Z0-9\-_]*$', min_length=3, max_length=32, **kwargs
    )


def FNameField(**kwargs):
    return Field(
        pattern=r'^[a-zA-Z0-9][a-zA-Z0-9\-_]*$', min_length=3, max_length=128, **kwargs
    )


T = TypeVar('T', bound=BaseModel)


def merge_pydantic_models(base: T, nxt: T) -> T:
    """Merge two Pydantic model instances.

    The attributes of 'base' and 'nxt' that weren't explicitly set are dumped into dicts
    using '.model_dump(exclude_unset=True)', which are then merged using 'deepmerge',
    and the merged result is turned into a model instance using '.model_validate'.

    For attributes set on both 'base' and 'nxt', the value from 'nxt' will be used in
    the output result.
    """
    base_dict = base.model_dump(exclude_unset=True)
    nxt_dict = nxt.model_dump(exclude_unset=True)
    merged_dict = always_merger.merge(base_dict, nxt_dict)
    return base.model_validate(merged_dict)


Primitive = Union[int, float, bool, str]
Vars = Dict[str, Primitive]
if TYPE_CHECKING:
    RecVars = Dict[str, Union[Primitive, 'RecVars']]
else:
    RecVars = TypeAliasType('RecVars', "Dict[str, Union[Primitive, 'RecVars']]")


def expand_var(value: Primitive) -> Primitive:
    if not isinstance(value, str):
        return value
    if value.startswith('\\'):
        return value[1:]
    if not value.startswith('py`') or not value.endswith('`'):
        return value
    res = eval(value[3:-1])
    for supported_type in [str, int, float, bool]:
        if isinstance(res, supported_type):
            return res

    raise TypeError(
        f'Variable with backticks should evaluate to a primitive Python type: {value}'
    )


def expand_vars(recvars: RecVars) -> Vars:
    vars = {}

    def solve(rec: RecVars, prefix: str) -> None:
        nonlocal vars
        for k, v in rec.items():
            if isinstance(v, dict):
                solve(v, f'{prefix}.{k}')
            else:
                key = f'{prefix}.{k}'.strip('.')
                vars[key] = expand_var(v)

    solve(recvars, '')
    return vars
