import contextlib
import enum
import functools
import json
import os
import os.path
import pathlib
import re
import shutil
import subprocess
import sys
from typing import Any, Optional, Type, TypeVar, Union

import rich
import rich.markup
import rich.prompt
import rich.status
import ruyaml
import semver
import typer
import yaml
from pydantic import BaseModel
from rich import text
from rich.highlighter import JSONHighlighter

from rbx import __version__
from rbx.console import console

T = TypeVar('T', bound=BaseModel)
APP_NAME = 'rbx'
PIP_NAME = 'rbx.cp'
PathOrStr = Union[pathlib.Path, str]


class SemVerCompatibility(enum.Enum):
    COMPATIBLE = 'compatible'
    OUTDATED = 'outdated'
    BREAKING_CHANGE = 'breaking_change'


def get_version() -> str:
    return __version__.__version__


def get_semver() -> semver.VersionInfo:
    return semver.VersionInfo.parse(get_version())


def get_upgrade_command(
    version: Optional[Union[str, semver.VersionInfo]] = None,
) -> str:
    parsed_version = (
        semver.VersionInfo.parse(version) if isinstance(version, str) else version
    ) or get_semver()
    return f'pipx install --upgrade {PIP_NAME}@{parsed_version.major}'


def check_version_compatibility_between(
    installed: str,
    required: str,
) -> SemVerCompatibility:
    installed_version = semver.VersionInfo.parse(installed)
    required_version = semver.VersionInfo.parse(required)
    if installed_version < required_version:
        return SemVerCompatibility.OUTDATED
    if installed_version.major > required_version.major:
        return SemVerCompatibility.BREAKING_CHANGE
    return SemVerCompatibility.COMPATIBLE


def check_version_compatibility(required: str) -> SemVerCompatibility:
    installed = get_version()
    return check_version_compatibility_between(installed, required)


def print_open_fd_count(id: Optional[str] = None) -> int:
    import psutil

    try:
        open_fds = get_open_fds()
        print(f'Number of opened file descriptors for {id or "..."}: {open_fds}')
    except psutil.AccessDenied:
        print('Access denied. Run with appropriate permissions (e.g., sudo) if needed.')
    except Exception as e:
        print(f'An error occurred: {e}')


class FdLeakDetector:
    def __init__(self, id: Optional[str] = None, diff: bool = False):
        self.open_fds = 0
        self.id = id
        self.diff = diff

    def __enter__(self):
        self.open_fds = get_open_fds()
        return self

    def __exit__(self, *args, **kwargs):
        open_fds = get_open_fds()
        if open_fds > self.open_fds:
            print(
                f'File descriptor leak detected for {self.id or "..."}: {open_fds - self.open_fds} new file descriptors opened'
            )
        elif self.diff and open_fds < self.open_fds:
            print(
                f'File descriptor diff detected for {self.id or "..."}: {self.open_fds - open_fds} file descriptors closed'
            )
        self.open_fds = open_fds


def create_and_write(path: pathlib.Path, *args, **kwargs):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(*args, **kwargs)


def highlight_str(s: str) -> text.Text:
    txt = text.Text(s)
    JSONHighlighter().highlight(txt)
    return txt


def escape_markup(s: str) -> str:
    return rich.markup.escape(s, _escape=re.compile(r'(\\*)(\[)').sub)


def abspath(path: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(os.path.abspath(path))


def relpath(path: pathlib.Path, base: pathlib.Path) -> pathlib.Path:
    if sys.version_info >= (3, 12):
        return path.relative_to(base, walk_up=True)
    else:
        return pathlib.Path(os.path.relpath(path, base))


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
    return abspath(path)


def model_json(model: BaseModel) -> str:
    return model.model_dump_json(indent=4, exclude_unset=True, exclude_none=True)


def uploaded_schema_path(model: Type[BaseModel]) -> str:
    return f'https://rsalesc.github.io/rbx/schemas/{model.__name__}.json'


def model_to_yaml(model: BaseModel, **kwargs) -> str:
    """Convert model to YAML string with proper boolean handling.

    This function works around Pydantic's issue where Union[str, int, float, bool]
    fields convert booleans to floats when using mode='json'.
    """
    # Use regular dump to preserve boolean types
    data = model.model_dump(exclude_unset=True, exclude_none=True)

    # Ensure the result is JSON-serializable by converting any non-JSON types
    json_safe_data = _ensure_json_serializable(data)

    # Add schema path comment and convert to YAML
    path = uploaded_schema_path(model.__class__)
    schema_comment = f'# yaml-language-server: $schema={path}\n\n'

    yaml_content = yaml.safe_dump(
        json_safe_data, sort_keys=False, allow_unicode=True, **kwargs
    )

    return schema_comment + yaml_content


def _ensure_json_serializable(obj):
    """Recursively ensure an object is JSON-serializable while preserving booleans."""
    from datetime import date, datetime
    from enum import Enum
    from pathlib import Path
    from uuid import UUID

    from rbx.autoenum import AutoEnum

    if isinstance(obj, dict):
        return {k: _ensure_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_ensure_json_serializable(item) for item in obj]
    elif isinstance(obj, tuple):
        return [_ensure_json_serializable(item) for item in obj]
    elif isinstance(obj, set):
        return [_ensure_json_serializable(item) for item in obj]
    elif isinstance(obj, AutoEnum):
        return str(obj)
    elif isinstance(obj, Enum):
        return obj.value
    elif isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    elif isinstance(obj, (datetime, date)):
        return obj.isoformat()
    elif isinstance(obj, UUID):
        return str(obj)
    elif isinstance(obj, Path):
        return str(obj)
    else:
        # For any other type, try to convert to string
        return str(obj)


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


def get_open_fds() -> int:
    import psutil

    try:
        current_process = psutil.Process()
        open_fds = current_process.num_fds()
        return open_fds
    except psutil.AccessDenied:
        return 0
    except Exception as e:
        print(f'An error occurred: {e}')
        return 0

    # fds = []
    # soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    # for fd in range(0, soft):
    #     try:
    #         fcntl.fcntl(fd, fcntl.F_GETFD)
    #     except IOError:
    #         continue
    #     fds.append(fd)
    # return fds


def command_exists(command):
    try:
        subprocess.run(
            [command], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        return True
    except FileNotFoundError:
        return False
    except subprocess.CalledProcessError:
        return True


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


def _safe_match(matcher, path):
    try:
        return matcher(path)
    except ValueError:
        return False


def copytree_honoring_gitignore(
    src: pathlib.Path, dst: pathlib.Path, extra_gitignore: Optional[str] = None
):
    from gitignore_parser import parse_gitignore, parse_gitignore_str

    ignore_matchers = []

    if extra_gitignore is not None:
        ignore_matchers.append(parse_gitignore_str(extra_gitignore, base_dir=src))

    for file in src.rglob('.gitignore'):
        if file.is_file():
            ignore_matchers.append(parse_gitignore(file))

    # TODO: use recursive walk
    for file in src.rglob('*'):
        matching_file = file
        ignored = False
        while matching_file.is_relative_to(src):
            if any(
                _safe_match(ignore_matcher, matching_file)
                for ignore_matcher in ignore_matchers
            ):
                ignored = True
                break
            matching_file = matching_file.parent
        if ignored:
            continue
        rel = relpath(file, src)
        if file.is_file():
            write_to = dst / rel
            write_to.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, write_to)


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
