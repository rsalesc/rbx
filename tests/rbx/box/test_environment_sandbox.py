from rbx.box.environment import (
    EnvironmentSandbox,
    ExecutionConfig,
    SolutionExecutionOverrides,
    get_sandbox_params_from_config,
    merge_execution_configs,
)


def test_stack_limit_reaches_the_sandbox_params():
    params = get_sandbox_params_from_config(EnvironmentSandbox(stackLimit=64))

    assert params.stack_space == 64


def test_stack_limit_is_unset_by_default():
    params = get_sandbox_params_from_config(EnvironmentSandbox())

    assert params.stack_space is None


def test_stack_limit_can_be_overridden_for_solutions_only():
    config = ExecutionConfig(
        sandbox=EnvironmentSandbox(stackLimit=8),
        solutionOverrides=SolutionExecutionOverrides(
            sandbox=EnvironmentSandbox(stackLimit=256)
        ),
    )

    for_solutions = merge_execution_configs([config], solution=True)
    assert for_solutions.sandbox is not None
    assert for_solutions.sandbox.stackLimit == 256

    # `merge_execution_configs` mutates the config it is given, so re-build it
    # before asking for the non-solution view.
    config = ExecutionConfig(
        sandbox=EnvironmentSandbox(stackLimit=8),
        solutionOverrides=SolutionExecutionOverrides(
            sandbox=EnvironmentSandbox(stackLimit=256)
        ),
    )
    for_others = merge_execution_configs([config], solution=False)
    assert for_others.sandbox is not None
    assert for_others.sandbox.stackLimit == 8
