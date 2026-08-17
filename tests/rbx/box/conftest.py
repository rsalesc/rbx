import os
import pathlib
import subprocess
from collections.abc import Iterator
from typing import Dict, List, Optional
from unittest.mock import patch

import pytest

from rbx import testing_utils
from rbx.box import package, setter_config
from rbx.box.environment import VerificationLevel
from rbx.box.generation_schema import GenerationMetadata, GenerationTestcaseEntry
from rbx.box.schema import ScoreType, Solution, Testcase
from rbx.box.solutions import (
    GroupSkeleton,
    SolutionReportSkeleton,
    SolutionSkeleton,
)
from rbx.box.statements.latex import LatexResult
from rbx.box.testcase_schema import TestcaseEntry
from rbx.box.testing import testing_package
from rbx.config import CACHE_DIR_NAME, LEGACY_CACHE_DIR_NAME
from rbx.grading.limits import Limits
from rbx.grading.steps import (
    CheckerResult,
    Evaluation,
    Outcome,
    TestcaseIO,
    TestcaseLog,
)
from rbx.utils import copytree_honoring_gitignore


@pytest.fixture(scope='session')
def pkg_cder(tmp_path_factory):
    class PkgCder:
        def __init__(self, pkg_dir: pathlib.Path):
            self.pkg_dir = pkg_dir

        def __enter__(self):
            self.old_cwd = pathlib.Path.cwd()
            self.old_temp_dir = package.TEMP_DIR
            package.TEMP_DIR = tmp_path_factory.mktemp('tmp')
            os.chdir(self.pkg_dir)

        def __exit__(self, exc_type, exc_value, traceback):
            os.chdir(self.old_cwd)
            package.TEMP_DIR = self.old_temp_dir

    yield PkgCder


@pytest.fixture
def pkg_cleandir(cleandir: pathlib.Path, pkg_cder) -> Iterator[pathlib.Path]:
    pkgdir = cleandir / 'pkg'
    pkgdir.mkdir(exist_ok=True, parents=True)
    with pkg_cder(pkgdir.absolute()):
        yield pkgdir.absolute()


@pytest.fixture
def pkg_from_testdata(
    request, testdata_path: pathlib.Path, pkg_cleandir: pathlib.Path, pkg_cder
) -> Iterator[pathlib.Path]:
    marker = request.node.get_closest_marker('test_pkg')
    if marker is None:
        raise ValueError('test_pkg marker not found')
    testdata = testdata_path / marker.args[0]
    copytree_honoring_gitignore(
        testdata,
        pkg_cleandir,
        extra_gitignore=f'{CACHE_DIR_NAME}\n{LEGACY_CACHE_DIR_NAME}\nbuild\n.limits/\n',
    )
    with pkg_cder(pkg_cleandir.absolute()):
        testing_utils.clear_all_functools_cache()
        yield pkg_cleandir


@pytest.fixture
def pkg_from_resources(
    request, resources_path: pathlib.Path, pkg_cleandir: pathlib.Path, pkg_cder
):
    marker = request.node.get_closest_marker('resource_pkg')
    if marker is None:
        raise ValueError('resource_pkg marker not found')
    testdata = resources_path / marker.args[0]
    copytree_honoring_gitignore(
        testdata,
        pkg_cleandir,
        extra_gitignore=f'{CACHE_DIR_NAME}/\n{LEGACY_CACHE_DIR_NAME}/\nbuild/\n',
    )
    with pkg_cder(pkg_cleandir.absolute()):
        testing_utils.clear_all_functools_cache()
        yield pkg_cleandir


@pytest.fixture(scope='session')
def testing_pkg_factory(tmp_path_factory):
    def new_testing_pkg(
        pkg_dir: Optional[pathlib.Path] = None,
    ) -> testing_package.TestingPackage:
        if pkg_dir is None:
            pkg_dir = tmp_path_factory.mktemp('pkg')
        return testing_package.TestingPackage(pkg_dir)

    return new_testing_pkg


@pytest.fixture
def testing_pkg(pkg_cleandir: pathlib.Path) -> Iterator[testing_package.TestingPackage]:
    with testing_package.TestingPackage(pkg_cleandir) as pkg:
        yield pkg


@pytest.fixture
def testing_pkg_from_testdata(
    pkg_from_testdata: pathlib.Path,
) -> Iterator[testing_package.TestingPackage]:
    with testing_package.TestingPackage(pkg_from_testdata) as pkg:
        yield pkg


@pytest.fixture(autouse=True, scope='session')
def precompilation_should_use_tmp_cache(monkeysession, tmp_path_factory):
    cache_dir = tmp_path_factory.mktemp('cache')
    monkeysession.setattr(
        'rbx.box.global_package.get_global_cache_dir_path',
        lambda: cache_dir / CACHE_DIR_NAME,
    )


@pytest.fixture(autouse=True, scope='session')
def mock_setter_config(mock_app_path):
    cfg = setter_config.get_setter_config()
    cfg.judging = setter_config.JudgingConfig(check_stack=False)
    setter_config.save_setter_config(cfg)


# Synthetic run skeletons and evaluations.
#
# Shared by every test that needs to feed `get_solution_outcome_report` (and
# whatever is built on top of it) without running a real package: building one
# in-memory is instant, deterministic, and does not need a compiler.


@pytest.fixture
def mock_limits():
    """Create mock limits for testing."""
    return Limits(time=1000, memory=256, profile=None, isDoubleTL=False)


def make_generation_entry(
    group: str, index: int, tmp_path: pathlib.Path
) -> GenerationTestcaseEntry:
    """Create a minimal GenerationTestcaseEntry for testing."""
    entry = TestcaseEntry(group=group, index=index)
    return GenerationTestcaseEntry(
        group_entry=entry,
        subgroup_entry=entry,
        metadata=GenerationMetadata(
            copied_to=Testcase(inputPath=tmp_path / f'{group}_{index}.in'),
        ),
    )


@pytest.fixture
def mock_skeleton(tmp_path, mock_limits):
    """Create a minimal skeleton for testing.

    Groups default to ``score=0``, so a POINTS-scoring test must pass
    ``scores_per_group`` or it will assert against ``maxScore == 0`` vacuously.
    """

    def _create_skeleton(
        solutions: List[Solution],
        num_entries: int = 5,
        entries_per_group: Optional[Dict[str, int]] = None,
        scores_per_group: Optional[Dict[str, int]] = None,
    ) -> SolutionReportSkeleton:
        if entries_per_group is None:
            entries_per_group = {'test': num_entries}
        entries = [
            make_generation_entry(group, i, tmp_path)
            for group, count in entries_per_group.items()
            for i in range(count)
        ]
        groups = [
            GroupSkeleton(
                name=group,
                score=(scores_per_group or {}).get(group, 0),
                deps=[],
                testcases=[
                    entry.metadata.copied_to
                    for entry in entries
                    if entry.group_entry.group == group
                ],
            )
            for group in entries_per_group
        ]
        return SolutionReportSkeleton(
            solutions=[
                SolutionSkeleton(**sol.model_dump(), runs_dir=tmp_path / f'run_{i}')
                for i, sol in enumerate(solutions)
            ],
            entries=entries,
            groups=groups,
            limits={'cpp': mock_limits},
            compiled_solutions={
                str(sol.path): f'digest_{i}' for i, sol in enumerate(solutions)
            },
            verification=VerificationLevel.FULL,
        )

    return _create_skeleton


def make_evaluation(
    outcome: Outcome,
    time_ms: Optional[int] = 100,
    memory_bytes: Optional[int] = 1024,
    message: str = '',
    no_tle_outcome: Optional[Outcome] = None,
    sanitizer_warnings: bool = False,
    testcase_index: int = 0,
) -> Evaluation:
    """Helper to create evaluation objects."""
    return Evaluation(
        result=CheckerResult(
            outcome=outcome,
            message=message,
            no_tle_outcome=no_tle_outcome,
            sanitizer_warnings=sanitizer_warnings,
        ),
        log=TestcaseLog(
            time=time_ms / 1000.0 if time_ms is not None else None,
            memory=memory_bytes,
        ),
        testcase=TestcaseIO(index=testcase_index),
    )


@pytest.fixture
def mock_binary_scoring():
    with patch('rbx.box.solutions.package.get_scoring', return_value=ScoreType.BINARY):
        yield


@pytest.fixture
def mock_points_scoring():
    # `outcomePerGroup` is only loadable under POINTS scoring (see
    # `Package.check_scoring_fields`), so every per-group test must run here and
    # not under `mock_binary_scoring`, which would be an impossible package.
    with patch('rbx.box.solutions.package.get_scoring', return_value=ScoreType.POINTS):
        yield


@pytest.fixture(autouse=True, scope='session')
def mock_pdflatex(monkeysession):
    monkeysession.setattr(
        'rbx.box.statements.latex.Latex.build_pdf',
        lambda *args, **kwargs: LatexResult(
            result=subprocess.CompletedProcess(
                args='', returncode=0, stdout=b'', stderr=b''
            ),
            pdf=b'',
        ),
    )
