import pathlib
from typing import Any, Dict, List, Optional, Tuple

from rbx.grading import grading_context, profiling, steps
from rbx.grading.caching import DependencyCache, NoCacheException
from rbx.grading.judge.sandbox import SandboxBase, SandboxParams
from rbx.grading.steps import (
    GradingArtifacts,
    GradingLogsHolder,
    RunLog,
    RunLogMetadata,
)


def _get_prefixed_cacheable_params(
    params: Dict[str, Any], prefix: str
) -> Dict[str, Any]:
    return {f'{prefix}.{k}': v for k, v in params.items()}


def compile(
    commands: List[str],
    params: SandboxParams,
    sandbox: SandboxBase,
    artifacts: GradingArtifacts,
    dependency_cache: DependencyCache,
):
    artifacts.logs = GradingLogsHolder()

    ok = True
    cached_profile = profiling.Profiler('steps.compile[cached]', start=True)
    with dependency_cache(
        commands, [artifacts], params.get_cacheable_params()
    ) as is_cached:
        if not is_cached:
            with profiling.Profiler('steps.compile'):
                profiling.add_to_counter('steps.compile')
                ok = steps.compile(
                    commands=commands,
                    params=params,
                    artifacts=artifacts,
                    sandbox=sandbox,
                )
                if not ok:
                    raise NoCacheException()
        else:
            cached_profile.stop()
            profiling.add_to_counter('steps.compile[cached]')

    return ok


async def run(
    command: str,
    params: SandboxParams,
    sandbox: SandboxBase,
    artifacts: GradingArtifacts,
    dependency_cache: DependencyCache,
    metadata: Optional[RunLogMetadata] = None,
) -> Optional[RunLog]:
    artifacts.logs = GradingLogsHolder()

    cacheable_params = params.get_cacheable_params()
    if metadata is not None and metadata.retryIndex is not None:
        cacheable_params['__retry_index__'] = metadata.retryIndex

    with grading_context.cache_level(
        grading_context.CacheLevel.NO_CACHE,
        when=grading_context.is_compilation_only,
    ):
        cached_profile = profiling.Profiler('steps.run[cached]', start=True)
        with dependency_cache([command], [artifacts], cacheable_params) as is_cached:
            if not is_cached:
                with profiling.Profiler('steps.run'):
                    profiling.add_to_counter('steps.run')
                    await steps.run(
                        command=command,
                        params=params,
                        artifacts=artifacts,
                        sandbox=sandbox,
                        metadata=metadata,
                    )
            else:
                cached_profile.stop()
                profiling.add_to_counter('steps.run[cached]')
    return artifacts.logs.run


async def run_coordinated(
    interactor: steps.CoordinatedRunParams,
    solution: steps.CoordinatedRunParams,
    artifacts: GradingArtifacts,
    sandbox: SandboxBase,
    dependency_cache: DependencyCache,
    merged_capture: Optional[pathlib.Path] = None,
) -> Tuple[Optional[RunLog], Optional[RunLog]]:
    artifacts.logs = GradingLogsHolder()

    cacheable_params = {
        **_get_prefixed_cacheable_params(
            interactor.params.get_cacheable_params(), 'interactor'
        ),
        **_get_prefixed_cacheable_params(
            solution.params.get_cacheable_params(), 'solution'
        ),
    }

    if interactor.metadata is not None and interactor.metadata.retryIndex is not None:
        cacheable_params['interactor.__retry_index__'] = interactor.metadata.retryIndex
    if solution.metadata is not None and solution.metadata.retryIndex is not None:
        cacheable_params['solution.__retry_index__'] = solution.metadata.retryIndex

    with grading_context.cache_level(
        grading_context.CacheLevel.NO_CACHE,
        when=grading_context.is_compilation_only,
    ):
        cached_profile = profiling.Profiler('steps.run_coordinated[cached]', start=True)
        with dependency_cache(
            [interactor.command, solution.command],
            [artifacts],
            cacheable_params,
        ) as is_cached:
            if not is_cached:
                with profiling.Profiler('steps.run_coordinated'):
                    profiling.add_to_counter('steps.run_coordinated')
                    await steps.run_coordinated(
                        interactor,
                        solution,
                        artifacts,
                        sandbox,
                        merged_capture=merged_capture,
                    )
            else:
                cached_profile.stop()
                profiling.add_to_counter('steps.run_coordinated[cached]')

    return (
        artifacts.logs.interactor_run,
        artifacts.logs.run,
    )
