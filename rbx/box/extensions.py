from typing import Optional

from pydantic import BaseModel, Field

from rbx.box.packaging.boca.extension import BocaExtension, BocaLanguageExtension
from rbx.box.packaging.moj.extension import MojExtension, MojLanguageExtension
from rbx.box.packaging.polygon.extension import PolygonLanguageExtension
from rbx.box.tooling.domjudge.extension import (
    DomjudgeExtension,
    DomjudgeLanguageExtension,
)


# Extension abstractions.
class Extensions(BaseModel):
    boca: Optional[BocaExtension] = Field(
        default=None, description='Environment-level extensions for BOCA packaging.'
    )

    moj: Optional[MojExtension] = Field(
        default=None, description='Environment-level extensions for MOJ packaging.'
    )

    domjudge: Optional[DomjudgeExtension] = Field(
        default=None,
        description='Environment-level extensions for DOMjudge tooling.',
    )


class LanguageExtensions(BaseModel):
    boca: Optional[BocaLanguageExtension] = Field(
        default=None, description='Language-level extensions for BOCA packaging.'
    )

    moj: Optional[MojLanguageExtension] = Field(
        default=None, description='Language-level extensions for MOJ packaging.'
    )

    polygon: Optional[PolygonLanguageExtension] = Field(
        default=None, description='Language-level extensions for Polygon packaging.'
    )

    domjudge: Optional[DomjudgeLanguageExtension] = Field(
        default=None, description='Language-level extensions for DOMjudge tooling.'
    )
