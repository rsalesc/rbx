import json
import pathlib

import pytest

from scripts.casts.postprocess import CastVerificationError, cast_text
from scripts.casts.recorder import record
from scripts.casts.spec import RecordingSpec


@pytest.fixture
def fixtures_root(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / 'fixtures'
    (root / 'ab-problem').mkdir(parents=True)
    (root / 'ab-problem' / 'problem.rbx.yml').write_text('name: ab-problem\n')
    return root


def _spec(**kwargs) -> RecordingSpec:
    base = dict(
        name='run-basic',
        fixture='ab-problem',
        instructions=['cat problem.rbx.yml'],
        width=80,
        height=24,
    )
    base.update(kwargs)
    return RecordingSpec(**base)


def test_record_writes_a_valid_cast(
    fixtures_root: pathlib.Path, tmp_path: pathlib.Path
):
    out = tmp_path / 'out' / 'run-basic.cast'

    record(_spec(), fixtures_root=fixtures_root, out_path=out)

    header = json.loads(out.read_text().splitlines()[0])
    assert header['version'] == 2
    assert 'name: ab-problem' in cast_text(out.read_text())


def test_record_runs_inside_a_copy_of_the_fixture(
    fixtures_root: pathlib.Path, tmp_path: pathlib.Path
):
    out = tmp_path / 'run-basic.cast'

    record(_spec(instructions=['pwd']), fixtures_root=fixtures_root, out_path=out)

    assert '~/problems/ab-problem' in cast_text(out.read_text())


def test_record_scrubs_machine_paths_out_of_the_cast(
    fixtures_root: pathlib.Path, tmp_path: pathlib.Path
):
    out = tmp_path / 'run-basic.cast'

    record(
        _spec(instructions=['pwd', 'echo $HOME']),
        fixtures_root=fixtures_root,
        out_path=out,
    )

    text = out.read_text()
    assert '/var/folders' not in text
    assert '/private' not in text


def test_record_never_mutates_the_source_fixture(
    fixtures_root: pathlib.Path, tmp_path: pathlib.Path
):
    before = sorted(p.name for p in (fixtures_root / 'ab-problem').iterdir())

    record(
        _spec(instructions=['touch side-effect.txt']),
        fixtures_root=fixtures_root,
        out_path=tmp_path / 'o.cast',
    )

    assert sorted(p.name for p in (fixtures_root / 'ab-problem').iterdir()) == before


def test_record_fails_when_an_expectation_is_missing(
    fixtures_root: pathlib.Path, tmp_path: pathlib.Path
):
    out = tmp_path / 'run-basic.cast'

    with pytest.raises(CastVerificationError):
        record(
            _spec(expect_contains=['Wrong answer']),
            fixtures_root=fixtures_root,
            out_path=out,
        )

    assert not out.exists()


def test_a_failed_recording_leaves_the_previous_cast_intact(
    fixtures_root: pathlib.Path, tmp_path: pathlib.Path
):
    out = tmp_path / 'run-basic.cast'
    out.write_text('PREVIOUS GOOD CAST\n')

    with pytest.raises(CastVerificationError):
        record(
            _spec(expect_contains=['Wrong answer']),
            fixtures_root=fixtures_root,
            out_path=out,
        )

    assert out.read_text() == 'PREVIOUS GOOD CAST\n'


def test_record_reports_a_missing_fixture(
    fixtures_root: pathlib.Path, tmp_path: pathlib.Path
):
    with pytest.raises(FileNotFoundError, match='nope'):
        record(
            _spec(fixture='nope'),
            fixtures_root=fixtures_root,
            out_path=tmp_path / 'o.cast',
        )
