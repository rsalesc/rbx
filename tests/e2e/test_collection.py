import pytest


def test_collects_scenarios(pytester):
    pytester.makepyfile(
        conftest="""
from tests.e2e.conftest import *
"""
    )
    pytester.makefile(
        '.rbx.yml',
        **{
            'testdata/x/e2e': 'scenarios:\n  - name: a\n    steps: []\n  - name: b\n    steps: []\n',
        },
    )
    result = pytester.runpytest('--collect-only', '-q')
    result.stdout.fnmatch_lines(['*x/e2e.rbx.yml::a*', '*x/e2e.rbx.yml::b*'])


def test_scenarios_are_marked_e2e(pytester):
    pytester.makepyfile(
        conftest="""
from tests.e2e.conftest import *
"""
    )
    pytester.makeini(
        """
[pytest]
markers =
    e2e: mark test as end-to-end test
"""
    )
    pytester.makefile(
        '.rbx.yml',
        **{
            'testdata/x/e2e': 'scenarios:\n  - name: a\n    steps: []\n',
        },
    )

    selected = pytester.runpytest('-m', 'e2e', '--collect-only', '-q')
    assert selected.ret == 0
    selected.stdout.fnmatch_lines(['*x/e2e.rbx.yml::a*'])

    deselected = pytester.runpytest('-m', 'not e2e', '--collect-only', '-q')
    assert deselected.ret == pytest.ExitCode.NO_TESTS_COLLECTED
