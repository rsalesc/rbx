"""Uploading a built MOJ package to the judge.

Unlike `rbx time --runner moj`, which uploads a throwaway probe to a private
`rbxt-` problem, this uploads a package meant to be used. It goes through the
same CLI wrapper -- `rbx.box.runners.moj.cli` -- so credentials never pass
through rbx and the session `moj login` established is reused.
"""

import re
from typing import Optional

from rbx.box.runners.moj.cli import MojCliError
from rbx.box.runners.moj.problem_id import RBXT_PREFIX

# MOJ's own rules, read off `cmd_new` in the CLI, which mirrors what the server's
# `/problems/create` enforces. Checked here so an illegal name fails by name
# rather than as a server-side 400 long after the build was paid for.
_ORG_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$')
_SLUG_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{1,80}$')


def build_problem_id(login: str, org: Optional[str], basename: str) -> str:
    """The `<org>#<slug>` this package uploads to.

    Pure on purpose: everything that needs a loaded package or a live CLI lives
    in `resolve_problem_id`, so the naming rules can be tested on their own.
    """
    resolved_org = org or login
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
