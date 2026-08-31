"""What the *package* says, as the config detectors need it.

The mirror of `run_state`, and deliberately not a `Package`: a detector is handed
counts, names and language lists that have already been extracted, so it stays a
pure function testable against a state built by hand. `run_state`'s promise --
that it reads `.rbx/runs` and nothing else, loads no package and is instant --
is untouched, because these inputs live here instead of being bolted onto it.

Collecting a state is the impure half, and it lives here rather than among the
detectors so the seam stays visible: everything below `collect_config_state`
touches the filesystem, everything in `config_detectors` does not.
"""

import pathlib
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel

from rbx.box import package, testcase_extractors, testcase_sample_utils
from rbx.box.schema import Package, Solution
from rbx.box.statements.render import parse_jinja_block_names
from rbx.box.statements.schema import Statement, StatementType


class ConfigState(BaseModel):
    """Everything the config detectors read. No package, no paths to open."""

    solutions: List[Solution] = []
    has_validator: bool = False
    # Every group declared in `problem.rbx.yml`, mapped to how many tests it
    # actually generated. A group present with a 0 is the finding; a group
    # absent from the map was never declared.
    group_test_counts: Dict[str, int] = {}
    sample_count: int = 0
    # This problem's own statement languages, in declaration order.
    statement_languages: List[str] = []
    # Sample index -> the languages a `.rbx`-suffixed explanation blocks file
    # defines. Only samples with such a file appear at all: a language-agnostic
    # explanation covers every language by construction and has nothing to
    # check.
    explanation_languages: Dict[int, List[str]] = {}
    # Sample index -> that explanation file, so the issue can name it.
    explanation_paths: Dict[int, pathlib.Path] = {}
    # The languages the contest declares. Empty outside a contest, which is not
    # the same as "no languages wanted" -- the detector reading it says nothing
    # when it is empty rather than accusing a standalone problem of missing
    # every language in the world.
    contest_languages: List[str] = []


def _explanation_suffix_of(statement: Statement) -> str:
    """The on-disk suffix of a sample explanation for this statement's type.

    The same rule `build_statements._explanation_suffix` applies, restated rather
    than imported: `build_statements` pulls in the whole statement build graph,
    and `rbx summary` should not pay for it to answer a question about filenames.
    """
    return '.md' if statement.type == StatementType.rbxMarkdown else '.tex'


async def _collect_explanations(
    statements: List[Statement],
) -> Tuple[Dict[int, List[str]], Dict[int, pathlib.Path]]:
    """The languages each blocks-file explanation defines.

    Grouped by suffix because the suffix is a property of the statement *type*:
    an rbxMarkdown statement's explanations live in `.rbx.md` files and a rbxTeX
    statement's in `.rbx.tex` ones, so a problem shipping both has two
    independent sets of explanation files to check.
    """
    languages: Dict[int, List[str]] = {}
    paths: Dict[int, pathlib.Path] = {}
    root = package.find_problem()

    for suffix in sorted({_explanation_suffix_of(st) for st in statements}):
        samples = await testcase_sample_utils.get_statement_samples(
            explanation_suffix=suffix
        )
        for index, sample in enumerate(samples):
            if not sample.explanationFromBlocks or sample.explanationPath is None:
                continue
            try:
                names = parse_jinja_block_names(
                    root,
                    sample.explanationPath.read_bytes(),
                    mode='markdown' if suffix == '.md' else 'latex',
                )
            except Exception:
                # A template broken enough not to compile is a failure the
                # statement build reports properly, with a location and a
                # message. `rbx summary` is not the command that should die on
                # it, and recording "covers no languages" would be a lie that
                # reads as a finding.
                continue
            languages[index] = names
            paths[index] = sample.explanationPath
    return languages, paths


async def collect_config_state(
    pkg: Package,
    contest_languages: Optional[List[str]] = None,
) -> ConfigState:
    """Build a `ConfigState` from the package in the current directory."""
    entries = await testcase_extractors.extract_generation_testcases_from_groups()

    # Seeded from the declared groups, not from the entries: a group that
    # generated nothing has no entry to be counted, and it is the one this
    # exists to find.
    group_test_counts: Dict[str, int] = {group.name: 0 for group in pkg.testcases}
    for entry in entries:
        group = entry.group_entry.group
        group_test_counts[group] = group_test_counts.get(group, 0) + 1

    statements = pkg.expanded_statements
    explanation_languages, explanation_paths = await _collect_explanations(statements)

    return ConfigState(
        solutions=package.get_solutions(),
        has_validator=pkg.validator is not None,
        group_test_counts=group_test_counts,
        sample_count=sum(1 for entry in entries if entry.is_sample()),
        statement_languages=[st.language for st in statements],
        explanation_languages=explanation_languages,
        explanation_paths=explanation_paths,
        contest_languages=list(contest_languages or []),
    )
