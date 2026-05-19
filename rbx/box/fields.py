from typing import TYPE_CHECKING, Dict, Optional, TypeVar, Union

from deepmerge import always_merger
from pydantic import BaseModel, Field
from typing_extensions import TypeAliasType

from rbx.box import safeeval


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


def expand_var(value: Primitive, ctx: Optional[RecVars] = None) -> Primitive:
    if not isinstance(value, str):
        return value
    if value.startswith('\\'):
        return value[1:]
    if not value.startswith('py`') or not value.endswith('`'):
        return value
    res = safeeval.eval(value[3:-1], {'vars': ctx or {}})
    for supported_type in [str, int, float, bool]:
        if isinstance(res, supported_type):
            return res

    raise TypeError(
        f'Variable with backticks should evaluate to a primitive Python type: {value}'
    )


def expand_vars(recvars: RecVars) -> Vars:
    def count_primitives(rec: RecVars) -> int:
        res = 0
        for v in rec.values():
            if isinstance(v, dict):
                res += count_primitives(v)
            else:
                res += 1
        return res

    num_vars = count_primitives(recvars)
    ctx: RecVars = {}

    def solve_step(rec: RecVars, new_ctx: RecVars, should_raise: bool = False):
        nonlocal ctx
        for k, v in rec.items():
            if isinstance(v, dict):
                solve_step(v, new_ctx.setdefault(k, {}), should_raise=should_raise)
            else:
                try:
                    new_ctx[k] = expand_var(v, ctx)
                except (safeeval.NameNotDefined, safeeval.AttributeDoesNotExist):
                    if should_raise:
                        raise

    for _ in range(num_vars):
        next_ctx: RecVars = {}
        solve_step(recvars, next_ctx)
        ctx = next_ctx
        num_expanded = count_primitives(ctx)
        if num_expanded == num_vars:
            # All variables were expanded.
            break

    num_expanded = count_primitives(ctx)
    if num_expanded != num_vars:
        try:
            solve_step(recvars, {}, should_raise=True)
        except Exception as err:
            raise err
        raise ValueError(
            f'Failed to expand variables: only {num_expanded} out of {num_vars} were expanded.\n'
            'This probably means that there is a cyclic reference.'
        )

    vars = {}

    def expand_keys(rec: RecVars, prefix: str) -> None:
        nonlocal vars
        for k, v in rec.items():
            if isinstance(v, dict):
                expand_keys(v, f'{prefix}.{k}')
            else:
                key = f'{prefix}.{k}'.strip('.')
                vars[key] = v

    expand_keys(ctx, '')
    return vars
