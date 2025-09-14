import math
import pathlib
from functools import reduce
from typing import Any, Callable, Optional, Union

import simpleeval

NameNotDefined = simpleeval.NameNotDefined
AttributeDoesNotExist = simpleeval.AttributeDoesNotExist

PathLike = Union[str, pathlib.Path]


def _step_down(x: Any, step: int) -> int:
    x = int(x)
    return x // step * step


def _step_up(x: Any, step: int) -> int:
    x = int(x)
    return (x + step - 1) // step * step


def _step_closest(x: Any, step: int) -> int:
    x = int(x)
    return round(x / step) * step


def _path_ext(path: pathlib.Path) -> str:
    return path.suffix[1:]


def _with_path_ext(path: pathlib.Path, ext: str) -> pathlib.Path:
    return path.with_suffix(f'.{ext}')


def _path_fn(fn: Callable[[pathlib.Path], PathLike]) -> Callable[[PathLike], str]:
    def res_fn(path: PathLike) -> str:
        return str(fn(pathlib.Path(path)))

    return res_fn


def _path_fn_2args(
    fn: Callable[[pathlib.Path, str], PathLike],
) -> Callable[[PathLike, str], str]:
    def res_fn(path: PathLike, arg: str) -> str:
        return str(fn(pathlib.Path(path), arg))

    return res_fn


def _path_stem(path: pathlib.Path) -> str:
    return path.stem


def _path_parent(path: pathlib.Path) -> pathlib.Path:
    return path.parent


def _path_suffix(path: pathlib.Path) -> str:
    return path.suffix


def _get_functions(functions: Optional[dict[str, Any]]) -> dict[str, Any]:
    res = {}
    res.update(
        # Math functions.
        int=int,
        float=float,
        str=str,
        bool=bool,
        len=len,
        floor=math.floor,
        ceil=math.ceil,
        round=round,
        abs=abs,
        step_down=_step_down,
        step_up=_step_up,
        step_closest=_step_closest,
        max=max,
        min=min,
        sum=sum,
        map=map,
        zip=zip,
        filter=filter,
        reduce=reduce,
        # Path functions.
        stem=_path_fn(_path_stem),
        parent=_path_fn(_path_parent),
        suffix=_path_fn(_path_suffix),
        ext=_path_fn(_path_ext),
        with_suffix=_path_fn_2args(pathlib.Path.with_suffix),
        with_stem=_path_fn_2args(pathlib.Path.with_stem),
        with_ext=_path_fn_2args(_with_path_ext),
    )
    res.update(functions or {})
    return res


def eval(
    expression: str,
    names: Optional[dict[str, Any]] = None,
    functions: Optional[dict[str, Any]] = None,
) -> Any:
    return simpleeval.simple_eval(
        expression, names=names, functions=_get_functions(functions)
    )


def eval_int(
    expression: str,
    names: Optional[dict[str, Any]] = None,
    functions: Optional[dict[str, Any]] = None,
) -> int:
    return int(eval(expression, names, functions))


def eval_float(
    expression: str,
    names: Optional[dict[str, Any]] = None,
    functions: Optional[dict[str, Any]] = None,
) -> float:
    return float(eval(expression, names, functions))


def eval_string(
    expression: str,
    names: Optional[dict[str, Any]] = None,
    functions: Optional[dict[str, Any]] = None,
) -> str:
    return f'{eval(expression, names, functions)}'


def eval_as_fstring(
    expression: str,
    names: Optional[dict[str, Any]] = None,
    functions: Optional[dict[str, Any]] = None,
) -> str:
    # Escape single quotes in the expression so f-string is
    # parsed correctly.
    expression = expression.replace("'", "\\'")
    return eval_string(f"f'{expression}'", names, functions)
