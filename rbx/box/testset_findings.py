"""What building the testset has to say about it, as a fact a run can keep.

The build used to print these inline, between progress lines, where they were
easy to scroll past and impossible to find again. Now it hands them to the
warning stack: a command without an issues section prints them when it ends,
and `rbx run` records them on its skeleton so `rbx issues` keeps reporting them
until the testset changes.
"""

from typing import Literal, Optional

from pydantic import BaseModel


class DuplicateTest(BaseModel):
    """A test that repeats an earlier one, and neither allows it.

    `reason` says how it was caught: the same generator `call`, or the same
    `input` bytes. A test caught by its call is not checked by its input too --
    the same call almost always means the same bytes, and saying so twice is
    noise.
    """

    # Both as the build names them, e.g. `testplan/3 (gen 5)`.
    test: str
    of: str
    reason: Literal['call', 'input']
    # The generator call, when `reason` is `call`.
    call: Optional[str] = None
    # The test's unambiguous name, what a scoped `issues.ignore` rule matches:
    # `main/3`, or `main/small/0` inside a subgroup. Not the group-and-index
    # `test` starts with, which restarts its index in every subgroup and so can
    # name two tests at once. Absent on a record from an older rbx.
    name: Optional[str] = None
