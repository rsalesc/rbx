"""Local lint tying `{{ asciinema(...) }}` references to committed casts."""

import dataclasses
import pathlib
import re
from typing import Iterator, List

# `{{ asciinema("name") }}` / `{{ asciinema("name", speed=1.5) }}`
_MACRO = re.compile(r'{{\s*asciinema\(\s*[\'"]([^\'"]+)[\'"]')
# asciinema.org url tokens are 25 chars of [A-Za-z0-9].
_LEGACY_ID = re.compile(r'^[A-Za-z0-9]{25}$')
_TODO = re.compile(r'<!--\s*TODO\(record\)')
_PLACEHOLDER = 'REPLACE_ME_CAST_ID'

# Design/plan documents are not part of the published site and routinely quote
# the macro while describing it. Scanning them yields nothing but noise.
EXCLUDED_DIRS = ('plans',)


@dataclasses.dataclass(frozen=True)
class Reference:
    target: str
    page: pathlib.Path
    line: int


@dataclasses.dataclass(frozen=True)
class Pending:
    page: pathlib.Path
    line: int
    detail: str


@dataclasses.dataclass(frozen=True)
class LinkReport:
    missing: List[Reference]
    orphans: List[str]
    legacy: List[str]
    pending: List[Pending]

    @property
    def ok(self) -> bool:
        return not (self.missing or self.orphans or self.pending)


def iter_pages(docs_root: pathlib.Path) -> Iterator[pathlib.Path]:
    for page in sorted(docs_root.rglob('*.md')):
        if page.relative_to(docs_root).parts[0] in EXCLUDED_DIRS:
            continue
        yield page


def iter_references(docs_root: pathlib.Path) -> Iterator[Reference]:
    for page in iter_pages(docs_root):
        for number, line in enumerate(page.read_text().splitlines(), start=1):
            for match in _MACRO.finditer(line):
                yield Reference(target=match.group(1), page=page, line=number)


def _iter_pending(docs_root: pathlib.Path) -> Iterator[Pending]:
    for page in iter_pages(docs_root):
        for number, line in enumerate(page.read_text().splitlines(), start=1):
            if _PLACEHOLDER in line:
                yield Pending(page, number, f'placeholder {_PLACEHOLDER}')
            if _TODO.search(line):
                yield Pending(page, number, 'unrecorded TODO(record) marker')


def check_links(docs_root: pathlib.Path, casts_root: pathlib.Path) -> LinkReport:
    available = {path.stem for path in casts_root.glob('*.cast')}

    missing: List[Reference] = []
    legacy: List[str] = []
    referenced = set()

    for reference in iter_references(docs_root):
        if reference.target == _PLACEHOLDER:
            continue
        if _LEGACY_ID.match(reference.target):
            legacy.append(reference.target)
            continue
        referenced.add(reference.target)
        if reference.target not in available:
            missing.append(reference)

    return LinkReport(
        missing=missing,
        orphans=sorted(available - referenced),
        legacy=legacy,
        pending=list(_iter_pending(docs_root)),
    )
