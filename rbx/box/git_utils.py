import json
import pathlib
import subprocess
import time
from typing import TYPE_CHECKING, Dict, List, Optional

from rbx import utils

if TYPE_CHECKING:
    import git


def get_repo_or_nil(
    root: pathlib.Path = pathlib.Path(), search_parent_directories: bool = False
) -> Optional['git.Repo']:
    # GitPython is expensive to import (~80ms), so keep it off the module level:
    # only the few commands that really need a `Repo` object should pay for it.
    import git

    try:
        return git.Repo(root, search_parent_directories=search_parent_directories)
    except git.InvalidGitRepositoryError:
        return None


def find_repo_root(
    path: pathlib.Path, search_parent_directories: bool = True
) -> Optional[pathlib.Path]:
    """Find the working tree root containing `path`, without going through GitPython."""
    path = utils.abspath(path)
    candidates = [path, *path.parents] if search_parent_directories else [path]
    for candidate in candidates:
        if (candidate / '.git').exists():
            return candidate
    return None


def is_repo(path: pathlib.Path) -> bool:
    return find_repo_root(path, search_parent_directories=False) is not None


def is_within_repo(path: pathlib.Path) -> bool:
    return find_repo_root(path, search_parent_directories=True) is not None


def get_any_remote(repo: 'git.Repo') -> Optional['git.Remote']:
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


def resolve_remote_head(uri: str) -> str:
    """Return the commit SHA the remote's default branch (HEAD) points at."""
    if not utils.command_exists('git'):
        raise ValueError('git is not installed')
    try:
        out = subprocess.check_output(['git', 'ls-remote', uri, 'HEAD'], text=True)
    except subprocess.CalledProcessError as ex:
        raise ValueError(f'Could not resolve HEAD for {uri}') from ex
    parts = out.split()
    if not parts:
        raise ValueError(f'No HEAD found for {uri}')
    return parts[0]


def check_symlinks(root: pathlib.Path) -> bool:
    working_dir = find_repo_root(root)
    if working_dir is None:
        return True
    if not utils.command_exists('git'):
        return True

    completed_process = subprocess.run(
        ['git', 'ls-files', '-s'],
        cwd=working_dir,
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
        fp = working_dir / rel
        try:
            if fp.exists() and not fp.is_symlink():
                bad.append(rel)
        except OSError:
            bad.append(rel)

    return len(bad) == 0


# The symlink check runs before every command dispatch, and costs a `git
# ls-files` over the whole working tree. Remember a good verdict for a day so
# only the first invocation of the day pays for it.
SYMLINK_CHECK_TTL_SECONDS = 24 * 60 * 60


def _symlink_check_cache_path() -> pathlib.Path:
    return utils.get_app_path() / 'symlink-check.json'


def _read_symlink_check_cache() -> Dict[str, float]:
    try:
        cache = json.loads(_symlink_check_cache_path().read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(cache, dict):
        return {}
    return {
        key: value for key, value in cache.items() if isinstance(value, (int, float))
    }


def _write_symlink_check_cache(cache: Dict[str, float]) -> None:
    path = _symlink_check_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache))
    except OSError:
        # A cache we cannot persist is not worth failing a command over.
        pass


def check_symlinks_cached(root: pathlib.Path) -> bool:
    """`check_symlinks`, remembering a good verdict per repository for a day.

    Only successful checks are cached: a repository that does not preserve
    symlinks keeps warning on every command until it is actually fixed.
    """
    working_dir = find_repo_root(root)
    if working_dir is None:
        return True

    now = time.time()
    cache = _read_symlink_check_cache()
    checked_at = cache.get(str(working_dir))
    if checked_at is not None and 0 <= now - checked_at < SYMLINK_CHECK_TTL_SECONDS:
        return True

    if not check_symlinks(working_dir):
        return False

    cache = {
        key: value
        for key, value in cache.items()
        if 0 <= now - value < SYMLINK_CHECK_TTL_SECONDS
    }
    cache[str(working_dir)] = now
    _write_symlink_check_cache(cache)
    return True
