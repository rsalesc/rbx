from typing import List, Optional

from rbx.grading import steps
from rbx.grading.caching import DependencyCache, NoCacheException
from rbx.grading.judge.sandbox import SandboxBase, SandboxParams
from rbx.grading.steps import (
    GradingArtifacts,
    GradingLogsHolder,
    RunLog,
    RunLogMetadata,
)


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


def run(
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
            steps.run(
                command=command,
                params=params,
                artifacts=artifacts,
                sandbox=sandbox,
                metadata=metadata,
            )

    return artifacts.logs.run
