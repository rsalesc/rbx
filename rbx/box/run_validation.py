"""What a run knows about the validity of the testcases it ran on.

`rbx run` validates every input before running anything, and by default an
invalid one aborts the run: at the terminal that is the right call, since the
setter is right there to fix the test. A client that started the run on the
setter's behalf -- the VS Code extension -- has no such loop to offer, so it asks
for `--on-invalid=warn` instead: the run goes ahead, and which testcases failed
validation rides the run skeleton for the client to flag.
"""

import enum
from typing import TYPE_CHECKING, Iterable, List, Optional

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


class RunValidation(BaseModel):
    mode: RunValidationMode
    # Every (testcase, validator) rejection, in validation order. Carried whole
    # rather than as a count so a client can flag each testcase without reading
    # `build/testset.yml`, which a later build may already have replaced.
    invalid: List[InvalidTestcase] = []


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
    return RunValidation(
        mode=RunValidationMode(on_invalid.value),
        invalid=invalid_testcases(infos, testcase),
    )
