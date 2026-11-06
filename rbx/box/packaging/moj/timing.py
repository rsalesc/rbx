"""Time limits for a MOJ package.

MOJ *measures* the time limit: `calibreitor.sh` runs every `sols/good` solution,
takes the worst time per language, and writes

    TL[<lang>] = <TLMOD[calibrafactor]> * <worst measured time> + 0.02

into `tl`, with `TL[default]` the smallest of those. `build-and-test.sh` then adds
`TLMOD[<lang>.sum]` to whichever entry applies before judging.

A setter who does not want a measured limit at all authors `TLOVERRIDE` instead:

    TLOVERRIDE[<lang>] // TLOVERRIDE[default] // calibrated[<lang>]

is the limit MOJ judges with -- applied *after* the `TLMOD` arithmetic, so it wins
over every other knob -- and the same value it displays everywhere (training,
contest, the TL sheet, `/problems/tl`). Calibration still runs and its history stays
visible; the override simply outranks whatever it measured. Values are read by grep,
never evaluated, so only a literal number of seconds is accepted here.

Everything here is in integer milliseconds, the unit rbx's limits profiles use;
only the emitted strings are in seconds, the unit mojtools uses.
"""

import math
from typing import Dict, List, NamedTuple, Optional, Tuple

# `calibreitor.sh` enforces this dummy limit (`CALIBRATIONTL`, 5s by default) on the
# accepted solutions while it measures them. A problem whose own limit is larger
# would see them time out during calibration, so the dummy is raised to match.
DEFAULT_CALIBRATION_TL_SECONDS = 5


class FixedTimeLimits(NamedTuple):
    """Pinned limits: a default every language falls back to, plus per-language ones."""

    base_ms: int
    # MOJ language id -> its own limit, in ms. Only languages off the default.
    per_language_ms: Dict[str, int]


def fmt_seconds(ms: int) -> str:
    """Milliseconds as the exact decimal number of seconds mojtools reads."""
    sign = '-' if ms < 0 else ''
    ms = abs(ms)
    return f'{sign}{ms // 1000}.{ms % 1000:03d}'


def calibration_tl_seconds(
    limits: FixedTimeLimits, inference_timeout_ms: Optional[int] = None
) -> int:
    """The `CALIBRATIONTL` a package with these limits needs, in whole seconds.

    The override wins at judging time, but calibration still has to *finish*: the
    largest pinned limit is the floor that matters, since an accepted solution is
    allowed to run right up to its own language's limit and a tighter dummy limit
    would TLE it during calibration and abort the run.

    It is additionally never below mojtools' own 5s default, nor below
    `inferenceTimeout` -- the cap rbx enforced while *estimating*, which is how long
    a solution it measured was allowed to take. Calibration re-runs those same
    solutions (`pass`/`slow`/`wrong` after `good`), so anything rbx was willing to
    wait for, calibration must be too.
    """
    largest_ms = max([limits.base_ms, *limits.per_language_ms.values()])
    floor_seconds = DEFAULT_CALIBRATION_TL_SECONDS
    if inference_timeout_ms is not None:
        floor_seconds = max(floor_seconds, math.ceil(inference_timeout_ms / 1000))
    return max(floor_seconds, math.ceil(largest_ms / 1000))


def build_fixed_limits(
    limits_by_language_ms: Dict[str, int], base_ms: int
) -> FixedTimeLimits:
    """Split per-language limits into a common default and the languages off it.

    The default is the tightest limit involved -- the profile's own base included,
    since a language MOJ knows but the package emits no scripts for falls back to
    `TLOVERRIDE[default]`.
    """
    base = min([base_ms, *limits_by_language_ms.values()])
    per_language = {
        language: limit
        for language, limit in limits_by_language_ms.items()
        if limit != base
    }
    return FixedTimeLimits(base_ms=base, per_language_ms=per_language)


# Why the numbers below are what they are, when they come from `rbx time -p moj`.
PROFILE_EXPLANATION = [
    '# Time limits are PINNED here, not calibrated: they come from the `moj`',
    '# limits profile `rbx time -p moj` estimated. MOJ applies TLOVERRIDE after',
    '# everything else -- calibration and the TLMOD knobs alike -- both when it',
    '# judges and everywhere it shows a limit, so these are the numbers that',
    '# count. calibreitor.sh still has to run, since mojtools refuses to judge a',
    '# package with no `tl` file, but what it measures no longer decides anything.',
]

# ... and when this package exists only for rbx to measure timings on the judge.
PROBE_EXPLANATION = [
    '# Time limits are PINNED here, not calibrated: this package exists for rbx to',
    '# measure solution timings on the judge, and the limits below are what it is',
    '# measuring under. `rbx time` runs in two phases and pins a different shape in',
    '# each: one cap for every language while it estimates from the accepted',
    '# solutions, and one limit per language group while it checks the solutions',
    '# expected to be too slow against the limit it estimated. MOJ applies',
    '# TLOVERRIDE after everything else, so these are the limits every run here sees.',
]


def fixed_limit_lines(
    limits: FixedTimeLimits,
    inference_timeout_ms: Optional[int] = None,
    explanation: Optional[List[str]] = None,
) -> List[str]:
    """The `conf` block pinning the limits, as commented lines.

    `explanation` says where the numbers came from; it defaults to the profile's
    story, since that is what `rbx package moj` emits.
    """
    lines = [
        *(explanation if explanation is not None else PROFILE_EXPLANATION),
        f'# Default time limit: {limits.base_ms} ms.',
        f'TLOVERRIDE[default]={fmt_seconds(limits.base_ms)}',
        '',
    ]
    if limits.per_language_ms:
        lines.extend(
            [
                '# And the languages whose own limit differs from that default.',
            ]
        )
        for language, limit_ms in sorted(limits.per_language_ms.items()):
            lines.append(f'# {language}: {limit_ms} ms.')
            lines.append(f'TLOVERRIDE[{language}]={fmt_seconds(limit_ms)}')
        lines.append('')

    calibration_tl = calibration_tl_seconds(limits, inference_timeout_ms)
    if calibration_tl > DEFAULT_CALIBRATION_TL_SECONDS:
        lines.extend(
            [
                '# Dummy limit calibreitor.sh enforces while it runs the solutions. Its',
                '# default of 5s is below what this problem allows -- its own pinned',
                '# limits, and the inferenceTimeout rbx measured under -- so a solution',
                '# that legitimately takes that long would time out during calibration',
                '# and abort it.',
                f'CALIBRATIONTL={calibration_tl}',
                '',
            ]
        )
    return lines


# Why a `--calibrate` package carries a rule rather than a limit.
CALIBRATE_EXPLANATION = [
    '# MOJ ESTIMATES the time limit, by the Kattis rule: per language, the',
    '# smallest multiple of the resolution that is at least acToTimeLimit times',
    '# the slowest accepted test, measured on the judge machine. These are the',
    "# problem's own timing.multipliers, so the limit lands where `rbx time` would",
    '# have put it. Package without --calibrate to pin the limits instead.',
]


def kattis_limit_lines(
    ac_to_time_limit: float,
    time_limit_to_tle: Optional[float],
    time_resolution_ms: int,
    inference_timeout_ms: int,
    explanation: List[str],
) -> List[str]:
    """The `conf` block asking MOJ to estimate the limit by the Kattis rule.

    rbx's `timing.multipliers` are that rule: `TLKATTIS[lang]` is the smallest
    multiple of `r` that is at least `a x` the worst accepted test of `lang`
    (mojtools `tl-methods.sh`). No `TLOVERRIDE`: the calibrated limit is the
    answer, and calibration ignores an override anyway (`MOJ_CALIBRATING=1`).
    `explanation` says which package asks. Only a setter's `--calibrate` one
    does: the `rbx time` probe pins its calibration instead
    (`capped_calibration_lines`), because the Kattis limit MOJ judges the slow
    solutions at is not the limit rbx ends up writing.
    """
    calibration_tl = max(
        DEFAULT_CALIBRATION_TL_SECONDS, math.ceil(inference_timeout_ms / 1000)
    )
    tle_ratio = time_limit_to_tle if time_limit_to_tle is not None else 1.5
    return [
        *explanation,
        'TLMETHOD=kattis',
        f'KATTIS_AC_TO_TIME_LIMIT={ac_to_time_limit:g}',
        f'KATTIS_TIME_LIMIT_TO_TLE={tle_ratio:g}',
        f'KATTIS_TIME_RESOLUTION={time_resolution_ms / 1000:g}',
        '',
        '# The cap the accepted solutions run under while MOJ measures them: the',
        "# problem's inferenceTimeout, exactly what `rbx time` caps them at locally.",
        f'CALIBRATIONTL={calibration_tl}',
        '',
    ]


# MOJ's own method adds this to every calibrated limit (`calibreitor.sh`:
# `TL[lang] = calibrafactor * W[lang] + 0.02`), and the capped probe below has to
# take it back out to land on the cap exactly.
MOJ_TL_OFFSET_MS = 20

# ... and in the throwaway package `rbx time --runner moj` estimates on.
PROBE_CAPPED_EXPLANATION = [
    '# ONE CALIBRATION, BOTH rbx time PHASES, EVERY SOLUTION CAPPED AT THE SAME',
    "# LIMIT: the problem's inferenceTimeout. TLOVERRIDE is ignored during",
    '# calibration (MOJ_CALIBRATING=1), so the cap goes through the two limits',
    '# calibration does use. sols/good runs under CALIBRATIONTL, set to the cap.',
    '# sols/slow runs under TL[lang] = calibrafactor x W[lang] + 0.02, which bc',
    '# evaluates; a factor of "<cap - 0.02>+0" reads as (cap - 0.02) + 0 x W + 0.02,',
    '# the cap whatever sols/good measured. So a slow solution either finishes with',
    '# its real time or is known to take longer than the cap -- which is what',
    '# `rbx time` checks its own limit against. No TLMOD[lang.sum]: MOJ adds it to',
    '# the Kattis limit too, which stretches every timed-out test in sols/slow to',
    '# about cap + 2 x the worst accepted time instead of cap + 2.2 s. The limit',
    '# MOJ itself would publish by the Kattis rule (TLKATTIS) is computed from the',
    '# same measurements anyway.',
]


def _seconds(ms: int) -> str:
    """`fmt_seconds` without trailing zeros: `1980` -> `1.98`, `5000` -> `5`."""
    return fmt_seconds(ms).rstrip('0').rstrip('.')


def capped_calibration_lines(
    cap_ms: int,
    kattis: Optional[Tuple[float, int]] = None,
) -> List[str]:
    """The `conf` block making a calibration judge everything at `cap_ms`.

    What the `rbx time` probe asks for: see `PROBE_CAPPED_EXPLANATION`.

    The cap is reached without `TLMOD[<lang>.sum]` on purpose. `build-and-test.sh`
    adds the sum to the *other* method's limit as well while it judges
    `pass`/`slow`/`wrong`, and lets each test run until
    `max(that limit, b x TLKATTIS) + 0.5 s` when that exceeds `TL + 2.2 s`
    (`MOJ_CALIB_ALT`). With a sum of `cap - 0.02` that floor was
    `cap + a x W + 0.5`, so every test a slow solution timed out on ran well past
    the cap -- 25 s per test on a 15 s cap -- for nothing rbx reads.

    `kattis` is the problem's `(acToTimeLimit, timeResolution)`, when it has
    `timing.multipliers`: MOJ computes its Kattis limit from these same
    measurements whatever the method, and rbx shows it beside its own. A formula
    has no such ratio, and mojtools then falls back to its own defaults.

    `KATTIS_TIME_LIMIT_TO_TLE` is pinned to 1 either way, rather than the
    problem's own: it only decides MOJ's own verdict on the slow solutions, which
    rbx does not read, and how long a timed-out test keeps running past the cap
    (through the `b x TLKATTIS` floor above), which rbx does not need.
    """
    if cap_ms <= MOJ_TL_OFFSET_MS:
        raise ValueError(
            f'A capped MOJ calibration needs a cap above {MOJ_TL_OFFSET_MS} ms, '
            f'got `{cap_ms}`.'
        )
    return [
        *PROBE_CAPPED_EXPLANATION,
        'TLMETHOD=moj',
        f'TLMOD[calibrafactor]={_seconds(cap_ms - MOJ_TL_OFFSET_MS)}+0',
        f'CALIBRATIONTL={_seconds(cap_ms)}',
        '',
        *(
            [
                '# Only for TLKATTIS, which MOJ computes from the same measurements:',
                "# the problem's own acToTimeLimit and timeResolution.",
                f'KATTIS_AC_TO_TIME_LIMIT={kattis[0]:g}',
                'KATTIS_TIME_LIMIT_TO_TLE=1',
                f'KATTIS_TIME_RESOLUTION={kattis[1] / 1000:g}',
            ]
            if kattis is not None
            else [
                '# How long MOJ lets a test run past the cap, through its Kattis',
                '# floor: as short as it goes.',
                'KATTIS_TIME_LIMIT_TO_TLE=1',
            ]
        ),
        '',
    ]


def clock_lines() -> List[str]:
    """The `conf` block charging the time limit by CPU time, in every package.

    MOJ defaults to the wall clock (`TLCLOCK=wall`); rbx judges solutions by CPU
    time locally, so a MOJ package asks for the same clock -- a setter's package
    and a probe alike, so what `rbx time --runner moj` measures is what the
    package will be judged by. The wall clock stays as a looser ceiling (3x the
    limit, at least the limit + 3.2 s), so a solution that sleeps or blocks still
    dies, as TLE. MOJ refuses this on a parallel problem (`CPUNEEDED > 1`), which
    rbx never emits.
    """
    return [
        '# Charge the time limit by CPU time (user + sys, child processes included),',
        '# as rbx does locally. The wall clock is only a looser ceiling: 3x the limit,',
        '# at least the limit + 3.2 s.',
        'TLCLOCK=cpu',
        '',
    ]


def unified_lines() -> List[str]:
    """The `conf` block giving every language one time limit (`TLUNIFIED=y`).

    Emitted when `extensions.moj.unifiedTimeLimit` is set. MOJ then takes the
    worst accepted time across every language, as if they were one (the Kattis
    model). Per-language `TLOVERRIDE`/`TLMOD` still apply on top of it.
    """
    return [
        '# One time limit for every language: MOJ calibrates from the worst accepted',
        '# time across all of them, as if they were a single language.',
        'TLUNIFIED=y',
        '',
    ]
