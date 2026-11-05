import os
import pathlib
from typing import Optional
from unittest import mock

import pytest
from pydantic import ValidationError

from rbx.box import package_utils
from rbx.box.contest import contest_package
from rbx.box.contest.schema import Contest
from rbx.box.extensions import Extensions
from rbx.box.packaging.moj import settings
from rbx.box.packaging.moj.extension import (
    DEFAULT_FIGURE_SCALE,
    MojExtension,
    MojStatementExtension,
)
from rbx.box.schema import Package


def test_figure_scale_defaults_to_unset_so_lower_levels_can_inherit():
    assert MojExtension().figureScale is None
    assert MojStatementExtension().figureScale is None


@pytest.mark.parametrize('value', [0, -1, 'big'])
def test_figure_scale_must_be_a_positive_number(value):
    with pytest.raises(ValidationError):
        MojStatementExtension.model_validate({'figureScale': value})


def test_figure_scale_is_read_at_every_level():
    env = Extensions.model_validate({'moj': {'org': 'x', 'figureScale': 1.2}})
    contest = Contest.model_validate(
        {'name': 'contest', 'extensions': {'moj': {'figureScale': 1.3}}}
    )
    problem = Package.model_validate(
        {
            'name': 'problem',
            'timeLimit': 1000,
            'memoryLimit': 256,
            'extensions': {'moj': {'figureScale': 1.4}},
        }
    )
    assert env.moj is not None and env.moj.figureScale == 1.2
    assert contest.extensions is not None and contest.extensions.moj is not None
    assert contest.extensions.moj.figureScale == 1.3
    assert problem.extensions is not None and problem.extensions.moj is not None
    assert problem.extensions.moj.figureScale == 1.4


def test_the_org_is_an_environment_setting_only():
    with pytest.raises(ValidationError):
        MojStatementExtension.model_validate({'org': 'x'})


def test_merge_takes_the_lowest_level_that_sets_a_field():
    def ext(scale: Optional[float]):
        return MojStatementExtension.model_validate(
            {} if scale is None else {'figureScale': scale}
        )

    assert settings.merge(ext(1.2), ext(1.3), ext(1.4)).figureScale == 1.4
    assert settings.merge(ext(1.2), ext(1.3), ext(None)).figureScale == 1.3
    assert settings.merge(ext(1.2), None, None).figureScale == 1.2
    assert settings.merge(None, None, None).figureScale is None
    explicit_null = MojStatementExtension.model_validate({'figureScale': None})
    assert settings.merge(ext(1.2), explicit_null).figureScale == 1.2


def _clear_caches():
    contest_package.find_contest_yaml.cache_clear()
    contest_package.find_contest_package.cache_clear()
    package_utils.clear_package_cache()


@pytest.fixture
def problem_in_a_contest(tmp_path: pathlib.Path):
    def write(contest_scale=None, problem_scale=None):
        problem = 'name: problem-a\ntimeLimit: 1000\nmemoryLimit: 256\n'
        if problem_scale is not None:
            problem += f'extensions:\n  moj:\n    figureScale: {problem_scale}\n'
        contest = 'name: a-contest\nproblems:\n  - short_name: A\n'
        if contest_scale is not None:
            contest += f'extensions:\n  moj:\n    figureScale: {contest_scale}\n'
        (tmp_path / 'A').mkdir(exist_ok=True)
        (tmp_path / 'A' / 'problem.rbx.yml').write_text(problem)
        (tmp_path / 'contest.rbx.yml').write_text(contest)
        _clear_caches()

    cwd = os.getcwd()
    write()
    os.chdir(tmp_path / 'A')
    try:
        yield write
    finally:
        os.chdir(cwd)
        _clear_caches()


def _with_env(scale: Optional[float]):
    env = MojExtension() if scale is None else MojExtension(figureScale=scale)
    return mock.patch(
        'rbx.box.environment.get_extension',
        side_effect=lambda name, cls: env if name == 'moj' else None,
    )


def test_figure_scale_defaults_when_nothing_sets_it(problem_in_a_contest):
    with _with_env(None):
        assert settings.figure_scale() == DEFAULT_FIGURE_SCALE == 1.09


def test_figure_scale_comes_from_the_environment(problem_in_a_contest):
    with _with_env(1.5):
        assert settings.figure_scale() == 1.5


def test_the_contest_overrides_the_environment(problem_in_a_contest):
    problem_in_a_contest(contest_scale=1.25)
    with _with_env(1.5):
        assert settings.figure_scale() == 1.25


def test_the_problem_overrides_the_contest(problem_in_a_contest):
    problem_in_a_contest(contest_scale=1.25, problem_scale=1.0)
    with _with_env(1.5):
        assert settings.figure_scale() == 1.0
