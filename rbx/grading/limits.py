from typing import Optional

from pydantic import BaseModel, Field


class Limits(BaseModel):
    time: Optional[int] = Field(
        default=None, description='Value to override time limit with, in milliseconds.'
    )
    configuredTime: Optional[int] = Field(
        default=None,
        description='The declared time limit, in milliseconds, regardless of '
        'whether it is enforced for a given run. ``time`` is nulled to signal '
        '"do not enforce a TL", which loses the declared value; this preserves '
        'it for display/reporting.',
    )
    memory: Optional[int] = Field(
        default=None, description='Value to override memory limit with, in MB.'
    )
    output: Optional[int] = Field(
        default=None, description='Value to override output limit with, in KB.'
    )

    isDoubleTL: bool = Field(
        default=False, description='Whether to use double TL for this language.'
    )

    profile: Optional[str] = Field(
        default=None, description='The profile that was used to get these limits.'
    )

    def get_expanded_tl(self) -> Optional[int]:
        if self.time is None:
            return None
        if self.isDoubleTL:
            return self.time * 2
        return self.time

    def display_time(self) -> Optional[int]:
        """The declared time limit to show in reports, independent of whether it
        is enforced for a given run.

        Prefers ``configuredTime`` (set even when ``time`` is nulled to disable
        enforcement) and falls back to the enforced ``time`` for limits that
        predate the field or were built without it.
        """
        if self.configuredTime is not None:
            return self.configuredTime
        return self.time
