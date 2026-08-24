"""The two MOJ API calls rbx makes directly.

Nothing here touches the network: `requests.get` is replaced wholesale, and the
assertions are about the URL and parameters rbx *would* have requested. The wire
shapes those assertions encode -- the error envelope, the two listing widths, the
`400 id_invalid` rule -- were read off MOJ's published OpenAPI spec and confirmed
against the live server on 2026-08-24.
"""

import pathlib
from typing import Any, Dict, List, Optional
from unittest import mock

import pytest

from rbx.box.runners.moj.cli import MojCliError
from rbx.box.tooling.moj import api

# A submission id as MOJ issues one: an md5 digest, not a number.
_SUB = 'd89e6b7735c675fd7b50b3354ba64097'
_OTHER_SUB = '6ac4364288283cda5c5f8732eae6f144'


class _Response:
    """Just enough of `requests.Response` for `_get` to work on."""

    def __init__(
        self, status_code: int = 200, text: str = '', json_body: Optional[Any] = None
    ):
        self.status_code = status_code
        self.text = text
        self._json_body = json_body

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        if self._json_body is None:
            raise ValueError('not json')
        return self._json_body


@pytest.fixture
def get_calls():
    """Yields `(calls, holder)` with `requests.get` patched out.

    `calls` accumulates what rbx asked for; assigning `holder['response']` sets
    what comes back, so a test that only cares about the request can ignore it.
    """
    holder: Dict[str, Any] = {'response': _Response()}
    calls: List[Dict[str, Any]] = []

    def fake(url, params=None, headers=None, timeout=None):
        calls.append({'url': url, 'params': params or {}, 'headers': headers or {}})
        response = holder['response']
        return response(url, params or {}) if callable(response) else response

    with mock.patch.object(api.requests, 'get', fake):
        yield calls, holder


# -- The session on disk. ------------------------------------------------------


def test_token_comes_from_the_per_contest_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    monkeypatch.setenv('MOJ_CONFIG_DIR', str(tmp_path))
    (tmp_path / 'token-sbc2026').write_text('tok-abc')

    assert api.read_token('sbc2026') == 'tok-abc'


def test_treino_falls_back_to_the_legacy_unsuffixed_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """`lib/core.sh` keeps this fallback for `treino`, and for nothing else.

    A contest reading someone's stale `treino` token would authenticate as the
    wrong account against the wrong contest -- so the fallback stays narrow.
    """
    monkeypatch.setenv('MOJ_CONFIG_DIR', str(tmp_path))
    (tmp_path / 'token').write_text('tok-legacy')

    assert api.read_token('treino') == 'tok-legacy'
    with pytest.raises(MojCliError):
        api.read_token('sbc2026')


def test_the_suffixed_token_wins_over_the_legacy_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    monkeypatch.setenv('MOJ_CONFIG_DIR', str(tmp_path))
    (tmp_path / 'token').write_text('tok-legacy')
    (tmp_path / 'token-treino').write_text('tok-current')

    assert api.read_token('treino') == 'tok-current'


def test_a_missing_token_says_which_login_command_makes_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    monkeypatch.setenv('MOJ_CONFIG_DIR', str(tmp_path))

    with pytest.raises(MojCliError) as exc_info:
        api.read_token('sbc2026')
    assert 'moj-contest login sbc2026' in str(exc_info.value)


def test_an_empty_token_file_is_no_session_at_all(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    """An empty file would otherwise send `Bearer ` and fail as a 401 later."""
    monkeypatch.setenv('MOJ_CONFIG_DIR', str(tmp_path))
    (tmp_path / 'token-sbc2026').write_text('\n')

    with pytest.raises(MojCliError):
        api.read_token('sbc2026')


def test_base_url_honours_moj_url_and_drops_its_trailing_slash(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv('MOJ_URL', 'http://localhost:8080/')
    assert api.base_url() == 'http://localhost:8080'


def test_base_url_defaults_to_the_production_server(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv('MOJ_URL', raising=False)
    assert api.base_url() == api.DEFAULT_MOJ_URL


# -- The line parser. ----------------------------------------------------------


def test_parses_the_seven_field_own_history_form():
    line = f'1755000000:ana:A:cpp:Accepted:1755000000:{_SUB}'

    assert api.parse_submission_line(line) == api.SubmissionRow(
        subid=_SUB, lang='cpp', epoch=1755000000, verdict='Accepted'
    )


def test_parses_the_nine_field_judge_form_with_trailing_identity():
    """`/contest/allsubmissions` appends `fullname:univ` after the id."""
    line = f'1755000000:ana:A:py:Wrong Answer:1755000000:{_SUB}:Ana A:UFPB'

    row = api.parse_submission_line(line)

    assert row is not None
    assert row.subid == _SUB
    assert row.lang == 'py'


def test_survives_a_verdict_containing_a_colon():
    """MOJ documents that the verdict may carry colons.

    Its own `judge.js` splits the 9-field form positionally (`v[4]` verdict,
    `v[6]` id) and reads this line as a submission whose id is `No_Servers`.
    Anchoring on the `epoch:subid` pair is what makes rbx immune.
    """
    line = f'1755000000:ana:A:java:Judge Error: No_Servers:1755000000:{_SUB}:Ana:U'

    row = api.parse_submission_line(line)

    assert row is not None
    assert row.subid == _SUB
    assert row.lang == 'java'
    assert row.epoch == 1755000000


def test_returns_none_for_a_pending_line_with_no_submission_id():
    assert api.parse_submission_line('1755000000:ana:A:cpp:On queue::') is None


def test_returns_none_for_a_blank_line():
    assert api.parse_submission_line('') is None


def test_does_not_mistake_a_short_hex_run_for_a_submission_id():
    """32 characters exactly -- the server's own rule, and `400 id_invalid` below."""
    short = 'd89e6b7735c675fd7b50b3354ba640'
    assert (
        api.parse_submission_line(f'1755000000:ana:A:cpp:AC:1755000000:{short}') is None
    )


# -- Listing. ------------------------------------------------------------------


def test_a_judge_lists_every_submission(get_calls):
    calls, holder = get_calls
    holder['response'] = _Response(
        text=(
            f'1755000000:ana:A:cpp:Accepted:1755000000:{_SUB}:Ana A:UFPB\n'
            f'1755000100:bob:B:py:Wrong Answer:1755000100:{_OTHER_SUB}:Bob B:UFPE\n'
        )
    )

    rows = api.list_submissions('sbc2026', 'tok', any_submission=True)

    assert set(rows) == {_SUB, _OTHER_SUB}
    assert rows[_OTHER_SUB].lang == 'py'
    assert calls[0]['url'].endswith('/api/v1/contest/allsubmissions')
    assert calls[0]['params']['contest'] == 'sbc2026'
    assert calls[0]['headers']['Authorization'] == 'Bearer tok'


def test_a_competitor_lists_only_their_own(get_calls):
    """The judge endpoint answers `403 judge_required` to them, so it is not tried."""
    calls, holder = get_calls
    holder['response'] = _Response(
        text=f'1755000000:ana:A:cpp:Accepted:1755000000:{_SUB}\n'
    )

    rows = api.list_submissions('sbc2026', 'tok', any_submission=False)

    assert set(rows) == {_SUB}
    assert calls[0]['url'].endswith('/api/v1/contest/history')


def test_listing_skips_lines_that_carry_no_id(get_calls):
    _, holder = get_calls
    holder['response'] = _Response(
        text=(
            '\n'
            '1755000000:ana:A:cpp:On queue::\n'
            f'1755000100:ana:A:cpp:Accepted:1755000100:{_SUB}\n'
        )
    )

    assert set(api.list_submissions('sbc2026', 'tok', any_submission=False)) == {_SUB}


def test_a_denied_listing_surfaces_the_servers_own_message(get_calls):
    _, holder = get_calls
    holder['response'] = _Response(
        status_code=403,
        json_body={
            'success': False,
            'error': {'message': 'Judge/monitor only', 'code': 'judge_required'},
        },
    )

    with pytest.raises(MojCliError) as exc_info:
        api.list_submissions('sbc2026', 'tok', any_submission=True)
    assert 'Judge/monitor only' in str(exc_info.value)
    assert '403' in str(exc_info.value)


def test_a_non_json_error_page_still_names_the_status(get_calls):
    """nginx serves 502/504 as HTML, and `.json()` refuses it.

    The status alone is thin, but it beats an empty message -- which is the bug
    MOJ's own `_api_fail` was patched to stop producing.
    """
    _, holder = get_calls
    holder['response'] = _Response(status_code=502, text='<html>502</html>')

    with pytest.raises(MojCliError) as exc_info:
        api.list_submissions('sbc2026', 'tok', any_submission=True)
    assert '502' in str(exc_info.value)


# -- Source download. ----------------------------------------------------------


def test_download_sends_the_id_and_the_epoch(get_calls):
    calls, holder = get_calls
    holder['response'] = _Response(text='int main() { return 0; }\n')
    row = api.SubmissionRow(subid=_SUB, lang='cpp', epoch=1755000000)

    source = api.download_source('sbc2026', 'tok', row)

    assert source == 'int main() { return 0; }\n'
    assert calls[0]['url'].endswith('/api/v1/submission/source')
    assert calls[0]['params'] == {
        'contest': 'sbc2026',
        'id': _SUB,
        'time': '1755000000',
    }


def test_download_surfaces_a_missing_source(get_calls):
    _, holder = get_calls
    holder['response'] = _Response(
        status_code=404,
        json_body={
            'success': False,
            'error': {
                'message': 'Submission source not found',
                'code': 'source_notfound',
            },
        },
    )
    row = api.SubmissionRow(subid=_SUB, lang='cpp', epoch=1755000000)

    with pytest.raises(MojCliError) as exc_info:
        api.download_source('sbc2026', 'tok', row)
    assert 'Submission source not found' in str(exc_info.value)


def test_moj_host_is_sent_when_set(monkeypatch: pytest.MonkeyPatch, get_calls):
    """How a setter points a real client at a local instance."""
    calls, holder = get_calls
    monkeypatch.setenv('MOJ_HOST', 'moj.local')
    holder['response'] = _Response(text='')

    api.list_submissions('sbc2026', 'tok', any_submission=False)

    assert calls[0]['headers']['Host'] == 'moj.local'


def test_the_verdict_is_read_off_the_line():
    line = f'1755000000:ana:A:cpp:Wrong Answer:1755000000:{_SUB}'

    row = api.parse_submission_line(line)

    assert row is not None
    assert row.verdict == 'Wrong Answer'
    assert not row.is_pending


def test_a_colon_bearing_verdict_is_kept_whole():
    line = f'1755000000:ana:A:java:Judge Error: No_Servers:1755000000:{_SUB}:Ana:U'

    row = api.parse_submission_line(line)

    assert row is not None
    assert row.verdict == 'Judge Error: No_Servers'


@pytest.mark.parametrize(
    'verdict', ['Not Answered Yet', 'On queue', 'on queue', 'Running', '']
)
def test_a_submission_still_being_judged_is_pending(verdict: str):
    """Observed live: a fresh submission sits at `Not Answered Yet`.

    Its source is not archived until the judging daemon has a verdict, so this
    is what stands between a setter and a `404` that reads as "no such id".
    """
    line = f'1755000000:ana:A:cpp:{verdict}:1755000000:{_SUB}'

    row = api.parse_submission_line(line)

    assert row is not None
    assert row.is_pending


def test_an_accepted_submission_is_not_pending():
    line = f'1755000000:ana:A:cpp:Accepted:1755000000:{_SUB}'

    row = api.parse_submission_line(line)

    assert row is not None
    assert not row.is_pending
