import json
import os
import pathlib
import stat

import pytest

from scripts.casts.postprocess import CastVerificationError
from scripts.casts.recorder import AutocastFailedError, AutocastMissingError, record
from scripts.casts.spec import RecordingSpec

# A stand-in for the real `autocast` binary. It reads the generated input, finds
# the hidden `cd` instruction, and emits a canned cast that echoes that working
# directory -- which lets tests assert the scrubbing actually happened.
_FAKE_AUTOCAST = """\
#!/usr/bin/env python3
import json
import pathlib
import sys

args = [a for a in sys.argv[1:] if not a.startswith('-')]
workdir = 'UNKNOWN'
for line in pathlib.Path(args[0]).read_text().splitlines():
    if 'cd /' in line:
        workdir = line.split('cd ', 1)[1].strip().strip('\\'"')
lines = [
    json.dumps(
        {
            'version': 2,
            'width': 100,
            'height': 30,
            'timestamp': 1234,
            'env': {'TERM': 'x', 'USER': 'me'},
        }
    ),
    json.dumps([0.0, 'o', '$ pwd\\r\\n' + workdir + '\\r\\n']),
    json.dumps([0.5, 'o', 'Accepted\\r\\n']),
]
pathlib.Path(args[1]).write_text('\\n'.join(lines) + '\\n')
"""

_FAILING_AUTOCAST = """\
#!/usr/bin/env python3
import sys

print('prompt detection timed out', file=sys.stderr)
sys.exit(1)
"""


def _install_fake(tmp_path: pathlib.Path, monkeypatch, source: str) -> pathlib.Path:
    bindir = tmp_path / 'bin'
    bindir.mkdir(exist_ok=True)
    script = bindir / 'autocast'
    script.write_text(source)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv('PATH', f'{bindir}{os.pathsep}{os.environ["PATH"]}')
    return script


@pytest.fixture
def fake_autocast(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    return _install_fake(tmp_path, monkeypatch, _FAKE_AUTOCAST)


@pytest.fixture
def fixtures_root(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / 'fixtures'
    (root / 'ab-problem').mkdir(parents=True)
    (root / 'ab-problem' / 'problem.rbx.yml').write_text('name: ab-problem\n')
    return root


def _spec(**kwargs) -> RecordingSpec:
    base = dict(name='run-basic', fixture='ab-problem', instructions=['rbx run'])
    base.update(kwargs)
    return RecordingSpec(**base)


def test_record_writes_a_cast(
    fake_autocast, fixtures_root: pathlib.Path, tmp_path: pathlib.Path
):
    out = tmp_path / 'out' / 'run-basic.cast'

    record(_spec(), fixtures_root=fixtures_root, out_path=out)

    assert out.exists()
    header = json.loads(out.read_text().splitlines()[0])
    assert header['version'] == 2


def test_record_scrubs_the_tmpdir_out_of_the_cast(
    fake_autocast, fixtures_root: pathlib.Path, tmp_path: pathlib.Path
):
    out = tmp_path / 'out' / 'run-basic.cast'

    record(_spec(), fixtures_root=fixtures_root, out_path=out)

    text = out.read_text()
    assert '~/problems/ab-problem' in text
    assert '/var/folders' not in text


def test_record_never_mutates_the_source_fixture(
    fake_autocast, fixtures_root: pathlib.Path, tmp_path: pathlib.Path
):
    before = sorted(p.name for p in (fixtures_root / 'ab-problem').iterdir())

    record(_spec(), fixtures_root=fixtures_root, out_path=tmp_path / 'o.cast')

    assert sorted(p.name for p in (fixtures_root / 'ab-problem').iterdir()) == before


def test_record_fails_when_an_expectation_is_missing(
    fake_autocast, fixtures_root: pathlib.Path, tmp_path: pathlib.Path
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
    fake_autocast, fixtures_root: pathlib.Path, tmp_path: pathlib.Path
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


def test_record_surfaces_autocast_failure_output(
    fixtures_root: pathlib.Path, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    _install_fake(tmp_path, monkeypatch, _FAILING_AUTOCAST)

    with pytest.raises(AutocastFailedError, match='prompt detection timed out'):
        record(_spec(), fixtures_root=fixtures_root, out_path=tmp_path / 'o.cast')


def test_record_reports_a_missing_fixture(
    fake_autocast, fixtures_root: pathlib.Path, tmp_path: pathlib.Path
):
    with pytest.raises(FileNotFoundError, match='nope'):
        record(
            _spec(fixture='nope'),
            fixtures_root=fixtures_root,
            out_path=tmp_path / 'o.cast',
        )


def test_record_reports_a_missing_autocast_binary(
    fixtures_root: pathlib.Path, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    empty = tmp_path / 'empty'
    empty.mkdir()
    monkeypatch.setenv('PATH', str(empty))

    with pytest.raises(AutocastMissingError, match='cargo binstall autocast'):
        record(_spec(), fixtures_root=fixtures_root, out_path=tmp_path / 'o.cast')
