import contextlib
import fcntl
import functools
import json
import os
import pathlib
import resource
from typing import Any, Optional, Type, TypeVar

import rich
import rich.prompt
import rich.status
import ruyaml
import typer
import yaml
from pydantic import BaseModel
from rich import text
from rich.highlighter import JSONHighlighter

from rbx.console import console

T = TypeVar('T', bound=BaseModel)
APP_NAME = 'rbx'


def create_and_write(path: pathlib.Path, *args, **kwargs):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(*args, **kwargs)


def highlight_str(s: str) -> text.Text:
    txt = text.Text(s)
    JSONHighlighter().highlight(txt)
    return txt


def highlight_json_obj(obj: Any) -> text.Text:
    js = json.dumps(obj)
    return highlight_str(js)


def normalize_with_underscores(s: str) -> str:
    res = s.replace(' ', '_').replace('.', '_').strip('_')
    final = []

    last = ''
    for c in res:
        if c == '_' and last == c:
            continue
        last = c
        final.append(c)
    return ''.join(final)


def get_app_path() -> pathlib.Path:
    app_dir = typer.get_app_dir(APP_NAME)
    return pathlib.Path(app_dir)


def dump_schema_str(model: Type[BaseModel]) -> str:
    return json.dumps(model.model_json_schema(), indent=4)


def dump_schema(model: Type[BaseModel], path: pathlib.Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = dump_schema_str(model)
    path.write_text(schema)


def ensure_schema(model: Type[BaseModel]) -> pathlib.Path:
    path = get_app_path() / 'schemas' / f'{model.__name__}.json'
    dump_schema(model, path)
    return path.resolve()


def model_json(model: BaseModel) -> str:
    return model.model_dump_json(indent=4, exclude_unset=True, exclude_none=True)


def uploaded_schema_path(model: Type[BaseModel]) -> str:
    return f'https://rsalesc.github.io/rbx/schemas/{model.__name__}.json'


def model_to_yaml(model: BaseModel) -> str:
    path = uploaded_schema_path(model.__class__)
    return f'# yaml-language-server: $schema={path}\n\n' + yaml.dump(
        model.model_dump(mode='json', exclude_unset=True, exclude_none=True),
        sort_keys=False,
        allow_unicode=True,
    )


def model_from_yaml(model: Type[T], s: str) -> T:
    return model(**yaml.safe_load(s))


def validate_field(model: Type[T], field: str, value: Any):
    model.__pydantic_validator__.validate_assignment(
        model.model_construct(), field, value
    )


def save_ruyaml(path: pathlib.Path, yml: ruyaml.YAML, data: ruyaml.Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w') as f:
        yml.dump(data, f)


@functools.cache
def get_empty_sentinel_path() -> pathlib.Path:
    path = get_app_path() / '.empty'
    path.write_text('')
    return path


@contextlib.contextmanager
def no_progress(status: Optional[rich.status.Status]):
    if status:
        status.stop()
    yield
    if status:
        status.start()


def confirm_on_status(status: Optional[rich.status.Status], *args, **kwargs) -> bool:
    with no_progress(status):
        res = rich.prompt.Confirm.ask(*args, **kwargs, console=console)
    return res


def get_open_fds():
    fds = []
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    for fd in range(0, soft):
        try:
            fcntl.fcntl(fd, fcntl.F_GETFD)
        except IOError:
            continue
        fds.append(fd)
    return fds


@contextlib.contextmanager
def new_cd(x: pathlib.Path):
    d = os.getcwd()

    # This could raise an exception, but it's probably
    # best to let it propagate and let the caller
    # deal with it, since they requested x
    os.chdir(x)

    try:
        yield

    finally:
        # This could also raise an exception, but you *really*
        # aren't equipped to figure out what went wrong if the
        # old working directory can't be restored.
        os.chdir(d)


class StatusProgress(rich.status.Status):
    _message: str
    processed: int
    keep: bool

    def __init__(
        self, message: str, formatted_message: Optional[str] = None, keep: bool = False
    ):
        self._message = formatted_message or message
        self.keep = keep
        self.processed = 0
        super().__init__(message.format(processed=0), console=console)
        self.start()

    def __enter__(self):
        super().__enter__()
        return self

    def __exit__(self, *args, **kwargs):
        super().__exit__(*args, **kwargs)
        if self.keep:
            console.print(self._message.format(processed=self.processed))

    def update_with_progress(self, processed: int):
        self.processed = processed
        self.update(self._message.format(processed=processed))

    def step(self, delta: int = 1):
        self.processed += delta
        self.update_with_progress(self.processed)
