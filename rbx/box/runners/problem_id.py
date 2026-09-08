"""The one identity an rbx package has on any remote judge.

Every remote runner needs a name to put its throwaway problem under, and every
one of them needs that name to be *the same name next time*: an id that moved
between runs would orphan a problem on the server and re-upload the whole testset
to a fresh one. Each backend used to answer that question its own way -- MOJ from
a slug it minted into `.moj-id`, DOMjudge from a hash of the package name and its
testcase count -- so one package had two unrelated identities, and DOMjudge's
moved whenever a testcase was added.

There is now one slug, in `.rbx-id` at the package root, and each backend renders
its own id from it:

- MOJ: `<login>#rbxt-<slug>`, because MOJ scopes ids by org and the org is
  whoever is logged in.
- DOMjudge: `rbxt-<slug>-<purpose>`, because DOMjudge's ids are flat and the two
  `rbx time` phases pin different limits.

**The slug is not derived from anything.** Not from the package name (rbx names
are not unique -- two setters working through the same tutorial package would
collide on a shared server, and one would be writing over the other's problem),
and not from the testset (which changes constantly, and every change would strand
a dead problem). It is random, minted once, and then kept.

**`rbxt-` is the marker that a problem is rbx's to overwrite.** It is what stands
between a timing package and a setter's real, published problem, and it belongs
to this module rather than to any one backend for that reason.
"""

import json
import os
import pathlib
import secrets
from typing import Any, Dict, Optional

# Where the slug lives: beside `problem.rbx.yml`, not under `.rbx/`. The cache is
# regenerated freely and a slug that vanished with it would leave a dead problem
# on the server after every `rbx clean`.
RBX_ID_NAME = '.rbx-id'

# The prefix marks a problem as one rbx created for its own use, so a human
# browsing the server can tell it apart from a real, published problem.
RBXT_PREFIX = 'rbxt-'


def rbx_id_path(root: pathlib.Path = pathlib.Path()) -> pathlib.Path:
    return root / RBX_ID_NAME


def ensure_slug(root: pathlib.Path = pathlib.Path()) -> str:
    """This package's slug, minting and recording one on first use.

    Idempotent, and that is the whole contract: two calls, two runs, two backends
    and two commands all have to get the same answer, or each of them binds to a
    problem of its own.
    """
    slug = read_slug(root)
    if slug is not None:
        return slug
    slug = _new_slug()
    _write_payload(rbx_id_path(root), {'slug': slug})
    return slug


def read_slug(root: pathlib.Path = pathlib.Path()) -> Optional[str]:
    """The recorded slug, or `None` when there is not a usable one.

    Anything unreadable -- absent, truncated, not JSON, not the shape it was
    written in -- reads as absent rather than raising. This file is a binding to
    a disposable `rbxt-` problem, never authored content: a half-written or
    hand-mangled one has nothing worth preserving, and refusing to run until the
    setter deletes a file they have most likely never heard of trades a working
    run for a puzzle. Nothing is lost by rebinding -- the old remote problem is
    simply left behind on the server.
    """
    payload = _read_payload(rbx_id_path(root))
    slug = payload.get('slug')
    if not isinstance(slug, str):
        return None
    slug = slug.strip()
    return slug or None


def adopt_slug(slug: str, root: pathlib.Path = pathlib.Path()) -> str:
    """Record `slug` as this package's, unless it already has one.

    How a package that predates this file keeps the problem it is already using.
    A `.moj-id` committed months ago carries a perfectly good slug, and minting a
    fresh one beside it would silently move MOJ's problem to a new server-side
    problem the next time the two were reconciled.

    **An existing slug always wins**, even against a binding that looks more
    authoritative. Overwriting it would move whichever backend had already bound
    to it, which is the one outcome this module exists to prevent; the backends
    are then free to disagree, and each stays on the problem it is already using.
    """
    existing = read_slug(root)
    if existing is not None:
        return existing
    _write_payload(rbx_id_path(root), {'slug': slug})
    return slug


def _new_slug() -> str:
    """A slug that no other package will pick."""
    return secrets.token_hex(4)


def _read_payload(path: pathlib.Path) -> Dict[str, Any]:
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
    """Rewrite the file, keeping every field somebody else put there.

    JSON with one key rather than a bare line of text, so a later need for a
    second field is an addition rather than a format change -- and so a reader
    that finds something unexpected can tell "not the shape I write" from
    "corrupt".

    Written through a temporary file and an atomic rename, so an interrupted
    write leaves the previous binding intact rather than the half-written file
    `_read_payload` exists to tolerate.
    """
    merged = _read_payload(path)
    merged.update(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'{path.name}.tmp')
    tmp.write_text(json.dumps(merged, indent=2) + '\n')
    os.replace(tmp, path)
