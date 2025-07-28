import pathlib
import re
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple, Union

import typer

from rbx import console, utils
from rbx.box import cd, package
from rbx.box.formatting import href, ref
from rbx.box.tooling.boca.scraper import BocaRun

PathLike = Union[str, pathlib.Path]


class Expander(ABC):
    def get_remote_path(self, path: pathlib.Path) -> pathlib.Path:
        return package.get_problem_remote_dir() / path

    def cacheable_paths(self, path: pathlib.Path) -> List[pathlib.Path]:
        return []

    def cacheable_globs(self, path: pathlib.Path) -> List[str]:
        return []

    @abstractmethod
    def expand(self, path: pathlib.Path) -> Optional[pathlib.Path]:
        pass


class MainExpander(Expander):
    def expand(self, path: pathlib.Path) -> Optional[pathlib.Path]:
        if str(path) != '@main':
            return None
        sol = package.get_main_solution()
        if sol is None:
            return None
        return sol.path


class BocaExpander(Expander):
    BOCA_REGEX = re.compile(r'\@boca\/(\d+)(?:\-(\d+))?')

    def get_match(self, path_str: str) -> Optional[Tuple[int, int]]:
        match = self.BOCA_REGEX.match(path_str)
        if match is None:
            return None
        run_number = int(match.group(1))
        site_number = int(match.group(2)) if match.group(2) is not None else 1
        return run_number, site_number

    def get_boca_folder(self) -> pathlib.Path:
        return self.get_remote_path(pathlib.Path('boca'))

    def get_boca_path(self, run_number: int, site_number: int) -> pathlib.Path:
        return self.get_boca_folder() / f'{run_number}-{site_number}'

    def cacheable_globs(self, path: pathlib.Path) -> List[str]:
        match = self.get_match(str(path))
        if match is None:
            return []
        run_number, site_number = match
        return [str(self.get_boca_path(run_number, site_number)) + '.*']

    def expand(self, path: pathlib.Path) -> Optional[pathlib.Path]:
        from rbx.box.tooling.boca import scraper as boca_upload

        match = self.get_match(str(path))
        if match is None:
            return None
        run_number, site_number = match

        run = BocaRun.from_run_number(run_number, site_number)
        boca_uploader = boca_upload.get_boca_scraper()
        boca_uploader.login()
        sol_path = boca_uploader.download_run(run, self.get_boca_folder())
        console.console.print(f'Downloaded {href(sol_path)} from BOCA...')
        return sol_path


REGISTERED_EXPANDERS: List['Expander'] = [
    MainExpander(),
    BocaExpander(),
]


def _relative_to_pkg(path: pathlib.Path) -> pathlib.Path:
    return utils.abspath(path).relative_to(pathlib.Path.cwd())


def _try_cacheable_paths(
    path: pathlib.Path, expander: Expander
) -> Optional[pathlib.Path]:
    cached_paths = expander.cacheable_paths(path)
    for cached_path in cached_paths:
        if cached_path.exists():
            return _relative_to_pkg(cached_path)
    return None


def _try_cacheable_globs(
    path: pathlib.Path, expander: Expander
) -> Optional[pathlib.Path]:
    cached_globs = expander.cacheable_globs(path)
    for cached_glob in cached_globs:
        rel_glob = _relative_to_pkg(pathlib.Path(cached_glob))
        globbed = list(pathlib.Path.cwd().glob(str(rel_glob)))
        if not globbed:
            continue
        return _relative_to_pkg(globbed[0])
    return None


def _try_cache(path: pathlib.Path, expander: Expander) -> Optional[pathlib.Path]:
    cached = _try_cacheable_paths(path, expander)
    if cached is not None:
        return cached
    return _try_cacheable_globs(path, expander)


def _expand_path(path: pathlib.Path) -> Optional[pathlib.Path]:
    if not cd.is_problem_package():
        console.console.print(
            f'Skipping expansion of {ref(path)} because we are not in a problem package.'
        )
        raise typer.Exit(1)

    for expander in REGISTERED_EXPANDERS:
        cached = _try_cache(path, expander)
        if cached is not None:
            return cached
        expanded = expander.expand(path)
        if expanded is not None:
            return _relative_to_pkg(expanded)
    return None


def _expand_paths(paths: List[pathlib.Path]) -> List[pathlib.Path]:
    res = []
    for path in paths:
        if not str(path).startswith('@'):
            res.append(path)
            continue
        expanded = _expand_path(path)
        if expanded is None:
            console.console.print(
                f'[warning]Remote solution [item]{path}[/item] could not be expanded. Skipping.[/warning]'
            )
            continue
        res.append(expanded)
    return res


def expand_files(files: List[str]) -> List[pathlib.Path]:
    return _expand_paths([pathlib.Path(file) for file in files])


def expand_file(file: str) -> pathlib.Path:
    res = expand_files([file])
    if len(res) != 1:
        console.console.print(
            f'Could not expand {ref(file)} because it is not a valid expansion.'
        )
        raise typer.Exit(1)
    return res[0]


def is_path_remote(path: pathlib.Path) -> bool:
    remote_dir = package.get_problem_remote_dir()
    return utils.abspath(path).is_relative_to(utils.abspath(remote_dir))
