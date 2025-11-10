from typing import Optional

from rbx.box.code import find_language_name, get_extension
from rbx.box.environment import get_language
from rbx.box.packaging.polygon.extension import PolygonLanguageExtension
from rbx.box.schema import CodeItem


def get_polygon_language_from_code_item(code_item: CodeItem) -> Optional[str]:
    language = find_language_name(code_item)
    language_extension = get_language(language).get_extension_or_default(
        'polygon', PolygonLanguageExtension
    )
    if language_extension.polygonLanguage:
        return language_extension.polygonLanguage
    ext = get_extension(code_item)
    if ext in ['cpp', 'cc']:
        return 'cpp.gcc13-64-winlibs-g++20'
    if ext in ['java']:
        return 'java21'
    return None
