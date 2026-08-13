"""Resolution of the time limit estimation strategy in effect for a problem.

The environment picks between a formula and a set of multipliers, and a problem
may override any subset of the multipliers. This module owns that decision so
that callers do not have to re-derive which of the two modes is active.
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, model_validator

from rbx.box.environment import TimingConfig, TimingMultipliers
from rbx.box.schema import PackageTiming


class ResolutionError(ValueError):
    """The problem and the environment disagree on how to estimate."""


class TimingStrategy(BaseModel):
    """How to estimate a time limit. Exactly one of the fields is set."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    formula: Optional[str] = None
    multipliers: Optional[TimingMultipliers] = None

    @model_validator(mode='after')
    def _validate_exactly_one_strategy(self):
        if (self.formula is None) == (self.multipliers is None):
            raise ValueError(
                'a timing strategy must set exactly one of formula and multipliers.'
            )
        return self


def resolve_multipliers(
    env_timing: TimingConfig,
    package_timing: Optional[PackageTiming],
) -> Optional[TimingMultipliers]:
    """The multipliers in effect for this problem, or None in formula mode."""
    override = package_timing.multipliers if package_timing is not None else None
    if env_timing.multipliers is None:
        if override is not None:
            raise ResolutionError(
                'this problem overrides timing.multipliers, but the environment '
                'estimates with a formula; the two are mutually exclusive.'
            )
        return None
    if override is None:
        return env_timing.multipliers
    merged = env_timing.multipliers.model_dump()
    merged.update(override.model_dump(exclude_none=True))
    return TimingMultipliers(**merged)


def resolve_strategy(
    env_timing: TimingConfig,
    package_timing: Optional[PackageTiming],
) -> TimingStrategy:
    """The estimation strategy in effect for this problem."""
    multipliers = resolve_multipliers(env_timing, package_timing)
    if multipliers is not None:
        return TimingStrategy(multipliers=multipliers)
    return TimingStrategy(formula=env_timing.resolved_formula())
