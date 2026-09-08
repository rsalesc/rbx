"""The DOMjudge REST surface rbx uses, and nothing else.

A deliberately small client. `MojRunner` shells out to the `moj` bash CLI and
pays for it in quoting, `PATH` and bash-version problems; DOMjudge ships no CLI,
so rbx speaks HTTP itself and the transport becomes rbx's own testable code
rather than a foreign program's.

**Sync `requests` behind `asyncio.to_thread`.** The project already depends on
`requests` and on no async HTTP client, and this runner's concurrency is a
handful of in-flight polls -- nowhere near the workload that would justify adding
one. The thread hop is what keeps `prepare` and the poll loops awaitable.

Every method here maps to one endpoint and returns parsed JSON. Deciding what to
do about a result -- retry, refuse, warn -- belongs to `staging.py` and
`runner.py`, so that this module stays a description of DOMjudge rather than of
rbx's policy.
"""

import asyncio
import dataclasses
import json
import os
import pathlib
import uuid
from typing import Any, Dict, List, Optional, Tuple

import requests

from rbx.box.exception import RbxException

# Where the credentials come from. Which DOMjudge a setter can reach is a
# property of their machine, not of the problem, so this is deliberately not an
# `env.rbx.yml` or `problem.rbx.yml` setting -- committing one setter's server
# would break the package for everyone else. Same reasoning as `RBX_MOJ_BINARY`.
SERVER_VAR = 'RBX_DOMJUDGE_SERVER'
USERNAME_VAR = 'RBX_DOMJUDGE_USERNAME'
PASSWORD_VAR = 'RBX_DOMJUDGE_PASSWORD'

# How long a single request may take. Long enough for a package upload on a slow
# link, short enough that a wedged server fails rather than hangs the run.
UPLOAD_TIMEOUT_SECONDS = 300.0
REQUEST_TIMEOUT_SECONDS = 60.0


class DomjudgeApiError(RbxException):
    """A DOMjudge call failed, or the credentials to make it are missing.

    Message is **plain text with backticks**, never rich markup: `main.py` prints
    an `RbxException` with a bare builtin `print`, so `[item]` tags would reach
    the setter literally.
    """

    def __init__(self, message: str):
        super().__init__()
        self.message = message
        self.msg.append(message)


@dataclasses.dataclass(frozen=True)
class Credentials:
    server: str
    username: str
    password: str

    @property
    def api(self) -> str:
        return self.server.rstrip('/') + '/api/v4'


def credentials_from_env() -> Credentials:
    """The configured DOMjudge, or a refusal naming what is missing.

    Named one variable at a time rather than as "set the DOMjudge variables",
    because a setter who has set two of three needs to be told which one is
    absent, not to re-read all three.
    """
    missing = [
        var
        for var in (SERVER_VAR, USERNAME_VAR, PASSWORD_VAR)
        if not os.environ.get(var)
    ]
    if missing:
        listed = ', '.join(f'`{var}`' for var in missing)
        raise DomjudgeApiError(
            f'The DOMjudge runner needs {listed} to be set in the environment.\n'
            f'Set `{SERVER_VAR}` to the instance root (for example '
            f'`http://localhost:12345/`), and `{USERNAME_VAR}`/`{PASSWORD_VAR}` '
            f'to an account with admin rights on it.'
        )
    return Credentials(
        server=os.environ[SERVER_VAR],
        username=os.environ[USERNAME_VAR],
        password=os.environ[PASSWORD_VAR],
    )


class DomjudgeApi:
    """One DOMjudge instance, reached as one user."""

    def __init__(self, credentials: Credentials):
        self._credentials = credentials
        self._session = requests.Session()
        self._session.auth = (credentials.username, credentials.password)

    @property
    def server(self) -> str:
        return self._credentials.server

    # -- transport ------------------------------------------------------------

    def _call(
        self,
        method: str,
        path: str,
        *,
        data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Tuple[str, bytes]]] = None,
        json_body: Optional[Any] = None,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> Any:
        url = self._credentials.api + path
        try:
            response = self._session.request(
                method,
                url,
                data=data,
                files=files,
                json=json_body,
                timeout=timeout,
            )
        except requests.RequestException as exception:
            raise DomjudgeApiError(
                f'Could not reach the DOMjudge server at `{self._credentials.server}`: '
                f'{exception}'
            ) from exception

        if response.status_code == 401:
            raise DomjudgeApiError(
                f'DOMjudge rejected the credentials in `{USERNAME_VAR}`/`{PASSWORD_VAR}`.'
            )
        if response.status_code == 403:
            raise DomjudgeApiError(
                f'The DOMjudge user `{self._credentials.username}` is not allowed to '
                f'{method} `{path}`. The runner needs an account with admin rights.'
            )
        if response.status_code == 413:
            raise DomjudgeApiError(
                'DOMjudge refused the upload as too large (413). The server has to be '
                'configured to accept bigger files before it can hold this package.'
            )
        if response.status_code >= 400:
            raise DomjudgeApiError(
                f'DOMjudge answered {response.status_code} to {method} `{path}`: '
                f'{_readable_error(response)}'
            )

        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            # Some endpoints answer with a bare string body (`POST /contests`
            # returns the new contest id). Hand it back rather than failing.
            return response.text.strip()

    async def _acall(self, *args, **kwargs) -> Any:
        return await asyncio.to_thread(self._call, *args, **kwargs)

    # -- reads ----------------------------------------------------------------

    async def version(self) -> Any:
        return await self._acall('GET', '/version')

    async def config(self) -> Dict[str, Any]:
        return await self._acall('GET', '/config')

    async def judgehosts(self) -> List[Dict[str, Any]]:
        return await self._acall('GET', '/judgehosts')

    async def contests(self) -> List[Dict[str, Any]]:
        return await self._acall('GET', '/contests')

    async def teams(self) -> List[Dict[str, Any]]:
        return await self._acall('GET', '/teams')

    async def languages(self, contest: str) -> List[Dict[str, Any]]:
        return await self._acall('GET', f'/contests/{contest}/languages')

    async def problems(self, contest: str) -> List[Dict[str, Any]]:
        return await self._acall('GET', f'/contests/{contest}/problems')

    async def judgements(self, contest: str, submission: str) -> List[Dict[str, Any]]:
        return await self._acall(
            'GET', f'/contests/{contest}/judgements?submission_id={submission}'
        )

    async def runs(self, contest: str, judgement: str) -> List[Dict[str, Any]]:
        return await self._acall(
            'GET', f'/contests/{contest}/runs?judging_id={judgement}'
        )

    # -- writes ---------------------------------------------------------------

    async def create_contest(self, contest: Dict[str, Any]) -> str:
        """Create a contest from a JSON description; returns its external id.

        The caller passes an explicit, allow-listed dict. That is not stylistic:
        `penalty_time` in this payload rewrites the instance-wide setting of the
        same name -- observed changing an unrelated contest from 20 to 0 -- so a
        dict assembled loosely here would silently reconfigure someone's server.
        See the design doc, "penalty_time in a contest payload rewrites global
        configuration".
        """
        return await self._acall(
            'POST',
            '/contests',
            files={'json': ('contest.json', json.dumps(contest).encode())},
            timeout=UPLOAD_TIMEOUT_SECONDS,
        )

    async def add_problem_data(
        self, contest: str, problem_id: str, label: str, name: str
    ) -> List[str]:
        """Create an empty problem and link it to the contest.

        The two-step create-then-upload (this, then `upload_problem`) is what
        makes a re-upload land on the *same* problem instead of creating a
        second one; pol2dom uses the same split for the same reason.
        """
        payload = json.dumps([{'id': problem_id, 'label': label, 'name': name}])
        return await self._acall(
            'POST',
            f'/contests/{contest}/problems/add-data',
            files={'data': ('problems.json', payload.encode())},
        )

    async def upload_problem(
        self, contest: str, problem_id: str, zip_path: pathlib.Path
    ) -> Dict[str, Any]:
        """Overwrite `problem_id` in `contest` with the package at `zip_path`.

        The package's own `domjudge-problem.ini` must declare
        `externalid = <problem_id>`; DOMjudge otherwise derives the id from the
        zip filename and refuses the mismatch. The probe packager writes it.
        """
        return await self._acall(
            'POST',
            f'/contests/{contest}/problems',
            data={'problem': problem_id},
            files={'zip': (zip_path.name, zip_path.read_bytes())},
            timeout=UPLOAD_TIMEOUT_SECONDS,
        )

    async def unlink_problem(self, contest: str, problem_id: str) -> None:
        await self._acall('DELETE', f'/contests/{contest}/problems/{problem_id}')

    async def link_problem(
        self, contest: str, problem_id: str, label: str, lazy_eval_results: int
    ) -> Dict[str, Any]:
        """Link an existing problem, choosing its lazy-evaluation mode.

        `lazy_eval_results` overrides the global setting for this contest-problem
        alone, which is how the runner gets full judging without reconfiguring a
        shared instance. DOMjudge refuses this call when the problem is already
        linked, so callers unlink first.
        """
        return await self._acall(
            'PUT',
            f'/contests/{contest}/problems/{problem_id}',
            json_body={'label': label, 'lazy_eval_results': lazy_eval_results},
        )

    async def submit(
        self,
        contest: str,
        problem_id: str,
        language_id: str,
        team_id: str,
        filename: str,
        source: bytes,
    ) -> Dict[str, Any]:
        return await self._acall(
            'POST',
            f'/contests/{contest}/submissions',
            data={'problem': problem_id, 'language': language_id, 'team_id': team_id},
            files={'code[]': (filename, source)},
            timeout=UPLOAD_TIMEOUT_SECONDS,
        )


def _readable_error(response: requests.Response) -> str:
    """DOMjudge's own words, unwrapped one layer where it nests them.

    An import failure arrives as a JSON `message` whose value is itself a JSON
    document of `{info, warning, danger}` lists. Printing that raw shows the
    setter an escaped blob; the `danger` entries are the actual complaint.
    """
    try:
        body = response.json()
    except ValueError:
        return response.text.strip()[:600]

    message = body.get('message') if isinstance(body, dict) else None
    if not isinstance(message, str):
        return json.dumps(body)[:600]

    try:
        nested = json.loads(message)
    except ValueError:
        return message[:600]

    if isinstance(nested, dict) and nested.get('danger'):
        return ' '.join(str(item) for item in nested['danger'])[:600]
    return message[:600]


def unique_suffix() -> str:
    """Six hex characters, for building an id nothing else on the server holds."""
    return uuid.uuid4().hex[:6]
