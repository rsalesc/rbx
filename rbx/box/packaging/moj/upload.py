"""Uploading a built MOJ package to the judge.

Unlike `rbx time --runner moj`, which uploads a throwaway probe to a private
`rbxt-` problem, this uploads a package meant to be used. It goes through the
same CLI wrapper -- `rbx.box.runners.moj.cli` -- so credentials never pass
through rbx and the session `moj login` established is reused.
"""

import pathlib
import re
from typing import Optional, Tuple

from rbx import console
from rbx.box import environment
from rbx.box.packaging.moj.extension import MojExtension
from rbx.box.runners.moj import cli
from rbx.box.runners.moj.cli import MojCliError
from rbx.box.runners.moj.problem_id import RBXT_PREFIX

# MOJ's own rules, read off `cmd_new` in the CLI, which mirrors what the server's
# `/problems/create` enforces. Checked here so an illegal name fails by name
# rather than as a server-side 400 long after the build was paid for.
_ORG_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$')
_SLUG_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{1,80}$')


def build_problem_id(org: str, basename: str) -> str:
    """The `<org>#<slug>` this package uploads to.

    Pure on purpose: everything that needs a loaded package or a live CLI lives
    in `resolve_org` / `resolve_problem_id`, so the naming rules can be tested on
    their own.
    """
    resolved_org = org
    if not _ORG_RE.match(resolved_org):
        raise MojCliError(
            f'`{resolved_org}` is not a valid MOJ org: an org is 2-64 characters '
            f'of `[A-Za-z0-9._-]` and cannot start with a punctuation character. '
            f'Set `extensions.moj.org` in your `env.rbx.yml`.'
        )

    # Lowercased rather than refused: rbx names legally contain uppercase and a
    # contest short name always does, so refusing would reject the common case.
    slug = basename.lower()
    if not _SLUG_RE.match(slug):
        raise MojCliError(
            f'`{slug}` is not a valid MOJ problem name: it must be 2-81 '
            f'characters of `[a-z0-9._-]` and cannot start with a punctuation '
            f'character. Rename the problem in your `problem.rbx.yml`.'
        )
    if slug.startswith(RBXT_PREFIX):
        raise MojCliError(
            f'`{slug}` starts with `{RBXT_PREFIX}`, which marks the throwaway '
            f'problems `rbx time --runner moj` creates and may overwrite without '
            f'asking. Rename the problem in your `problem.rbx.yml`.'
        )

    return f'{resolved_org}#{slug}'


def configured_org() -> Optional[str]:
    """`extensions.moj.org` from `env.rbx.yml`, if it is set."""
    return environment.get_extension_or_default('moj', MojExtension).org


async def resolve_org() -> Tuple[str, bool]:
    """The org every problem id lands under, and whether it is the personal one.

    Falling back to the login is what makes an unconfigured package uploadable at
    all, and the `moj whoami` that reads it is paid for **only** in that case: a
    package with `extensions.moj.org` set knows its ids offline, which is what
    lets `rbx tooling moj summary` list a whole contest without a live session.
    """
    org = configured_org()
    if org is not None:
        return org, False
    return await cli.whoami(), True


async def resolve_problem_id(basename: str) -> str:
    """The remote problem this package uploads to, warning if it is private.

    `basename` is the packager's own `package_basename()`, so the id on the
    server matches the artifact name on disk.
    """
    org, is_personal = await resolve_org()
    problem_id = build_problem_id(org, basename)

    if is_personal:
        # Not an error -- uploading under your own login is a perfectly good way
        # to try the flow -- but it is invisible to everyone else, and finding
        # that out from a co-setter is worse than hearing it here.
        console.console.print(
            f'[warning]No `extensions.moj.org` is set, so this package is going '
            f'to [item]{problem_id}[/item] -- your private personal org, which '
            f'nobody else can see.[/warning]\n'
            f'[warning]Set `extensions.moj.org` in your `env.rbx.yml` to upload '
            f'it somewhere shared.[/warning]'
        )
    return problem_id


async def upload_package(problem_id: str, directory: pathlib.Path) -> None:
    """Upload the built tree and queue the calibration that follows it.

    **Always both**, whatever settled the time limits. mojtools refuses to judge a
    package with no `tl` file, and calibration is what writes one -- so an uploaded
    package nobody calibrates is a package nobody can submit to, pinned limits
    included. `--calibrate` decides whether the numbers calibration measures survive
    `TLOVERRIDE`, not whether calibration runs.

    The **directory**, never the `.zip` beside it: `moj upload` tars what it is
    given, and an unzipped tree arrives with the judge's per-language scripts no
    longer executable (`zipfile.extract` does not restore mode bits).

    The server creates the problem when it does not exist -- that is how
    `rbx time --runner moj` bootstraps its own -- so there is nothing to create
    here first. What it does *not* create is the **org**: an upload to an org
    that does not exist fails, and the CLI's own message is what says so.

    The calibration is queued and **not waited on**. Calibrating is a long
    server-side job, and a setter who has just uploaded has nothing to block on;
    `moj check <id>` reports the state whenever they want it.
    """
    console.console.print(f'Uploading the package to [item]{problem_id}[/item]...')
    await cli.upload(problem_id, directory)
    console.console.print(
        f'[success]Package uploaded to [item]{problem_id}[/item]![/success]'
    )

    await cli.calibrate(problem_id)
    console.console.print(
        f'[status]Calibration queued for [item]{problem_id}[/item]. It runs on '
        f'the judge; check on it with [item]moj check {problem_id}[/item].'
        f'[/status]'
    )
