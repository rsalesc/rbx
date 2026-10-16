"""What a problem or a contest is made of: `rbx assets` and `rbx contest assets`.

The VS Code extension's Assets view draws this listing and nothing else, so
which files belong to a package -- and as what -- is rbx's to say: globs are
expanded, `{lang}` statement templates are resolved (through
`statements.listing`), and every path comes back absolute.

Like `rbx statements ls`, the answer carries `sources`: every YAML file it was
read from, so a client that caches it knows when to drop it.

Read-only by construction: it loads YAML and stats files, nothing else.
"""

import contextlib
import pathlib
import sys
from typing import Any, Dict, Iterator, List, Literal, Optional, Set

from pydantic import BaseModel

from rbx import console, utils
from rbx.box import package
from rbx.box.contest.contest_package import (
    find_contest_root,
    find_contest_yaml,
)
from rbx.box.contest.schema import Contest
from rbx.box.schema import CodeItem, Package, TestcaseSubgroup
from rbx.box.statements import listing as statement_listing
from rbx.box.yaml_validation import load_yaml_model_with_sources

# Bump when a change would make an older reader misread the listing.
ASSET_LISTING_VERSION = 1

AssetCategory = Literal[
    'manifest',
    'statement',
    'solution',
    'generator',
    'checker',
    'interactor',
    'validator',
    'visualizer',
    'testplan',
    'manual_test',
]


class ListedAsset(BaseModel):
    category: AssetCategory
    # Absolute.
    path: str
    # Category-specific facts, structured: `outcome` for a solution, `group`
    # for a testplan or a manual test, `language`/`kind`/`type` for a
    # statement, `glob` for a globbed manual test.
    detail: Dict[str, Any] = {}


class ListedProblem(BaseModel):
    # The contest letter; `None` outside a contest.
    short_name: Optional[str] = None
    name: Optional[str] = None
    title: Optional[str] = None
    root: str
    # Set when the problem could not be loaded; `assets` is then empty.
    error: Optional[str] = None
    assets: List[ListedAsset] = []


class ListedContest(BaseModel):
    root: str
    manifest: str
    # The resolved variant id; `None` for the canonical contest.rbx.yml.
    variant: Optional[str] = None
    title: Optional[str] = None
    assets: List[ListedAsset] = []


class AssetListing(BaseModel):
    version: int = ASSET_LISTING_VERSION
    scope: Literal['problem', 'contest']
    contest: Optional[ListedContest] = None
    problems: List[ListedProblem]
    sources: List[str]


@contextlib.contextmanager
def console_to_stderr() -> Iterator[None]:
    """Keep stdout clean for `--json`: rbx reports a broken package through the
    console, which otherwise writes to stdout."""
    previous = console.console.file
    console.console.file = sys.stderr
    try:
        yield
    finally:
        console.console.file = previous


def _abs(root: pathlib.Path, path: pathlib.Path) -> str:
    return str(utils.abspath(root / path))


def _code_assets(
    category: AssetCategory,
    items: List[CodeItem],
    root: pathlib.Path,
    detail_of=None,
) -> List[ListedAsset]:
    res = []
    for item in package.get_globbed_code_items(list(items), root):
        if not (root / item.path).is_file():
            continue
        detail = detail_of(item) if detail_of is not None else {}
        res.append(
            ListedAsset(category=category, path=_abs(root, item.path), detail=detail)
        )
    return res


def _groups(pkg: Package) -> Iterator[tuple]:
    """(group name, subgroup) for every top-level group and its subgroups."""
    for group in pkg.testcases:
        yield group.name, group
        for subgroup in group.subgroups:
            yield f'{group.name}/{subgroup.name}', subgroup


def _test_assets(pkg: Package, root: pathlib.Path) -> List[ListedAsset]:
    res: List[ListedAsset] = []
    seen: Set[str] = set()

    def add(asset: ListedAsset):
        if asset.path in seen:
            return
        seen.add(asset.path)
        res.append(asset)

    for name, group in _groups(pkg):
        group: TestcaseSubgroup
        if group.generatorScript is not None:
            script = root / group.generatorScript.path
            if script.is_file():
                add(
                    ListedAsset(
                        category='testplan',
                        path=_abs(root, group.generatorScript.path),
                        detail={'group': name},
                    )
                )
        if group.testcaseGlob is not None:
            for file in sorted(root.glob(group.testcaseGlob)):
                if file.is_file():
                    add(
                        ListedAsset(
                            category='manual_test',
                            path=str(utils.abspath(file)),
                            detail={'group': name, 'glob': group.testcaseGlob},
                        )
                    )
        for testcase in group.testcases:
            if (root / testcase.inputPath).is_file():
                add(
                    ListedAsset(
                        category='manual_test',
                        path=_abs(root, testcase.inputPath),
                        detail={'group': name},
                    )
                )
    return res


def _statement_assets(root: pathlib.Path) -> List[ListedAsset]:
    res = []
    for st in statement_listing.problem_listing(root).statements:
        if st.file is None or not pathlib.Path(st.file).is_file():
            continue
        res.append(
            ListedAsset(
                category='statement',
                path=st.file,
                detail={
                    'kind': st.kind,
                    'language': st.language,
                    'variant': st.variant,
                    'type': st.type,
                },
            )
        )
    return res


def _problem_assets(pkg: Package, root: pathlib.Path) -> List[ListedAsset]:
    assets: List[ListedAsset] = [
        ListedAsset(
            category='manifest', path=_abs(root, pathlib.Path('problem.rbx.yml'))
        )
    ]
    assets += _statement_assets(root)
    assets += _code_assets(
        'solution',
        list(pkg.solutions),
        root,
        lambda sol: {'outcome': sol.outcome.name},
    )
    assets += _code_assets('generator', list(pkg.generators), root)
    if pkg.checker is not None:
        assets += _code_assets('checker', [pkg.checker], root)
    if pkg.interactor is not None:
        assets += _code_assets('interactor', [pkg.interactor], root)
    validators: List[CodeItem] = []
    if pkg.validator is not None:
        validators.append(pkg.validator)
    validators += pkg.extraValidators
    assets += _code_assets('validator', validators, root)
    if pkg.visualizer is not None:
        assets += _code_assets('visualizer', [pkg.visualizer], root)
    assets += _test_assets(pkg, root)
    return assets


def _dedup(assets: List[ListedAsset]) -> List[ListedAsset]:
    """One row per (category, file): a statement file serving several kinds or
    languages is still one file to open."""
    seen: Set[tuple] = set()
    res = []
    for asset in assets:
        key = (asset.category, asset.path)
        if key not in seen:
            seen.add(key)
            res.append(asset)
    return res


def _describe(e: BaseException) -> str:
    message = str(e).strip()
    if message and not message.isdigit():
        return message
    return 'Could not load problem.rbx.yml; run an rbx command in it for details.'


def _list_problem(
    root: pathlib.Path, short_name: Optional[str], sources: Set[pathlib.Path]
) -> ListedProblem:
    root = utils.abspath(root)
    problem = ListedProblem(short_name=short_name, root=str(root))
    yaml_path = root / 'problem.rbx.yml'
    sources.add(yaml_path)
    try:
        sources |= load_yaml_model_with_sources(yaml_path, Package)[1]
        pkg = package.find_problem_package_or_die(root)
        problem.name = pkg.name
        problem.title = next(iter(pkg.titles.values()), None)
        problem.assets = _dedup(_problem_assets(pkg, root))
    except (Exception, SystemExit) as e:
        # A broken problem must not take the rest of the contest down with it.
        problem.error = _describe(e)
    return problem


def _sorted(sources: Set[pathlib.Path]) -> List[str]:
    return sorted(str(utils.abspath(path)) for path in sources)


def problem_asset_listing(root: pathlib.Path = pathlib.Path()) -> AssetListing:
    sources: Set[pathlib.Path] = set()
    problem_yaml = package.find_problem_yaml(root)
    assert problem_yaml is not None
    package_root = utils.abspath(problem_yaml.parent)
    contest_root = find_contest_root(package_root)
    if contest_root is not None:
        sources |= statement_listing._contest_sources(contest_root)  # noqa: SLF001
    problem = _list_problem(package_root, None, sources)
    return AssetListing(scope='problem', problems=[problem], sources=_sorted(sources))


def contest_asset_listing(root: pathlib.Path = pathlib.Path()) -> AssetListing:
    """The selected contest (`-C` / `RBX_CONTEST`) and each of its problems."""
    contest_root = find_contest_root(utils.abspath(root))
    assert contest_root is not None
    contest_root = utils.abspath(contest_root)
    sources: Set[pathlib.Path] = statement_listing._contest_sources(contest_root)  # noqa: SLF001
    contest_yaml = find_contest_yaml(contest_root)
    if contest_yaml is None:
        # A dispatcher with nothing selected: no letters to show.
        return AssetListing(scope='contest', problems=[], sources=_sorted(sources))

    contest, read = load_yaml_model_with_sources(contest_yaml, Contest)
    sources |= read
    variant = (
        None
        if contest_yaml.name == 'contest.rbx.yml'
        else contest_yaml.name[len('contest.') : -len('.rbx.yml')]
    )

    contest_assets = [ListedAsset(category='manifest', path=str(contest_yaml))]
    for st in statement_listing.contest_listing(contest_root).statements:
        if st.contest != variant or st.file is None:
            continue
        if not pathlib.Path(st.file).is_file():
            continue
        contest_assets.append(
            ListedAsset(
                category='statement',
                path=st.file,
                detail={
                    'kind': st.kind,
                    'language': st.language,
                    'variant': st.variant,
                    'type': st.type,
                    'name': st.name,
                },
            )
        )

    problems = [
        _list_problem(
            contest_root / (problem.path or pathlib.Path(problem.short_name)),
            problem.short_name,
            sources,
        )
        for problem in contest.problems
    ]
    return AssetListing(
        scope='contest',
        contest=ListedContest(
            root=str(contest_root),
            manifest=str(contest_yaml),
            variant=variant,
            title=next(iter(contest.titles.values()), None)
            if getattr(contest, 'titles', None)
            else None,
            assets=_dedup(contest_assets),
        ),
        problems=problems,
        sources=_sorted(sources),
    )


def print_asset_listing(listing: AssetListing) -> None:
    """The human form: a tree of problems and their assets."""
    import rich.markup
    import rich.tree

    def relative(path: str, root: str) -> str:
        try:
            return str(pathlib.Path(path).relative_to(root))
        except ValueError:
            return path

    if listing.contest is not None:
        label = 'contest'
        if listing.contest.variant is not None:
            label += f' {listing.contest.variant}'
        tree = rich.tree.Tree(f'[item]{label}[/item]')
        for asset in listing.contest.assets:
            tree.add(
                f'[info]{asset.category}[/info] '
                f'{rich.markup.escape(relative(asset.path, listing.contest.root))}'
            )
    else:
        tree = rich.tree.Tree('[item]problem[/item]')

    for problem in listing.problems:
        label = problem.name or pathlib.Path(problem.root).name
        if problem.short_name is not None:
            label = f'{problem.short_name} · {label}'
        node = tree.add(f'[item]{rich.markup.escape(label)}[/item]')
        if problem.error is not None:
            node.add(f'[error]{rich.markup.escape(problem.error)}[/error]')
            continue
        for asset in problem.assets:
            node.add(
                f'[info]{asset.category}[/info] '
                f'{rich.markup.escape(relative(asset.path, problem.root))}'
            )
    console.console.print(tree)
