"""What a limits profile says, and what an edit to it would break, as JSON.

The backend of the VS Code time-profile editor (`rbx time-inspect`). The editor
never re-derives a check: it hands rbx the buffer it holds (saved or not) plus at
most one edit, and draws what comes back. Every judgement here is read off
`timing_edit`, the same leaf module `rbx time --edit` routes through, so the two
editors can never disagree about a limit.

A published contract in the sense of `run_report.py`: structured values (ms, MB,
enum values), never rendered strings, and versioned by `INSPECT_VERSION`.
"""

import dataclasses
import pathlib
from typing import Any, Dict, List, Optional

import yaml
from pydantic import ValidationError

from rbx.box import environment, estimation_checksum, limits_info, package, timing_edit
from rbx.box.schema import (
    LimitsProfile,
    TimingGroupReport,
)

INSPECT_VERSION = 1

BASE = 'base'


@dataclasses.dataclass
class Edit:
    """At most one of these is applied, in the order the fields are listed."""

    # (`BASE` or a group index, limit in ms).
    set_time: Optional[tuple] = None
    # A group (`BASE` or an index) whose hand-set limit goes back to the estimate.
    revert: Optional[str] = None
    memory: Optional[int] = None
    inherit: Optional[bool] = None

    def any(self) -> bool:
        return any(
            v is not None
            for v in (self.set_time, self.revert, self.memory, self.inherit)
        )


class EditError(Exception):
    pass


def _parse(source: str) -> LimitsProfile:
    data = yaml.safe_load(source) if source.strip() else {}
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise EditError('A limits profile must be a YAML mapping.')
    return LimitsProfile.model_validate(data)


def _group_index(profile: LimitsProfile, key: str) -> Optional[int]:
    if key == BASE:
        return None
    try:
        index = int(key)
    except ValueError:
        raise EditError(f'Unknown group {key!r}.') from None
    if not profile.groups or not (0 <= index < len(profile.groups)):
        raise EditError(f'No group {index} in this profile.')
    return index


def _report_for(
    profile: LimitsProfile, index: Optional[int]
) -> Optional[TimingGroupReport]:
    if index is None:
        return profile.baseEstimate
    assert profile.groups is not None
    return profile.groups[index]


def apply_edit(profile: LimitsProfile, edit: Edit) -> LimitsProfile:
    if edit.set_time is not None:
        key, ms = edit.set_time
        if ms <= 0:
            raise EditError('A time limit must be positive.')
        index = _group_index(profile, key)
        if timing_edit.is_editable(profile) and (
            index is not None or profile.baseEstimate is not None
        ):
            return timing_edit.with_time_limit(profile, index, ms)
        if index is not None:
            raise EditError('This profile has no estimate to edit a group against.')
        profile = profile.model_copy(deep=True)
        profile.timeLimit = ms
        return profile
    if edit.revert is not None:
        index = _group_index(profile, edit.revert)
        report = _report_for(profile, index)
        if report is None:
            raise EditError('Nothing was estimated for this row.')
        return timing_edit.with_time_limit(
            profile, index, timing_edit.evidence_limit(report)
        )
    if edit.memory is not None:
        if edit.memory <= 0:
            raise EditError('A memory limit must be positive.')
        profile = profile.model_copy(deep=True)
        profile.memoryLimit = edit.memory
        return profile
    if edit.inherit is not None:
        # The evidence stays: unticking the box brings the estimate straight back.
        profile = profile.model_copy(deep=True)
        profile.inheritFromPackage = edit.inherit
        return profile
    return profile


def _languages(profile: LimitsProfile) -> List[str]:
    names: List[str] = []
    try:
        names = [lang.name for lang in environment.get_environment().languages]
    except Exception:
        pass
    for group in profile.groups or []:
        names.extend(group.languages)
    names.extend(profile.modifiers.keys())
    for timing in profile.solutions or []:
        names.append(timing.language)
    seen = set()
    return [n for n in names if not (n in seen or seen.add(n))]


def _effective(profile: LimitsProfile, root: pathlib.Path) -> Dict[str, Any]:
    pkg = package.find_problem_package_or_die(root=root)
    expanded = limits_info._expand_limits_profile(profile, root=root)  # noqa: SLF001
    languages = []
    for lang in _languages(profile):
        languages.append(
            {
                'language': lang,
                'timeLimit': expanded.timelimit_for_language(lang),
                'memoryLimit': expanded.memorylimit_for_language(lang),
            }
        )
    return {
        'timeLimit': expanded.timeLimit,
        'memoryLimit': expanded.memoryLimit,
        'outputLimit': expanded.outputLimit,
        'languages': languages,
        'package': {
            'timeLimit': pkg.timeLimit,
            'memoryLimit': pkg.memoryLimit,
            'outputLimit': pkg.outputLimit,
        },
    }


def _check_json(check: timing_edit.GroupCheck) -> Dict[str, Any]:
    return {
        **check.model_dump(mode='json'),
        'ok': check.ok,
        'belowMin': check.below_min,
        'breaksUpper': check.breaks_upper,
        'rejectsOwnSolutions': check.rejects_own_solutions,
    }


def _row(
    profile: LimitsProfile, key: str, report: Optional[TimingGroupReport]
) -> Dict[str, Any]:
    time_limit = (
        report.timeLimit
        if report is not None
        else (profile.timeLimit if profile.timeLimit is not None else None)
    )
    row: Dict[str, Any] = {
        'key': key,
        'report': report.model_dump(mode='json', exclude_none=True)
        if report is not None
        else None,
        'timeLimit': time_limit,
        'editable': timing_edit.is_editable(profile)
        and report is not None
        and report.origin.value == 'estimated',
        'check': None,
        'solutions': [],
    }
    if report is not None:
        timings = timing_edit.group_solutions(profile, report)
        row['check'] = _check_json(
            timing_edit.assess(report, profile.multipliers, solutions=timings)
        )
        if timings is not None:
            row['solutions'] = [
                c.model_dump(mode='json')
                for c in timing_edit.check_solutions(
                    timings, profile.multipliers, report.timeLimit
                )
            ]
    return row


def _rows(profile: LimitsProfile) -> List[Dict[str, Any]]:
    rows = [_row(profile, BASE, profile.baseEstimate)]
    for index, report in enumerate(profile.groups or []):
        rows.append(_row(profile, str(index), report))
    if profile.groups and profile.solutions:
        # The base row lists only what no group claimed: the rest is already
        # shown under its own group, at that group's limit.
        grouped = {lang for g in profile.groups for lang in g.languages}
        rows[0]['solutions'] = [
            s for s in rows[0]['solutions'] if s['language'] not in grouped
        ]
    return rows


def _stale(profile: LimitsProfile) -> Optional[str]:
    if profile.estimationChecksum is None:
        return None
    try:
        bucket = estimation_checksum.compare(profile.estimationChecksum)
    except Exception:
        return None
    return bucket.value if bucket is not None else None


def inspect(
    source: str,
    profile_name: str,
    edit: Optional[Edit] = None,
    root: pathlib.Path = pathlib.Path(),
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        'version': INSPECT_VERSION,
        'profile': profile_name,
        'path': str(package.get_limits_file(profile_name, root=root)),
        'errors': [],
    }
    try:
        profile = _parse(source)
    except (yaml.YAMLError, ValidationError, EditError) as e:
        out['errors'].append(str(e))
        return out

    if edit is not None and edit.any():
        try:
            profile = apply_edit(profile, edit)
        except EditError as e:
            out['errors'].append(str(e))
            return out
        out['yaml'] = limits_info.profile_to_yaml(profile)

    out.update(
        {
            'inheritFromPackage': profile.inheritFromPackage,
            'timeLimit': profile.timeLimit,
            'memoryLimit': profile.memoryLimit,
            'outputLimit': profile.outputLimit,
            'formula': profile.formula,
            'multipliers': profile.multipliers.model_dump(
                mode='json', exclude_none=True
            )
            if profile.multipliers is not None
            else None,
            'modifiers': {
                k: v.model_dump(mode='json', exclude_none=True)
                for k, v in profile.modifiers.items()
            },
            'editable': timing_edit.is_editable(profile),
            'hasSolutions': bool(profile.solutions),
            'rows': _rows(profile),
            'effective': _effective(profile, root),
            'stale': _stale(profile),
        }
    )
    return out
