import pathlib
import subprocess
from typing import List, Optional

import git
import semver


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


def _parse_tag_from_ref(ref: str) -> str:
    return ref.split('/')[-1].split('^{}')[0]


def ls_remote_tags(uri: str) -> List[str]:
    completed_process = subprocess.run(
        ['git', 'ls-remote', '--tags', uri],
        check=True,
        capture_output=True,
        text=True,
    )
    return [
        _parse_tag_from_ref(line.split('\t')[1])
        for line in completed_process.stdout.split('\n')
        if line
    ]


def latest_remote_tag(uri: str) -> str:
    tags = ls_remote_tags(uri)
    valid_tags = [tag for tag in tags if semver.Version.is_valid(tag)]
    if not valid_tags:
        raise ValueError(f'No valid tags found for {uri}')
    return sorted(valid_tags, key=semver.VersionInfo.parse)[-1]
