from typing import List, Optional

from pydantic import BaseModel

from rbx.box.environment import LanguageGroup, LanguageGroupFallback


class ResolvedGroup(BaseModel):
    languages: List[str]
    whenEmpty: Optional[LanguageGroupFallback] = None


def build_partition(
    env_groups: List[LanguageGroup],
    all_languages: List[str],
) -> List[ResolvedGroup]:
    """Build a disjoint partition: explicit env groups first (in order), then an
    implicit singleton for every language not covered by an explicit group."""
    grouped: set[str] = set()
    result: List[ResolvedGroup] = []
    for group in env_groups:
        result.append(
            ResolvedGroup(languages=list(group.languages), whenEmpty=group.whenEmpty)
        )
        grouped.update(group.languages)
    for lang in all_languages:
        if lang not in grouped:
            result.append(ResolvedGroup(languages=[lang]))
            grouped.add(lang)
    return result
