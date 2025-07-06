import os
import pathlib
import sys

import pytest

from rbx.grading import grading_context, steps_with_caching
from rbx.grading.caching import DependencyCache
from rbx.grading.judge.cacher import FileCacher
from rbx.grading.judge.digester import digest_cooperatively
from rbx.grading.judge.sandbox import SandboxBase, SandboxParams
from rbx.grading.steps import (
    DigestOrSource,
    GradingArtifacts,
    GradingFileInput,
    GradingFileOutput,
    RunLogMetadata,
)


async def test_run_from_digest(
    cleandir: pathlib.Path,
    dependency_cache: DependencyCache,
    sandbox: SandboxBase,
    file_cacher: FileCacher,
):
    executable = DigestOrSource.create(file_cacher.put_file_text('print(5)'))
    artifacts = GradingArtifacts()
    artifacts.inputs.append(
        GradingFileInput(**executable.expand(), dest=pathlib.Path('executable.py'))
    )
    artifacts.outputs.append(
        GradingFileOutput(src=pathlib.Path('box-out.txt'), dest=pathlib.Path('out.txt'))
    )
    await steps_with_caching.run(
        f'{sys.executable} executable.py',
        params=SandboxParams(stdout_file=pathlib.Path('box-out.txt')),
        sandbox=sandbox,
        artifacts=artifacts,
        dependency_cache=dependency_cache,
        metadata=RunLogMetadata(),
    )

    assert (cleandir / 'out.txt').read_text().strip() == '5'
    assert artifacts.logs is not None
    assert artifacts.logs.run is not None
    assert artifacts.logs.run.metadata is not None
    assert not artifacts.logs.cached


async def test_run_from_disk(
    cleandir: pathlib.Path,
    dependency_cache: DependencyCache,
    sandbox: SandboxBase,
):
    pathlib.Path('executable.py').write_text('print(42)')

    executable = DigestOrSource.create(pathlib.Path('executable.py'))
    artifacts = GradingArtifacts()
    artifacts.inputs.append(
        GradingFileInput(**executable.expand(), dest=pathlib.Path('executable.py'))
    )
    artifacts.outputs.append(
        GradingFileOutput(src=pathlib.Path('box-out.txt'), dest=pathlib.Path('out.txt'))
    )
    await steps_with_caching.run(
        f'{sys.executable} executable.py',
        params=SandboxParams(stdout_file=pathlib.Path('box-out.txt')),
        sandbox=sandbox,
        artifacts=artifacts,
        dependency_cache=dependency_cache,
    )

    assert (cleandir / 'out.txt').read_text().strip() == '42'
    assert artifacts.logs is not None
    assert artifacts.logs.run is not None
    assert not artifacts.logs.cached


async def test_run_reruns_if_cache_disabled(
    cleandir: pathlib.Path,
    dependency_cache: DependencyCache,
    sandbox: SandboxBase,
    file_cacher: FileCacher,
):
    async def configure_and_run_with_dest(dest: pathlib.Path) -> GradingArtifacts:
        executable = DigestOrSource.create(file_cacher.put_file_text('print(5)'))
        artifacts = GradingArtifacts()
        artifacts.inputs.append(
            GradingFileInput(**executable.expand(), dest=pathlib.Path('executable.py'))
        )
        artifacts.outputs.append(
            GradingFileOutput(src=pathlib.Path('box-out.txt'), dest=dest)
        )
        with grading_context.cache_level(grading_context.CacheLevel.NO_CACHE):
            await steps_with_caching.run(
                f'{sys.executable} executable.py',
                params=SandboxParams(stdout_file=pathlib.Path('box-out.txt')),
                sandbox=sandbox,
                artifacts=artifacts,
                dependency_cache=dependency_cache,
            )
        return artifacts

    artifacts = await configure_and_run_with_dest(pathlib.Path('out.txt'))
    assert (cleandir / 'out.txt').read_text().strip() == '5'
    assert artifacts.logs is not None
    assert not artifacts.logs.cached

    another_artifacts = await configure_and_run_with_dest(pathlib.Path('out.txt'))
    assert (cleandir / 'out.txt').read_text().strip() == '5'
    assert another_artifacts.logs is not None
    assert not another_artifacts.logs.cached


async def test_run_reruns_if_first_run_cache_disabled(
    cleandir: pathlib.Path,
    dependency_cache: DependencyCache,
    sandbox: SandboxBase,
    file_cacher: FileCacher,
):
    async def configure_and_run_with_dest(
        dest: pathlib.Path, cache: bool = True
    ) -> GradingArtifacts:
        executable = DigestOrSource.create(file_cacher.put_file_text('print(5)'))
        artifacts = GradingArtifacts()
        artifacts.inputs.append(
            GradingFileInput(**executable.expand(), dest=pathlib.Path('executable.py'))
        )
        artifacts.outputs.append(
            GradingFileOutput(src=pathlib.Path('box-out.txt'), dest=dest)
        )
        with grading_context.cache_level(
            grading_context.CacheLevel.NO_CACHE, when=cache
        ):
            await steps_with_caching.run(
                f'{sys.executable} executable.py',
                params=SandboxParams(stdout_file=pathlib.Path('box-out.txt')),
                sandbox=sandbox,
                artifacts=artifacts,
                dependency_cache=dependency_cache,
            )
        return artifacts

    artifacts = await configure_and_run_with_dest(pathlib.Path('out.txt'), cache=False)
    assert (cleandir / 'out.txt').read_text().strip() == '5'
    assert artifacts.logs is not None
    assert not artifacts.logs.cached

    another_artifacts = await configure_and_run_with_dest(pathlib.Path('out.txt'))
    assert (cleandir / 'out.txt').read_text().strip() == '5'
    assert another_artifacts.logs is not None
    assert not another_artifacts.logs.cached


async def test_run_reruns_if_second_run_cache_disabled(
    cleandir: pathlib.Path,
    dependency_cache: DependencyCache,
    sandbox: SandboxBase,
    file_cacher: FileCacher,
):
    async def configure_and_run_with_dest(
        dest: pathlib.Path, cache: bool = True
    ) -> GradingArtifacts:
        executable = DigestOrSource.create(file_cacher.put_file_text('print(5)'))
        artifacts = GradingArtifacts()
        artifacts.inputs.append(
            GradingFileInput(**executable.expand(), dest=pathlib.Path('executable.py'))
        )
        artifacts.outputs.append(
            GradingFileOutput(src=pathlib.Path('box-out.txt'), dest=dest)
        )
        with grading_context.cache_level(
            grading_context.CacheLevel.NO_CACHE, when=cache
        ):
            await steps_with_caching.run(
                f'{sys.executable} executable.py',
                params=SandboxParams(stdout_file=pathlib.Path('box-out.txt')),
                sandbox=sandbox,
                artifacts=artifacts,
                dependency_cache=dependency_cache,
            )
        return artifacts

    artifacts = await configure_and_run_with_dest(pathlib.Path('out.txt'))
    assert (cleandir / 'out.txt').read_text().strip() == '5'
    assert artifacts.logs is not None
    assert not artifacts.logs.cached

    another_artifacts = await configure_and_run_with_dest(
        pathlib.Path('out.txt'), cache=False
    )
    assert (cleandir / 'out.txt').read_text().strip() == '5'
    assert another_artifacts.logs is not None
    assert not another_artifacts.logs.cached


async def test_run_caches_intermediate_digest_if_dest_changes(
    cleandir: pathlib.Path,
    dependency_cache: DependencyCache,
    sandbox: SandboxBase,
    file_cacher: FileCacher,
):
    async def configure_and_run_with_dest(dest: pathlib.Path) -> GradingArtifacts:
        executable = DigestOrSource.create(file_cacher.put_file_text('print(5)'))
        artifacts = GradingArtifacts()
        artifacts.inputs.append(
            GradingFileInput(**executable.expand(), dest=pathlib.Path('executable.py'))
        )
        artifacts.outputs.append(
            GradingFileOutput(src=pathlib.Path('box-out.txt'), dest=dest)
        )
        await steps_with_caching.run(
            f'{sys.executable} executable.py',
            params=SandboxParams(stdout_file=pathlib.Path('box-out.txt')),
            sandbox=sandbox,
            artifacts=artifacts,
            dependency_cache=dependency_cache,
        )
        return artifacts

    artifacts = await configure_and_run_with_dest(pathlib.Path('out.txt'))
    assert (cleandir / 'out.txt').read_text().strip() == '5'
    assert artifacts.logs is not None
    assert not artifacts.logs.cached

    another_artifacts = await configure_and_run_with_dest(
        pathlib.Path('another-out.txt')
    )
    assert (cleandir / 'another-out.txt').read_text().strip() == '5'
    assert another_artifacts.logs is not None
    assert another_artifacts.logs.cached


async def test_run_caches_intermediate_digest_if_dest_changes_and_cache_transient(
    cleandir: pathlib.Path,
    dependency_cache: DependencyCache,
    sandbox: SandboxBase,
    file_cacher: FileCacher,
):
    async def configure_and_run_with_dest(dest: pathlib.Path) -> GradingArtifacts:
        executable = DigestOrSource.create(file_cacher.put_file_text('print(5)'))
        artifacts = GradingArtifacts()
        artifacts.inputs.append(
            GradingFileInput(**executable.expand(), dest=pathlib.Path('executable.py'))
        )
        artifacts.outputs.append(
            GradingFileOutput(src=pathlib.Path('box-out.txt'), dest=dest)
        )

        with grading_context.cache_level(grading_context.CacheLevel.CACHE_TRANSIENTLY):
            await steps_with_caching.run(
                f'{sys.executable} executable.py',
                params=SandboxParams(stdout_file=pathlib.Path('box-out.txt')),
                sandbox=sandbox,
                artifacts=artifacts,
                dependency_cache=dependency_cache,
            )
        return artifacts

    artifacts = await configure_and_run_with_dest(pathlib.Path('out.txt'))
    assert (cleandir / 'out.txt').read_text().strip() == '5'
    assert artifacts.logs is not None
    assert not artifacts.logs.cached

    another_artifacts = await configure_and_run_with_dest(
        pathlib.Path('another-out.txt')
    )
    assert (cleandir / 'another-out.txt').read_text().strip() == '5'
    assert another_artifacts.logs is not None
    assert another_artifacts.logs.cached


async def test_run_overwrites_changed_file_when_storage_value_is_changed_and_cache_transient(
    cleandir: pathlib.Path,
    dependency_cache: DependencyCache,
    sandbox: SandboxBase,
    file_cacher: FileCacher,
):
    async def configure_and_run_with_dest(dest: pathlib.Path) -> GradingArtifacts:
        executable = DigestOrSource.create(file_cacher.put_file_text('print(5)'))
        artifacts = GradingArtifacts()
        artifacts.inputs.append(
            GradingFileInput(**executable.expand(), dest=pathlib.Path('executable.py'))
        )
        artifacts.outputs.append(
            GradingFileOutput(src=pathlib.Path('box-out.txt'), dest=dest)
        )
        with grading_context.cache_level(grading_context.CacheLevel.CACHE_TRANSIENTLY):
            await steps_with_caching.run(
                f'{sys.executable} executable.py',
                params=SandboxParams(stdout_file=pathlib.Path('box-out.txt')),
                sandbox=sandbox,
                artifacts=artifacts,
                dependency_cache=dependency_cache,
            )
        return artifacts

    artifacts = await configure_and_run_with_dest(pathlib.Path('out.txt'))
    assert (cleandir / 'out.txt').read_text().strip() == '5'
    assert artifacts.logs is not None
    assert not artifacts.logs.cached

    pathlib.Path('out.txt').write_text('42')

    another_artifacts = await configure_and_run_with_dest(pathlib.Path('out.txt'))
    assert (cleandir / 'out.txt').read_text().strip() == '5'
    assert another_artifacts.logs is not None
    assert another_artifacts.logs.cached


async def test_run_overwrites_changed_file_when_file_deleted_and_cache_transient(
    cleandir: pathlib.Path,
    dependency_cache: DependencyCache,
    sandbox: SandboxBase,
    file_cacher: FileCacher,
):
    async def configure_and_run_with_dest(dest: pathlib.Path) -> GradingArtifacts:
        executable = DigestOrSource.create(file_cacher.put_file_text('print(5)'))
        artifacts = GradingArtifacts()
        artifacts.inputs.append(
            GradingFileInput(**executable.expand(), dest=pathlib.Path('executable.py'))
        )
        artifacts.outputs.append(
            GradingFileOutput(src=pathlib.Path('box-out.txt'), dest=dest)
        )
        with grading_context.cache_level(grading_context.CacheLevel.CACHE_TRANSIENTLY):
            await steps_with_caching.run(
                f'{sys.executable} executable.py',
                params=SandboxParams(stdout_file=pathlib.Path('box-out.txt')),
                sandbox=sandbox,
                artifacts=artifacts,
                dependency_cache=dependency_cache,
            )
        return artifacts

    artifacts = await configure_and_run_with_dest(pathlib.Path('out.txt'))
    assert (cleandir / 'out.txt').read_text().strip() == '5'
    assert artifacts.logs is not None
    assert not artifacts.logs.cached

    pathlib.Path('out.txt').unlink()

    another_artifacts = await configure_and_run_with_dest(pathlib.Path('out.txt'))
    assert (cleandir / 'out.txt').read_text().strip() == '5'
    assert another_artifacts.logs is not None
    assert another_artifacts.logs.cached


async def test_run_fails_when_storage_value_is_changed_and_integrity_check_is_enabled(
    cleandir: pathlib.Path,
    dependency_cache: DependencyCache,
    sandbox: SandboxBase,
    file_cacher: FileCacher,
):
    async def configure_and_run_with_dest(dest: pathlib.Path) -> GradingArtifacts:
        executable = DigestOrSource.create(file_cacher.put_file_text('print(5)'))
        artifacts = GradingArtifacts()
        artifacts.inputs.append(
            GradingFileInput(**executable.expand(), dest=pathlib.Path('executable.py'))
        )
        artifacts.outputs.append(
            GradingFileOutput(src=pathlib.Path('box-out.txt'), dest=dest)
        )
        await steps_with_caching.run(
            f'{sys.executable} executable.py',
            params=SandboxParams(stdout_file=pathlib.Path('box-out.txt')),
            sandbox=sandbox,
            artifacts=artifacts,
            dependency_cache=dependency_cache,
        )
        return artifacts

    artifacts = await configure_and_run_with_dest(pathlib.Path('out.txt'))
    assert (cleandir / 'out.txt').read_text().strip() == '5'
    assert artifacts.logs is not None
    assert not artifacts.logs.cached

    pathlib.Path('out.txt').write_text('42')

    with pytest.raises(ValueError) as exc_info:
        await configure_and_run_with_dest(pathlib.Path('out.txt'))
    assert 'rbx clean' in str(exc_info.value)
    assert (cleandir / 'out.txt').read_text().strip() == '42'


async def test_run_evicts_and_recreates_deleted_file_with_storage_value(
    cleandir: pathlib.Path,
    dependency_cache: DependencyCache,
    sandbox: SandboxBase,
    file_cacher: FileCacher,
):
    async def configure_and_run_with_dest(dest: pathlib.Path) -> GradingArtifacts:
        executable = DigestOrSource.create(file_cacher.put_file_text('print(5)'))
        artifacts = GradingArtifacts()
        artifacts.inputs.append(
            GradingFileInput(**executable.expand(), dest=pathlib.Path('executable.py'))
        )
        artifacts.outputs.append(
            GradingFileOutput(src=pathlib.Path('box-out.txt'), dest=dest)
        )
        await steps_with_caching.run(
            f'{sys.executable} executable.py',
            params=SandboxParams(stdout_file=pathlib.Path('box-out.txt')),
            sandbox=sandbox,
            artifacts=artifacts,
            dependency_cache=dependency_cache,
        )
        return artifacts

    artifacts = await configure_and_run_with_dest(pathlib.Path('out.txt'))
    assert (cleandir / 'out.txt').read_text().strip() == '5'
    assert artifacts.logs is not None
    assert not artifacts.logs.cached

    pathlib.Path('out.txt').unlink()

    another_artifacts = await configure_and_run_with_dest(pathlib.Path('out.txt'))
    assert (cleandir / 'out.txt').read_text().strip() == '5'
    assert another_artifacts.logs is not None
    assert another_artifacts.logs.cached


async def test_run_evicts_when_storage_value_deleted(
    cleandir: pathlib.Path,
    dependency_cache: DependencyCache,
    sandbox: SandboxBase,
    file_cacher: FileCacher,
):
    async def configure_and_run_with_dest(dest: pathlib.Path) -> GradingArtifacts:
        executable = DigestOrSource.create(file_cacher.put_file_text('print(5)'))
        artifacts = GradingArtifacts()
        artifacts.inputs.append(
            GradingFileInput(**executable.expand(), dest=pathlib.Path('executable.py'))
        )
        artifacts.outputs.append(
            GradingFileOutput(src=pathlib.Path('box-out.txt'), dest=dest)
        )
        await steps_with_caching.run(
            f'{sys.executable} executable.py',
            params=SandboxParams(stdout_file=pathlib.Path('box-out.txt')),
            sandbox=sandbox,
            artifacts=artifacts,
            dependency_cache=dependency_cache,
        )
        return artifacts

    artifacts = await configure_and_run_with_dest(pathlib.Path('out.txt'))
    assert (cleandir / 'out.txt').read_text().strip() == '5'
    assert artifacts.logs is not None
    assert not artifacts.logs.cached

    # Delete the file from the cache
    with pathlib.Path('out.txt').open('rb') as f:
        digest = digest_cooperatively(f)
    file_cacher.delete(digest)

    another_artifacts = await configure_and_run_with_dest(pathlib.Path('out.txt'))
    assert (cleandir / 'out.txt').read_text().strip() == '5'
    assert another_artifacts.logs is not None
    assert not another_artifacts.logs.cached


async def test_run_overwrite_exec_bit_when_changed(
    cleandir: pathlib.Path,
    dependency_cache: DependencyCache,
    sandbox: SandboxBase,
    file_cacher: FileCacher,
):
    async def configure_and_run_with_dest(dest: pathlib.Path) -> GradingArtifacts:
        executable = DigestOrSource.create(file_cacher.put_file_text('print(5)'))
        artifacts = GradingArtifacts()
        artifacts.inputs.append(
            GradingFileInput(
                **executable.expand(),
                dest=pathlib.Path('executable.py'),
            )
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('box-out.txt'), dest=dest, executable=True
            )
        )
        await steps_with_caching.run(
            f'{sys.executable} executable.py',
            params=SandboxParams(stdout_file=pathlib.Path('box-out.txt')),
            sandbox=sandbox,
            artifacts=artifacts,
            dependency_cache=dependency_cache,
        )
        return artifacts

    artifacts = await configure_and_run_with_dest(pathlib.Path('out.txt'))
    assert (cleandir / 'out.txt').read_text().strip() == '5'
    assert artifacts.logs is not None
    assert not artifacts.logs.cached
    assert os.access('out.txt', os.X_OK)

    pathlib.Path('out.txt').chmod(0o644)

    another_artifacts = await configure_and_run_with_dest(pathlib.Path('out.txt'))
    assert (cleandir / 'out.txt').read_text().strip() == '5'
    assert another_artifacts.logs is not None
    assert another_artifacts.logs.cached
    assert os.access('out.txt', os.X_OK)


async def test_run_evicts_when_changed_file_and_no_hash(
    cleandir: pathlib.Path,
    dependency_cache: DependencyCache,
    sandbox: SandboxBase,
    file_cacher: FileCacher,
):
    async def configure_and_run_with_dest(dest: pathlib.Path) -> GradingArtifacts:
        executable = DigestOrSource.create(file_cacher.put_file_text('print(5)'))
        artifacts = GradingArtifacts()
        artifacts.inputs.append(
            GradingFileInput(**executable.expand(), dest=pathlib.Path('executable.py'))
        )
        artifacts.outputs.append(
            GradingFileOutput(src=pathlib.Path('box-out.txt'), dest=dest, hash=False)
        )
        await steps_with_caching.run(
            f'{sys.executable} executable.py',
            params=SandboxParams(stdout_file=pathlib.Path('box-out.txt')),
            sandbox=sandbox,
            artifacts=artifacts,
            dependency_cache=dependency_cache,
        )
        return artifacts

    artifacts = await configure_and_run_with_dest(pathlib.Path('out.txt'))
    assert (cleandir / 'out.txt').read_text().strip() == '5'
    assert artifacts.logs is not None
    assert not artifacts.logs.cached

    pathlib.Path('out.txt').write_text('42')

    another_artifacts = await configure_and_run_with_dest(pathlib.Path('out.txt'))
    assert (cleandir / 'out.txt').read_text().strip() == '5'
    assert another_artifacts.logs is not None
    assert not another_artifacts.logs.cached


async def test_run_evicts_when_exec_bit_different_and_no_hash(
    cleandir: pathlib.Path,
    dependency_cache: DependencyCache,
    sandbox: SandboxBase,
    file_cacher: FileCacher,
):
    async def configure_and_run_with_dest(dest: pathlib.Path) -> GradingArtifacts:
        executable = DigestOrSource.create(file_cacher.put_file_text('print(5)'))
        artifacts = GradingArtifacts()
        artifacts.inputs.append(
            GradingFileInput(**executable.expand(), dest=pathlib.Path('executable.py'))
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('box-out.txt'), dest=dest, hash=False, executable=True
            )
        )
        await steps_with_caching.run(
            f'{sys.executable} executable.py',
            params=SandboxParams(stdout_file=pathlib.Path('box-out.txt')),
            sandbox=sandbox,
            artifacts=artifacts,
            dependency_cache=dependency_cache,
        )
        return artifacts

    artifacts = await configure_and_run_with_dest(pathlib.Path('out.txt'))
    assert (cleandir / 'out.txt').read_text().strip() == '5'
    assert artifacts.logs is not None
    assert not artifacts.logs.cached

    pathlib.Path('out.txt').chmod(0o0644)

    another_artifacts = await configure_and_run_with_dest(pathlib.Path('out.txt'))
    assert (cleandir / 'out.txt').read_text().strip() == '5'
    assert another_artifacts.logs is not None
    assert not another_artifacts.logs.cached


async def test_run_evicts_when_input_fingerprint_changes(
    cleandir: pathlib.Path,
    dependency_cache: DependencyCache,
    sandbox: SandboxBase,
):
    async def configure_and_run() -> GradingArtifacts:
        executable = DigestOrSource.create(pathlib.Path('executable.py'))
        artifacts = GradingArtifacts()
        artifacts.inputs.append(
            GradingFileInput(**executable.expand(), dest=pathlib.Path('executable.py'))
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('box-out.txt'),
                dest=pathlib.Path('out.txt'),
            )
        )
        await steps_with_caching.run(
            f'{sys.executable} executable.py',
            params=SandboxParams(stdout_file=pathlib.Path('box-out.txt')),
            sandbox=sandbox,
            artifacts=artifacts,
            dependency_cache=dependency_cache,
        )
        return artifacts

    pathlib.Path('executable.py').write_text('print(5)')

    artifacts = await configure_and_run()
    assert (cleandir / 'out.txt').read_text().strip() == '5'
    assert artifacts.logs is not None
    assert not artifacts.logs.cached

    pathlib.Path('executable.py').write_text('print(42)')

    another_artifacts = await configure_and_run()
    assert (cleandir / 'out.txt').read_text().strip() == '42'
    assert another_artifacts.logs is not None
    assert not another_artifacts.logs.cached


async def test_run_evicts_when_output_is_deleted_and_no_hash(
    cleandir: pathlib.Path,
    dependency_cache: DependencyCache,
    sandbox: SandboxBase,
):
    async def configure_and_run() -> GradingArtifacts:
        executable = DigestOrSource.create(pathlib.Path('executable.py'))
        artifacts = GradingArtifacts()
        artifacts.inputs.append(
            GradingFileInput(**executable.expand(), dest=pathlib.Path('executable.py'))
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('box-out.txt'),
                dest=pathlib.Path('out.txt'),
                hash=False,
            )
        )
        await steps_with_caching.run(
            f'{sys.executable} executable.py',
            params=SandboxParams(stdout_file=pathlib.Path('box-out.txt')),
            sandbox=sandbox,
            artifacts=artifacts,
            dependency_cache=dependency_cache,
        )
        return artifacts

    pathlib.Path('executable.py').write_text('print(5)')

    artifacts = await configure_and_run()
    assert (cleandir / 'out.txt').read_text().strip() == '5'
    assert artifacts.logs is not None
    assert not artifacts.logs.cached

    pathlib.Path('out.txt').unlink()

    another_artifacts = await configure_and_run()
    assert (cleandir / 'out.txt').read_text().strip() == '5'
    assert another_artifacts.logs is not None
    assert not another_artifacts.logs.cached


async def test_run_misses_when_input_file_changes(
    cleandir: pathlib.Path,
    dependency_cache: DependencyCache,
    sandbox: SandboxBase,
    file_cacher: FileCacher,
):
    async def configure_and_run(number: int) -> GradingArtifacts:
        executable = DigestOrSource.create(
            file_cacher.put_file_text(f'print({number})')
        )
        artifacts = GradingArtifacts()
        artifacts.inputs.append(
            GradingFileInput(**executable.expand(), dest=pathlib.Path('executable.py'))
        )
        artifacts.outputs.append(
            GradingFileOutput(
                src=pathlib.Path('box-out.txt'),
                dest=pathlib.Path('out.txt'),
                hash=False,
            )
        )
        await steps_with_caching.run(
            f'{sys.executable} executable.py',
            params=SandboxParams(stdout_file=pathlib.Path('box-out.txt')),
            sandbox=sandbox,
            artifacts=artifacts,
            dependency_cache=dependency_cache,
        )
        return artifacts

    artifacts = await configure_and_run(5)
    assert (cleandir / 'out.txt').read_text().strip() == '5'
    assert artifacts.logs is not None
    assert not artifacts.logs.cached

    pathlib.Path('out.txt').write_text('42')

    another_artifacts = await configure_and_run(42)
    assert (cleandir / 'out.txt').read_text().strip() == '42'
    assert another_artifacts.logs is not None
    assert not another_artifacts.logs.cached
