"""Smoke test: load_yaml_model surfaces YamlValidationError end-to-end."""

from __future__ import annotations

import pathlib

import pytest

from rbx.box.package import (
    find_problem_package,
    find_problem_package_or_die,
    get_expanded_vars_for_group,
)
from rbx.box.yaml_validation import YamlValidationError

_PKG_WITH_GROUP_VARS = """
name: with-vars
timeLimit: 1000
memoryLimit: 256
vars:
  AB:
    min: -200
    max: 200
testcases:
  - name: sub2
    vars:
      AB:
        min: 0
  - name: sub4
"""


def test_find_problem_package_raises_yaml_validation_error_on_bad_yml(
    cleandir: pathlib.Path,
):
    # Minimal broken problem.rbx.yml: timeLimit must be int, given a string.
    (cleandir / 'problem.rbx.yml').write_text(
        'name: bad-problem\ntimeLimit: "not a number"\nmemoryLimit: 256\n'
    )
    # The cache may already hold a None from prior tests; clear it.
    find_problem_package.cache_clear()

    with pytest.raises(YamlValidationError) as exc_info:
        find_problem_package(cleandir)

    rendered = str(exc_info.value)
    assert 'problem.rbx.yml' in rendered
    assert 'timeLimit' in rendered


def test_get_expanded_vars_for_group_matches_the_package_method(
    cleandir: pathlib.Path,
):
    (cleandir / 'problem.rbx.yml').write_text(_PKG_WITH_GROUP_VARS)
    pkg = find_problem_package_or_die(cleandir)

    for group_name in ['sub2', 'sub4', 'nope', None]:
        assert get_expanded_vars_for_group(
            group_name, cleandir
        ) == pkg.expanded_vars_for_group(group_name)

    assert get_expanded_vars_for_group('sub2', cleandir) == {
        'AB.min': 0,
        'AB.max': 200,
    }


def test_get_expanded_vars_for_group_is_cached_per_group(
    cleandir: pathlib.Path,
):
    (cleandir / 'problem.rbx.yml').write_text(_PKG_WITH_GROUP_VARS)

    # Expansion is far too costly to redo once per validated testcase, so a
    # repeated call must hand back the very same object, not an equal one.
    first = get_expanded_vars_for_group('sub2', cleandir)
    assert get_expanded_vars_for_group('sub2', cleandir) is first

    # ...but the cache is keyed per group, so a different group still resolves
    # to its own vars.
    assert get_expanded_vars_for_group('sub4', cleandir) == {
        'AB.min': -200,
        'AB.max': 200,
    }
