import functools
import importlib.resources
import os
import pathlib
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Optional

import typer
from pydantic import BaseModel

from rbx import utils
from rbx.console import console
from rbx.grading.judge.storage import copyfileobj

app = typer.Typer(no_args_is_help=True)

_RESOURCES_PKG = 'rbx.resources'
_CONFIG_FILE_NAME = 'default_config.json'


def format_vars(template: str, **kwargs) -> str:
    res = template
    for key, value in kwargs.items():
        key = key.replace('_', '-')
        res = res.replace(f'%{{{key}}}', value)
    return res


class Artifact(BaseModel):
    filename: Optional[str] = None
    executable: bool = False
    optional: bool = False


class Language(BaseModel):
    template: str
    file: str
    submitFile: Optional[str] = None
    preprocess: Optional[List[str]] = None
    exec: str
    artifacts: Dict[str, Optional[Artifact]] = {}
    submitor: Optional[str] = None

    def get_file(self, basename: str) -> str:
        return format_vars(self.file, problem_code=basename)

    def has_submit_file(self) -> bool:
        return self.submitFile is not None

    def get_submit_file(self, basename: str) -> str:
        if not self.submitFile:
            return self.get_file(basename)
        return format_vars(
            self.submitFile, file=self.get_file(basename), problem_code=basename
        )

    def get_template(self) -> str:
        return get_app_file(pathlib.Path('templates') / self.template).read_text()


SubmitorConfig = Dict[str, Any]
Credentials = Dict[str, Any]


class Config(BaseModel):
    defaultLanguage: str
    languages: Dict[str, Language]
    editor: Optional[str] = None
    submitor: Dict[str, SubmitorConfig]
    credentials: Credentials
    boxEnvironment: str = 'default'

    def get_default_language(self) -> Optional[Language]:
        return self.languages.get(self.defaultLanguage)

    def get_language(self, name: Optional[str] = None) -> Optional[Language]:
        return self.languages.get(name or self.defaultLanguage)


def get_app_path() -> pathlib.Path:
    return utils.get_app_path()


def get_empty_app_persist_path() -> pathlib.Path:
    app_dir = get_app_path() / 'persist'
    shutil.rmtree(str(app_dir), ignore_errors=True)
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def get_app_file(path: pathlib.Path) -> pathlib.Path:
    file_path = get_app_path() / path
    if file_path.is_file():
        return file_path

    with importlib.resources.as_file(
        importlib.resources.files('rbx') / 'resources' / path  # type: ignore
    ) as file:
        if file.is_file():
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with file.open('rb') as fr:
                with file_path.open('wb') as fw:
                    copyfileobj(fr, fw)
    return file_path


def _download_checker(name: str, save_at: pathlib.Path):
    import requests

    console.print(f'Downloading checker {name}...')
    r = requests.get(
        f'https://raw.githubusercontent.com/MikeMirzayanov/testlib/master/checkers/{name}'
    )

    if r.ok:
        save_at.parent.mkdir(parents=True, exist_ok=True)
        with save_at.open('wb') as f:
            f.write(r.content)


def _download_testlib(save_at: pathlib.Path):
    import requests

    console.print('Downloading testlib.h...')
    r = requests.get(
        'https://raw.githubusercontent.com/MikeMirzayanov/testlib/master/testlib.h'
    )

    if r.ok:
        save_at.parent.mkdir(parents=True, exist_ok=True)
        with save_at.open('wb') as f:
            f.write(r.content)
    else:
        console.print('[error]Failed to download testlib.h.[/error]')
        raise typer.Exit(1)


def _download_jngen(save_at: pathlib.Path):
    import requests

    console.print('Downloading jngen.h...')
    r = requests.get('https://raw.githubusercontent.com/ifsmirnov/jngen/master/jngen.h')

    if r.ok:
        save_at.parent.mkdir(parents=True, exist_ok=True)
        with save_at.open('wb') as f:
            f.write(r.content)
    else:
        console.print('[error]Failed to download jngen.h.[/error]')
        raise typer.Exit(1)


def _download_bits_stdcpp(save_at: pathlib.Path):
    import requests

    console.print('Downloading bits/stdc++.h...')
    r = requests.get(
        'https://raw.githubusercontent.com/tekfyl/bits-stdc-.h-for-mac/master/stdc%2B%2B.h'
    )

    if r.ok:
        save_at.parent.mkdir(parents=True, exist_ok=True)
        with save_at.open('wb') as f:
            f.write(r.content)
    else:
        console.print('[error]Failed to download bits/stdc++.h.[/error]')
        raise typer.Exit(1)


def get_builtin_checker(name: str) -> pathlib.Path:
    app_file = get_app_file(pathlib.Path('checkers') / name)
    if not app_file.exists():
        _download_checker(name, app_file)
    return app_file


def get_testlib() -> pathlib.Path:
    app_file = get_app_file(pathlib.Path('testlib.h'))
    if not app_file.exists():
        _download_testlib(app_file)
    return app_file


def get_jngen() -> pathlib.Path:
    app_file = get_app_file(pathlib.Path('jngen.h'))
    if not app_file.exists():
        _download_jngen(app_file)
    return app_file


def get_bits_stdcpp() -> pathlib.Path:
    app_file = get_app_file(pathlib.Path('stdc++.h'))
    if not app_file.exists():
        _download_bits_stdcpp(app_file)
    return app_file


def get_default_config_path() -> pathlib.Path:
    with importlib.resources.as_file(
        importlib.resources.files('rbx') / 'resources' / _CONFIG_FILE_NAME
    ) as file:
        return file


def get_default_app_path() -> pathlib.Path:
    return get_default_config_path().parent


def get_default_config() -> Config:
    return Config.model_validate_json(get_default_config_path().read_text())


def get_config_path() -> pathlib.Path:
    return get_app_path() / 'config.json'


def get_editor():
    return get_config().editor or os.environ.get('EDITOR', None)


def is_vim_editor() -> bool:
    editor = get_editor()
    if editor is None:
        return False
    return editor.endswith('vim')


def open_editor(path: Any, *args):
    editor = get_editor()
    if editor is None:
        raise Exception('No editor found. Please set the EDITOR environment variable.')
    subprocess.run([editor, str(path), *[str(arg) for arg in args]])


def _readonly_copy(path: pathlib.Path) -> pathlib.Path:
    temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False)
    shutil.copy(str(path), temp_file.name)
    temp_file.close()
    return pathlib.Path(temp_file.name)


def edit_multiple(paths: List[pathlib.Path], readonly: bool = False):
    if is_vim_editor():
        if readonly:
            open_editor('-R', '-O', *paths)
        else:
            open_editor('-O', *paths)
        return

    if readonly:
        paths = [_readonly_copy(path) for path in paths]
    open_editor(*paths)


@functools.cache
def get_config() -> Config:
    config_path = get_config_path()
    if not config_path.is_file():
        utils.create_and_write(config_path, utils.model_json(get_default_config()))
    return Config.model_validate_json(config_path.read_text())


def save_config(cfg: Config):
    cfg_path = get_config_path()
    cfg_path.write_text(utils.model_json(cfg))
    get_config.cache_clear()


@app.command()
def path():
    """
    Show the absolute path of the config file.
    """
    get_config()  # Ensure config is created.
    console.print(get_config_path())


@app.command('list, ls')
def list():
    """
    Pretty print the config file.
    """
    console.print_json(utils.model_json(get_config()))


@app.command()
def reset():
    """
    Reset the config file to the default one.
    """
    if not typer.confirm('Do you really want to reset your config to the default one?'):
        return
    cfg_path = get_config_path()
    cfg_path.unlink(missing_ok=True)
    get_config()  # Reset the config.


@app.command('edit, e')
def edit():
    """
    Open the config in an editor.
    """
    # Ensure config is created before calling the editor.
    get_config()

    open_editor(get_config_path())
