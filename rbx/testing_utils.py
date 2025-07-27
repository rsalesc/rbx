import importlib.resources
import os
import pathlib

import rich.markup
import rich.text
import rich.tree
from rich.filesize import decimal

from rbx import console


def get_testdata_path() -> pathlib.Path:
    with importlib.resources.as_file(
        importlib.resources.files('rbx') / 'testdata' / 'compatible'
    ) as file:
        return file.parent


def get_resources_path() -> pathlib.Path:
    with importlib.resources.as_file(
        importlib.resources.files('rbx') / 'resources' / 'default_setter_config.yml'
    ) as file:
        return file.parent


def clear_all_functools_cache():
    from rbx.box import environment, header, package

    pkgs = [environment, package, header]

    for pkg in pkgs:
        for fn in pkg.__dict__.values():
            if hasattr(fn, 'cache_clear'):
                fn.cache_clear()


def walk_directory(
    directory: pathlib.Path, tree: rich.tree.Tree, show_hidden: bool = False
) -> None:
    """Recursively build a Tree with directory contents."""
    # Sort dirs first then by filename
    paths = sorted(
        pathlib.Path(directory).iterdir(),
        key=lambda path: (path.is_file(), path.name.lower()),
    )
    for path in paths:
        # Remove hidden files
        if path.name.startswith('.') and not show_hidden:
            continue
        if path.is_dir():
            style = 'dim' if path.name.startswith('__') else ''
            branch = tree.add(
                f'[bold magenta]:open_file_folder: [link file://{path}]{rich.markup.escape(path.name)}',
                style=style,
                guide_style=style,
            )
            walk_directory(path, branch, show_hidden=show_hidden)
        else:
            text_filename = rich.text.Text(path.name, 'green')
            text_filename.highlight_regex(r'\..*$', 'bold red')
            text_filename.stylize(f'link file://{path}')

            # Check if it's a symlink and show the resolved path
            if path.is_symlink():
                try:
                    resolved = path.resolve()
                    text_filename.append(' → ', 'cyan')
                    text_filename.append(str(resolved), 'cyan italic')
                except (OSError, RuntimeError):
                    text_filename.append(' → ', 'red')
                    text_filename.append(f'{os.readlink(path)}', 'red italic')

            file_size = path.stat().st_size
            text_filename.append(f' ({decimal(file_size)})', 'blue')
            icon = (
                '🔗 '
                if path.is_symlink()
                else ('🐍 ' if path.suffix == '.py' else '📄 ')
            )
            tree.add(rich.text.Text(icon) + text_filename)


def print_directory_tree(directory: pathlib.Path, show_hidden: bool = False):
    tree = rich.tree.Tree(directory.name)
    walk_directory(directory, tree, show_hidden=show_hidden)
    console.console.print(tree)
