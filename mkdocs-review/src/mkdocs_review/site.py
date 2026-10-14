"""Map a built mkdocs site back to the markdown sources it came from."""

import dataclasses
import pathlib
import posixpath
from typing import Dict, Iterable, List, Optional, Set

import yaml

# Built HTML that is not a documentation page.
SKIP_PREFIXES = ('assets/', 'search/', '_mr/')
SKIP_PAGES = frozenset(['404.html'])


class _TolerantLoader(yaml.SafeLoader):
    """Loads mkdocs.yml without resolving `!ENV` or `!!python/...` tags."""


_TolerantLoader.add_multi_constructor('', lambda loader, suffix, node: None)


def load_mkdocs_config(text: str) -> dict:
    config = yaml.load(text, Loader=_TolerantLoader) or {}
    if not isinstance(config.get('docs_dir'), str):
        config['docs_dir'] = 'docs'
    if not isinstance(config.get('use_directory_urls'), bool):
        config['use_directory_urls'] = True
    return config


def dest_path(src: str, use_directory_urls: bool) -> str:
    """Where mkdocs writes the page built from `src` (relative to docs_dir)."""
    directory, name = posixpath.split(src)
    stem = posixpath.splitext(name)[0]
    if stem in ('index', 'README'):
        return posixpath.join(directory, 'index.html')
    if use_directory_urls:
        return posixpath.join(directory, stem, 'index.html')
    return posixpath.join(directory, f'{stem}.html')


def source_map(
    files: Iterable[str], docs_dir: str, use_directory_urls: bool
) -> Dict[str, str]:
    """Built page path -> repository path of its markdown source."""
    prefix = docs_dir.strip('/') + '/'
    result = {}
    for path in files:
        if path.startswith(prefix) and path.endswith('.md'):
            result[dest_path(path[len(prefix) :], use_directory_urls)] = path
    return result


def list_built_pages(site_dir: pathlib.Path) -> Set[str]:
    pages = set()
    for path in site_dir.rglob('*.html'):
        rel = path.relative_to(site_dir).as_posix()
        if rel in SKIP_PAGES or rel.startswith(SKIP_PREFIXES):
            continue
        pages.add(rel)
    return pages


@dataclasses.dataclass(frozen=True)
class Page:
    path: str
    base_source: Optional[str]
    head_source: Optional[str]
    in_base: bool
    in_head: bool

    def source(self, side: str) -> Optional[str]:
        return self.head_source if side == 'head' else self.base_source


def page_table(
    base_pages: Set[str],
    head_pages: Set[str],
    base_sources: Dict[str, str],
    head_sources: Dict[str, str],
) -> List[Page]:
    return [
        Page(
            path,
            base_sources.get(path) if path in base_pages else None,
            head_sources.get(path) if path in head_pages else None,
            path in base_pages,
            path in head_pages,
        )
        for path in sorted(base_pages | head_pages)
    ]
