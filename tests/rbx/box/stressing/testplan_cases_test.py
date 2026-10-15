"""The VS Code extension finds testplan statements with its own scanner
(vscode/src/rbx/testplan.ts) and addresses each test as `<script>:<line>`. Both
it and `statement_spans` are held to the same cases file, so a grammar change
that moves a statement's line fails here as well as there."""

import json
import pathlib

import pytest

from rbx.box.stressing.generator_script_parser import statement_spans

CASES = (
    pathlib.Path(__file__).parents[4] / 'vscode' / 'src' / 'rbx' / 'testplan.cases.json'
)
KIND = {'generator_call': 'call', 'copy_test': 'copy', 'inline_input': 'input'}


@pytest.mark.parametrize(
    'case', json.loads(CASES.read_text()), ids=lambda case: case['name']
)
def test_statement_spans_match_the_extension_cases(case):
    spans = statement_spans(case['script'])

    assert [
        {'line': s.start_line, 'endLine': s.end_line, 'kind': KIND[s.kind]}
        for s in spans
    ] == case['statements']
