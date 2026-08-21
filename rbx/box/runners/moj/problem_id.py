"""The binding between an rbx package and its problem on the MOJ server.

MOJ identifies a problem as `<org>#<slug>`, where the org is a login. rbx uses a
throwaway, private problem per package -- `<login>#rbxt-<slug>` -- purely as a
place to run timings, and records it in `.moj-id` at the package root.

`.moj-id` is **the CLI's own convention**, not an invention: `moj testrun` accepts
a directory in place of an id and reads exactly this file out of it. Committing it
is what makes two setters on the same problem reach the same remote problem
instead of each orphaning one on the server.
"""

import json
import os
import pathlib
import re
import secrets
from typing import Any, Dict

MOJ_ID_NAME = '.moj-id'

# The prefix marks a problem as one rbx created for its own use, so a human
# browsing the server can tell it apart from a real, published problem.
RBXT_PREFIX = 'rbxt-'

_RBXT_ID = re.compile(r'^(?P<org>[^#]+)#' + re.escape(RBXT_PREFIX) + r'(?P<slug>.+)$')


def moj_id_path(root: pathlib.Path = pathlib.Path()) -> pathlib.Path:
    """Where the binding lives: beside `problem.rbx.yml`, and git-tracked.

    Relative to the package root rather than under the cache directory, the same
    way `.limits` is: the cache is per-machine and disposable, and a binding that
    did not survive a clone would give every setter their own remote problem.
    """
    return root / MOJ_ID_NAME


def is_rbxt_id(moj_id: str) -> bool:
    """Whether this id names a throwaway problem rbx created for its own use.

    **A caller that writes must branch on this.** `ensure_moj_id` can hand back an
    id rbx did not create -- see its docstring -- and `cli.upload` overwrites
    whatever id it is given. Uploading an rbx timing package over a setter's real,
    published problem destroys their work, silently and with no `rbxt-` marker
    anywhere to warn a reader afterwards.
    """
    return _RBXT_ID.match(moj_id) is not None


def ensure_moj_id(login: str, root: pathlib.Path = pathlib.Path()) -> str:
    """The remote problem id for this package, creating the binding if needed.

    The **slug** is the stable half and the **org** is not. The org is whoever is
    logged in, and a setter cannot write under someone else's org; keeping the
    committed one would make a co-setter's run fail on a problem they have no
    permission for, rather than reach their own copy of it.

    **The returned id is not necessarily one of ours.** `.moj-id` is written by
    `moj upload` too, so a package may already be bound to a real, published
    problem; that binding is returned untouched rather than hijacked. A caller
    that only *reads* the problem may use the id as it comes, but a caller that
    **writes** -- `upload`, `calibrate` -- must first ask `is_rbxt_id`, or it will
    overwrite a real problem with an rbx timing package.
    """
    path = moj_id_path(root)
    payload = _read_payload(path)

    current = payload.get('id')
    current = current.strip() if isinstance(current, str) else ''

    if current:
        match = _RBXT_ID.match(current)
        if match is None:
            # Not one of ours. `moj upload` writes this same file, so a package
            # may legitimately be bound to a real, published problem; reclaiming
            # that under the current login would point the run at a problem that
            # does not exist, and would destroy a binding rbx never created.
            # Returning it is therefore right, and is also the hazard `is_rbxt_id`
            # exists for: what comes back here must not be uploaded over.
            return current
        slug = match.group('slug')
    else:
        slug = _new_slug()

    moj_id = f'{login}#{RBXT_PREFIX}{slug}'
    if moj_id != current:
        payload['id'] = moj_id
        _write_payload(path, payload)
    return moj_id


def _new_slug() -> str:
    """A slug that no other package will pick.

    Random rather than derived from the problem's name: ids share one namespace
    across every setter on the server, and rbx package names are not unique --
    two setters both working through the same tutorial package would otherwise
    collide on the server, and one of them would be writing over the other's
    problem. Stability comes from committing `.moj-id`, not from derivation.
    """
    return secrets.token_hex(4)


def _read_payload(path: pathlib.Path) -> Dict[str, Any]:
    """The file's contents, or an empty binding when it cannot be read.

    Regenerating rather than raising, deliberately: this file is a binding to a
    disposable `rbxt-` problem, never authored content. A half-written or
    hand-mangled one has nothing worth preserving, and refusing to run until the
    setter deletes a file they have most likely never heard of trades a working
    run for a puzzle. Nothing is lost by rebinding -- the old remote problem is
    simply left behind on the server.
    """
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _write_payload(path: pathlib.Path, payload: Dict[str, Any]) -> None:
    """Rewrite the file, keeping every field the `moj` CLI put there.

    The CLI stores `title`, `public` and `collections` here too, and only the id
    is ours to decide.

    Written through a temporary file and an atomic rename, so that an interrupted
    write leaves the previous binding intact rather than the half-written file
    `_read_payload` exists to tolerate. Tolerating one is still right -- the file
    is shared with the CLI and with whatever a setter does to it by hand -- but rbx
    should not be a way to produce one.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'{path.name}.tmp')
    tmp.write_text(json.dumps(payload, indent=2) + '\n')
    os.replace(tmp, path)
