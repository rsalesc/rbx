import pathlib
import subprocess
from typing import List, Optional

import git

from rbx import utils


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
    if not utils.command_exists('git'):
        raise ValueError('git is not installed')
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


def ls_version_remote_tags(uri: str) -> List[str]:
    tags = ls_remote_tags(uri)
    valid_tags = [tag for tag in tags if utils.is_valid_semver(tag)]
    return valid_tags


def latest_remote_tag(
    uri: str,
    before: Optional[str] = None,
    after: Optional[str] = None,
    include_prerelease: bool = False,
) -> str:
    try:
        tags = ls_version_remote_tags(uri)
        if not include_prerelease:
            tags = [tag for tag in tags if not utils.get_semver(tag).is_prerelease]
    except subprocess.CalledProcessError as ex:
        raise ValueError(f'Could not fetch tags for {uri}') from ex
    if not tags:
        raise ValueError(f'No valid tags found for {uri}')
    if before is not None:
        tags = [
            tag for tag in tags if utils.get_semver(tag) <= utils.get_semver(before)
        ]
    if after is not None:
        tags = [tag for tag in tags if utils.get_semver(tag) >= utils.get_semver(after)]
    return sorted(tags, key=utils.get_semver)[-1]


def has_remote_tag(uri: str, tag: str) -> bool:
    tags = ls_remote_tags(uri)
    return tag in tags


def check_symlinks(root: pathlib.Path) -> bool:
    if not utils.command_exists('git'):
        return True
    repo = get_repo_or_nil(root, search_parent_directories=True)
    if repo is None:
        return True

    completed_process = subprocess.run(
        ['git', 'ls-files', '-s'],
        cwd=repo.working_dir,
        check=True,
        capture_output=True,
        text=True,
    )

    symlink_paths: list[str] = []
    for line in completed_process.stdout.splitlines():
        # Format: "<mode> <object> <stage>\t<path>"
        # Example: "120000 <sha> 0\tpath/to/link"
        if line.startswith('120000 '):
            try:
                path = line.split('\t', 1)[1]
            except IndexError:
                continue
            symlink_paths.append(path)

    bad = []
    for rel in symlink_paths:
        fp = pathlib.Path(repo.working_dir) / rel
        try:
            if fp.exists() and not fp.is_symlink():
                bad.append(rel)
        except OSError:
            bad.append(rel)

    return len(bad) == 0
