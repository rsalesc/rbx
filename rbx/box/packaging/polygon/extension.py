from typing import Optional

from pydantic import BaseModel


class PolygonLanguageExtension(BaseModel):
    # Polygon language this rbx language matches with.
    polygonLanguage: Optional[str] = None
