import pathlib
import sys

from rbx.grading import steps_with_caching
from rbx.grading.caching import DependencyCache
from rbx.grading.judge.cacher import FileCacher
from rbx.grading.judge.sandbox import SandboxBase, SandboxParams
from rbx.grading.steps import (
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
