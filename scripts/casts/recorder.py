"""Records a docs cast: fixture -> tmpdir -> autocast -> scrub -> verify."""

import pathlib
import shutil
import subprocess
import tempfile

from scripts.casts.autocast_input import build_autocast_input
from scripts.casts.postprocess import scrub_cast, verify_cast
from scripts.casts.spec import RecordingSpec, dump_autocast_yaml

DISPLAY_ROOT = '~/problems'

_INSTALL_HINT = (
    'autocast is required to record docs casts but was not found on PATH.\n'
    'Install it with one of:\n'
    '  cargo binstall autocast\n'
    '  cargo install autocast\n'
    '  https://github.com/k9withabone/autocast/releases'
)


class AutocastMissingError(RuntimeError):
    pass


class AutocastFailedError(RuntimeError):
    pass


def record(
    spec: RecordingSpec, fixtures_root: pathlib.Path, out_path: pathlib.Path
) -> pathlib.Path:
    if shutil.which('autocast') is None:
        raise AutocastMissingError(_INSTALL_HINT)

    fixture = fixtures_root / spec.fixture
    if not fixture.is_dir():
        raise FileNotFoundError(
            f'recording `{spec.name}` references fixture `{spec.fixture}`, '
            f'but {fixture} does not exist'
        )

    with tempfile.TemporaryDirectory(prefix='rbx-cast-') as tmp:
        tmpdir = pathlib.Path(tmp).resolve()
        # The fixture is copied so recording side effects (build/, .rbx/) never
        # touch the source tree, and HOME is redirected so the real rbx cache is
        # neither used nor leaked into the cast.
        workdir = tmpdir / spec.fixture
        home = tmpdir / 'home'
        shutil.copytree(fixture, workdir)
        home.mkdir()

        data = build_autocast_input(spec, workdir=str(workdir), home=str(home))
        input_path = tmpdir / 'autocast.yml'
        cast_path = tmpdir / 'out.cast'
        input_path.write_text(dump_autocast_yaml(data))

        process = subprocess.run(
            ['autocast', str(input_path), str(cast_path), '--overwrite'],
            capture_output=True,
            text=True,
        )
        if process.returncode != 0:
            raise AutocastFailedError(
                f'autocast failed while recording `{spec.name}` '
                f'(exit {process.returncode}):\n{process.stderr}'
            )

        raw = cast_path.read_text()
        scrubbed = scrub_cast(
            raw,
            tmpdir=str(tmpdir),
            display_root=DISPLAY_ROOT,
            home=str(home),
            title=spec.title,
        )
        # Verify before writing, so a broken recording never overwrites a good
        # committed cast.
        verify_cast(scrubbed, spec.expect_contains, name=spec.name)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(scrubbed)
    return out_path
