"""The enforced time limit may vary per language within one run."""

from typing import Optional

import pytest

from rbx.box import solutions


@pytest.mark.parametrize(
    ('override', 'lang', 'expected'),
    [
        (None, 'cpp', None),
        (1000, 'cpp', 1000),
        (1000, None, 1000),
        ({'cpp': 1500, 'py': 4000}, 'cpp', 1500),
        ({'cpp': 1500, 'py': 4000}, 'py', 4000),
        # A language the mapping does not mention keeps the profile's own limit.
        ({'cpp': 1500}, 'java', None),
        # A mapping cannot be resolved without knowing the language.
        ({'cpp': 1500}, None, None),
    ],
)
def test_resolve_timelimit_override(override, lang: Optional[str], expected):
    assert solutions.resolve_timelimit_override(override, lang) == expected
