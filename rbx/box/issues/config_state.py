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
from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.issue_codes import (
    CODE_SUBJECTS,
    IgnoreRule,
    IssueSubject,
    IssueThresholds,
    glob_matches,
)
from rbx.box.schema import Package, Solution
from rbx.box.statements.render import parse_jinja_block_names
from rbx.box.statements.schema import Statement, StatementType


class TestcaseSize(BaseModel):
    """One built testcase's input and answer, and how large each is."""

    # Not a test class, whatever its name says.
    __test__ = False

    input_path: pathlib.Path
    input_bytes: int
    answer_path: Optional[pathlib.Path] = None
    answer_bytes: int = 0


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
    # The built testset's size in bytes, inputs and expected answers apart.
    # None when nothing is built: a testset nobody generated has no size, and
    # reporting it as zero would read as a finding about the real one.
    testset_input_bytes: Optional[int] = None
    testset_answer_bytes: Optional[int] = None
    # Every built testcase's own sizes, in build order. Empty when unbuilt.
    testcase_sizes: List[TestcaseSize] = []
    # The environment's limits, handed in for the reason `RunState` takes them.
    thresholds: IssueThresholds = IssueThresholds()
    # The problem's own scoped `issues.ignore` rules whose `on` matches no
    # solution, file or group of the package. Collected here, against the
    # filesystem, so the detector stays pure.
    stale_ignore_rules: List[IgnoreRule] = []


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


def _file_size(path: Optional[pathlib.Path]) -> int:
    if path is None:
        return 0
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _measure_testcases(
    entries: List[GenerationTestcaseEntry],
) -> List[TestcaseSize]:
    """Each built testcase's sizes; empty when nothing is built.

    Only the entries whose input is actually on disk are measured, which is the
    same notion of "built" `rbx run` uses to decide what to run.
    """
    sizes: List[TestcaseSize] = []
    for entry in testcase_extractors.find_built_testcases(entries):
        copied_to = entry.metadata.copied_to
        sizes.append(
            TestcaseSize(
                input_path=copied_to.inputPath,
                input_bytes=_file_size(copied_to.inputPath),
                answer_path=copied_to.outputPath,
                answer_bytes=_file_size(copied_to.outputPath),
            )
        )
    return sizes


def _measure_testset(
    sizes: List[TestcaseSize],
) -> Tuple[Optional[int], Optional[int]]:
    """The built testset's input and answer bytes, or `(None, None)` unbuilt."""
    if not sizes:
        return None, None
    return (
        sum(size.input_bytes for size in sizes),
        sum(size.answer_bytes for size in sizes),
    )


def _is_stale(
    rule: IgnoreRule, solution_paths: List[str], group_names: List[str]
) -> bool:
    """Whether a scoped rule's `on` matches nothing the package has.

    A solution rule is held against the *declared* solutions, not the files on
    disk: a solution dropped from `solutions:` leaves its file behind, and a
    rule for it silences nothing all the same. Other files are looked for on
    disk, since no single list declares them all. Tests are never judged stale:
    which ones exist depends on the last build, and a rule written ahead of one
    is not a mistake.
    """
    if rule.on is None:
        return False
    subject = CODE_SUBJECTS.get(rule.code)
    if subject is IssueSubject.SOLUTION:
        return not any(glob_matches(rule.on, path) for path in solution_paths)
    if subject is IssueSubject.FILE:
        return not any(path.is_file() for path in pathlib.Path().glob(rule.on))
    if subject is IssueSubject.GROUP:
        return not any(glob_matches(rule.on, name) for name in group_names)
    return False


async def collect_config_state(
    pkg: Package,
    contest_languages: Optional[List[str]] = None,
    thresholds: Optional[IssueThresholds] = None,
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
    testcase_sizes = _measure_testcases(entries)
    input_bytes, answer_bytes = _measure_testset(testcase_sizes)

    solutions = package.get_solutions()
    solution_paths = [solution.path.as_posix() for solution in solutions]

    return ConfigState(
        solutions=solutions,
        has_validator=pkg.validator is not None,
        group_test_counts=group_test_counts,
        sample_count=sum(1 for entry in entries if entry.is_sample()),
        statement_languages=[st.language for st in statements],
        explanation_languages=explanation_languages,
        explanation_paths=explanation_paths,
        contest_languages=list(contest_languages or []),
        testset_input_bytes=input_bytes,
        testset_answer_bytes=answer_bytes,
        testcase_sizes=testcase_sizes,
        thresholds=thresholds or IssueThresholds(),
        # The problem's rules only: a contest rule is written for every problem
        # at once, and missing from most of them is what it is for.
        stale_ignore_rules=[
            rule
            for rule in pkg.issues.rules()
            if _is_stale(rule, solution_paths, list(group_test_counts))
        ],
    )
