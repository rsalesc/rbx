"""What is known about the solutions expected to be too slow.

Validating an estimated time limit asks one question per slow solution: does it
take at least ``timeLimit * timeLimitToTle``? Running it under exactly that limit
answers the question without measuring it -- a solution killed at the limit
cleared the bound, and one that finished did not, and hands us its real time on
the way out.

The answer is monotone, which is what makes the picker loop cheap: a solution
killed at ``L`` is also killed at any lower limit, and a solution that finished
is answered by arithmetic forever after.
"""

import dataclasses
import math
from fractions import Fraction
from typing import Dict, Optional


def probe_limit(time_limit: int, time_limit_to_tle: float) -> int:
    """The limit a slow solution must survive for ``time_limit`` to hold.

    Rounded up, and computed from the ratio the setter typed rather than from its
    binary approximation, so it agrees with `timing.compute_bounds` on the
    boundary case where a solution takes exactly ``time_limit * ratio``.
    """
    return math.ceil(time_limit * Fraction(str(time_limit_to_tle)))


@dataclasses.dataclass
class _SolutionKnowledge:
    # Its real time, once it finished under some probe limit.
    time: Optional[int] = None
    # The highest limit it was killed at, so its time exceeds this.
    survived: Optional[int] = None


@dataclasses.dataclass
class SlowKnowledge:
    """What each slow solution has already told us, across probe limits."""

    _per_solution: Dict[str, _SolutionKnowledge] = dataclasses.field(
        default_factory=dict
    )

    def _entry(self, solution: str) -> _SolutionKnowledge:
        return self._per_solution.setdefault(solution, _SolutionKnowledge())

    def record_time(self, solution: str, time: int) -> None:
        """It finished under its probe limit, in ``time`` ms."""
        self._entry(solution).time = time

    def record_timeout(self, solution: str, limit: int) -> None:
        """It was still running at ``limit`` ms."""
        entry = self._entry(solution)
        entry.survived = max(entry.survived or 0, limit)

    def measured_time(self, solution: str) -> Optional[int]:
        """Its real time, or None if it has only ever been killed."""
        return self._per_solution.get(solution, _SolutionKnowledge()).time

    def is_confirmed(self, solution: str) -> bool:
        """Whether it is known to be too slow rather than merely unmeasured."""
        entry = self._per_solution.get(solution)
        return entry is not None and entry.time is None and entry.survived is not None

    def needs_run(self, solution: str, limit: int) -> bool:
        """Whether answering the question at ``limit`` requires running it."""
        entry = self._per_solution.get(solution)
        if entry is None:
            return True
        if entry.time is not None:
            # A real measurement answers every limit by arithmetic.
            return False
        return entry.survived is None or entry.survived < limit
