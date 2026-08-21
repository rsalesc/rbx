"""Resolution of the time limit estimation strategy in effect for a problem.

The environment picks between a formula and a set of multipliers, and a problem
may override any subset of the multipliers. This module owns that decision so
that callers do not have to re-derive which of the two modes is active, and it
resolves the estimation cap (`inferenceTimeout`), which applies to both modes.
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rbx.box.environment import DEFAULT_INFERENCE_TIMEOUT, TimingConfig
from rbx.box.exception import RbxException
from rbx.box.schema import PackageTiming, TimingMultipliers


class TimingStrategyError(RbxException):
    """The problem and the environment disagree on how to estimate."""

    def __init__(self, message: str):
        super().__init__()
        self.message = message
        self.msg.append(message)


class TimingStrategy(BaseModel):
    """How to estimate a time limit.

    Exactly one of `formula` and `multipliers` is set; `inferenceTimeout` applies
    to both.
    """

    model_config = ConfigDict(extra='forbid', frozen=True)

    formula: Optional[str] = None
    multipliers: Optional[TimingMultipliers] = None

    inferenceTimeout: int = Field(
        default=DEFAULT_INFERENCE_TIMEOUT,
        gt=0,
        description="""The cap enforced on every solution run while estimating.
It is a property of the estimation, not of the multipliers, so it is resolved even
in formula mode.""",
    )

    @model_validator(mode='after')
    def _validate_exactly_one_strategy(self):
        if (self.formula is None) == (self.multipliers is None):
            raise ValueError(
                'A timing strategy must set exactly one of formula and multipliers.'
            )
        return self

    @property
    def uses_multipliers(self) -> bool:
        """Whether this strategy estimates with multipliers rather than a formula."""
        return self.multipliers is not None

    def formula_or_die(self) -> str:
        """The formula to estimate with. Only call in formula mode."""
        assert self.formula is not None, 'This strategy estimates with multipliers.'
        return self.formula

    def multipliers_or_die(self) -> TimingMultipliers:
        """The multipliers to estimate with. Only call in multipliers mode."""
        assert self.multipliers is not None, 'This strategy estimates with a formula.'
        return self.multipliers


def resolve_multipliers(
    env_timing: TimingConfig,
    package_timing: Optional[PackageTiming],
) -> Optional[TimingMultipliers]:
    """The multipliers in effect for this problem, or None in formula mode."""
    override = package_timing.multipliers if package_timing is not None else None
    if env_timing.multipliers is None:
        if override is not None:
            how = (
                f'with the formula `{env_timing.formula}`'
                if env_timing.formula is not None
                else 'with the default formula'
            )
            raise TimingStrategyError(
                f'`problem.rbx.yml` sets `timing.multipliers`, but `env.rbx.yml` has '
                f'no `timing.multipliers` block (it estimates {how}). Add '
                f'`timing.multipliers` to the environment, or remove the override '
                f'from the problem.'
            )
        return None
    if override is None:
        return env_timing.multipliers
    merged = env_timing.multipliers.model_dump()
    merged.update(override.model_dump(exclude_none=True))
    return TimingMultipliers(**merged)


def resolve_inference_timeout(
    env_timing: TimingConfig,
    package_timing: Optional[PackageTiming],
) -> int:
    """The cap in effect for this problem, most specific declaration first.

    The `timing`-level spelling wins over the deprecated `timing.multipliers` one,
    and the problem wins over the environment. Unlike the multipliers, this is
    resolved whatever the estimation strategy is, so a formula-mode problem can
    raise it too.
    """
    if package_timing is not None:
        if package_timing.inferenceTimeout is not None:
            return package_timing.inferenceTimeout
        if (
            package_timing.multipliers is not None
            and package_timing.multipliers.inferenceTimeout is not None
        ):
            return package_timing.multipliers.inferenceTimeout
    return env_timing.resolved_inference_timeout()


def resolve_strategy(
    env_timing: TimingConfig,
    package_timing: Optional[PackageTiming],
) -> TimingStrategy:
    """The estimation strategy in effect for this problem."""
    multipliers = resolve_multipliers(env_timing, package_timing)
    inference_timeout = resolve_inference_timeout(env_timing, package_timing)
    if multipliers is not None:
        return TimingStrategy(
            multipliers=multipliers, inferenceTimeout=inference_timeout
        )
    return TimingStrategy(
        formula=env_timing.resolved_formula(), inferenceTimeout=inference_timeout
    )
