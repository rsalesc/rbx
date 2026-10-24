"""What `env.rbx.yml` and `contest.rbx.yml` say about a CMS contest.

The same `cms` block lives at both levels: a preset ships an organisation's
defaults in `env.rbx.yml`, and a contest overrides them field by field in
`contest.rbx.yml` (see `settings.resolve`). It has two halves, because CMS keeps
submission limits and tokens on the contest *and* on each task, and applies
both.

Every key maps to one the CMS v1.5.1 loaders read, and every enum lists only
values that version accepts. An unset field is not emitted, leaving CMS's own
default -- except `task.scoreMode` and `task.publicTestcases`, whose CMS
defaults do not match what rbx means (see `settings`).
"""

import datetime
import enum
import zoneinfo
from typing import Annotated, Any, List, Optional

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
    field_validator,
    model_validator,
)


class CmsScoreMode(str, enum.Enum):
    MAX = 'max'
    MAX_SUBTASK = 'maxSubtask'
    MAX_TOKENED_LAST = 'maxTokenedLast'


class CmsFeedbackLevel(str, enum.Enum):
    FULL = 'full'
    RESTRICTED = 'restricted'


class CmsPublicTestcases(str, enum.Enum):
    SAMPLES = 'samples'
    ALL = 'all'
    NONE = 'none'


class CmsTokenMode(str, enum.Enum):
    DISABLED = 'disabled'
    FINITE = 'finite'
    INFINITE = 'infinite'


class CmsTokens(BaseModel):
    """CMS tokens. Replaced as a whole when a contest overrides a preset."""

    model_config = ConfigDict(extra='forbid')

    mode: CmsTokenMode = Field(
        description='`disabled`: no tokens. `infinite`: a contestant may token every '
        'submission. `finite`: tokens are generated over time, as the fields below say. '
        "Written to CMS's `token_mode`.",
    )
    maxNumber: Optional[PositiveInt] = Field(
        default=None,
        description='Most tokens a contestant may use in total (`token_max_number`). '
        'Unset means no cap. `finite` mode only.',
    )
    minInterval: Optional[NonNegativeInt] = Field(
        default=None,
        description='Seconds a contestant must wait between two tokens '
        '(`token_min_interval`). `finite` mode only.',
    )
    genInitial: Optional[NonNegativeInt] = Field(
        default=None,
        description='Tokens a contestant starts with (`token_gen_initial`). '
        '`finite` mode only.',
    )
    genNumber: Optional[NonNegativeInt] = Field(
        default=None,
        description='Tokens generated every `genInterval` (`token_gen_number`). '
        '`finite` mode only.',
    )
    genInterval: Optional[PositiveInt] = Field(
        default=None,
        description='Seconds between two generations (`token_gen_interval`). '
        '`finite` mode only.',
    )
    genMax: Optional[PositiveInt] = Field(
        default=None,
        description='Most tokens a contestant may hold at once (`token_gen_max`). '
        'Unset means no cap. `finite` mode only.',
    )

    @model_validator(mode='after')
    def check_finite_only_fields(self):
        if self.mode == CmsTokenMode.FINITE:
            return self
        # CMS reads every other field only in finite mode.
        set_fields = sorted(self.model_fields_set - {'mode'})
        if set_fields:
            raise ValueError(
                f'Token mode {self.mode.value!r} takes no other field, but '
                f'{", ".join(set_fields)} {"is" if len(set_fields) == 1 else "are"} '
                'set. Only `finite` mode reads them.'
            )
        return self


class CmsLimits(BaseModel):
    """Limits CMS keeps both on the contest and on each task."""

    model_config = ConfigDict(extra='forbid')

    maxSubmissionNumber: Optional[PositiveInt] = Field(
        default=None,
        description='Most submissions a contestant may make (`max_submission_number`).',
    )
    maxUserTestNumber: Optional[PositiveInt] = Field(
        default=None,
        description='Most user tests a contestant may run (`max_user_test_number`).',
    )
    minSubmissionInterval: Optional[PositiveInt] = Field(
        default=None,
        description='Seconds a contestant must wait between two submissions '
        '(`min_submission_interval`).',
    )
    minUserTestInterval: Optional[PositiveInt] = Field(
        default=None,
        description='Seconds a contestant must wait between two user tests '
        '(`min_user_test_interval`).',
    )
    scorePrecision: Optional[NonNegativeInt] = Field(
        default=None,
        description='Decimal places scores are shown with (`score_precision`).',
    )
    tokens: Optional[CmsTokens] = Field(
        default=None,
        description='Tokens. A contestant may use one on a task only when both the '
        'contest and the task allow it.',
    )


class CmsTaskSettings(CmsLimits):
    """Settings applied to every task of the contest.

    The limits here apply to each task separately.
    """

    scoreMode: Optional[CmsScoreMode] = Field(
        default=None,
        description="How the task score comes out of a contestant's submissions "
        '(`score_mode`). `max`: the best submission. `maxSubtask`: the best score on '
        'each subtask, summed across submissions. `maxTokenedLast`: the best of the '
        'tokened submissions and the last one. Defaults to `max`, which is what rbx '
        "means by a solution's score; CMS's own default is `maxTokenedLast`.",
    )
    feedbackLevel: Optional[CmsFeedbackLevel] = Field(
        default=None,
        description='How much contestants see about a submission on its public '
        "testcases (`feedback_level`). `full`: every testcase's outcome, time and "
        'memory. `restricted`: less.',
    )
    publicTestcases: Optional[CmsPublicTestcases] = Field(
        default=None,
        description='Which testcases contestants see results for. `samples`: the '
        'tests of the `samples` group. `all`: every test. `none`: no test. '
        'Defaults to `samples`.',
    )


def _restore_yaml_offset(value: Any) -> Any:
    # The YAML loader turns `2026-09-28T08:00:00-03:00` into a naive datetime in
    # UTC, keeping the offset it read aside. Put it back, so the instant is kept
    # and a timestamp written without an offset is still refused.
    yaml_info = getattr(value, '_yaml', None)
    if not isinstance(value, datetime.datetime) or not yaml_info:
        return value
    if yaml_info.get('tz') is None:
        return value
    utc = datetime.datetime(*value.timetuple()[:6], value.microsecond).replace(
        tzinfo=datetime.timezone.utc
    )
    offset = yaml_info.get('delta')
    if not isinstance(offset, datetime.timedelta):
        offset = datetime.timedelta()  # `Z` is stored as a plain 0.
    return utc.astimezone(datetime.timezone(offset))


ContestTime = Annotated[AwareDatetime, BeforeValidator(_restore_yaml_offset)]


def _check_timezone(timezone: Optional[str]) -> Optional[str]:
    if timezone is None:
        return None
    try:
        zoneinfo.ZoneInfo(timezone)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        raise ValueError(
            f"{timezone!r} is not an IANA timezone name, such as 'America/Sao_Paulo'."
        ) from None
    return timezone


class CmsContestSettings(CmsLimits):
    """Settings of the CMS contest itself.

    The limits here count across all tasks.
    """

    start: Optional[ContestTime] = Field(
        default=None,
        description='When the contest starts (`start`), with a UTC offset, such as '
        '`2026-09-28T08:00:00-03:00`. `contest.rbx.yml` only.',
    )
    stop: Optional[ContestTime] = Field(
        default=None,
        description='When the contest ends (`stop`), with a UTC offset. '
        '`contest.rbx.yml` only.',
    )
    perUserTime: Optional[PositiveInt] = Field(
        default=None,
        description='Seconds each contestant gets, starting when they choose to, '
        'within the contest window (`per_user_time`). `contest.rbx.yml` only.',
    )
    timezone: Annotated[Optional[str], AfterValidator(_check_timezone)] = Field(
        default=None,
        description='IANA name of the timezone CMS shows times in (`timezone`), '
        'such as `America/Sao_Paulo`. Separate from the UTC offsets on `start` '
        'and `stop`.',
    )
    allowUserTests: Optional[bool] = Field(
        default=None,
        description='Whether contestants may run their code on their own inputs '
        '(`allow_user_tests`).',
    )
    allowQuestions: Optional[bool] = Field(
        default=None,
        description='Whether contestants may ask questions (`allow_questions`).',
    )
    submissionsDownloadAllowed: Optional[bool] = Field(
        default=None,
        description='Whether contestants may download their submissions '
        '(`submissions_download_allowed`).',
    )
    allowPasswordAuthentication: Optional[bool] = Field(
        default=None,
        description='Whether contestants may log in with a password '
        '(`allow_password_authentication`).',
    )
    allowRegistration: Optional[bool] = Field(
        default=None,
        description='Whether people may register themselves (`allow_registration`).',
    )
    ipRestriction: Optional[bool] = Field(
        default=None,
        description='Whether a contestant may log in only from their own IP '
        'addresses (`ip_restriction`).',
    )
    ipAutologin: Optional[bool] = Field(
        default=None,
        description='Whether a contestant is logged in from their IP address, '
        'without a password (`ip_autologin`).',
    )
    blockHiddenParticipations: Optional[bool] = Field(
        default=None,
        description='Whether hidden participations are kept from logging in '
        '(`block_hidden_participations`).',
    )
    allowedLocalizations: Optional[List[str]] = Field(
        default=None,
        description='Interface languages contestants may pick, such as `en` and '
        '`pt_BR` (`allowed_localizations`). Unset or empty allows them all.',
    )

    @model_validator(mode='after')
    def check_window(self):
        if self.start is not None and self.stop is not None:
            if self.stop <= self.start:
                raise ValueError('`stop` must come after `start`.')
            window = self.stop - self.start
            if (
                self.perUserTime is not None
                and datetime.timedelta(seconds=self.perUserTime) > window
            ):
                raise ValueError(
                    f'`perUserTime` ({self.perUserTime}s) is longer than the '
                    f'contest window ({int(window.total_seconds())}s).'
                )
        return self


# The contest's own schedule. A preset carrying one is a mistake, so `env.rbx.yml`
# refuses these.
EVENT_FIELDS = ('start', 'stop', 'perUserTime')


class CmsExtension(BaseModel):
    """CMS settings: the contest's own, and those applied to every task."""

    model_config = ConfigDict(extra='forbid')

    contest: Optional[CmsContestSettings] = Field(
        default=None, description='Settings of the CMS contest itself.'
    )
    task: Optional[CmsTaskSettings] = Field(
        default=None, description='Settings applied to every task of the contest.'
    )


class CmsEnvironmentExtension(CmsExtension):
    """CMS settings in `env.rbx.yml`: a preset's defaults, without a schedule."""

    @field_validator('contest')
    @classmethod
    def reject_event_fields(cls, contest: Optional[CmsContestSettings]):
        if contest is None:
            return contest
        set_fields = [f for f in EVENT_FIELDS if f in contest.model_fields_set]
        if set_fields:
            raise ValueError(
                f'{", ".join(set_fields)} can only be set in contest.rbx.yml: a '
                'preset is shared between contests, and a schedule belongs to one.'
            )
        return contest
