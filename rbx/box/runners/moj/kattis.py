"""Reading a MOJ calibration back as `rbx time` measurements.

When a problem estimates with `timing.multipliers`, `rbx time --runner moj` does not
testrun anything: it uploads a package carrying the solutions the estimate is about
(`ProbeCalibrated`), has MOJ calibrate it, and reads the calibration back. This
module is the reading half, kept pure so it can be checked against recorded
calibrations rather than against a judge.

The probe **caps every limit of the calibration at `inferenceTimeout`** (see
`packaging.moj.timing.capped_calibration_lines`): the accepted solutions are
measured under it, and the slow ones are judged against it rather than against
MOJ's per-language Kattis limit -- which is not the limit rbx ends up writing, so
evidence taken there answered the wrong question. `check_cap` is what makes sure
the judge really did apply it.

What a calibration says, per judge and per solution (`cli.CalibSolution`), is the
same `{name, code, time, tl}` vector a testrun reports. Two facts shape how it is
pooled across judges:

- **The limit is the max across the judges that calibrated**, so an accepted
  solution's time is its worst test on its slowest judge, and a timeout on any
  one judge is a timeout.
- **A slow solution's evidence is the *weakest* judge's**: the fastest it finished
  in on a judge that ran every test, or -- only when no judge finished it -- the
  shortest time it was seen to take on a test that exceeded the cap. A `TLE` time
  is how long that test ran -- its real time, or the `etl` kill (`cap + 2.2 s`)
  -- so either way the solution is known to take at least that. A judge split
  between the two (one times it out, another finishes it) is the noisy-judge case
  this rule exists for: the finish wins.

Design: `docs/plans/2026-11-01-moj-parallel-run-and-kattis-calibration-design.md`.
"""

import dataclasses
from typing import Dict, List, Optional, Tuple

from rbx.box.runners.moj import cli
from rbx.box.schema import Solution

# MOJ's per-test codes for a test that passed. `AC,PE` is a pass: MOJ scores it as
# correct (see `runner._OUTCOME_BY_MOJ_CODE`).
_PASS_CODES = frozenset({'AC', 'AC,PE'})
_TIMEOUT_CODE = 'TLE'
# The code for a test the judge never executed: the absence of a verdict, not one.
_NOT_EXECUTED_CODES = frozenset({'NT'})


@dataclasses.dataclass(frozen=True)
class KattisMeasurement:
    """What the calibration established about one solution, pooled over judges."""

    solution: Solution
    # `good` or `slow`: the `sols/` directory the solution was shipped in.
    category: str
    # The judges whose calibration carries this solution.
    hosts: Tuple[str, ...]
    # Accepted solutions: the worst test on the slowest judge, in ms. Slow ones:
    # the weakest judge's evidence -- the fastest worst-test some judge finished
    # it in, else (`timed_out`) the shortest time it survived on a judge that
    # timed it out. See `_pool_accepted` and `_pool_weakest`.
    time_ms: Optional[int]
    # Accepted: some test hit the limit on *some* judge. Slow: no judge finished
    # it, and every judge timed it out.
    timed_out: bool
    # Accepted: every judge reported a verdict for every test. Slow: some judge
    # finished it -- every test reported, none timed out -- and every other judge
    # either finished it or timed it out.
    complete: bool
    # The bad codes that are not a timeout (`WA`, `RE`, `CE`, ...), in the order
    # first met. A solution with any is broken for a reason other than its speed.
    bad_codes: Tuple[str, ...]

    @property
    def measured(self) -> bool:
        return bool(self.hosts) and self.time_ms is not None


def _ms(seconds: Optional[float]) -> Optional[int]:
    if seconds is None:
        return None
    # Rounded, not truncated: MOJ reports two decimals of a second, so `0.29` is
    # 290 ms exactly, and truncating its binary approximation would read 289.
    return int(round(seconds * 1000))


def _per_host(
    sol: cli.CalibSolution, expected_tests: int
) -> Tuple[Optional[int], bool, bool, List[str]]:
    """(worst ms, timed out, complete, bad codes) for one judge's run of one solution."""
    tests = {
        name: test
        for name, test in sol.by_name.items()
        if test.code not in _NOT_EXECUTED_CODES
    }
    times = [ms for ms in (_ms(test.time) for test in tests.values()) if ms is not None]
    codes = [test.code for test in tests.values()]
    timed_out = any(code == _TIMEOUT_CODE for code in codes)
    bad = [code for code in codes if code not in _PASS_CODES and code != _TIMEOUT_CODE]
    if timed_out:
        # What it is known to have survived is the timed-out test's own time --
        # its real time, or the `etl` kill -- not the worst over every test, which
        # would only differ if a pass ever ran longer than a timeout.
        worst = max(
            (
                _ms(test.time)
                for test in tests.values()
                if test.code == _TIMEOUT_CODE and test.time is not None
            ),
            default=None,
        )
    else:
        worst = max(times, default=None)
    return worst, timed_out, len(tests) >= expected_tests, bad


_HostStats = Tuple[Optional[int], bool, bool, List[str]]


def _pool_accepted(
    per_host: List[_HostStats],
) -> Tuple[Optional[int], bool, bool]:
    """(time, timed out, complete) of an accepted solution: the strongest judge.

    Its time is the worst test on the slowest judge, and a timeout on *any* judge
    is a timeout -- the limit is the max across judges, so that judge alone sets
    it, and it ran past the cap there.
    """
    times = [worst for worst, _, _, _ in per_host if worst is not None]
    return (
        max(times, default=None),
        any(timed_out for _, timed_out, _, _ in per_host),
        bool(per_host) and all(complete for _, _, complete, _ in per_host),
    )


def _pool_weakest(
    per_host: List[_HostStats],
) -> Tuple[Optional[int], bool, bool]:
    """(time, timed out, complete) of a slow solution: the weakest judge's evidence.

    A judge either *finished* it (every test reported, none timed out: its worst
    test is its time) or *timed it out* (its timed-out test is a time it is known
    to survive). A finish is always the stronger evidence -- it is within the cap,
    a timeout is past it -- so any finish makes the solution complete, at the
    fastest finish; only when no judge finished is it timed out, at the shortest
    timeout. A judge that did neither (stopped early, or reported no time) knows
    nothing, and its speed could undercut every other judge's, so the solution is
    then neither complete nor timed out.
    """
    finished: List[int] = []
    survived: List[int] = []
    for worst, timed_out, complete, _ in per_host:
        if worst is None:
            return None, False, False
        if timed_out:
            survived.append(worst)
        elif complete:
            finished.append(worst)
        else:
            return None, False, False
    if finished:
        return min(finished), False, True
    if survived:
        return min(survived), True, False
    return None, False, False


def measure_solutions(
    hosts: List[cli.CalibHost],
    solutions_by_file: Dict[Tuple[str, str], Solution],
    expected_tests: int,
) -> Dict[str, KattisMeasurement]:
    """Every shipped solution's measurement, keyed by its rbx path.

    `solutions_by_file` maps `(category, basename)` -- exactly what a calibration
    names a solution by -- to the solution the package shipped there. A solution no
    judge reports on comes back with no hosts and no time: unmeasured, never zero.
    """
    seen: Dict[Tuple[str, str], List[Tuple[str, cli.CalibSolution]]] = {}
    for host in hosts:
        for sol in host.sols:
            key = (sol.category, sol.file)
            if key in solutions_by_file:
                seen.setdefault(key, []).append((host.host, sol))

    measurements: Dict[str, KattisMeasurement] = {}
    for key, solution in solutions_by_file.items():
        category = key[0]
        runs = seen.get(key, [])
        per_host = [(name, _per_host(sol, expected_tests)) for name, sol in runs]
        bad: List[str] = []
        for _, (_, _, _, codes) in per_host:
            for code in codes:
                if code not in bad:
                    bad.append(code)
        if category == 'good':
            time_ms, timed_out, complete = _pool_accepted(
                [stats for _, stats in per_host]
            )
        else:
            time_ms, timed_out, complete = _pool_weakest(
                [stats for _, stats in per_host]
            )
        measurements[str(solution.path)] = KattisMeasurement(
            solution=solution,
            category=category,
            hosts=tuple(name for name, _ in per_host),
            time_ms=time_ms,
            timed_out=timed_out,
            complete=complete,
            bad_codes=tuple(bad),
        )
    return measurements


def limits_ms(calibration: cli.MojCalibration) -> Dict[str, int]:
    """MOJ's published Kattis limit per MOJ language, in ms (`default` included)."""
    out: Dict[str, int] = {}
    for language, seconds in calibration.kattis_limits().items():
        try:
            ms = _ms(float(seconds))
        except ValueError:
            continue
        if ms is not None:
            out[language] = ms
    return out


@dataclasses.dataclass(frozen=True)
class KattisCalibrationResult:
    """One finished calibration, read back."""

    moj_id: str
    # The judges whose calibration describes the uploaded package.
    hosts: Tuple[str, ...]
    measurements: Dict[str, KattisMeasurement]
    # MOJ's own Kattis limit per MOJ language, in ms.
    moj_limits_ms: Dict[str, int]
    # Whether the package was already calibrated, so nothing was queued.
    reused: bool
    # What `replay_test` reads. The cap every limit of the calibration was pinned
    # at; each judge's whole calibration; where each shipped solution was filed,
    # as `(category, file)`, keyed by its rbx path; and the MOJ name of each
    # built testcase, keyed by `runner._entry_key`.
    cap_ms: int = 0
    calib_hosts: Tuple[cli.CalibHost, ...] = ()
    files: Dict[str, Tuple[str, str]] = dataclasses.field(default_factory=dict)
    names_by_entry: Dict[Tuple[str, int], str] = dataclasses.field(default_factory=dict)

    def can_replay(self, solution_path: str, time_limit_ms: int) -> bool:
        """Whether this calibration judged `solution_path` long enough to say what
        it does at `time_limit_ms`: it was shipped, and the limit is within the
        cap every test ran under."""
        return solution_path in self.files and time_limit_ms <= self.cap_ms


def _at_limit(test: cli.TestrunTest, time_limit_ms: int) -> cli.TestrunTest:
    """`test`, judged at `time_limit_ms` instead of the cap it ran under.

    mojtools' own rule (`_verdict_for`: TLE when the time exceeds the limit, the
    run's own verdict otherwise), so it is exact for any limit within the cap: a
    test that finished within it has its real time and its real code, and one
    that ran past the cap ran past every lower limit too.
    """
    code = test.code
    if test.time is not None and test.time * 1000 > time_limit_ms:
        code = _TIMEOUT_CODE
    return cli.TestrunTest(
        name=test.name, code=code, time=test.time, tl=time_limit_ms / 1000
    )


def replay_test(
    result: KattisCalibrationResult,
    solution_path: str,
    name: str,
    time_limit_ms: int,
) -> Optional[cli.TestrunTest]:
    """One test of one shipped solution, as a judge at `time_limit_ms` reports it.

    On its **worst** judge, since MOJ judges a submission on whichever is free:
    a failure on any judge beats a pass, and among equals the slower one wins.
    `None` when no judge ran it -- it was never shipped, or the run halted at an
    earlier timeout (`STOPWHEN_TLE`) -- which the caller reports as skipped,
    exactly as it does for a testrun.
    """
    key = result.files.get(solution_path)
    if key is None:
        return None
    candidates: List[cli.TestrunTest] = []
    for host in result.calib_hosts:
        for sol in host.sols:
            if (sol.category, sol.file) != key:
                continue
            test = sol.by_name.get(name)
            if test is not None and test.code not in _NOT_EXECUTED_CODES:
                candidates.append(_at_limit(test, time_limit_ms))
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda test: (test.code not in _PASS_CODES, test.time or 0.0),
    )


@dataclasses.dataclass(frozen=True)
class OffCapTest:
    """A test the judge ran under some limit other than the cap rbx asked for."""

    host: str
    category: str
    file: str
    test: str
    tl_ms: Optional[int]


def check_cap(
    hosts: List[cli.CalibHost],
    solutions_by_file: Dict[Tuple[str, str], Solution],
    cap_ms: int,
) -> List[OffCapTest]:
    """Every executed test of a shipped solution whose limit is not `cap_ms`.

    The cap is reached by MOJ's own arithmetic (`calibrafactor`, the dummy table,
    `TLMOD` sums), none of which MOJ promises to keep. Every measurement and every
    verdict rbx reads assumes the cap, so a single test judged under anything else
    -- a missing sum, a changed formula -- means none of it can be trusted.
    """
    off: List[OffCapTest] = []
    for host in hosts:
        for sol in host.sols:
            if (sol.category, sol.file) not in solutions_by_file:
                continue
            for test in sol.by_name.values():
                if test.code in _NOT_EXECUTED_CODES:
                    continue
                tl_ms = _ms(test.tl)
                if tl_ms != cap_ms:
                    off.append(
                        OffCapTest(host.host, sol.category, sol.file, test.name, tl_ms)
                    )
    return off
