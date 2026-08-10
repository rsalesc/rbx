import pathlib
import re
from typing import Iterable

from rbx.box import linting

_ANSI = re.compile(r'\x1b\[[0-9;]*m')


def _plain(captured: str) -> str:
    """Console output without rich's styling, so assertions can match spans of
    text that the highlighter breaks up with escape codes."""
    return _ANSI.sub('', captured)


def _preset_with_dirs(
    root: pathlib.Path, body: str, dirs: Iterable[str]
) -> pathlib.Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'preset.rbx.yml').write_text(body)
    for inner in dirs:
        (root / inner).mkdir(parents=True, exist_ok=True)
    return root


class TestLintingCoversVariants:
    """`rbx fix` on a preset must format every template's package yaml, not just
    the canonical one."""

    UNFORMATTED = "name: 'template-problem'\n"
    UNFORMATTED_CONTEST = "name: 'template-contest'\nproblems: []\n"

    def _assert_formatted(self, path: pathlib.Path):
        text = path.read_text()
        assert text.startswith('---')
        assert "'" not in text

    def test_formats_problem_variants(self, tmp_path):
        root = _preset_with_dirs(
            tmp_path / 'preset',
            """---
name: "with-variant"
uri: "test/with-variant"
min_version: "1.0.0"
problem: "problem"
problemVariants:
  - id: interactive
    path: "problem-interactive"
""",
            ['problem', 'problem-interactive'],
        )
        (root / 'problem' / 'problem.rbx.yml').write_text(self.UNFORMATTED)
        (root / 'problem-interactive' / 'problem.rbx.yml').write_text(self.UNFORMATTED)

        linting.fix_package(root)

        self._assert_formatted(root / 'problem' / 'problem.rbx.yml')
        self._assert_formatted(root / 'problem-interactive' / 'problem.rbx.yml')

    def test_formats_contest_variants(self, tmp_path):
        root = _preset_with_dirs(
            tmp_path / 'preset',
            """---
name: "with-variant"
uri: "test/with-variant"
min_version: "1.0.0"
contest: "contest"
contestVariants:
  - id: div1
    path: "contest-div1"
""",
            ['contest', 'contest-div1'],
        )
        (root / 'contest' / 'contest.rbx.yml').write_text(self.UNFORMATTED_CONTEST)
        (root / 'contest-div1' / 'contest.rbx.yml').write_text(self.UNFORMATTED_CONTEST)

        linting.fix_package(root)

        self._assert_formatted(root / 'contest' / 'contest.rbx.yml')
        self._assert_formatted(root / 'contest-div1' / 'contest.rbx.yml')

    def test_template_without_package_yaml_does_not_stop_the_others(self, tmp_path):
        root = _preset_with_dirs(
            tmp_path / 'preset',
            """---
name: "with-variant"
uri: "test/with-variant"
min_version: "1.0.0"
problem: "problem"
problemVariants:
  - id: empty
    path: "problem-empty"
  - id: interactive
    path: "problem-interactive"
""",
            ['problem', 'problem-empty', 'problem-interactive'],
        )
        (root / 'problem' / 'problem.rbx.yml').write_text(self.UNFORMATTED)
        (root / 'problem-interactive' / 'problem.rbx.yml').write_text(self.UNFORMATTED)

        linting.fix_package(root)

        self._assert_formatted(root / 'problem-interactive' / 'problem.rbx.yml')

    def test_contest_template_without_package_yaml_does_not_stop_the_others(
        self, tmp_path
    ):
        root = _preset_with_dirs(
            tmp_path / 'preset',
            """---
name: "with-variant"
uri: "test/with-variant"
min_version: "1.0.0"
contest: "contest"
contestVariants:
  - id: div1
    path: "contest-div1"
""",
            ['contest', 'contest-div1'],
        )
        # The canonical contest template exists but carries no contest.rbx.yml.
        (root / 'contest-div1' / 'contest.rbx.yml').write_text(self.UNFORMATTED_CONTEST)

        linting.fix_package(root)

        self._assert_formatted(root / 'contest-div1' / 'contest.rbx.yml')


_UNFORMATTED_ANCESTOR = "name: 'ancestor-problem'\ntimeLimit: 1000\n"


class TestLintingStaysInsideThePreset:
    """A preset template that carries no package yaml must not make `fix_package`
    escape the preset.

    `fix_package` -- and the `is_*_package` checks it starts with -- resolve
    through `find_package`, which walks UP the directory tree and does not stop
    at `preset.rbx.yml` unless asked to (`consider_presets`). So recursing into
    a template directory that holds no `contest.rbx.yml` used to resolve to
    whatever unrelated package sat around the preset, and reformat that one.
    """

    def _ancestor_package(self, tmp_path: pathlib.Path) -> pathlib.Path:
        """An unrelated problem package, deliberately unformatted (no `---`
        header, single-quoted values) so that reformatting it is observable
        byte-for-byte."""
        ancestor = tmp_path / 'ancestor'
        ancestor.mkdir(parents=True, exist_ok=True)
        (ancestor / 'problem.rbx.yml').write_text(_UNFORMATTED_ANCESTOR)
        return ancestor

    def test_does_not_reformat_the_package_above_the_preset(self, tmp_path):
        ancestor = self._ancestor_package(tmp_path)
        # The declared directory exists but holds no `contest.rbx.yml`, so
        # recursing into it would resolve, via `find_package`'s walk up the tree,
        # to the unrelated package above the preset.
        root = _preset_with_dirs(
            ancestor / 'preset',
            """---
name: "escaping"
uri: "test/escaping"
min_version: "1.0.0"
contest: "contest"
""",
            ['contest'],
        )

        linting.fix_package(root)

        assert (ancestor / 'problem.rbx.yml').read_text() == _UNFORMATTED_ANCESTOR

    def test_does_not_reformat_an_unrelated_package_beside_the_preset(self, tmp_path):
        ancestor = self._ancestor_package(tmp_path)
        # Same hazard reached through a *variant* declaration, and landing on a
        # package that merely sits beside the preset rather than above it. The
        # declaration itself is relative and contained -- the schema would reject
        # a `../unrelated` outright -- so the escape is smuggled in as a symlink,
        # which only `resolve_template`'s real-path check can see.
        sibling = ancestor / 'unrelated'
        sibling.mkdir()
        (sibling / 'problem.rbx.yml').write_text(_UNFORMATTED_ANCESTOR)
        root = _preset_with_dirs(
            ancestor / 'preset',
            """---
name: "escaping"
uri: "test/escaping"
min_version: "1.0.0"
contest: "contest"
contestVariants:
  - id: div1
    path: "unrelated"
""",
            ['contest'],
        )
        (root / 'unrelated').symlink_to(sibling, target_is_directory=True)
        (root / 'contest' / 'contest.rbx.yml').write_text(
            "name: 'template-contest'\nproblems: []\n"
        )

        linting.fix_package(root)

        assert (sibling / 'problem.rbx.yml').read_text() == _UNFORMATTED_ANCESTOR
        # The template that does carry a package yaml is still formatted.
        assert (root / 'contest' / 'contest.rbx.yml').read_text().startswith('---')


class TestMissingPackageYamlIsReported:
    """A template directory that exists but carries no package yaml is reported,
    so it gets the same signal as one whose directory is missing entirely."""

    def test_reports_problem_template_without_package_yaml(self, tmp_path, capsys):
        root = _preset_with_dirs(
            tmp_path / 'preset',
            """---
name: "with-variant"
uri: "test/with-variant"
min_version: "1.0.0"
problem: "problem"
""",
            ['problem'],
        )

        linting.fix_package(root)

        out = _plain(capsys.readouterr().out)
        assert str(root / 'problem') in out
        assert 'problem.rbx.yml' in out
        assert 'skipping it' in out

    def test_reports_contest_template_without_package_yaml(self, tmp_path, capsys):
        root = _preset_with_dirs(
            tmp_path / 'preset',
            """---
name: "with-variant"
uri: "test/with-variant"
min_version: "1.0.0"
contest: "contest"
""",
            ['contest'],
        )

        linting.fix_package(root)

        out = _plain(capsys.readouterr().out)
        assert str(root / 'contest') in out
        assert 'contest.rbx.yml' in out
        assert 'skipping it' in out
