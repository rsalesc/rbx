"""The API client's own decisions: credentials, and reading DOMjudge's errors.

The transport is thin on purpose, so what is worth pinning is the two places it
does interpret something -- what it says when it cannot be configured, and how it
unwraps the doubly-encoded error an import failure arrives as.
"""

import json

import pytest

from rbx.box.runners.domjudge import api


class FakeResponse:
    def __init__(self, body, text=''):
        self._body = body
        self.text = text

    def json(self):
        if self._body is None:
            raise ValueError('not json')
        return self._body


def test_credentials_come_from_the_environment(monkeypatch):
    monkeypatch.setenv(api.SERVER_VAR, 'http://localhost:12345/')
    monkeypatch.setenv(api.USERNAME_VAR, 'admin')
    monkeypatch.setenv(api.PASSWORD_VAR, 'secret')

    credentials = api.credentials_from_env()

    assert credentials.username == 'admin'
    assert credentials.api == 'http://localhost:12345/api/v4'


def test_a_trailing_slash_does_not_double_up_in_the_api_root():
    assert api.Credentials('http://host/', 'u', 'p').api == 'http://host/api/v4'
    assert api.Credentials('http://host', 'u', 'p').api == 'http://host/api/v4'


def test_only_the_missing_variables_are_named(monkeypatch):
    """A setter who has set two of three needs to be told which one is absent,
    not to re-read all three."""
    monkeypatch.setenv(api.SERVER_VAR, 'http://localhost:12345/')
    monkeypatch.delenv(api.USERNAME_VAR, raising=False)
    monkeypatch.setenv(api.PASSWORD_VAR, 'secret')

    with pytest.raises(api.DomjudgeApiError) as exc:
        api.credentials_from_env()

    message = exc.value.message
    assert api.USERNAME_VAR in message
    assert api.PASSWORD_VAR not in message.split('Set `')[0]


def test_an_import_failure_is_unwrapped_to_domjudges_own_words():
    """DOMjudge nests the real complaint two layers deep: a JSON body whose
    `message` is itself a JSON document of {info, warning, danger} lists.
    Printing that raw shows the setter an escaped blob."""
    nested = json.dumps(
        {
            'info': [],
            'warning': [],
            'danger': ['Error: External ID of problem to import into does not match'],
        }
    )
    response = FakeResponse({'code': 400, 'message': nested})

    assert (
        api._readable_error(response)  # noqa: SLF001
        == 'Error: External ID of problem to import into does not match'
    )


def test_a_plain_message_survives_unwrapping():
    response = FakeResponse({'code': 400, 'message': 'No testcases set for problem 8'})

    assert api._readable_error(response)  # noqa: SLF001 == 'No testcases set for problem 8'


def test_a_non_json_body_falls_back_to_its_text():
    response = FakeResponse(None, text='  <html>502 Bad Gateway</html>  ')

    assert api._readable_error(response)  # noqa: SLF001 == '<html>502 Bad Gateway</html>'
