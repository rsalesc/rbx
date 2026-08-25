"""The two MOJ API calls no `moj` CLI layer wraps.

Everything else rbx asks of MOJ goes through the judge's own CLI, so that
credentials never pass through rbx (`rbx.box.runners.moj.cli`). Listing a
contest's submissions and downloading one's source are the exceptions: `moj`,
`moj-contest`, `moj-judges` and `moj-comp` between them expose no command that
reaches `/contest/history`, `/contest/allsubmissions` or `/submission/source`.

So these two go over HTTP, reusing the bearer token the CLI's own session left on
disk. The layout is read off `lib/core.sh`, the core shared by all four layers,
and this module mirrors it exactly -- including `MOJ_CONFIG_DIR`, `MOJ_URL` and
`MOJ_HOST`, so that a setter pointing their CLI at a dev server points rbx at it
too, and the legacy unsuffixed token file that exists for `treino` alone.

**rbx never writes here.** It reads the token a `moj-contest login` created; it
cannot create one, and says so when there is none.
"""

import os
import pathlib
import re
from typing import Dict, Optional

import requests
from pydantic import BaseModel

from rbx.box.runners.moj.cli import MojCliError

# Mirrors `lib/core.sh`: `MOJ_URL="${MOJ_URL:-https://moj.naquadah.com.br}"`.
DEFAULT_MOJ_URL = 'https://moj.naquadah.com.br'

# Every path below is relative to this. The spec's own `servers` entry.
API_PREFIX = '/api/v1'

# `CONTEST="${MOJ_CONTEST:-treino}"` in the CLI -- and the one contest whose token
# file may be unsuffixed, from before sessions were per-contest.
TREINO = 'treino'

# How long a single call may take. The listings are plain TXT and the sources are
# capped at 1 MB server-side (`SUBMIT_MAX_KB`), so nothing here is a long read;
# what this actually bounds is a hung or wrong `MOJ_URL`.
_TIMEOUT_S = 30


# The verdicts that mean the judge has not finished. Taken from `moj-comp`'s own
# `_watch_verdict`, which polls until the verdict leaves this set, and matched
# case-insensitively because it lists `On queue` and `on queue` both.
#
# An empty verdict counts: the same loop treats it as still in flight.
PENDING_VERDICTS = frozenset({'', 'not answered yet', 'on queue', 'running', 'judging'})


class SubmissionRow(BaseModel):
    """One line of a MOJ history listing, reduced to what a download needs."""

    subid: str
    lang: str
    epoch: int
    verdict: str = ''

    @property
    def is_pending(self) -> bool:
        """Whether the judge is still working on this submission.

        Worth knowing before a download, because the source is archived by the
        judging daemon *after* it produces a verdict (`FLOW.md`, step 5). Ask for
        a pending submission's source and MOJ answers `404 source_notfound` --
        the same reply it gives for an id that does not exist, about one that
        plainly does and that rbx has just listed.
        """
        return self.verdict.strip().lower() in PENDING_VERDICTS


class CachedListing(BaseModel):
    """A listing as it was last read from MOJ, on its way to and from disk.

    An envelope rather than a bare dict so that the file carries a shape a future
    field can be added to, and so that reading one back is a single validation
    that either yields rows or raises -- a half-written or older file has to read
    as *no cache*, never as a partial one.
    """

    rows: Dict[str, SubmissionRow] = {}


def config_dir() -> pathlib.Path:
    """`CFG` in `lib/core.sh`."""
    override = os.environ.get('MOJ_CONFIG_DIR')
    if override:
        return pathlib.Path(override)
    return pathlib.Path.home() / '.config' / 'moj'


def base_url() -> str:
    """The server the CLI would talk to, without a trailing slash."""
    return (os.environ.get('MOJ_URL') or DEFAULT_MOJ_URL).rstrip('/')


def _headers(token: str) -> Dict[str, str]:
    headers = {'Authorization': f'Bearer {token}'}
    # `HDR=(-H "Host: $MOJ_HOST")` in the CLI: how a setter points a real client
    # at a local instance behind the production vhost.
    host = os.environ.get('MOJ_HOST')
    if host:
        headers['Host'] = host
    return headers


def read_token(contest: str) -> str:
    """The bearer token of the session `moj-contest login <contest>` created.

    `token_file` in `lib/core.sh`, including its one fallback: `treino` may still
    be sitting in an unsuffixed `token` from before sessions were per-contest, and
    no other contest ever may.
    """
    cfg = config_dir()
    candidates = [cfg / f'token-{contest}']
    if contest == TREINO:
        candidates.append(cfg / 'token')

    for candidate in candidates:
        if candidate.is_file():
            token = candidate.read_text().strip()
            if token:
                return token

    raise MojCliError(
        f'There is no MOJ session for the contest `{contest}`: no token file in '
        f'`{cfg}`.\nLog in with `moj-contest login {contest}` and try again.'
    )


def _get(path: str, contest: str, token: str, **params: str) -> requests.Response:
    """GET one API path, turning MOJ's error envelope into a readable failure."""
    url = f'{base_url()}{API_PREFIX}{path}'
    try:
        response = requests.get(
            url,
            params={'contest': contest, **params},
            headers=_headers(token),
            timeout=_TIMEOUT_S,
        )
    except requests.RequestException as e:
        raise MojCliError(f'Could not reach MOJ at `{url}`: {e}') from e

    if response.ok:
        return response

    # `{"success":false,"error":{"message":..,"code":..}}` on every handled
    # failure; an nginx error page on the rest, which `.json()` refuses.
    message = None
    try:
        body = response.json()
        if isinstance(body, dict):
            error = body.get('error')
            if isinstance(error, dict):
                message = error.get('message')
            message = message or body.get('message')
    except ValueError:
        pass

    detail = f': {message}' if message else ''
    raise MojCliError(
        f'MOJ answered {response.status_code} for `{path}`{detail}.\n'
        f'Contest `{contest}`, server `{base_url()}`.'
    )


# The `<epoch>:<subid>` pair, which is what makes a history line parseable at all.
#
# Both listings are colon-separated, and **the verdict may contain colons** -- MOJ
# documents this, and its own `contest.js` slices from the end to survive it. That
# works for the 7-field own-history form (`…:epoch:subid`) but not for the 9-field
# judge form, which appends `fullname:univ`; MOJ's `judge.js` splits *that* one
# positionally and would misread a colon-bearing verdict.
#
# Anchoring on the pair sidesteps the whole question: a >=9-digit epoch followed by
# a 32-hex md5 digest is unmistakable in either form. `lang` is then field 3 from
# the front, which is safe because the verdict is the only variable-width field and
# it sits *after* `lang`.
_ROW_RE = re.compile(r':(\d{9,}):([0-9a-f]{32})(?::|$)')

# The submission id as MOJ issues it: `submit.sh` "valida + gera id (md5)". Checked
# before any request, because it is the server's own check (`400 id_invalid`) and
# matching it locally turns a typo into an instant error instead of a round-trip.
SUBID_RE = re.compile(r'^[0-9a-f]{32}$')


def parse_submission_line(line: str) -> Optional[SubmissionRow]:
    """One listing line, or `None` when it carries no submission id.

    A line without one is normal rather than broken: a submission still queued has
    no id in the aggregated views, and blank lines end the payload.
    """
    match = _ROW_RE.search(line)
    if match is None:
        return None

    # Everything before the anchored pair is `tempo:user:probid:lang:verdict`,
    # and the verdict is whatever is left once the four fixed fields are taken --
    # which is how a verdict carrying colons survives being read.
    fields = line[: match.start()].split(':')
    if len(fields) < 5:
        return None
    return SubmissionRow(
        subid=match.group(2),
        lang=fields[3],
        epoch=int(match.group(1)),
        verdict=':'.join(fields[4:]),
    )


def list_submissions(
    contest: str, token: str, any_submission: bool
) -> Dict[str, SubmissionRow]:
    """The submissions this session can see, keyed by id.

    `any_submission` picks the endpoint, and the two are not interchangeable:
    `/contest/allsubmissions` is judge-gated and answers `403 judge_required` to
    anyone else, while `/contest/history` is every session's own and covers a
    judge's own submissions too.
    """
    path = '/contest/allsubmissions' if any_submission else '/contest/history'
    text = _get(path, contest, token).text

    rows: Dict[str, SubmissionRow] = {}
    for line in text.splitlines():
        row = parse_submission_line(line.strip())
        if row is not None:
            rows[row.subid] = row
    return rows


def download_source(contest: str, token: str, row: SubmissionRow) -> str:
    """The source of one submission, as `text/plain`.

    `time` is the submission's epoch. The server treats it as optional -- format
    validation passes without it -- but every MOJ front-end sends it, and matching
    them costs nothing and keeps rbx on the path the server actually serves.
    """
    return _get(
        '/submission/source',
        contest,
        token,
        id=row.subid,
        time=str(row.epoch),
    ).text
