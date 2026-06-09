import pathlib

import pytest

from rbx.box.statements import overlay
from rbx.box.statements.overlay import OverlayCollisionError


def _write(path: pathlib.Path, content: str = 'x') -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


class TestMirrorTree:
    def test_copies_nested_files_preserving_structure(self, tmp_path):
        src = tmp_path / 'src'
        _write(src / 'a.tex', 'a')
        _write(src / 'imgs' / 'fig.png', 'png')
        _write(src / 'inc' / 'deep' / 'part.tex', 'part')

        dest = tmp_path / 'dest'
        overlay.mirror_tree(src, dest)

        assert (dest / 'a.tex').read_text() == 'a'
        assert (dest / 'imgs' / 'fig.png').read_text() == 'png'
        assert (dest / 'inc' / 'deep' / 'part.tex').read_text() == 'part'

    def test_returns_relative_paths_copied(self, tmp_path):
        src = tmp_path / 'src'
        _write(src / 'a.tex')
        _write(src / 'imgs' / 'fig.png')

        dest = tmp_path / 'dest'
        copied = overlay.mirror_tree(src, dest)

        assert set(copied) == {
            pathlib.Path('a.tex'),
            pathlib.Path('imgs') / 'fig.png',
        }

    def test_missing_source_dir_is_noop(self, tmp_path):
        dest = tmp_path / 'dest'
        copied = overlay.mirror_tree(tmp_path / 'does-not-exist', dest)
        assert copied == []


class TestStageStandaloneOverlay:
    def test_merges_chrome_and_problem_into_one_root(self, tmp_path):
        chrome = tmp_path / 'chrome'
        _write(chrome / 'icpc.sty', 'sty')
        _write(chrome / 'logo.png', 'logo')

        problem = tmp_path / 'problem'
        _write(problem / 'statement.rbx.tex', 'tex')
        _write(problem / 'imgs' / 'fig.png', 'fig')

        root = tmp_path / 'root'
        overlay.stage_standalone_overlay(root, chrome_dir=chrome, problem_dir=problem)

        assert (root / 'icpc.sty').read_text() == 'sty'
        assert (root / 'logo.png').read_text() == 'logo'
        assert (root / 'statement.rbx.tex').read_text() == 'tex'
        assert (root / 'imgs' / 'fig.png').read_text() == 'fig'

    def test_errors_on_collision_between_chrome_and_problem(self, tmp_path):
        chrome = tmp_path / 'chrome'
        _write(chrome / 'common.tex', 'from-chrome')

        problem = tmp_path / 'problem'
        _write(problem / 'common.tex', 'from-problem')

        root = tmp_path / 'root'
        with pytest.raises(OverlayCollisionError):
            overlay.stage_standalone_overlay(
                root, chrome_dir=chrome, problem_dir=problem
            )

    def test_no_chrome_is_allowed(self, tmp_path):
        problem = tmp_path / 'problem'
        _write(problem / 'statement.rbx.tex', 'tex')

        root = tmp_path / 'root'
        overlay.stage_standalone_overlay(root, chrome_dir=None, problem_dir=problem)
        assert (root / 'statement.rbx.tex').read_text() == 'tex'


class TestStageJoin:
    def test_isolates_problems_under_dot_problems(self, tmp_path):
        problem_a = tmp_path / 'a'
        _write(problem_a / 'statement.rbx.tex', 'A')
        _write(problem_a / 'fig.png', 'A-fig')

        problem_b = tmp_path / 'b'
        _write(problem_b / 'statement.rbx.tex', 'B')
        _write(problem_b / 'fig.png', 'B-fig')  # same name as A's asset

        root = tmp_path / 'root'
        dir_a = overlay.stage_join_problem(root, problem_a, 'A')
        dir_b = overlay.stage_join_problem(root, problem_b, 'B')

        # Same-named assets across problems must NOT collide.
        assert (dir_a / 'fig.png').read_text() == 'A-fig'
        assert (dir_b / 'fig.png').read_text() == 'B-fig'
        assert dir_a == root / '.problems' / 'A'
        assert dir_b == root / '.problems' / 'B'

    def test_chrome_overlaid_at_root(self, tmp_path):
        chrome = tmp_path / 'chrome'
        _write(chrome / 'icpc.sty', 'sty')

        root = tmp_path / 'root'
        overlay.stage_chrome(root, chrome)
        assert (root / 'icpc.sty').read_text() == 'sty'
