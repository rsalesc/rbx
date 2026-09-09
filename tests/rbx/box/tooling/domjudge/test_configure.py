"""Applying a plan, and noticing when DOMjudge quietly did not apply it.

Both write endpoints answer 200 to requests they only partly carried out: an
unknown language id is dropped without a word, and an unknown configuration key
is accepted and discarded. So the contract these tests pin is that the command
fails on the *answer*, not on the status code.
"""

from typing import Any, Dict, List

import pytest

from rbx.box.tooling.domjudge import configure
from rbx.box.tooling.domjudge.plan import ConfigChange, Plan, build_plan
from tests.rbx.box.tooling.domjudge.test_plan import CPP, environment, language


class FakeApi:
    """A DOMjudge that records what it was told and answers as told to."""

    def __init__(
        self,
        languages_result: List[Dict[str, Any]],
        config_result: Dict[str, Any],
    ):
        self.server = 'http://localhost:12345/'
        self._languages_result = languages_result
        self._config_result = config_result
        self.language_payload: List[Dict[str, Any]] = []
        self.executables: Dict[str, bytes] = {}
        self.config_payload: Dict[str, Any] = {}

    async def configure_languages(self, entries):
        self.language_payload = entries
        return self._languages_result

    async def update_language_executable(self, language_id, zip_bytes):
        self.executables[language_id] = zip_bytes

    async def update_config(self, values):
        self.config_payload = values
        return self._config_result


def cpp_plan():
    return build_plan(
        environment(
            [language('cpp', 'cpp', commands=['g++ -O2 -o {executable} {compilable}'])]
        ),
        [CPP],
        {},
    )


@pytest.mark.asyncio
async def test_sends_the_whole_language_set_and_the_compile_script():
    api = FakeApi([{'id': 'cpp'}], {})

    assert await configure.apply_plan(api, cpp_plan())

    assert api.language_payload == [
        {'id': 'cpp', 'allow_submit': True, 'extensions': ['cpp', 'cc', 'cxx']}
    ]
    assert set(api.executables) == {'cpp'}


@pytest.mark.asyncio
async def test_fails_when_domjudge_silently_drops_a_language():
    """An id that matches no `externalid` is skipped -- and everything else is
    already disabled by the same call, so this has to be loud."""
    api = FakeApi([{'id': 'c'}], {})

    assert not await configure.apply_plan(api, cpp_plan())


@pytest.mark.asyncio
async def test_fails_when_a_configuration_key_does_not_stick():
    plan = Plan(
        languages=[],
        preserved=[],
        unmatched=[],
        config=[ConfigChange(key='memory_limit', current=1, desired=1048576)],
    )
    api = FakeApi([], {'memory_limit': 1})

    assert not await configure.apply_plan(api, plan)
    assert api.config_payload == {'memory_limit': 1048576}
