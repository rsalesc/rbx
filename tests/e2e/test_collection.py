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
