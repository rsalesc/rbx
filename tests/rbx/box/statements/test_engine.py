import pathlib

import pytest

from rbx.box.statements import engine
from rbx.box.statements.overlay import OverlayCollisionError


def _write(path: pathlib.Path, content: str = 'x') -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


class TestRelativizeTemplate:
    def test_template_under_chrome_dir_is_referenced_relative(self, tmp_path):
        contest_root = tmp_path / 'contest'
        chrome_dir = contest_root / 'statements'
        _write(chrome_dir / 'tpl.rbx.tex', 'T')
        overlay_root = tmp_path / 'overlay'
        overlay_root.mkdir()

        rel = engine.relativize_template(
            contest_root,
            chrome_dir,
            pathlib.Path('statements/tpl.rbx.tex'),
            overlay_root,
        )
        assert rel == 'tpl.rbx.tex'

    def test_template_outside_chrome_is_copied_to_root(self, tmp_path):
        contest_root = tmp_path / 'contest'
        chrome_dir = contest_root / 'statements'
        chrome_dir.mkdir(parents=True)
        _write(contest_root / 'shared' / 'tpl.rbx.tex', 'OUTSIDE')
        overlay_root = tmp_path / 'overlay'
        overlay_root.mkdir()

        rel = engine.relativize_template(
            contest_root,
            chrome_dir,
            pathlib.Path('shared/tpl.rbx.tex'),
            overlay_root,
        )
        assert rel == 'tpl.rbx.tex'
        assert (overlay_root / 'tpl.rbx.tex').read_text() == 'OUTSIDE'

    def test_outside_template_basename_collision_errors(self, tmp_path):
        contest_root = tmp_path / 'contest'
        chrome_dir = contest_root / 'statements'
        chrome_dir.mkdir(parents=True)
        _write(contest_root / 'shared' / 'tpl.rbx.tex', 'OUTSIDE')
        overlay_root = tmp_path / 'overlay'
        overlay_root.mkdir()
        _write(overlay_root / 'tpl.rbx.tex', 'EXISTING CHROME ASSET')

        with pytest.raises(OverlayCollisionError):
            engine.relativize_template(
                contest_root,
                chrome_dir,
                pathlib.Path('shared/tpl.rbx.tex'),
                overlay_root,
            )
