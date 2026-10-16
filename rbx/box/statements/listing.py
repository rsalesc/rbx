"""What a package's statement entries resolve to: `rbx statements ls` and
`rbx contest statements ls`.

A statement entry is not a file until rbx has resolved it: `language: '*'`
stands for one entry per language of the effective `languages:` list (which a
problem may inherit from its contest, through any number of `!include`s), a
concrete entry overrides the wildcard one with its key, and `extends` fills in
the file of an entry that names none. This module answers with the resolved
entries, so a client never has to re-derive any of that.

It also answers with the `sources`: every YAML file the answer was read from.
A client that caches the listing invalidates it on a change to any of them --
notably a contest file or an included fragment, which a problem's own
`problem.rbx.yml` gives no sign of.

Read-only by construction, like `rbx vars`: it loads YAML and touches nothing
else, because the VS Code extension spawns it while the setter edits.
"""

import pathlib
from typing import Iterable, List, Literal, Optional, Set

from pydantic import BaseModel

from rbx import utils
from rbx.box import package
from rbx.box.contest.contest_package import (
    discover_contest_variants,
    find_contest_root,
)
from rbx.box.contest.schema import Contest
from rbx.box.schema import Package
from rbx.box.statements.schema import BaseStatement
from rbx.box.yaml_validation import load_yaml_model_with_sources

# Bump when a change would make an older reader misread the listing.
LISTING_VERSION = 1

ListedKind = Literal['statement', 'tutorial', 'document']


class ListedStatement(BaseModel):
    kind: ListedKind
    language: str
    variant: str
    type: str
    # Absolute. `None` only for an entry rbx itself would refuse to build.
    file: Optional[str] = None
    # Contest entries only: the entry's `name`, and the id of the contest
    # variant that declares it (`None` for the canonical `contest.rbx.yml`).
    name: Optional[str] = None
    contest: Optional[str] = None


class StatementListing(BaseModel):
    version: int = LISTING_VERSION
    scope: Literal['problem', 'contest']
    root: str
    statements: List[ListedStatement]
    sources: List[str]


def _listed(
    statements: Iterable[BaseStatement],
    kind: ListedKind,
    root: pathlib.Path,
    contest: Optional[str] = None,
) -> List[ListedStatement]:
    return [
        ListedStatement(
            kind=kind,
            language=st.language,
            variant=st.variant,
            type=st.type.value,
            file=None if st.file is None else str(utils.abspath(root / st.file)),
            name=getattr(st, 'name', None),
            contest=contest,
        )
        for st in statements
    ]


def _contest_files(contest_root: pathlib.Path) -> List[pathlib.Path]:
    """The canonical contest file, then every variant beside it.

    The canonical is named even when it is a dispatcher, which
    `discover_contest_variants` leaves out: flipping `use_variants` changes
    what the variants resolve to.
    """
    canonical = contest_root / 'contest.rbx.yml'
    files = [canonical] if canonical.is_file() else []
    for path in discover_contest_variants(contest_root).values():
        if path not in files:
            files.append(path)
    return files


def _contest_sources(contest_root: pathlib.Path) -> Set[pathlib.Path]:
    sources: Set[pathlib.Path] = set()
    for path in _contest_files(contest_root):
        sources |= load_yaml_model_with_sources(path, Contest)[1]
    return sources


def _sorted(sources: Set[pathlib.Path]) -> List[str]:
    return sorted(str(utils.abspath(path)) for path in sources)


def problem_listing(root: pathlib.Path = pathlib.Path()) -> StatementListing:
    """The statements and tutorials of the problem at `root`, resolved."""
    pkg = package.find_problem_package_or_die(root)
    problem_yaml = package.find_problem_yaml(root)
    assert problem_yaml is not None
    package_root = utils.abspath(problem_yaml.parent)

    _, sources = load_yaml_model_with_sources(problem_yaml, Package)
    # The effective `languages:` may be the contest's. Every contest file is
    # named, not just the selected one: which one is selected is a matter of
    # `-C` or `RBX_CONTEST`, and neither reaches a cached answer.
    contest_root = find_contest_root(package_root)
    if contest_root is not None:
        sources |= _contest_sources(contest_root)

    return StatementListing(
        scope='problem',
        root=str(package_root),
        statements=_listed(pkg.expanded_statements, 'statement', package_root)
        + _listed(pkg.expanded_tutorials, 'tutorial', package_root),
        sources=_sorted(sources),
    )


def contest_listing(contest_root: pathlib.Path) -> StatementListing:
    """The statements, tutorials and documents of every contest at
    `contest_root` -- the canonical one and each variant -- resolved."""
    contest_root = utils.abspath(contest_root)
    statements: List[ListedStatement] = []
    sources: Set[pathlib.Path] = set()
    for variant_id, path in discover_contest_variants(contest_root).items():
        contest, read = load_yaml_model_with_sources(path, Contest)
        sources |= read
        statements += _listed(
            contest.expanded_statements, 'statement', contest_root, variant_id
        )
        statements += _listed(
            contest.expanded_tutorials, 'tutorial', contest_root, variant_id
        )
        statements += _listed(
            contest.expanded_documents, 'document', contest_root, variant_id
        )
    sources |= _contest_sources(contest_root)
    return StatementListing(
        scope='contest',
        root=str(contest_root),
        statements=statements,
        sources=_sorted(sources),
    )


def print_listing(listing: StatementListing) -> None:
    """The human form: one line per entry, its file relative to the root."""
    import rich.markup

    from rbx import console

    root = pathlib.Path(listing.root)
    if not listing.statements:
        console.console.print('[warning]No statements declared.[/warning]')
        return
    for st in listing.statements:
        file = '-' if st.file is None else str(_relative(pathlib.Path(st.file), root))
        label = st.kind if st.name is None else f'{st.kind} {st.name}'
        if st.contest is not None:
            label = f'{label} (contest {st.contest})'
        console.console.print(
            f'[item]{rich.markup.escape(label)}[/item] '
            f'{st.language}/{rich.markup.escape(st.variant)} '
            f'[info]{st.type}[/info] {rich.markup.escape(file)}',
            highlight=False,
        )


def _relative(path: pathlib.Path, root: pathlib.Path) -> pathlib.Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return path
