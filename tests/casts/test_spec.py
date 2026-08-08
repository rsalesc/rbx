import pathlib

import pytest
from pydantic import ValidationError

from scripts.casts.spec import RecordingSpec, load_spec


def test_minimal_spec_applies_defaults():
    spec = RecordingSpec(fixture='ab-problem', instructions=['rbx run'])

    assert spec.fixture == 'ab-problem'
    assert spec.width == 100
    assert spec.height == 30
    assert spec.type_speed == '60ms'
    assert spec.timeout == '120s'
    assert spec.setup == []
    assert spec.expect_contains == []


def test_unknown_field_is_rejected():
    with pytest.raises(ValidationError):
        RecordingSpec(fixture='ab-problem', instructions=['rbx run'], colour='red')


def test_empty_instructions_are_rejected():
    with pytest.raises(ValidationError):
        RecordingSpec(fixture='ab-problem', instructions=[])


def test_load_spec_derives_name_from_filename(tmp_path: pathlib.Path):
    path = tmp_path / 'run-basic.yml'
    path.write_text(
        'fixture: ab-problem\n'
        'title: Running solutions\n'
        'setup:\n'
        '  - rbx build\n'
        'instructions:\n'
        '  - rbx run\n'
        'expect_contains:\n'
        '  - Accepted\n'
    )

    spec = load_spec(path)

    assert spec.name == 'run-basic'
    assert spec.title == 'Running solutions'
    assert spec.setup == ['rbx build']
    assert spec.expect_contains == ['Accepted']


def test_load_spec_preserves_autocast_tagged_instructions(tmp_path: pathlib.Path):
    path = tmp_path / 'ui.yml'
    path.write_text(
        'fixture: ab-problem\n'
        'instructions:\n'
        '  - rbx run\n'
        '  - !Wait 3s\n'
        '  - !Interactive\n'
        '    command: rbx ui\n'
        '    keys: [j, j, "^C"]\n'
    )

    spec = load_spec(path)

    assert spec.instructions[0] == 'rbx run'
    assert spec.instructions[1].tag == 'Wait'
    assert spec.instructions[1].value == '3s'
    assert spec.instructions[2].tag == 'Interactive'
    assert spec.instructions[2].value == {'command': 'rbx ui', 'keys': ['j', 'j', '^C']}


def test_load_spec_rejects_an_explicit_name(tmp_path: pathlib.Path):
    path = tmp_path / 'run-basic.yml'
    path.write_text('name: other\nfixture: ab-problem\ninstructions:\n  - rbx run\n')

    with pytest.raises(ValueError, match='derived from the filename'):
        load_spec(path)
