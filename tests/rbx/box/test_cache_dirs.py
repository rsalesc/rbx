"""Tests for the rbx cache directory naming (issue #306: .box -> .rbx)."""

from __future__ import annotations

import pathlib

from rbx.box import package
from rbx.box.package import find_problem_yaml
from rbx.config import CACHE_DIR_NAME


def test_problem_cache_path_uses_rbx_dir(cleandir: pathlib.Path):
    (cleandir / 'problem.rbx.yml').write_text(
        'name: cache-dir-problem\ntimeLimit: 1000\nmemoryLimit: 256\n'
    )
    find_problem_yaml.cache_clear()
    package.get_problem_cache_path.cache_clear()

    cache_path = package.get_problem_cache_path(cleandir)

    assert cache_path.name == CACHE_DIR_NAME
    assert cache_path.parent == cleandir
