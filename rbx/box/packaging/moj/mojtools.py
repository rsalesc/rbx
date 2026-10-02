"""MOJ's own driver files, taken from upstream mojtools whenever possible.

Some files a MOJ package carries are not rbx's to write: the stubs that point the
judge at mojtools' checker bridge and interactive driver, and the interactive driver
itself, which has to be a real copy because it runs in the jail. They belong to
[mojtools](https://github.com/cd-moj/mojtools), and a copy that lags behind it is
exactly how one bug ended up replicated across hundreds of MOJ packages.

So the packager fetches them from mojtools' `master` at packaging time, and falls
back to the snapshot rbx bundles (`rbx/resources/packagers/moj/mojtools/`, at the
commit in its `COMMIT` file) when it cannot. Either way it says so when the result
is not what rbx bundles: a fetched file that differs means the snapshot is stale, and
a failed fetch means the package may carry an outdated driver.

The set is resolved atomically: if any file fails to fetch, every file comes from
the snapshot, so a package never mixes two mojtools versions.
"""

import dataclasses
import pathlib
from typing import Dict, Optional, Sequence

from rbx import console
from rbx.config import get_default_app_path

UPSTREAM_RAW_URL = 'https://raw.githubusercontent.com/cd-moj/mojtools/master'
FETCH_TIMEOUT_SECONDS = 5

# Paths relative to the root of the mojtools repository.
CHECKER_COMPARE_STUB = 'testlib/compare-stub.sh'
INTERACTIVE_COMPARE_STUB = 'interactive/compare-stub.sh'
INTERACTIVE_PREP_STUB = 'interactive/prep-stub.sh'
INTERACTIVE_RUN = 'interactive/run.sh'


def vendored_root() -> pathlib.Path:
    return get_default_app_path() / 'packagers' / 'moj' / 'mojtools'


def vendored_commit() -> str:
    return (vendored_root() / 'COMMIT').read_text().strip()


def vendored(path: str) -> bytes:
    return (vendored_root() / path).read_bytes()


def fetch_upstream(path: str) -> Optional[bytes]:
    """The file at `path` on mojtools' `master`, or `None` when it cannot be fetched."""
    import requests

    try:
        response = requests.get(
            f'{UPSTREAM_RAW_URL}/{path}', timeout=FETCH_TIMEOUT_SECONDS
        )
        response.raise_for_status()
    except requests.RequestException:
        return None
    return response.content


@dataclasses.dataclass(frozen=True)
class MojtoolsFiles:
    files: Dict[str, bytes]
    upstream: bool

    def write(self, path: str, dest: pathlib.Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.files[path])
        # Every one of these is executed by the judge; without +x it gets
        # "Permission denied" and every test is a judge error.
        dest.chmod(0o755)


def resolve(paths: Sequence[str]) -> MojtoolsFiles:
    commit = vendored_commit()[:8]
    fetched: Dict[str, bytes] = {}
    for path in paths:
        data = fetch_upstream(path)
        if data is None:
            console.console.print(
                f'[warning]Could not fetch [item]{path}[/item] from mojtools; the '
                'package uses the copy bundled with rbx (mojtools '
                f'[item]{commit}[/item]), which may be outdated.[/warning]'
            )
            return MojtoolsFiles({path: vendored(path) for path in paths}, False)
        fetched[path] = data

    stale = [path for path in paths if fetched[path] != vendored(path)]
    if stale:
        console.console.print(
            '[warning]mojtools changed since the copy bundled with rbx (mojtools '
            f'[item]{commit}[/item]): '
            + ', '.join(f'[item]{path}[/item]' for path in stale)
            + '. The package uses the current upstream version.[/warning]'
        )
    return MojtoolsFiles(fetched, True)
