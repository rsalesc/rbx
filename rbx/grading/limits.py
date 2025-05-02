from typing import Optional

from pydantic import BaseModel, Field


class Limits(BaseModel):
    time: Optional[int] = Field(
        default=None, description='Value to override time limit with, in milliseconds.'
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

    def get_expanded_tl(self) -> Optional[int]:
        if self.time is None:
            return None
        if self.isDoubleTL:
            return self.time * 2
        return self.time
