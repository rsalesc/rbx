"""Smoke test: load_yaml_model surfaces YamlValidationError end-to-end for contests."""

from __future__ import annotations

import pathlib

import pytest

from rbx.box.contest.contest_package import find_contest_package
from rbx.box.yaml_validation import YamlValidationError


def test_find_contest_package_raises_yaml_validation_error_on_bad_yml(
    cleandir: pathlib.Path,
):
    (cleandir / 'contest.rbx.yml').write_text(
        'name: my-contest\nproblems: "not-a-list"\n'
    )
    # The cache may already hold a None from prior tests; clear it.
    find_contest_package.cache_clear()

    with pytest.raises(YamlValidationError) as exc_info:
        find_contest_package(cleandir)

    rendered = str(exc_info.value)
    assert 'contest.rbx.yml' in rendered
    assert 'problems' in rendered
