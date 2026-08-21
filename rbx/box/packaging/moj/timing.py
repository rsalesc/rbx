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
from typing import Dict, List, NamedTuple, Optional

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


def calibrated_limit_lines(ac_to_time_limit: float) -> List[str]:
    """The `conf` block letting MOJ calibrate, as commented lines."""
    return [
        '# MOJ MEASURES the time limit: the judge runs every sols/good solution,',
        '# takes the worst time per language, and scales it by this factor. It is',
        "# rbx's own acToTimeLimit, so the calibrated limit lands where `rbx time`",
        "# would have put it -- but from the judge machine's measurements, which",
        '# rbx never sees. Package without --calibrate to pin the limits instead.',
        f'TLMOD[calibrafactor]={ac_to_time_limit:g}',
        '',
    ]
