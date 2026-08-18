"""Time limits for a MOJ package.

MOJ *measures* the time limit: `calibreitor.sh` runs every `sols/good` solution,
takes the worst time per language, and writes

    TL[<lang>] = <TLMOD[calibrafactor]> * <worst measured time> + 0.02

into `tl`, with `TL[default]` the smallest of those. `build-and-test.sh` then adds
`TLMOD[<lang>.sum]` to whichever entry applies before judging.

Both values are spliced into `bc` expressions as *text*, which is what makes fixed
limits expressible at all: a factor of `<b>+0` turns the first expression into
`<b> + 0 * worst + 0.02`, a line with slope zero, so the calibrated limit no longer
depends on what the judge measured. `<lang>.sum` then lifts each language from that
common floor to its own limit.

Everything here is in integer milliseconds, the unit rbx's limits profiles use;
only the emitted strings are in seconds, the unit mojtools uses.
"""

import math
from typing import Dict, List, NamedTuple

# The constant `calibreitor.sh` adds to every limit it writes. Subtracted from the
# pinned base so a fixed limit lands exactly on the number rbx estimated instead of
# 20ms above it.
CALIBRATION_INCREMENT_MS = 20

# `calibreitor.sh` enforces this dummy limit (`CALIBRATIONTL`, 5s by default) on the
# accepted solutions while it measures them. A problem whose own limit is larger
# would see them time out during calibration, so the dummy is raised to match.
DEFAULT_CALIBRATION_TL_SECONDS = 5


class FixedTimeLimits(NamedTuple):
    """Pinned limits: a base every language starts from, plus per-language deltas."""

    base_ms: int
    # MOJ language id -> its own limit, in ms. Only languages above the base.
    per_language_ms: Dict[str, int]


def fmt_seconds(ms: int) -> str:
    """Milliseconds as the exact decimal number of seconds mojtools reads with `bc`."""
    sign = '-' if ms < 0 else ''
    ms = abs(ms)
    return f'{sign}{ms // 1000}.{ms % 1000:03d}'


def calibrafactor_for_fixed_limit(base_ms: int) -> str:
    """The `TLMOD[calibrafactor]` value pinning every calibrated limit to `base_ms`.

    The factor is spliced in front of a multiplication (`<factor> * worst + 0.02`),
    so `<base - 0.02>+0` makes the whole expression evaluate to `base` regardless of
    what the judge measured -- and regardless of the language, since `TL[default]`
    is then the same constant too.
    """
    pinned = max(base_ms - CALIBRATION_INCREMENT_MS, 0)
    return f'{fmt_seconds(pinned)}+0'


def calibration_tl_seconds(limits: FixedTimeLimits) -> int:
    """The `CALIBRATIONTL` a package with these limits needs, in whole seconds.

    An accepted solution is allowed to run up to the problem's own limit, so the
    dummy limit calibration enforces must not be tighter than the largest of them.
    """
    largest_ms = max([limits.base_ms, *limits.per_language_ms.values()])
    return max(DEFAULT_CALIBRATION_TL_SECONDS, math.ceil(largest_ms / 1000))


def build_fixed_limits(
    limits_by_language_ms: Dict[str, int], base_ms: int
) -> FixedTimeLimits:
    """Split per-language limits into a common base and the deltas above it.

    The base is the tightest limit involved -- the profile's own base included, since
    a language MOJ knows but the package emits no scripts for falls back to
    `TL[default]`, which the pinned factor sets to exactly this value.
    """
    base = min([base_ms, *limits_by_language_ms.values()])
    per_language = {
        language: limit
        for language, limit in limits_by_language_ms.items()
        if limit != base
    }
    return FixedTimeLimits(base_ms=base, per_language_ms=per_language)


def fixed_limit_lines(limits: FixedTimeLimits) -> List[str]:
    """The `conf` block pinning the limits, as commented lines."""
    lines = [
        '# Time limits are PINNED here, not calibrated: they come from the `moj`',
        '# limits profile `rbx time -p moj` estimated. calibreitor.sh still has to',
        '# run, since mojtools refuses to judge a package with no `tl` file, but the',
        '# factor below has slope zero -- it expands to',
        '#   <base - 0.02> + 0 * <worst measured time> + 0.02',
        '# -- so every language lands on the same base limit whatever it measures.',
        f'# Base time limit: {limits.base_ms} ms.',
        f'TLMOD[calibrafactor]={calibrafactor_for_fixed_limit(limits.base_ms)}',
        '',
    ]
    if limits.per_language_ms:
        lines.extend(
            [
                '# And the increment each language needs on top of that base to reach',
                '# its own time limit, added by build-and-test.sh before judging.',
            ]
        )
        for language, limit_ms in sorted(limits.per_language_ms.items()):
            lines.append(f'# {language}: {limit_ms} ms.')
            lines.append(
                f'TLMOD[{language}.sum]={fmt_seconds(limit_ms - limits.base_ms)}'
            )
        lines.append('')

    calibration_tl = calibration_tl_seconds(limits)
    if calibration_tl > DEFAULT_CALIBRATION_TL_SECONDS:
        lines.extend(
            [
                '# Dummy limit calibreitor.sh enforces while it measures the accepted',
                "# solutions. Its default of 5s is below this problem's own limit, so",
                '# a legitimately slow accepted solution would time out during',
                '# calibration and abort it.',
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
