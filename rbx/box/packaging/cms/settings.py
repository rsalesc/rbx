"""The CMS settings a package is exported with, as CMS names them.

`resolve` merges the `cms` block of `env.rbx.yml` (a preset's defaults) with the
one of `contest.rbx.yml`, field by field, the contest winning. `tokens` is the
exception: it is replaced whole, because changing `mode` makes the inherited
finite-mode fields meaningless.

An unset field is not emitted, so CMS keeps its own default. Three fields have
rbx defaults instead, because CMS's do not mean what rbx means:

- `scoreMode` is `max`: CMS's `max_tokened_last` scores the *last* submission
  when tokens are off, and rbx's per-submission score means the best one.
- `publicTestcases` is `samples`: CMS's Polygon importer marks every test
  public, which would show contestants per-test results on the hidden set.
- `scorePrecision` is 2, at both levels: CMS's 0 shows a 45.84 rbx computes
  as 46.
"""

from typing import Any, Dict, List, Optional, Sequence, TypeVar, Union

from pydantic import BaseModel

from rbx import console
from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.packaging.cms import scoring
from rbx.box.packaging.cms.extension import (
    CmsContestSettings,
    CmsExtension,
    CmsLimits,
    CmsPublicTestcases,
    CmsScoreMode,
    CmsTaskSettings,
    CmsTokenMode,
    CmsTokens,
)
from rbx.box.scoring import partial

M = TypeVar('M', bound=BaseModel)

# The decimal places CMS shows scores with, unless the settings say otherwise.
# CMS's own default is 0, which rounds a 45.84 to 46; rbx shows two.
SCORE_PRECISION = partial.PRECISION

_SCORE_MODES = {
    CmsScoreMode.MAX: 'max',
    CmsScoreMode.MAX_SUBTASK: 'max_subtask',
    CmsScoreMode.MAX_TOKENED_LAST: 'max_tokened_last',
}
_LIMIT_KEYS = {
    'maxSubmissionNumber': 'max_submission_number',
    'maxUserTestNumber': 'max_user_test_number',
    'minSubmissionInterval': 'min_submission_interval',
    'minUserTestInterval': 'min_user_test_interval',
    'scorePrecision': 'score_precision',
}
_TOKEN_KEYS = {
    'maxNumber': 'token_max_number',
    'minInterval': 'token_min_interval',
    'genInitial': 'token_gen_initial',
    'genNumber': 'token_gen_number',
    'genInterval': 'token_gen_interval',
    'genMax': 'token_gen_max',
}
# CMS keys holding a duration. Emitted in seconds; CMS wants a `timedelta`.
DURATION_KEYS = frozenset(
    {
        'min_submission_interval',
        'min_user_test_interval',
        'token_min_interval',
        'token_gen_interval',
    }
)


def _overlay(base: Optional[M], top: Optional[M]) -> Optional[M]:
    if top is None:
        return base
    if base is None:
        return top
    return base.model_copy(
        update={name: getattr(top, name) for name in top.model_fields_set}
    )


def merge(env: Optional[CmsExtension], contest: Optional[CmsExtension]) -> CmsExtension:
    """The settings `contest` leaves to `env`, plus those it sets."""
    env = env or CmsExtension()
    contest = contest or CmsExtension()
    return CmsExtension(
        contest=_overlay(env.contest, contest.contest),
        task=_overlay(env.task, contest.task),
    )


def resolve() -> CmsExtension:
    """The settings in effect for the package in the current directory.

    A problem inside a contest takes the contest's settings over its
    environment's; one outside a contest has only the environment's.
    """
    from rbx.box import environment
    from rbx.box.contest import contest_package

    env = environment.get_extension('cms', CmsExtension)
    contest = contest_package.find_contest_package()
    contest_cms = (
        contest.extensions.cms
        if contest is not None and contest.extensions is not None
        else None
    )
    return merge(env, contest_cms)


def _tokens(tokens: CmsTokens) -> Dict[str, Any]:
    keys = {'token_mode': tokens.mode.value}
    for field, key in _TOKEN_KEYS.items():
        value = getattr(tokens, field)
        if value is not None:
            keys[key] = value
    return keys


def _limits(limits: CmsLimits) -> Dict[str, Any]:
    keys = {}
    for field, key in _LIMIT_KEYS.items():
        value = getattr(limits, field)
        if value is not None:
            keys[key] = value
    if limits.tokens is not None:
        keys.update(_tokens(limits.tokens))
    return keys


def task_keys(task: Optional[CmsTaskSettings]) -> Dict[str, Any]:
    """The task columns to set in CMS, durations in seconds."""
    task = task or CmsTaskSettings()
    keys: Dict[str, Any] = {
        'score_mode': _SCORE_MODES[task.scoreMode]
        if task.scoreMode is not None
        else scoring.SCORE_MODE
    }
    if task.feedbackLevel is not None:
        keys['feedback_level'] = task.feedbackLevel.value
    keys.update(_limits(task))
    keys.setdefault('score_precision', SCORE_PRECISION)
    return keys


# Contest flags, keyed by the field rbx names them with.
_CONTEST_FLAG_KEYS = {
    'allowUserTests': 'allow_user_tests',
    'allowQuestions': 'allow_questions',
    'submissionsDownloadAllowed': 'submissions_download_allowed',
    'allowPasswordAuthentication': 'allow_password_authentication',
    'allowRegistration': 'allow_registration',
    'ipRestriction': 'ip_restriction',
    'ipAutologin': 'ip_autologin',
    'blockHiddenParticipations': 'block_hidden_participations',
}


def contest_keys(contest: Optional[CmsContestSettings]) -> Dict[str, Any]:
    """The contest columns to set in CMS.

    Durations are in seconds, and `start`/`stop` are Unix timestamps.
    """
    contest = contest or CmsContestSettings()
    keys: Dict[str, Any] = {}
    for field, key in _CONTEST_FLAG_KEYS.items():
        value = getattr(contest, field)
        if value is not None:
            keys[key] = value
    if contest.start is not None:
        keys['start'] = int(contest.start.timestamp())
    if contest.stop is not None:
        keys['stop'] = int(contest.stop.timestamp())
    if contest.perUserTime is not None:
        keys['per_user_time'] = contest.perUserTime
    if contest.timezone is not None:
        keys['timezone'] = contest.timezone
    if contest.allowedLocalizations is not None:
        keys['allowed_localizations'] = list(contest.allowedLocalizations)
    keys.update(_limits(contest))
    keys.setdefault('score_precision', SCORE_PRECISION)
    return keys


def public_testcases(
    task: Optional[CmsTaskSettings], entries: Sequence[GenerationTestcaseEntry]
) -> Union[str, List[int]]:
    """`'all'`, or the 0-based indices in `entries` of the public tests."""
    public = (task.publicTestcases if task is not None else None) or (
        CmsPublicTestcases.SAMPLES
    )
    if public == CmsPublicTestcases.ALL:
        return 'all'
    if public == CmsPublicTestcases.NONE:
        return []
    return [i for i, entry in enumerate(entries) if entry.is_sample()]


def _set_fields(model: Optional[BaseModel]) -> List[str]:
    if model is None:
        return []
    return sorted(model.model_fields_set)


def warn_for_polygon(settings: CmsExtension):
    """Warn about settings that cannot reach CMS through a Polygon package.

    The Polygon contest importer sets its own contest options, so nothing under
    `contest` is carried: `rbx contest package cms-contest` builds the contest
    they belong to.
    """
    contest_fields = _set_fields(settings.contest)
    if contest_fields:
        console.console.print(
            '[warning]CMS contest settings are not carried by a Polygon package, '
            "since CMS's Polygon importer sets its own contest options. Ignoring "
            f'[item]{", ".join(contest_fields)}[/item]: import the contest from '
            '[item]rbx contest package cms-contest[/item] instead, or set them in '
            'CMS after importing.[/warning]'
        )
    _warn_tokened_last_without_tokens(settings)


def _warn_tokened_last_without_tokens(settings: CmsExtension):
    task = settings.task
    if task is None or task.scoreMode != CmsScoreMode.MAX_TOKENED_LAST:
        return
    # CMS's task default is no tokens; a contestant needs both levels to allow one.
    task_off = task.tokens is None or task.tokens.mode == CmsTokenMode.DISABLED
    contest_tokens = settings.contest.tokens if settings.contest else None
    contest_off = (
        contest_tokens is not None and contest_tokens.mode == CmsTokenMode.DISABLED
    )
    if task_off or contest_off:
        console.console.print(
            '[warning]CMS [item]scoreMode: maxTokenedLast[/item] is set, but tokens '
            'are disabled, so every task is scored by its last submission alone. '
            'Use [item]max[/item], or enable tokens.[/warning]'
        )
