import pathlib
import sys

from rbx.grading import caching, steps_with_caching
from rbx.grading.caching import DependencyCache
from rbx.grading.judge.cacher import FileCacher
from rbx.grading.judge.sandbox import SandboxBase, SandboxParams
from rbx.grading.steps import (
    DigestHolder,
    GradingArtifacts,
    GradingFileInput,
    GradingFileOutput,
    RunLogMetadata,
)


async def _run_from(
    src: pathlib.Path,
    out: pathlib.Path,
    sandbox: SandboxBase,
    dependency_cache: DependencyCache,
) -> GradingArtifacts:
    artifacts = GradingArtifacts()
    artifacts.inputs.append(
        GradingFileInput(src=src, dest=pathlib.Path('executable.py'))
    )
    artifacts.outputs.append(
        GradingFileOutput(src=pathlib.Path('box-out.txt'), dest=out)
    )
    await steps_with_caching.run(
        f'{sys.executable} executable.py',
        params=SandboxParams(stdout_file=pathlib.Path('box-out.txt')),
        sandbox=sandbox,
        artifacts=artifacts,
        dependency_cache=dependency_cache,
        metadata=RunLogMetadata(),
    )
    return artifacts


async def test_cache_hits_for_identical_content_at_a_different_path(
    cleandir: pathlib.Path,
    dependency_cache: DependencyCache,
    sandbox: SandboxBase,
    file_cacher: FileCacher,
):
    # Same bytes, two different absolute paths -- as happens when every test
    # copies its package into a fresh temporary directory.
    first = cleandir / 'a' / 'executable.py'
    second = cleandir / 'b' / 'executable.py'
    for path in (first, second):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('print(7)')

    await _run_from(first, pathlib.Path('out-a.txt'), sandbox, dependency_cache)
    artifacts = await _run_from(
        second, pathlib.Path('out-b.txt'), sandbox, dependency_cache
    )

    assert (cleandir / 'out-b.txt').read_text().strip() == '7'
    assert artifacts.logs is not None
    assert artifacts.logs.cached


async def test_cache_misses_when_content_differs(
    cleandir: pathlib.Path,
    dependency_cache: DependencyCache,
    sandbox: SandboxBase,
    file_cacher: FileCacher,
):
    first = cleandir / 'a' / 'executable.py'
    second = cleandir / 'b' / 'executable.py'
    first.parent.mkdir(parents=True, exist_ok=True)
    second.parent.mkdir(parents=True, exist_ok=True)
    first.write_text('print(7)')
    second.write_text('print(8)')

    await _run_from(first, pathlib.Path('out-a.txt'), sandbox, dependency_cache)
    artifacts = await _run_from(
        second, pathlib.Path('out-b.txt'), sandbox, dependency_cache
    )

    assert (cleandir / 'out-b.txt').read_text().strip() == '8'
    assert artifacts.logs is not None
    assert not artifacts.logs.cached


async def _run_with_hashed_outputs(
    src: pathlib.Path,
    sandbox: SandboxBase,
    dependency_cache: DependencyCache,
) -> GradingArtifacts:
    # Mirrors how a solution run is declared: both stdout and stderr are
    # captured as hashed outputs.
    artifacts = GradingArtifacts()
    artifacts.inputs.append(
        GradingFileInput(src=src, dest=pathlib.Path('executable.py'))
    )
    artifacts.outputs.append(
        GradingFileOutput(src=pathlib.Path('box-out.txt'), digest=DigestHolder())
    )
    artifacts.outputs.append(
        GradingFileOutput(src=pathlib.Path('box-err.txt'), digest=DigestHolder())
    )
    await steps_with_caching.run(
        f'{sys.executable} executable.py',
        params=SandboxParams(
            stdout_file=pathlib.Path('box-out.txt'),
            stderr_file=pathlib.Path('box-err.txt'),
        ),
        sandbox=sandbox,
        artifacts=artifacts,
        dependency_cache=dependency_cache,
        metadata=RunLogMetadata(),
    )
    return artifacts


async def test_is_artifact_ok_checks_every_hashed_output(file_cacher: FileCacher):
    present = await file_cacher.put_file_text('present')
    missing = await file_cacher.put_file_text('missing')
    await file_cacher.delete(missing)

    artifacts = GradingArtifacts()
    artifacts.outputs.append(
        GradingFileOutput(
            src=pathlib.Path('box-out.txt'), digest=DigestHolder(value=present)
        )
    )
    artifacts.outputs.append(
        GradingFileOutput(
            src=pathlib.Path('box-err.txt'), digest=DigestHolder(value=missing)
        )
    )

    assert not await caching.is_artifact_ok(artifacts, file_cacher)


async def test_cache_misses_when_a_later_hashed_output_is_gone_from_storage(
    cleandir: pathlib.Path,
    dependency_cache: DependencyCache,
    sandbox: SandboxBase,
    file_cacher: FileCacher,
):
    src = cleandir / 'executable.py'
    src.write_text('import sys; print(7); print(8, file=sys.stderr)')

    first = await _run_with_hashed_outputs(src, sandbox, dependency_cache)
    stderr_digest = first.outputs[1].digest
    assert stderr_digest is not None and stderr_digest.value is not None

    # The .err blob vanishes from the content store -- a partial clean, an
    # interrupted write, a storage directory copied between machines.
    await file_cacher.delete(stderr_digest.value)

    second = await _run_with_hashed_outputs(src, sandbox, dependency_cache)

    assert second.logs is not None
    assert not second.logs.cached
    for output in second.outputs:
        assert output.digest is not None and output.digest.value is not None
        assert await file_cacher.exists(output.digest.value)
