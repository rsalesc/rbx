"""What a run knows about the validity of the testcases it ran on.

`rbx run` validates every input before running anything, and by default an
invalid one aborts the run: at the terminal that is the right call, since the
setter is right there to fix the test. A client that started the run on the
setter's behalf -- the VS Code extension -- has no such loop to offer, so it asks
for `--on-invalid=warn` instead: the run goes ahead, and which testcases failed
validation rides the run skeleton for the client to flag.
"""

import enum
from typing import TYPE_CHECKING, Iterable, List, Literal, Optional

from pydantic import BaseModel

if TYPE_CHECKING:
    from rbx.box.testcase_schema import TestcaseEntry
    from rbx.box.validators import TestcaseValidationInfo


class OnInvalid(str, enum.Enum):
    """What a run does when some of its testcases fail validation."""

    # Abort before running anything. What a setter at the terminal wants.
    FAIL = 'fail'
    # Report the failures, then run every testcase anyway.
    WARN = 'warn'


class RunValidationMode(str, enum.Enum):
    """How the testcases of a run were validated, as published on its skeleton."""

    FAIL = 'fail'
    WARN = 'warn'
    # Not validated at all (`--no-validate`, or `-v0`).
    OFF = 'off'


class InvalidTestcase(BaseModel):
    group: str
    index: int
    # The validator that rejected it, as a package-relative path.
    validator: str
    message: Optional[str] = None


class UnhitBound(BaseModel):
    """A bound a validator enforces that no testcase reaches.

    The classic slip it catches is a testset without a max test: every input is
    valid, so validation passes, and the solution that is too slow at the limit
    is never asked to run there.
    """

    # The group whose tests were checked, or None when every group shares the
    # same bounds and the testset was checked as a whole.
    group: Optional[str] = None
    # The name the validator read the value under, e.g. `N`.
    name: str
    missing: List[Literal['min', 'max']]


class RunValidation(BaseModel):
    mode: RunValidationMode
    # Every (testcase, validator) rejection, in validation order. Carried whole
    # rather than as a count so a client can flag each testcase without reading
    # `build/testset.yml`, which a later build may already have replaced.
    invalid: List[InvalidTestcase] = []
    # Bounds no testcase reached, on a run that validated the whole testset.
    unhitBounds: List[UnhitBound] = []


def invalid_testcases(
    infos: Iterable['TestcaseValidationInfo'],
    testcase: Optional['TestcaseEntry'] = None,
) -> List[InvalidTestcase]:
    """The rejections among `infos`.

    `testcase` names the testcase every info is about, for a one-off validation
    (`rbx irun`) whose infos may carry none of their own.
    """
    invalid = []
    for info in infos:
        entry = info.testcase or testcase
        if info.ok or entry is None:
            continue
        invalid.append(
            InvalidTestcase(
                group=entry.group,
                index=entry.index,
                validator=str(info.validator.path),
                message=info.message.strip() if info.message else None,
            )
        )
    return invalid


def run_validation(
    on_invalid: OnInvalid,
    infos: Optional[Iterable['TestcaseValidationInfo']],
    testcase: Optional['TestcaseEntry'] = None,
) -> RunValidation:
    """The validation record of a run, from what its build validated.

    `infos` is None when the testcases were not validated at all.
    """
    if infos is None:
        return RunValidation(mode=RunValidationMode.OFF)
    infos = list(infos)
    # A run on one testcase (`rbx irun`) says nothing about the testset's
    # coverage: of course a single test misses most bounds.
    unhit: List[UnhitBound] = []
    if testcase is None:
        from rbx.box import validators

        unhit = validators.unhit_bounds(infos)
    return RunValidation(
        mode=RunValidationMode(on_invalid.value),
        invalid=invalid_testcases(infos, testcase),
        unhitBounds=unhit,
    )
