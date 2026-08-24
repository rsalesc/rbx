import os
import pathlib
import re
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple, Union

import typer

from rbx import console, utils
from rbx.box import cd, environment, package
from rbx.box.formatting import href, ref
from rbx.box.runners.moj import cli
from rbx.box.runners.moj.cli import MojCliError
from rbx.box.tooling.boca.scraper import BocaRun
from rbx.box.tooling.moj import api
from rbx.box.ui.review_app import start_review

PathLike = Union[str, pathlib.Path]


class Expander(ABC):
    def needs_review(self) -> bool:
        return False

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

    def needs_review(self) -> bool:
        return True

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


class MojExpander(Expander):
    """`@moj/<contest>/<submission>` -- a submission downloaded from MOJ.

    The contest is part of the reference because a reference gets committed into
    `problem.rbx.yml`, where it has to still mean something next month on someone
    else's machine. `@moj/<submission>` is accepted as a shorthand and resolves the
    contest from `MOJ_CONTEST`, the same variable every `moj` CLI layer reads.

    Reaching MOJ needs a session **for that contest**, which `moj login` does not
    create -- it covers `treino` alone. `moj-contest login <contest>` is the one
    that does, and every failure here says so.
    """

    # `@moj/<contest>/<subid>` or `@moj/<subid>`. The contest is whatever MOJ
    # accepts as a contest id, minus the `/` that separates the two.
    MOJ_REGEX = re.compile(r'^@moj/(?:([^/]+)/)?([^/]+)$')

    def needs_review(self) -> bool:
        return True

    def get_match(self, path_str: str) -> Optional[Tuple[str, str]]:
        """`(contest, subid)`, or `None` when this is not a MOJ reference.

        A malformed *submission id* raises rather than returning `None`: it is
        unambiguously addressed to this expander, and falling through would report
        it as "not a valid expansion", which says nothing about the real mistake.
        The server's own rule is the one applied, so a typo costs no round-trip.
        """
        match = self.MOJ_REGEX.match(path_str)
        if match is None:
            return None

        contest = match.group(1) or os.environ.get('MOJ_CONTEST')
        if not contest:
            raise MojCliError(
                f'`{path_str}` does not say which MOJ contest it belongs to.\n'
                f'Write it as `@moj/<contest>/{match.group(2)}`, or set '
                f'`MOJ_CONTEST` in your environment.'
            )

        subid = match.group(2)
        if not api.SUBID_RE.match(subid):
            raise MojCliError(
                f'`{subid}` is not a MOJ submission id: an id is exactly 32 '
                f'lowercase hexadecimal characters.\nYou can copy one from the '
                f'contest page, next to the submission.'
            )
        return contest, subid

    def get_moj_folder(self, contest: str) -> pathlib.Path:
        return self.get_remote_path(pathlib.Path('moj') / contest)

    def cacheable_globs(self, path: pathlib.Path) -> List[str]:
        match = self.get_match(str(path))
        if match is None:
            return []
        contest, subid = match
        return [str(self.get_moj_folder(contest) / subid) + '.*']

    def expand(self, path: pathlib.Path) -> Optional[pathlib.Path]:
        from rbx.box.packaging.moj import moj_language_utils

        match = self.get_match(str(path))
        if match is None:
            return None
        contest, subid = match

        # Before the token is even read: this is what turns a missing session or a
        # missing `moj-contest` into its own instruction, and it is also where the
        # role comes from, which decides which listing below can be asked for.
        who = cli.contest_whoami(contest)
        token = api.read_token(contest)

        rows = api.list_submissions(
            contest, token, any_submission=who.can_read_any_submission
        )
        row = rows.get(subid)
        if row is None:
            # Asked here rather than left to the download, which answers a bare
            # `404 source_notfound` that cannot tell "no such submission" from
            # "not yours" -- and those have very different fixes.
            scope = (
                'this contest' if who.can_read_any_submission else 'your submissions'
            )
            raise MojCliError(
                f'MOJ has no submission `{subid}` among {scope} in `{contest}`.\n'
                f'You are logged in as `{who.login}`.'
                + (
                    ''
                    if who.can_read_any_submission
                    else "\nReading someone else's submission needs a judge "
                    'account in that contest.'
                )
            )

        if row.is_pending:
            # The judging daemon archives the source only once it has a verdict,
            # so downloading now would answer `404 source_notfound` -- the same
            # reply as for an id that does not exist, about one just listed.
            raise MojCliError(
                f'MOJ is still judging submission `{subid}` (`{row.verdict}`).\n'
                f'Its source is only downloadable once it has a verdict; try '
                f'again in a moment.'
            )

        source = api.download_source(contest, token, row)

        # MOJ sends no filename with the source, so one is built. The extension
        # comes from the language rbx would compile it with, falling back to MOJ's
        # own id -- which is what its web UI names the download.
        rbx_language = moj_language_utils.get_rbx_language_from_moj_language(
            moj_language_utils.normalize_moj_language(row.lang)
        )
        extension = row.lang.lower()
        if rbx_language is not None:
            language = environment.get_language_or_nil(rbx_language)
            if language is not None:
                extension = language.extension

        final_path = self.get_moj_folder(contest) / f'{subid}.{extension}'
        final_path.parent.mkdir(parents=True, exist_ok=True)
        final_path.write_text(source)
        console.console.print(f'Downloaded {href(final_path)} from MOJ...')
        return final_path


REGISTERED_EXPANDERS: List['Expander'] = [
    MainExpander(),
    BocaExpander(),
    MojExpander(),
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
            if expander.needs_review() and not start_review(expanded):
                console.console.print(
                    f'[warning]Review approval required for {ref(expanded)}. Skipping.[/warning]'
                )
                expanded.unlink(missing_ok=True)
                return None
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
