import os
import pathlib
from typing import Optional

import pydantic
import pytest

from rbx.box import presets
from rbx.box.presets.schema import PackageSymlink, PackageVariant, Preset

_PRESET = """---
name: "linker"
uri: "linker"
min_version: "2.0.0"
problem: "problem"
contest: "contest"
symlinks:
  problem:
    - path: "graders/rbx.h"
      target: "rbx.h"
    - path: "shared.txt"
      target: "data/shared.txt"
  contest:
    - path: "statements/logo.png"
      target: "assets/logo.png"
problemVariants:
  - id: grader
    path: "problem-grader"
    symlinks:
      - path: "shared.txt"
        target: "data/other.txt"
      - path: "stubs/rbx.h"
        target: "rbx.h"
"""

_PROBLEM_YML = """---
name: "template-problem"
timeLimit: 1000
memoryLimit: 256
"""

_CONTEST_YML = """---
name: "template-contest"
"""


def _write_preset(root: pathlib.Path) -> pathlib.Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'preset.rbx.yml').write_text(_PRESET)
    for inner in ('problem', 'problem-grader'):
        (root / inner).mkdir()
        (root / inner / 'problem.rbx.yml').write_text(_PROBLEM_YML)
        (root / inner / 'rbx.h').write_text('// header\n')
    # The template ships a regular file where the canonical link goes.
    (root / 'problem' / 'shared.txt').write_text('template copy\n')
    (root / 'contest').mkdir()
    (root / 'contest' / 'contest.rbx.yml').write_text(_CONTEST_YML)
    return root


def _install_problem(tmp_path: pathlib.Path, variant: Optional[str]) -> pathlib.Path:
    preset_root = _write_preset(tmp_path / 'preset')
    package_dir = tmp_path / 'package'
    package_dir.mkdir()
    presets.install_preset_from_dir(preset_root, package_dir / '.local.rbx')
    presets.install_problem(package_dir, variant=variant)
    return package_dir


class TestSchema:
    @pytest.mark.parametrize('field', ['path', 'target'])
    @pytest.mark.parametrize('value', ['/etc/passwd', '../outside.h'])
    def test_paths_must_stay_in_the_package(self, field: str, value: str):
        entry = {'path': 'graders/rbx.h', 'target': 'rbx.h', field: value}
        with pytest.raises(pydantic.ValidationError):
            PackageSymlink.model_validate(entry)

    def test_variant_entries_win_by_path(self):
        preset = Preset.model_validate(
            {
                'name': 'linker',
                'uri': 'linker',
                'symlinks': {
                    'problem': [
                        {'path': 'a.h', 'target': 'x.h'},
                        {'path': 'b.h', 'target': 'y.h'},
                    ]
                },
            }
        )
        variant = PackageVariant(
            id='v',
            path=pathlib.Path('problem-v'),
            symlinks=[
                PackageSymlink(path=pathlib.Path('b.h'), target=pathlib.Path('z.h')),
                PackageSymlink(path=pathlib.Path('c.h'), target=pathlib.Path('w.h')),
            ],
        )

        merged = preset.merged_symlinks(variant, is_contest=False)

        assert [(str(s.path), str(s.target)) for s in merged] == [
            ('a.h', 'x.h'),
            ('b.h', 'z.h'),
            ('c.h', 'w.h'),
        ]
        assert preset.merged_symlinks(None, is_contest=True) == []


class TestCreatedOnInstall:
    def test_canonical_problem_gets_the_shared_links(self, tmp_path):
        package_dir = _install_problem(tmp_path, variant=None)

        link = package_dir / 'graders' / 'rbx.h'
        assert link.is_symlink()
        assert os.readlink(link) == os.path.join('..', 'rbx.h')
        assert link.read_text() == '// header\n'

    def test_a_link_replaces_the_template_file_at_its_path(self, tmp_path):
        package_dir = _install_problem(tmp_path, variant=None)

        shared = package_dir / 'shared.txt'
        assert shared.is_symlink()
        assert os.readlink(shared) == os.path.join('data', 'shared.txt')

    def test_target_need_not_exist_yet(self, tmp_path):
        package_dir = _install_problem(tmp_path, variant=None)

        shared = package_dir / 'shared.txt'
        assert not shared.exists()  # dangling until data/shared.txt appears
        (package_dir / 'data').mkdir()
        (package_dir / 'data' / 'shared.txt').write_text('later\n')
        assert shared.read_text() == 'later\n'

    def test_variant_links_merge_over_the_shared_ones(self, tmp_path):
        package_dir = _install_problem(tmp_path, variant='grader')

        assert os.readlink(package_dir / 'graders' / 'rbx.h') == os.path.join(
            '..', 'rbx.h'
        )
        assert os.readlink(package_dir / 'shared.txt') == os.path.join(
            'data', 'other.txt'
        )
        assert os.readlink(package_dir / 'stubs' / 'rbx.h') == os.path.join(
            '..', 'rbx.h'
        )

    def test_contest_gets_the_contest_links(self, tmp_path):
        preset_root = _write_preset(tmp_path / 'preset')
        package_dir = tmp_path / 'contest'
        package_dir.mkdir()
        presets.install_preset_from_dir(preset_root, package_dir / '.local.rbx')

        presets.install_contest(package_dir)

        logo = package_dir / 'statements' / 'logo.png'
        assert os.readlink(logo) == os.path.join('..', 'assets', 'logo.png')
        assert not (package_dir / 'graders').exists()
