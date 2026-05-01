"""Smoke test: load_yaml_model surfaces YamlValidationError end-to-end."""

from __future__ import annotations

import pathlib

import pytest

from rbx.box.package import find_problem_package
from rbx.box.yaml_validation import YamlValidationError


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
