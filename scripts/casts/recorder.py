"""Records a docs cast: fixture -> tmpdir -> engine -> scrub -> verify."""

import pathlib
import shutil
import tempfile

from scripts.casts.engine import run_recording
from scripts.casts.postprocess import scrub_cast, verify_cast
from scripts.casts.spec import RecordingSpec

DISPLAY_ROOT = '~/problems'


def record(
    spec: RecordingSpec, fixtures_root: pathlib.Path, out_path: pathlib.Path
) -> pathlib.Path:
    fixture = fixtures_root / spec.fixture
    if not fixture.is_dir():
        raise FileNotFoundError(
            f'recording `{spec.name}` references fixture `{spec.fixture}`, '
            f'but {fixture} does not exist'
        )

    # The real HOME is used, not a synthetic one. rbx keeps its compiler and
    # environment configuration under HOME, so a pristine HOME silently breaks
    # compilation -- and a cast of a failed build teaches nothing. The tradeoff
    # is that HOME appears in the output, which `scrub_cast` rewrites to `~`.
    home = pathlib.Path.home()

    with tempfile.TemporaryDirectory(prefix='rbx-cast-') as tmp:
        tmpdir = pathlib.Path(tmp).resolve()
        # The fixture is still copied, so recording side effects (build/,
        # .rbx/) never touch the source tree.
        workdir = tmpdir / spec.fixture
        shutil.copytree(fixture, workdir)

        raw = run_recording(spec, workdir=str(workdir), home=str(home))
        scrubbed = scrub_cast(
            raw,
            tmpdir=str(tmpdir),
            display_root=DISPLAY_ROOT,
            home=str(home),
            title=spec.title,
            # Commands under recording make their own temp directories, which
            # are siblings of `tmpdir`, not children. Passing the root lets the
            # scrubber catch those too -- in both spellings, since macOS
            # resolves /var/folders/... to /private/var/folders/... and a cast
            # can contain either.
            temp_roots=[
                tempfile.gettempdir(),
                str(pathlib.Path(tempfile.gettempdir()).resolve()),
            ],
        )
        # Verify before writing, so a broken recording never overwrites a good
        # committed cast.
        verify_cast(scrubbed, spec.expect_contains, name=spec.name)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(scrubbed)
    return out_path
