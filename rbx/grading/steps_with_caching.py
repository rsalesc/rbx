from typing import Any, Dict, List, Optional, Tuple

from rbx.grading import steps
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
    with dependency_cache(
        commands, [artifacts], params.get_cacheable_params()
    ) as is_cached:
        if not is_cached and not steps.compile(
            commands=commands,
            params=params,
            artifacts=artifacts,
            sandbox=sandbox,
        ):
            ok = False
            raise NoCacheException()

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

    with dependency_cache([command], [artifacts], cacheable_params) as is_cached:
        if not is_cached:
            await steps.run(
                command=command,
                params=params,
                artifacts=artifacts,
                sandbox=sandbox,
                metadata=metadata,
            )

    return artifacts.logs.run


async def run_coordinated(
    interactor: steps.CoordinatedRunParams,
    solution: steps.CoordinatedRunParams,
    dependency_cache: DependencyCache,
) -> Tuple[Optional[RunLog], Optional[RunLog]]:
    interactor.artifacts.logs = GradingLogsHolder()
    solution.artifacts.logs = GradingLogsHolder()

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

    with dependency_cache(
        [interactor.command, solution.command],
        [interactor.artifacts, solution.artifacts],
        cacheable_params,
    ) as is_cached:
        if not is_cached:
            await steps.run_coordinated(interactor, solution)

    return (
        interactor.artifacts.logs.run,
        solution.artifacts.logs.run,
    )
