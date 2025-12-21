import pathlib
from typing import List, Tuple

import typer

from rbx import console, utils


def get_relative_assets(
    relative_to: pathlib.Path,
    assets: List[str],
    root: pathlib.Path = pathlib.Path(),
) -> List[Tuple[pathlib.Path, pathlib.Path]]:
    relative_to = utils.abspath(relative_to)
    if not relative_to.is_dir():
        relative_to = relative_to.parent
    res = []
    for asset in assets:
        relative_path = pathlib.Path(asset)
        if not relative_path.is_file():
            globbed = list(
                path for path in root.glob(str(relative_path)) if path.is_file()
            )
            if not globbed and '*' not in str(relative_path):
                console.console.print(
                    f'[error]Asset [item]{asset}[/item] does not exist.[/error]'
                )
                raise typer.Exit(1)
            res.extend(get_relative_assets(relative_to, list(map(str, globbed)), root))
            continue
        if not utils.abspath(relative_path).is_relative_to(relative_to):
            console.console.print(
                f'[error]Asset [item]{asset}[/item] is not relative to your statement.[/error]'
            )
            raise typer.Exit(1)

        res.append(
            (
                utils.abspath(relative_path),
                utils.abspath(relative_path).relative_to(relative_to),
            )
        )

    return res
