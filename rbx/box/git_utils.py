import pathlib
from typing import Optional

import git


def get_repo_or_nil(
    root: pathlib.Path = pathlib.Path(), search_parent_directories: bool = False
) -> Optional[git.Repo]:
    try:
        return git.Repo(root, search_parent_directories=search_parent_directories)
    except git.InvalidGitRepositoryError:
        return None


def is_repo(path: pathlib.Path) -> bool:
    return get_repo_or_nil(path, search_parent_directories=False) is not None


def is_within_repo(path: pathlib.Path) -> bool:
    return get_repo_or_nil(path, search_parent_directories=True) is not None


def get_any_remote(repo: git.Repo) -> Optional[git.Remote]:
    for remote in repo.remotes:
        if remote.exists():
            return remote
    return None
