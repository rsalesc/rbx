from typing import Optional

from pydantic import BaseModel, Field

from rbx.box.packaging.boca.extension import BocaExtension, BocaLanguageExtension
from rbx.box.packaging.polygon.extension import PolygonLanguageExtension


# Extension abstractions.
class Extensions(BaseModel):
    boca: Optional[BocaExtension] = Field(
        default=None, description='Environment-level extensions for BOCA packaging.'
    )


class LanguageExtensions(BaseModel):
    boca: Optional[BocaLanguageExtension] = Field(
        default=None, description='Language-level extensions for BOCA packaging.'
    )

    polygon: Optional[PolygonLanguageExtension] = Field(
        default=None, description='Language-level extensions for Polygon packaging.'
    )
