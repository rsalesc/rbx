"""The provenance `rbx build` publishes about the testset it just built.

`build/tests` alone says what the testcases *are*; it says nothing about where
each one came from, whether a validator accepted it, or which constraints the
group ever hit. All of that is computed during a build and then dropped on the
floor -- the only place it ever reached disk is `.rbx/runs/skeleton.yml`, which
`rbx run` writes and `rbx build` does not.

This module writes `build/testset.yml`, the build's half of that record, for
readers that are not rbx itself (the VS Code extension, today).
"""

import pathlib
from typing import Dict, List, Optional, Set, Tuple

from pydantic import BaseModel

from rbx import console, utils
from rbx.box import package, visualizers
from rbx.box.fields import Vars
from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.schema import TaskType, Visualizer
from rbx.box.validators import (
    HitBounds,
    TestcaseValidationInfo,
    merge_hit_bounds_per_group,
)

MANIFEST_VERSION = 1


class TestsetGroup(BaseModel):
    name: str
    score: int = 0
    deps: List[str] = []
    subgroups: List[str] = []
    # The vars the group was actually validated against -- package vars with the
    # group's overrides already merged and expanded. A reader cannot redo this
    # merge, since expansion re-evaluates interpolated vars.
    vars: Vars = {}


class TestsetTestValidation(BaseModel):
    ok: bool = True
    validator: Optional[pathlib.Path] = None
    message: Optional[str] = None


class TestsetTestVisualization(BaseModel):
    input: Optional[pathlib.Path] = None
    output: Optional[pathlib.Path] = None


class TestsetTest(BaseModel):
    """Everything about one testcase that does not fit in its entry.

    Parallel to `entries` and keyed by group+index rather than folded into
    `GenerationTestcaseEntry`, because that model is also what `skeleton.yml`
    embeds: extending it would change the run's artifact for the benefit of one
    consumer of the build's.
    """

    group: str
    index: int
    validation: Optional[TestsetTestValidation] = None
    visualization: Optional[TestsetTestVisualization] = None
    # Stamped at dump time so a reader can size a testset without stat'ing
    # thousands of files.
    input_size: Optional[int] = None
    output_size: Optional[int] = None


class TestsetGroupValidation(BaseModel):
    group: str
    validator: Optional[pathlib.Path] = None
    bounds: HitBounds = {}


class TestsetManifest(BaseModel):
    version: int = MANIFEST_VERSION
    task_type: TaskType = TaskType.BATCH
    groups: List[TestsetGroup] = []
    # Dumped verbatim, in the same shape `skeleton.yml` uses, so a reader has
    # exactly one parser for both artifacts.
    entries: List[GenerationTestcaseEntry] = []
    tests: List[TestsetTest] = []
    # Absent entirely when the build did not validate (`-v0`, `--no-validate`).
    # An empty list would read as "nothing is covered", which is a much stronger
    # claim than "we did not look".
    validation: Optional[List[TestsetGroupValidation]] = None


def get_manifest_path(root: pathlib.Path = pathlib.Path()) -> pathlib.Path:
    return package.get_build_path(root) / 'testset.yml'


def _relpath(path: pathlib.Path) -> pathlib.Path:
    # Relative to the package root, not to the cwd: the reader resolves these
    # against the package it discovered, and a manifest is read from anywhere.
    return package.relpath(path, package.find_problem())


def _size_or_none(path: Optional[pathlib.Path]) -> Optional[int]:
    if path is None:
        return None
    try:
        return path.stat().st_size
    except OSError:
        return None


def _visualization_path(
    stem: Optional[pathlib.Path], visualizer: Optional[Visualizer]
) -> Optional[pathlib.Path]:
    if stem is None or visualizer is None:
        return None
    path = stem.with_suffix(visualizer.get_suffix())
    # `Visualizer.extension` is a free string and visualizers only run under
    # `--visualize`, so the manifest promises a path only for a file that is
    # actually sitting there.
    if not path.is_file():
        return None
    return _relpath(path)


def _visualization_for_entry(
    entry: GenerationTestcaseEntry,
) -> Optional[TestsetTestVisualization]:
    stems = visualizers.get_visualization_stems(entry.metadata.copied_to)
    input_path = _visualization_path(stems.input, entry.visualizer)
    # Same fallback `run_visualizers_for_entries` applies: a package with only
    # `visualizer` set uses it for both channels.
    output_path = _visualization_path(
        stems.output, entry.solution_visualizer or entry.visualizer
    )
    if input_path is None and output_path is None:
        return None
    return TestsetTestVisualization(input=input_path, output=output_path)


def _validation_by_testcase(
    infos: List[TestcaseValidationInfo],
) -> Dict[Tuple[str, int], TestsetTestValidation]:
    res: Dict[Tuple[str, int], TestsetTestValidation] = {}
    for info in infos:
        if info.testcase is None:
            continue
        key = (info.testcase.group, info.testcase.index)
        current = res.get(key)
        # A testcase can be seen by several validators (`extraValidators`). The
        # failing one is the interesting one, and the first failure is what the
        # report shows, so a recorded failure is never overwritten.
        if current is not None and not current.ok:
            continue
        if current is not None and info.ok:
            continue
        res[key] = TestsetTestValidation(
            ok=info.ok,
            validator=info.validator.path,
            # An accepted testcase carries `''`, not None, which the dump would
            # keep as an empty line rather than dropping.
            message=info.message or None,
        )
    return res


def _validator_per_group(
    infos: List[TestcaseValidationInfo],
) -> Dict[str, pathlib.Path]:
    res: Dict[str, pathlib.Path] = {}
    for info in infos:
        if info.testcase is None:
            continue
        res.setdefault(info.testcase.group, info.validator.path)
    return res


def _build_groups(group_names: Set[str]) -> List[TestsetGroup]:
    pkg = package.find_problem_package_or_die()
    return [
        TestsetGroup(
            name=group.name,
            score=group.score,
            deps=list(group.deps),
            subgroups=[subgroup.name for subgroup in group.subgroups],
            vars=dict(package.get_expanded_vars_for_group(group.name)),
        )
        for group in pkg.testcases
        if group.name in group_names
    ]


def build_manifest(
    entries: List[GenerationTestcaseEntry],
    validation_infos: Optional[List[TestcaseValidationInfo]],
) -> TestsetManifest:
    group_names = {entry.group_entry.group for entry in entries}

    validation_by_testcase = _validation_by_testcase(validation_infos or [])
    tests = []
    for entry in entries:
        testcase = entry.metadata.copied_to
        tests.append(
            TestsetTest(
                group=entry.group_entry.group,
                index=entry.group_entry.index,
                validation=validation_by_testcase.get(
                    (entry.group_entry.group, entry.group_entry.index)
                )
                if validation_infos is not None
                else None,
                visualization=_visualization_for_entry(entry),
                input_size=_size_or_none(testcase.inputPath),
                output_size=_size_or_none(testcase.outputPath),
            )
        )

    validation: Optional[List[TestsetGroupValidation]] = None
    if validation_infos is not None:
        validators_per_group = _validator_per_group(validation_infos)
        validation = [
            TestsetGroupValidation(
                group=group,
                validator=validators_per_group.get(group),
                bounds=bounds,
            )
            for group, bounds in merge_hit_bounds_per_group(validation_infos).items()
        ]

    return TestsetManifest(
        version=MANIFEST_VERSION,
        task_type=package.find_problem_package_or_die().type,
        groups=_build_groups(group_names),
        entries=list(entries),
        tests=tests,
        validation=validation,
    )


def write_manifest(
    entries: List[GenerationTestcaseEntry],
    validation_infos: Optional[List[TestcaseValidationInfo]],
) -> pathlib.Path:
    """Dump the manifest for the build that just finished, replacing any previous one.

    Never merged with what an earlier build left. `generate_testcases` opens
    every build by rmtree-ing the whole of `build/tests`, before it has even
    looked at the group filter, so after `rbx build --groups main` the other
    groups' testcases are genuinely gone from disk. Carrying their rows over
    would make the manifest assert testcases that no longer exist -- the one
    thing a reader of it may never be shown. A subset build's testset really is
    only those groups.
    """
    manifest = build_manifest(entries, validation_infos)

    path = get_manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(utils.model_to_yaml(manifest))
    return path


def write_manifest_or_warn(
    entries: List[GenerationTestcaseEntry],
    validation_infos: Optional[List[TestcaseValidationInfo]],
) -> None:
    """`write_manifest`, downgraded to a warning.

    The manifest is a convenience for external readers; nothing rbx itself does
    reads it back. Failing a build that produced perfectly good testcases over
    it would be a strictly worse trade.
    """
    try:
        write_manifest(entries, validation_infos)
    except Exception as e:
        console.console.print(
            f'[warning]Failed writing the testset manifest: {utils.escape_markup(str(e))}[/warning]'
        )
