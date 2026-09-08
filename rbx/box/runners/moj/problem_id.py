"""The binding between an rbx package and its problem on the MOJ server.

MOJ identifies a problem as `<org>#<slug>`, where the org is a login. rbx uses
throwaway, private problems -- `<login>#rbxt-<slug>` and ids derived from it --
purely as places to run timings.

**The slug comes from `.rbx-id`**, the one identity a package has on any remote
judge -- see `rbx.box.runners.problem_id`. What lives here is only what is
*MOJ's* about an id: the org, the `<org>#<slug>` spelling, the per-phase suffix,
and the fact that this file is shared with somebody else's CLI.

`.moj-id` is **the CLI's own convention**, not an invention: `moj testrun` accepts
a directory in place of an id and reads exactly this file out of it. So it is
still written, and it is still what the `moj` CLI reads -- but it is now a
rendering of the shared slug rather than the place the slug is decided. The one
case where it stays authoritative is a package bound *before* `.rbx-id` existed:
its slug is adopted rather than replaced, so a run keeps the problem it has been
using. See `ensure_moj_id`.
"""

import json
import os
import pathlib
import re
from typing import Any, Dict

from rbx.box.runners import problem_id

MOJ_ID_NAME = '.moj-id'

# Re-exported: the marker belongs to every remote runner, not to MOJ, but the
# guard below and its callers read it from here.
RBXT_PREFIX = problem_id.RBXT_PREFIX

_RBXT_ID = re.compile(r'^(?P<org>[^#]+)#' + re.escape(RBXT_PREFIX) + r'(?P<slug>.+)$')


def derived_id(moj_id: str, suffix: str) -> str:
    """`moj_id` with `suffix` appended to its slug.

    `rbx time` measures under different limits in each of its two phases, and
    MOJ's limits live *in the package*, so one problem holding both would be
    re-uploaded and re-calibrated on every phase change -- and, since the two
    take turns, its recorded fingerprint would never match at the start of a run.
    The fast path was therefore unreachable in practice. A problem per phase
    makes each package stable across runs instead.

    Derived rather than stored: `.moj-id` holds **one** id because that is the
    `moj` CLI's own convention (`moj testrun <dir>` reads exactly this file), and
    a second field there would be rbx inventing a format inside somebody else's.
    So the committed binding stays what it always was -- the estimation problem
    -- and every other phase hangs off it. That also means every `.moj-id` already
    committed keeps working untouched.

    A suffix rather than a second prefix, for the guard's sake: `is_rbxt_id` is
    what stands between a timing package and a setter's published problem, and
    widening it to a second marker is not a change worth making for a naming
    preference. Both forms carry the one `rbxt-` marker, and they sort next to
    each other for anyone browsing the server.
    """
    assert is_rbxt_id(moj_id), (
        f'refusing to derive a problem id from `{moj_id}`, which rbx did not create'
    )
    if not suffix:
        return moj_id
    return f'{moj_id}-{suffix}'


def moj_id_path(root: pathlib.Path = pathlib.Path()) -> pathlib.Path:
    """Where the binding lives: beside `problem.rbx.yml`.

    Relative to the package root rather than under the cache directory, the same
    way `.limits` is, and for the same reason `.rbx-id` is: the cache is
    regenerated freely, and a binding that vanished with it would leave a dead
    problem on the server after every clean.
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
            #
            # Nothing is adopted from it either: a foreign id's slug is the other
            # server's naming, not an identity rbx may hand to another judge.
            return current
        # A package bound before `.rbx-id` existed. Its slug is the one the
        # server already knows this package by, so it is offered to the shared
        # file rather than overwritten from it -- and `adopt_slug` keeps an
        # existing shared slug, so a package that has both simply keeps both.
        slug = problem_id.adopt_slug(match.group('slug'), root)
    else:
        slug = problem_id.ensure_slug(root)

    moj_id = f'{login}#{RBXT_PREFIX}{slug}'
    if moj_id != current:
        payload['id'] = moj_id
        _write_payload(path, payload)
    return moj_id


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
