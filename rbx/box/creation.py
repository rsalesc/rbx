import contextlib
import pathlib
import shutil
from typing import Annotated, Iterator, List, Optional

import pydantic
import typer

from rbx import console, utils
from rbx.box import package, presets
from rbx.box.schema import Package


@contextlib.contextmanager
def removing_on_failure(dest: pathlib.Path) -> Iterator[None]:
    """Delete `dest` if the block fails and `dest` did not exist before it, so
    a failed creation leaves no half-installed package behind. A directory the
    user agreed to create into is never removed."""
    existed = dest.exists()
    try:
        yield
    except BaseException:
        if not existed and dest.is_dir():
            shutil.rmtree(dest, ignore_errors=True)
        raise


def split_languages(values: Optional[List[str]]) -> Optional[List[str]]:
    """Normalize a repeatable `--languages` option that also accepts
    comma-separated values (`-l en,pt` == `-l en -l pt`)."""
    if values is None:
        return None
    return [
        lang.strip() for value in values for lang in value.split(',') if lang.strip()
    ]


LANGUAGES_OPTION_HELP = (
    'Languages to keep from a multi-language preset (e.g. `-l en,pt`). '
    'Omit to be prompted when the preset ships more than one language.'
)


def create(
    name: Annotated[
        str,
        typer.Argument(
            help='The name of the problem package to create. This will also be the name of the folder. '
            'A relative path may be given, in which case the problem name is its basename.'
        ),
    ],
    preset: Annotated[
        Optional[str],
        typer.Option(
            '--preset',
            '-p',
            help='Which preset to use to create this package. Can be a named of an already installed preset, or an URI, in which case the preset will be downloaded.',
        ),
    ] = None,
    path: Optional[pathlib.Path] = None,
    variant: Annotated[
        Optional[str],
        typer.Option(
            '--variant',
            '-v',
            help='Which template variant of the preset to use. Omit to use the '
            'canonical template, or to be prompted when the preset offers variants.',
        ),
    ] = None,
    local: Annotated[
        bool,
        typer.Option(
            '--local',
            help='Whether to fetch the init preset from the local version of rbx, instead of the remote one (not recommended).',
        ),
    ] = False,
    languages: Annotated[
        Optional[List[str]],
        typer.Option('--languages', '-l', help=LANGUAGES_OPTION_HELP),
    ] = None,
):
    dest_path = path or pathlib.Path(name)
    languages = split_languages(languages)

    # A problem created inside a contest (`rbx contest add`) follows the
    # contest's language list rather than carrying one of its own.
    from rbx.box.contest.contest_package import (
        find_contest_languages,
        find_contest_yaml,
    )

    inherit_languages = find_contest_yaml() is not None
    if inherit_languages and languages is None:
        find_contest_languages.cache_clear()
        languages = find_contest_languages()

    # The problem name is the basename of the destination folder, even when a
    # relative path is given (e.g. `problems/my-problem` -> `my-problem`).
    problem_name = dest_path.stem
    try:
        utils.validate_field(Package, 'name', problem_name)
    except pydantic.ValidationError:
        console.console.print(
            f'[error]Invalid problem name [item]{problem_name}[/item], '
            f'derived from [item]{name}[/item].[/error]'
        )
        console.console.print(
            '[error]A problem name must be 3-32 characters long and contain only '
            'letters, digits, dashes and underscores.[/error]'
        )
        raise typer.Exit(1) from None

    console.console.print(f'Creating new problem [item]{problem_name}[/item]...')

    fetch_info = presets.get_preset_fetch_info_with_fallback(preset, local=local)

    if dest_path.exists():
        console.console.print(
            f'[error]Directory [item]{dest_path}[/item] already exists.[/error]'
        )
        raise typer.Exit(1)

    with removing_on_failure(dest_path):
        template = presets.install_problem(
            dest_path,
            fetch_info,
            variant=variant,
            languages=languages,
            inherit_languages=inherit_languages,
        )

        # Change problem name.
        ru, problem = package.get_ruyaml(dest_path)
        problem['name'] = problem_name
        utils.save_ruyaml(dest_path / 'problem.rbx.yml', ru, problem)

        # fix_package(dest_path)

        presets.generate_lock(dest_path, template=template)

    if preset is not None:
        presets.maybe_offer_to_register(fetch_info, dest_path)
