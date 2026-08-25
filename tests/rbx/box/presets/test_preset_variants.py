import pathlib
import re
import shutil
from types import SimpleNamespace
from typing import Any, Iterable, Optional

import pytest
import questionary
import typer
from pydantic import ValidationError

from rbx.box import presets
from rbx.box.presets.lock_schema import PresetLock
from rbx.box.presets.schema import (
    Expansion,
    Libraries,
    Library,
    PackageVariant,
    Preset,
    ReplacementMode,
    TrackedAsset,
    Tracking,
    VariableExpansion,
)


def _preset(**kwargs: Any) -> Preset:
    # NOTE: `Preset` does not forbid extra fields, so a misspelled keyword here
    # is silently ignored and the assertion below would run against a default.
    base: dict = dict(name='my-preset', uri='owner/repo')
    base.update(kwargs)
    return Preset(**base)


class TestPackageVariant:
    def test_minimal_variant(self):
        variant = PackageVariant(
            id='interactive', path=pathlib.Path('problem-interactive')
        )
        assert variant.id == 'interactive'
        assert variant.description == ''
        assert variant.tracking == []
        assert variant.libraries == []
        assert variant.expansion == []

    @pytest.mark.parametrize('bad_id', ['1abc', 'has space', 'has.dot', '', 'a/b'])
    def test_rejects_malformed_id(self, bad_id):
        with pytest.raises(ValidationError):
            PackageVariant(id=bad_id, path=pathlib.Path('p'))

    def test_rejects_reserved_default_id(self):
        with pytest.raises(ValidationError, match='reserved'):
            PackageVariant(id='default', path=pathlib.Path('p'))

    @pytest.mark.parametrize('ok_id', ['default2', 'my-default', 'defaults'])
    def test_accepts_ids_merely_containing_default(self, ok_id):
        assert PackageVariant(id=ok_id, path=pathlib.Path('p')).id == ok_id

    def test_accepts_dashes_and_underscores(self):
        variant = PackageVariant(id='interactive-points_2', path=pathlib.Path('p'))
        assert variant.id == 'interactive-points_2'

    def test_constructs_nested_payload_from_dict(self):
        variant = PackageVariant(
            **{
                'id': 'interactive',
                'path': 'problem-interactive',
                'tracking': [{'path': 'interactor.cpp', 'symlink': True}],
                'libraries': [
                    {'name': 'testlib', 'source': 'a/b', 'dest': 'testlib.h'}
                ],
                'expansion': [{'needle': 'AUTHOR', 'prompt': 'Author?'}],
            }
        )

        assert variant.path == pathlib.Path('problem-interactive')

        assert variant.tracking == [
            TrackedAsset(path=pathlib.Path('interactor.cpp'), symlink=True)
        ]
        assert isinstance(variant.tracking[0], TrackedAsset)

        assert variant.libraries == [
            Library(name='testlib', source='a/b', dest=pathlib.Path('testlib.h'))
        ]
        assert isinstance(variant.libraries[0], Library)

        assert variant.expansion == [
            VariableExpansion(needle='AUTHOR', prompt='Author?')
        ]
        assert isinstance(variant.expansion[0], VariableExpansion)
        assert variant.expansion[0].replacement == ReplacementMode.PROMPT


class TestPresetVariants:
    def test_defaults_to_no_variants(self):
        preset = _preset(problem=pathlib.Path('problem'))
        assert preset.problemVariants == []
        assert preset.contestVariants == []

    def test_rejects_duplicate_variant_ids(self):
        with pytest.raises(
            ValidationError, match='duplicate variant id interactive in problemVariants'
        ):
            _preset(
                problem=pathlib.Path('problem'),
                problemVariants=[
                    PackageVariant(id='interactive', path=pathlib.Path('a')),
                    PackageVariant(id='interactive', path=pathlib.Path('b')),
                ],
            )

    def test_rejects_duplicate_contest_variant_ids(self):
        with pytest.raises(
            ValidationError, match='duplicate variant id div1 in contestVariants'
        ):
            _preset(
                contest=pathlib.Path('contest'),
                contestVariants=[
                    PackageVariant(id='div1', path=pathlib.Path('a')),
                    PackageVariant(id='div1', path=pathlib.Path('b')),
                ],
            )

    def test_same_id_allowed_across_kinds(self):
        preset = _preset(
            problem=pathlib.Path('problem'),
            contest=pathlib.Path('contest'),
            problemVariants=[PackageVariant(id='div1', path=pathlib.Path('a'))],
            contestVariants=[PackageVariant(id='div1', path=pathlib.Path('b'))],
        )
        assert preset.problemVariants[0].path != preset.contestVariants[0].path

    def test_find_variant_returns_none_for_unknown(self):
        preset = _preset(problem=pathlib.Path('problem'))
        assert preset.find_variant('nope', is_contest=False) is None

    def test_find_variant_is_scoped_by_kind(self):
        variant = PackageVariant(id='div1', path=pathlib.Path('a'))
        preset = _preset(
            problem=pathlib.Path('problem'),
            problemVariants=[variant],
        )
        assert preset.find_variant('div1', is_contest=False) == variant
        assert preset.find_variant('div1', is_contest=True) is None


class TestVariantMerging:
    def test_tracking_variant_entry_wins_over_shared(self):
        variant = PackageVariant(
            id='interactive',
            path=pathlib.Path('problem-interactive'),
            tracking=[
                TrackedAsset(path=pathlib.Path('shared.h'), symlink=True),
                TrackedAsset(path=pathlib.Path('interactor.cpp')),
            ],
        )
        preset = _preset(
            problem=pathlib.Path('problem'),
            tracking=Tracking(
                problem=[
                    TrackedAsset(path=pathlib.Path('.gitignore')),
                    TrackedAsset(path=pathlib.Path('shared.h'), symlink=False),
                ]
            ),
            problemVariants=[variant],
        )
        merged = preset.merged_tracking(variant, is_contest=False)
        # Shared order is preserved and variant-only entries are appended.
        assert [str(a.path) for a in merged] == [
            '.gitignore',
            'shared.h',
            'interactor.cpp',
        ]
        by_path = {str(a.path): a for a in merged}
        assert by_path['shared.h'].symlink is True

    def test_tracking_canonical_returns_shared_only(self):
        preset = _preset(
            problem=pathlib.Path('problem'),
            tracking=Tracking(problem=[TrackedAsset(path=pathlib.Path('.gitignore'))]),
            problemVariants=[
                PackageVariant(
                    id='interactive',
                    path=pathlib.Path('pi'),
                    tracking=[TrackedAsset(path=pathlib.Path('only-variant'))],
                )
            ],
        )
        merged = preset.merged_tracking(None, is_contest=False)
        assert [str(a.path) for a in merged] == ['.gitignore']

    def test_tracking_merges_contest_side_independently(self):
        variant = PackageVariant(
            id='div1',
            path=pathlib.Path('contest-div1'),
            tracking=[TrackedAsset(path=pathlib.Path('div1.tex'))],
        )
        preset = _preset(
            contest=pathlib.Path('contest'),
            tracking=Tracking(
                problem=[TrackedAsset(path=pathlib.Path('problem-only'))],
                contest=[TrackedAsset(path=pathlib.Path('contest-only'))],
            ),
            contestVariants=[variant],
        )
        merged = preset.merged_tracking(variant, is_contest=True)
        assert [str(a.path) for a in merged] == ['contest-only', 'div1.tex']

    def test_libraries_merge_by_name_variant_wins(self):
        shared = Library(name='testlib', source='a/b', dest=pathlib.Path('testlib.h'))
        other_shared = Library(name='jngen', source='e/f', dest=pathlib.Path('jngen.h'))
        override = Library(
            name='testlib', source='a/b', dest=pathlib.Path('testlib.h'), version='1.0'
        )
        extra = Library(name='interlib', source='c/d', dest=pathlib.Path('inter.h'))
        variant = PackageVariant(
            id='interactive',
            path=pathlib.Path('pi'),
            libraries=[override, extra],
        )
        preset = _preset(
            problem=pathlib.Path('problem'),
            libraries=Libraries(problem=[shared, other_shared]),
            problemVariants=[variant],
        )
        merged = preset.merged_libraries(variant, is_contest=False)
        assert [lib.name for lib in merged] == ['testlib', 'jngen', 'interlib']
        by_name = {lib.name: lib for lib in merged}
        assert by_name['testlib'].version == '1.0'
        assert by_name['jngen'] == other_shared

    def test_libraries_merge_contest_side_independently(self):
        problem_lib = Library(
            name='testlib', source='a/b', dest=pathlib.Path('testlib.h')
        )
        contest_lib = Library(name='jngen', source='e/f', dest=pathlib.Path('jngen.h'))
        variant_lib = Library(name='interlib', source='c/d', dest=pathlib.Path('i.h'))
        variant = PackageVariant(
            id='div1', path=pathlib.Path('contest-div1'), libraries=[variant_lib]
        )
        preset = _preset(
            contest=pathlib.Path('contest'),
            libraries=Libraries(problem=[problem_lib], contest=[contest_lib]),
            contestVariants=[variant],
        )
        merged = preset.merged_libraries(variant, is_contest=True)
        assert [lib.name for lib in merged] == ['jngen', 'interlib']

    def test_libraries_canonical_returns_shared_only(self):
        shared = Library(name='testlib', source='a/b', dest=pathlib.Path('testlib.h'))
        preset = _preset(
            problem=pathlib.Path('problem'),
            libraries=Libraries(problem=[shared]),
            problemVariants=[
                PackageVariant(
                    id='interactive',
                    path=pathlib.Path('pi'),
                    libraries=[
                        Library(
                            name='interlib', source='c/d', dest=pathlib.Path('inter.h')
                        )
                    ],
                )
            ],
        )
        assert preset.merged_libraries(None, is_contest=False) == [shared]

    def test_expansion_merges_by_needle(self):
        variant = PackageVariant(
            id='interactive',
            path=pathlib.Path('pi'),
            expansion=[
                VariableExpansion(needle='AUTHOR', prompt='Who wrote it?'),
                VariableExpansion(needle='JUDGE', prompt='Judge?'),
            ],
        )
        preset = _preset(
            problem=pathlib.Path('problem'),
            expansion=Expansion(
                problem=[
                    VariableExpansion(needle='AUTHOR', prompt='Author?'),
                    VariableExpansion(needle='TITLE', prompt='Title?'),
                ]
            ),
            problemVariants=[variant],
        )
        merged = preset.merged_expansion(variant, is_contest=False)
        assert [e.needle for e in merged] == ['AUTHOR', 'TITLE', 'JUDGE']
        assert merged[0].prompt == 'Who wrote it?'

    def test_expansion_merges_contest_side_independently(self):
        variant = PackageVariant(
            id='div1',
            path=pathlib.Path('contest-div1'),
            expansion=[VariableExpansion(needle='DIVISION', prompt='Division?')],
        )
        preset = _preset(
            contest=pathlib.Path('contest'),
            expansion=Expansion(
                problem=[VariableExpansion(needle='TITLE', prompt='Title?')],
                contest=[VariableExpansion(needle='AUTHOR', prompt='Author?')],
            ),
            contestVariants=[variant],
        )
        merged = preset.merged_expansion(variant, is_contest=True)
        assert [e.needle for e in merged] == ['AUTHOR', 'DIVISION']

    def test_expansion_canonical_returns_shared_only(self):
        shared = VariableExpansion(needle='AUTHOR', prompt='Author?')
        preset = _preset(
            problem=pathlib.Path('problem'),
            expansion=Expansion(problem=[shared]),
            problemVariants=[
                PackageVariant(
                    id='interactive',
                    path=pathlib.Path('pi'),
                    expansion=[VariableExpansion(needle='JUDGE', prompt='Judge?')],
                )
            ],
        )
        assert preset.merged_expansion(None, is_contest=False) == [shared]


PRESET_WITH_VARIANT = """---
name: "with-variant"
uri: "test/with-variant"
min_version: "1.0.0"
problem: "problem"
problemVariants:
  - id: interactive
    path: "problem-interactive"
    description: "Interactive"
"""


_ANSI = re.compile(r'\x1b\[[0-9;]*m')


def _plain(captured: str) -> str:
    """Console output without rich's styling, so assertions can match spans of
    text that the highlighter breaks up with escape codes."""
    return _ANSI.sub('', captured)


def _write_preset(root: pathlib.Path, body: str) -> pathlib.Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'preset.rbx.yml').write_text(body)
    (root / 'problem').mkdir(exist_ok=True)
    (root / 'problem-interactive').mkdir(exist_ok=True)
    return root


class TestResolveTemplate:
    def test_canonical_when_no_variant_requested(self, tmp_path):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        preset = presets.get_preset_yaml(root)
        resolved = presets.resolve_template(
            preset, root, is_contest=False, variant=None
        )
        assert resolved.variant_id is None
        assert resolved.path == root / 'problem'

    def test_named_variant(self, tmp_path):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        preset = presets.get_preset_yaml(root)
        resolved = presets.resolve_template(
            preset, root, is_contest=False, variant='interactive'
        )
        assert resolved.variant_id == 'interactive'
        assert resolved.path == root / 'problem-interactive'

    def test_default_keyword_means_canonical(self, tmp_path):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        preset = presets.get_preset_yaml(root)
        resolved = presets.resolve_template(
            preset, root, is_contest=False, variant='default'
        )
        assert resolved.variant_id is None
        assert resolved.path == root / 'problem'

    def test_unknown_variant_exits_and_lists_available(self, tmp_path, capsys):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        preset = presets.get_preset_yaml(root)
        with pytest.raises(typer.Exit):
            presets.resolve_template(preset, root, is_contest=False, variant='nope')
        out = _plain(capsys.readouterr().out)
        assert 'nope' in out
        assert 'interactive' in out
        assert 'default' in out

    def test_missing_canonical_without_variant_exits(self, tmp_path, capsys):
        root = _write_preset(
            tmp_path / 'preset',
            """---
name: "variant-only"
uri: "test/variant-only"
min_version: "1.0.0"
problemVariants:
  - id: interactive
    path: "problem-interactive"
""",
        )
        preset = presets.get_preset_yaml(root)
        with pytest.raises(typer.Exit):
            presets.resolve_template(preset, root, is_contest=False, variant=None)
        out = _plain(capsys.readouterr().out)
        assert 'interactive' in out

    def test_declared_but_missing_directory_exits(self, tmp_path, capsys):
        root = _write_preset(
            tmp_path / 'preset',
            """---
name: "with-variant"
uri: "test/with-variant"
min_version: "1.0.0"
problem: "problem"
problemVariants:
  - id: interactive
    path: "problem-gone"
""",
        )
        preset = presets.get_preset_yaml(root)
        with pytest.raises(typer.Exit):
            presets.resolve_template(
                preset, root, is_contest=False, variant='interactive'
            )
        out = _plain(capsys.readouterr().out)
        assert 'problem-gone' in out
        # The resolved location is shown too, so the user can tell which copy of
        # the preset is stale.
        assert str(root / 'problem-gone') in out

    def test_carries_merged_config(self, tmp_path):
        root = _write_preset(
            tmp_path / 'preset',
            """---
name: "with-variant"
uri: "test/with-variant"
min_version: "1.0.0"
problem: "problem"
tracking:
  problem:
    - path: ".gitignore"
expansion:
  problem:
    - needle: "AUTHOR"
      prompt: "Author?"
libraries:
  problem:
    - name: "testlib"
      source: "owner/testlib"
      dest: "testlib.h"
problemVariants:
  - id: interactive
    path: "problem-interactive"
    tracking:
      - path: "interactor.cpp"
    expansion:
      - needle: "JUDGE"
        prompt: "Judge?"
    libraries:
      - name: "jngen"
        source: "owner/jngen"
        dest: "jngen.h"
""",
        )
        preset = presets.get_preset_yaml(root)
        resolved = presets.resolve_template(
            preset, root, is_contest=False, variant='interactive'
        )
        assert [str(a.path) for a in resolved.tracking] == [
            '.gitignore',
            'interactor.cpp',
        ]
        assert [e.needle for e in resolved.expansion] == ['AUTHOR', 'JUDGE']
        assert [lib.name for lib in resolved.libraries] == ['testlib', 'jngen']

    def test_template_symlinked_outside_the_preset_exits(self, tmp_path, capsys):
        # The schema check is lexical, so `problem-interactive` looks perfectly
        # contained; only resolving symlinks reveals that it is not.
        outside = tmp_path / 'outside'
        outside.mkdir()
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        (root / 'problem-interactive').rmdir()
        (root / 'problem-interactive').symlink_to(outside, target_is_directory=True)
        preset = presets.get_preset_yaml(root)

        with pytest.raises(typer.Exit):
            presets.resolve_template(
                preset, root, is_contest=False, variant='interactive'
            )

        out = _plain(capsys.readouterr().out)
        assert 'problem-interactive' in out
        assert 'outside the preset folder' in out

    def test_template_symlinked_inside_the_preset_is_allowed(self, tmp_path):
        # A symlink is only a problem when it leaves the preset: an internal one
        # is a legitimate way to share a template directory.
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        (root / 'problem-interactive').rmdir()
        (root / 'problem-interactive').symlink_to(
            root / 'problem', target_is_directory=True
        )
        preset = presets.get_preset_yaml(root)

        resolved = presets.resolve_template(
            preset, root, is_contest=False, variant='interactive'
        )

        assert resolved.path == root / 'problem-interactive'

    def test_canonical_carries_shared_config_only(self, tmp_path):
        root = _write_preset(
            tmp_path / 'preset',
            """---
name: "with-variant"
uri: "test/with-variant"
min_version: "1.0.0"
problem: "problem"
tracking:
  problem:
    - path: ".gitignore"
problemVariants:
  - id: interactive
    path: "problem-interactive"
    tracking:
      - path: "interactor.cpp"
""",
        )
        preset = presets.get_preset_yaml(root)
        resolved = presets.resolve_template(
            preset, root, is_contest=False, variant=None
        )
        assert [str(a.path) for a in resolved.tracking] == ['.gitignore']

    def test_contest_variant_is_not_a_problem_variant(self, tmp_path, capsys):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        (root / 'contest').mkdir(exist_ok=True)
        (root / 'preset.rbx.yml').write_text(
            """---
name: "with-variant"
uri: "test/with-variant"
min_version: "1.0.0"
problem: "problem"
contest: "contest"
problemVariants:
  - id: interactive
    path: "problem-interactive"
"""
        )
        preset = presets.get_preset_yaml(root)
        with pytest.raises(typer.Exit):
            presets.resolve_template(
                preset, root, is_contest=True, variant='interactive'
            )
        out = _plain(capsys.readouterr().out)
        assert 'no contest variant' in out
        # Only the canonical contest template is offered; the problem variant is
        # not a valid choice here.
        assert 'interactive' not in out.split('Available contest templates')[1]

    def test_carries_preset_root_and_declared_inner_path(self, tmp_path):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        preset = presets.get_preset_yaml(root)
        resolved = presets.resolve_template(
            preset, root, is_contest=False, variant='interactive'
        )
        assert resolved.preset is preset
        assert resolved.preset_path == root
        assert resolved.inner == pathlib.Path('problem-interactive')
        assert resolved.path == resolved.preset_path / resolved.inner

    def test_lists_the_flag_to_use(self, tmp_path, capsys):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        preset = presets.get_preset_yaml(root)
        with pytest.raises(typer.Exit):
            presets.resolve_template(preset, root, is_contest=False, variant='nope')
        assert 'select with -v <id>' in _plain(capsys.readouterr().out)

    def test_no_templates_at_all_reports_only_that(self, tmp_path, capsys):
        root = _write_preset(
            tmp_path / 'preset',
            """---
name: "no-templates"
uri: "test/no-templates"
min_version: "1.0.0"
problem: "problem"
""",
        )
        preset = presets.get_preset_yaml(root)
        with pytest.raises(typer.Exit):
            presets.resolve_template(preset, root, is_contest=True, variant=None)
        out = _plain(capsys.readouterr().out)
        assert 'declares no contest templates at all' in out
        # No contradictory second message, and no empty list of alternatives.
        assert 'canonical' not in out
        assert 'Available' not in out


class TestVariantForPath:
    def test_maps_nested_cwd(self, tmp_path):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        preset = presets.get_preset_yaml(root)
        assert (
            presets.variant_for_path(
                preset,
                root,
                root / 'problem-interactive' / 'sols',
                is_contest=False,
            )
            == 'interactive'
        )
        assert (
            presets.variant_for_path(preset, root, root / 'problem', is_contest=False)
            == 'default'
        )

    def test_maps_the_variant_root_itself(self, tmp_path):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        preset = presets.get_preset_yaml(root)
        assert (
            presets.variant_for_path(
                preset, root, root / 'problem-interactive', is_contest=False
            )
            == 'interactive'
        )

    def test_preset_root_is_inside_no_template(self, tmp_path):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        preset = presets.get_preset_yaml(root)
        assert presets.variant_for_path(preset, root, root, is_contest=False) is None

    def test_path_outside_the_preset_is_inside_no_template(self, tmp_path):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        preset = presets.get_preset_yaml(root)
        assert (
            presets.variant_for_path(
                preset, root, tmp_path / 'elsewhere', is_contest=False
            )
            is None
        )

    def test_result_feeds_back_into_resolve_template(self, tmp_path):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        preset = presets.get_preset_yaml(root)
        for target, expected in (
            (root / 'problem', root / 'problem'),
            (root / 'problem-interactive', root / 'problem-interactive'),
        ):
            variant = presets.variant_for_path(preset, root, target, is_contest=False)
            resolved = presets.resolve_template(
                preset, root, is_contest=False, variant=variant
            )
            assert resolved.path == expected

    def test_prefers_the_deepest_matching_variant(self, tmp_path):
        root = tmp_path / 'preset'
        root.mkdir()
        (root / 'templates' / 'interactive').mkdir(parents=True)
        (root / 'preset.rbx.yml').write_text(
            """---
name: "nested"
uri: "test/nested"
min_version: "1.0.0"
problem: "problem"
problemVariants:
  - id: outer
    path: "templates"
  - id: inner
    path: "templates/interactive"
"""
        )
        preset = presets.get_preset_yaml(root)
        assert (
            presets.variant_for_path(
                preset,
                root,
                root / 'templates' / 'interactive' / 'sols',
                is_contest=False,
            )
            == 'inner'
        )
        assert (
            presets.variant_for_path(
                preset, root, root / 'templates' / 'other', is_contest=False
            )
            == 'outer'
        )

    def test_contest_templates_are_separate(self, tmp_path):
        root = _write_preset(tmp_path / 'preset', PRESET_WITH_VARIANT)
        preset = presets.get_preset_yaml(root)
        # The preset declares no contest templates at all, so nothing matches.
        assert (
            presets.variant_for_path(
                preset, root, root / 'problem-interactive', is_contest=True
            )
            is None
        )
        assert (
            presets.variant_for_path(preset, root, root / 'problem', is_contest=True)
            is None
        )


PRESET_WITH_TRACKED_VARIANT = """---
name: "with-variant"
uri: "test/with-variant"
min_version: "1.0.0"
problem: "problem"
tracking:
  problem:
    - path: "tracked.txt"
problemVariants:
  - id: interactive
    path: "problem-interactive"
    description: "Interactive"
"""

PRESET_WITHOUT_VARIANT = """---
name: "with-variant"
uri: "test/with-variant"
min_version: "1.0.0"
problem: "problem"
tracking:
  problem:
    - path: "tracked.txt"
"""

_PROBLEM_YML = """---
name: "template-problem"
timeLimit: 1000
memoryLimit: 256
"""


def _write_tracked_preset(root: pathlib.Path) -> pathlib.Path:
    """A preset whose canonical and `interactive` templates both track the same
    file name, with different contents -- so a sync against the wrong template
    is visible in the file's content."""
    root.mkdir(parents=True, exist_ok=True)
    (root / 'preset.rbx.yml').write_text(PRESET_WITH_TRACKED_VARIANT)
    for inner, content in (
        ('problem', 'canonical v1'),
        ('problem-interactive', 'variant v1'),
    ):
        (root / inner).mkdir(exist_ok=True)
        (root / inner / 'problem.rbx.yml').write_text(_PROBLEM_YML)
        (root / inner / 'tracked.txt').write_text(content)
    return root


def _install_package(tmp_path: pathlib.Path, variant: Optional[str]) -> pathlib.Path:
    """Create a package installed from `variant` of a freshly written preset,
    with a lock recording the template it came from."""
    preset_root = _write_tracked_preset(tmp_path / 'preset')
    package_dir = tmp_path / 'package'
    package_dir.mkdir()
    presets.install_preset_from_dir(preset_root, package_dir / '.local.rbx')
    template = presets.install_problem(package_dir, variant=variant)
    assert template.variant_id == variant
    presets.generate_lock(package_dir, template=template)
    return package_dir


def _bump_preset_templates(package_dir: pathlib.Path) -> None:
    """Simulate an upstream change to both templates of the installed preset."""
    local = package_dir / '.local.rbx'
    (local / 'problem' / 'tracked.txt').write_text('canonical v2')
    (local / 'problem-interactive' / 'tracked.txt').write_text('variant v2')


class TestLockVariant:
    def test_lock_defaults_to_none(self):
        assert PresetLock(name='p').variant is None

    def test_existing_lock_without_variant_still_parses(self):
        lock = PresetLock.model_validate({'name': 'default', 'assets': []})
        assert lock.variant is None

    def test_generate_lock_records_variant(self, tmp_path):
        package_dir = _install_package(tmp_path, variant='interactive')

        # The value round-trips through the YAML on disk.
        assert 'variant: interactive' in (package_dir / '.preset-lock.yml').read_text()
        lock = presets.get_preset_lock(package_dir)
        assert lock is not None
        assert lock.variant == 'interactive'

    def test_generate_lock_records_none_for_canonical(self, tmp_path):
        package_dir = _install_package(tmp_path, variant=None)
        lock = presets.get_preset_lock(package_dir)
        assert lock is not None
        assert lock.variant is None

    def test_relock_keeps_the_locked_variant(self, tmp_path, monkeypatch):
        package_dir = _install_package(tmp_path, variant='interactive')

        monkeypatch.chdir(package_dir)
        presets.lock()

        lock = presets.get_preset_lock(package_dir)
        assert lock is not None
        assert lock.variant == 'interactive'

    def test_relock_repairs_a_corrupt_lock(self, tmp_path, monkeypatch, capsys):
        package_dir = _install_package(tmp_path, variant='interactive')
        # `presets lock` is exactly the command you reach for here, so it must
        # not refuse to run.
        (package_dir / '.preset-lock.yml').write_text('{{ not yaml at all')

        monkeypatch.chdir(package_dir)
        presets.lock()

        lock = presets.get_preset_lock(package_dir)
        assert lock is not None
        # The variant could not be recovered, so canonical is assumed -- but the
        # user is told, rather than left to discover it at the next sync.
        assert lock.variant is None
        assert 'Could not read' in _plain(capsys.readouterr().out)

    def test_locking_a_package_with_no_lock_announces_the_guess(
        self, tmp_path, monkeypatch, capsys
    ):
        package_dir = _install_package(tmp_path, variant='interactive')
        # Adopting a package whose lock was never committed: nothing records
        # which template it came from.
        (package_dir / '.preset-lock.yml').unlink()

        monkeypatch.chdir(package_dir)
        presets.lock()

        lock = presets.get_preset_lock(package_dir)
        assert lock is not None
        assert lock.variant is None

        out = _plain(capsys.readouterr().out)
        # The guess is stated, and the alternatives it might have been are
        # listed, so a variant package can be corrected before the next sync.
        assert 'default' in out
        assert 'interactive' in out
        assert '.preset-lock.yml' in out

    def test_sync_uses_the_locked_variant(self, tmp_path, monkeypatch):
        package_dir = _install_package(tmp_path, variant='interactive')
        assert (package_dir / 'tracked.txt').read_text() == 'variant v1'
        _bump_preset_templates(package_dir)

        monkeypatch.chdir(package_dir)
        presets._sync()  # noqa: SLF001

        assert (package_dir / 'tracked.txt').read_text() == 'variant v2'
        # And the refreshed lock still points at the variant.
        lock = presets.get_preset_lock(package_dir)
        assert lock is not None
        assert lock.variant == 'interactive'

    def test_sync_uses_the_canonical_template_when_locked_to_it(
        self, tmp_path, monkeypatch
    ):
        package_dir = _install_package(tmp_path, variant=None)
        _bump_preset_templates(package_dir)

        monkeypatch.chdir(package_dir)
        presets._sync()  # noqa: SLF001

        assert (package_dir / 'tracked.txt').read_text() == 'canonical v2'

    def test_sync_errors_when_locked_variant_disappeared(
        self, tmp_path, monkeypatch, capsys
    ):
        package_dir = _install_package(tmp_path, variant='interactive')
        _bump_preset_templates(package_dir)
        # The preset was updated and no longer declares the variant.
        (package_dir / '.local.rbx' / 'preset.rbx.yml').write_text(
            PRESET_WITHOUT_VARIANT
        )

        monkeypatch.chdir(package_dir)
        with pytest.raises(typer.Exit) as exc_info:
            presets._sync()  # noqa: SLF001

        assert exc_info.value.exit_code != 0
        out = _plain(capsys.readouterr().out)
        assert 'interactive' in out
        assert '.preset-lock.yml' in out
        # `-v` is not a lever on `presets sync`, so it must not be suggested.
        assert '-v <id>' not in out
        # Crucially, the variant's asset was NOT overwritten with the
        # canonical template's content...
        assert (package_dir / 'tracked.txt').read_text() == 'variant v1'
        # ...and the lock was not rewritten to point at the canonical template,
        # which would make the next sync destroy the package quietly.
        lock = presets.get_preset_lock(package_dir)
        assert lock is not None
        assert lock.variant == 'interactive'

    def test_sync_does_not_blame_the_lock_for_an_unrelated_failure(
        self, tmp_path, monkeypatch, capsys
    ):
        package_dir = _install_package(tmp_path, variant='interactive')
        # A very common setup: `.local.rbx` is gitignored, so a fresh clone has
        # no installed preset at all. That has nothing to do with the lock.
        shutil.rmtree(package_dir / '.local.rbx')

        monkeypatch.chdir(package_dir)
        with pytest.raises(typer.Exit):
            presets._sync()  # noqa: SLF001

        out = _plain(capsys.readouterr().out)
        assert 'No preset is active' in out
        # No advice to go edit a lock file that is perfectly fine.
        assert 'variant' not in out

    def test_pre_variants_lock_syncs_against_the_canonical_template(
        self, tmp_path, monkeypatch
    ):
        package_dir = _install_package(tmp_path, variant=None)
        # A lock as written before variants existed: no `variant` key at all.
        lock_path = package_dir / '.preset-lock.yml'
        lock_text = '\n'.join(
            line
            for line in lock_path.read_text().splitlines()
            if not line.startswith('variant:')
        )
        assert 'variant:' not in lock_text
        lock_path.write_text(lock_text + '\n')
        _bump_preset_templates(package_dir)

        monkeypatch.chdir(package_dir)
        presets._sync()  # noqa: SLF001

        assert (package_dir / 'tracked.txt').read_text() == 'canonical v2'


CONTEST_PRESET_WITH_TRACKED_VARIANT = """---
name: "with-variant"
uri: "test/with-variant"
min_version: "1.0.0"
contest: "contest"
tracking:
  contest:
    - path: "tracked.txt"
contestVariants:
  - id: div1
    path: "contest-div1"
    description: "Div 1"
"""

_CONTEST_YML = """---
name: "template-contest"
problems: []
"""


class TestContestLockVariant:
    """The contest side goes through its own install entrypoint, so it gets its
    own end-to-end coverage of the same failure mode."""

    def _install_contest_package(
        self, tmp_path: pathlib.Path, variant: Optional[str]
    ) -> pathlib.Path:
        preset_root = tmp_path / 'preset'
        preset_root.mkdir()
        (preset_root / 'preset.rbx.yml').write_text(CONTEST_PRESET_WITH_TRACKED_VARIANT)
        for inner, content in (
            ('contest', 'canonical v1'),
            ('contest-div1', 'variant v1'),
        ):
            (preset_root / inner).mkdir()
            (preset_root / inner / 'contest.rbx.yml').write_text(_CONTEST_YML)
            (preset_root / inner / 'tracked.txt').write_text(content)

        package_dir = tmp_path / 'package'
        package_dir.mkdir()
        presets.install_preset_from_dir(preset_root, package_dir / '.local.rbx')
        template = presets.install_contest(package_dir, variant=variant)
        assert template.variant_id == variant
        presets.generate_lock(package_dir, template=template)
        return package_dir

    def test_install_contest_returns_the_template_and_lock_records_it(self, tmp_path):
        package_dir = self._install_contest_package(tmp_path, variant='div1')

        assert (package_dir / 'tracked.txt').read_text() == 'variant v1'
        lock = presets.get_preset_lock(package_dir)
        assert lock is not None
        assert lock.variant == 'div1'

    def test_sync_uses_the_locked_contest_variant(self, tmp_path, monkeypatch):
        package_dir = self._install_contest_package(tmp_path, variant='div1')
        local = package_dir / '.local.rbx'
        (local / 'contest' / 'tracked.txt').write_text('canonical v2')
        (local / 'contest-div1' / 'tracked.txt').write_text('variant v2')

        monkeypatch.chdir(package_dir)
        presets._sync()  # noqa: SLF001

        assert (package_dir / 'tracked.txt').read_text() == 'variant v2'


def _preset_with_dirs(
    root: pathlib.Path, body: str, dirs: Iterable[str]
) -> pathlib.Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'preset.rbx.yml').write_text(body)
    for inner in dirs:
        (root / inner).mkdir(parents=True, exist_ok=True)
    return root


class TestAllTemplates:
    def test_canonical_then_variants_in_declaration_order(self, tmp_path):
        root = _preset_with_dirs(
            tmp_path / 'preset',
            """---
name: "with-variants"
uri: "test/with-variants"
min_version: "1.0.0"
problem: "problem"
problemVariants:
  - id: interactive
    path: "problem-interactive"
  - id: alpha
    path: "problem-alpha"
""",
            ['problem', 'problem-interactive', 'problem-alpha'],
        )
        preset = presets.get_preset_yaml(root)

        templates = presets.all_templates(preset, root, is_contest=False)

        assert [t.variant_id for t in templates] == [None, 'interactive', 'alpha']
        assert [t.path for t in templates] == [
            root / 'problem',
            root / 'problem-interactive',
            root / 'problem-alpha',
        ]

    def test_canonical_only(self, tmp_path):
        root = _preset_with_dirs(
            tmp_path / 'preset',
            """---
name: "plain"
uri: "test/plain"
min_version: "1.0.0"
problem: "problem"
""",
            ['problem'],
        )
        preset = presets.get_preset_yaml(root)

        templates = presets.all_templates(preset, root, is_contest=False)

        assert [(t.variant_id, t.path) for t in templates] == [(None, root / 'problem')]

    def test_variants_only_without_canonical(self, tmp_path):
        root = _preset_with_dirs(
            tmp_path / 'preset',
            """---
name: "variant-only"
uri: "test/variant-only"
min_version: "1.0.0"
problemVariants:
  - id: interactive
    path: "problem-interactive"
""",
            ['problem-interactive'],
        )
        preset = presets.get_preset_yaml(root)

        templates = presets.all_templates(preset, root, is_contest=False)

        assert [(t.variant_id, t.path) for t in templates] == [
            ('interactive', root / 'problem-interactive')
        ]

    def test_no_templates_of_this_kind_returns_empty(self, tmp_path):
        root = _preset_with_dirs(
            tmp_path / 'preset',
            """---
name: "problem-only"
uri: "test/problem-only"
min_version: "1.0.0"
problem: "problem"
""",
            ['problem'],
        )
        preset = presets.get_preset_yaml(root)

        assert presets.all_templates(preset, root, is_contest=True) == []

    def test_missing_directory_is_warned_and_skipped(self, tmp_path, capsys):
        # Unlike `resolve_template`, sweeping over every template must not abort
        # on a stale declaration: the remaining templates still get processed.
        root = _preset_with_dirs(
            tmp_path / 'preset',
            """---
name: "stale"
uri: "test/stale"
min_version: "1.0.0"
problem: "problem-gone"
problemVariants:
  - id: interactive
    path: "problem-interactive"
""",
            ['problem-interactive'],
        )
        preset = presets.get_preset_yaml(root)

        templates = presets.all_templates(preset, root, is_contest=False)

        assert [(t.variant_id, t.path) for t in templates] == [
            ('interactive', root / 'problem-interactive')
        ]
        out = _plain(capsys.readouterr().out)
        assert 'problem-gone' in out

    def test_template_symlinked_outside_is_warned_and_skipped(self, tmp_path, capsys):
        # `is_dir()` happily follows the symlink, so this only trips inside
        # `resolve_template` -- a sweep must survive it and keep going.
        outside = tmp_path / 'outside'
        outside.mkdir()
        root = _preset_with_dirs(
            tmp_path / 'preset',
            """---
name: "escaping"
uri: "test/escaping"
min_version: "1.0.0"
problem: "problem"
problemVariants:
  - id: interactive
    path: "problem-interactive"
""",
            ['problem'],
        )
        (root / 'problem-interactive').symlink_to(outside, target_is_directory=True)
        preset = presets.get_preset_yaml(root)

        templates = presets.all_templates(preset, root, is_contest=False)

        assert [(t.variant_id, t.path) for t in templates] == [(None, root / 'problem')]
        out = _plain(capsys.readouterr().out)
        assert 'outside the preset folder' in out

    def test_carries_merged_config_per_template(self, tmp_path):
        root = _preset_with_dirs(
            tmp_path / 'preset',
            """---
name: "with-variant"
uri: "test/with-variant"
min_version: "1.0.0"
problem: "problem"
tracking:
  problem:
    - path: ".gitignore"
problemVariants:
  - id: interactive
    path: "problem-interactive"
    tracking:
      - path: "interactor.cpp"
""",
            ['problem', 'problem-interactive'],
        )
        preset = presets.get_preset_yaml(root)

        canonical, variant = presets.all_templates(preset, root, is_contest=False)

        assert [str(t.path) for t in canonical.tracking] == ['.gitignore']
        assert sorted(str(t.path) for t in variant.tracking) == [
            '.gitignore',
            'interactor.cpp',
        ]


class TestInstallCleansVariantDirs:
    """Build cruft sitting in a variant's template dir must not be carried into
    the installed preset."""

    PRESET = """---
name: "with-variants"
uri: "test/with-variants"
min_version: "1.0.0"
problem: "problem"
contest: "contest"
problemVariants:
  - id: interactive
    path: "problem-interactive"
contestVariants:
  - id: div1
    path: "contest-div1"
"""

    def _src(self, tmp_path: pathlib.Path) -> pathlib.Path:
        from rbx.config import CACHE_DIR_NAME

        src = _preset_with_dirs(
            tmp_path / 'src',
            self.PRESET,
            ['problem', 'problem-interactive', 'contest', 'contest-div1'],
        )
        (src / 'problem' / 'problem.rbx.yml').write_text(_PROBLEM_YML)
        (src / 'problem-interactive' / 'problem.rbx.yml').write_text(_PROBLEM_YML)
        (src / 'contest' / 'contest.rbx.yml').write_text(_CONTEST_YML)
        (src / 'contest-div1' / 'contest.rbx.yml').write_text(_CONTEST_YML)
        for inner in ('problem', 'problem-interactive', 'contest', 'contest-div1'):
            (src / inner / 'build').mkdir()
            (src / inner / 'build' / 'stale.o').write_text('junk')
            (src / inner / CACHE_DIR_NAME).mkdir()
            (src / inner / '.preset-lock.yml').write_text('name: "stale"\n')
        (src / 'contest' / '.local.rbx').mkdir()
        (src / 'contest-div1' / '.local.rbx').mkdir()
        return src

    def test_cleans_every_template_dir(self, tmp_path):
        from rbx.config import CACHE_DIR_NAME

        src = self._src(tmp_path)
        dst = tmp_path / 'installed'

        presets.install_preset_from_dir(src, dst)

        for inner in ('problem', 'problem-interactive', 'contest', 'contest-div1'):
            assert (dst / inner).is_dir()
            assert not (dst / inner / 'build').exists()
            assert not (dst / inner / CACHE_DIR_NAME).exists()
            assert not (dst / inner / '.preset-lock.yml').exists()
        # Contest templates get their .local.rbx stripped too, variants included.
        assert not (dst / 'contest' / '.local.rbx').exists()
        assert not (dst / 'contest-div1' / '.local.rbx').exists()


class _FakeSelect:
    """Stands in for `questionary.select(...)`, recording how it was called."""

    def __init__(self, answer: Any):
        self.answer = answer
        self.calls: list = []

    def __call__(self, message, choices, default=None, **kwargs):
        self.calls.append(
            SimpleNamespace(message=message, choices=choices, default=default)
        )
        return SimpleNamespace(ask=lambda: self.answer)

    @property
    def titles(self) -> list:
        assert len(self.calls) == 1
        return [choice.title for choice in self.calls[0].choices]

    @property
    def values(self) -> list:
        assert len(self.calls) == 1
        return [choice.value for choice in self.calls[0].choices]


@pytest.fixture
def fake_tty(monkeypatch):
    monkeypatch.setattr(presets.sys.stdin, 'isatty', lambda: True)


@pytest.fixture
def fake_no_tty(monkeypatch):
    monkeypatch.setattr(presets.sys.stdin, 'isatty', lambda: False)


def _patch_select(monkeypatch, answer: Any) -> _FakeSelect:
    fake = _FakeSelect(answer)
    monkeypatch.setattr(questionary, 'select', fake)
    return fake


class TestPickVariant:
    def test_no_variants_declared_never_prompts(self, monkeypatch, fake_tty):
        fake = _patch_select(monkeypatch, 'anything')
        preset = _preset(problem=pathlib.Path('problem'))

        assert presets.pick_variant(preset, is_contest=False, variant=None) is None
        assert fake.calls == []

    def test_explicit_variant_is_returned_unchanged(self, monkeypatch, fake_tty):
        fake = _patch_select(monkeypatch, 'anything')
        preset = _preset(
            problem=pathlib.Path('problem'),
            problemVariants=[
                PackageVariant(id='interactive', path=pathlib.Path('problem-i'))
            ],
        )

        assert (
            presets.pick_variant(preset, is_contest=False, variant='interactive')
            == 'interactive'
        )
        # Even an id the preset does not declare is passed through untouched --
        # rejecting it is `resolve_template`'s job.
        assert (
            presets.pick_variant(preset, is_contest=False, variant='bogus') == 'bogus'
        )
        assert fake.calls == []

    def test_non_tty_uses_canonical_without_prompting(self, monkeypatch, fake_no_tty):
        fake = _patch_select(monkeypatch, 'interactive')
        preset = _preset(
            problem=pathlib.Path('problem'),
            problemVariants=[
                PackageVariant(id='interactive', path=pathlib.Path('problem-i'))
            ],
        )

        assert presets.pick_variant(preset, is_contest=False, variant=None) is None
        assert fake.calls == []

    def test_non_tty_without_canonical_fails(
        self, monkeypatch, fake_no_tty, capsys: pytest.CaptureFixture[str]
    ):
        fake = _patch_select(monkeypatch, 'interactive')
        preset = _preset(
            problemVariants=[
                PackageVariant(id='interactive', path=pathlib.Path('problem-i'))
            ],
        )

        with pytest.raises(typer.Exit):
            presets.pick_variant(preset, is_contest=False, variant=None)

        assert fake.calls == []
        out = _plain(capsys.readouterr().out)
        assert 'does not have a canonical problem template' in out
        assert '-v <id>' in out
        assert 'interactive' in out

    def test_prompts_with_default_and_every_variant(self, monkeypatch, fake_tty):
        fake = _patch_select(monkeypatch, 'default')
        preset = _preset(
            problem=pathlib.Path('problem'),
            problemVariants=[
                PackageVariant(
                    id='interactive',
                    path=pathlib.Path('problem-i'),
                    description='An interactive problem.',
                ),
                PackageVariant(id='bare', path=pathlib.Path('problem-bare')),
            ],
        )

        # Answering 'default' maps back to the canonical template.
        assert presets.pick_variant(preset, is_contest=False, variant=None) is None

        assert fake.values == ['default', 'interactive', 'bare']
        assert fake.titles == [
            "default — the preset's main template",
            'interactive — An interactive problem.',
            'bare',
        ]
        assert fake.calls[0].default == 'default'

    def test_prompt_returns_selected_variant_id(self, monkeypatch, fake_tty):
        _patch_select(monkeypatch, 'interactive')
        preset = _preset(
            problem=pathlib.Path('problem'),
            problemVariants=[
                PackageVariant(id='interactive', path=pathlib.Path('problem-i'))
            ],
        )

        assert (
            presets.pick_variant(preset, is_contest=False, variant=None)
            == 'interactive'
        )

    def test_prompt_omits_default_when_no_canonical(self, monkeypatch, fake_tty):
        fake = _patch_select(monkeypatch, 'interactive')
        preset = _preset(
            problemVariants=[
                PackageVariant(id='interactive', path=pathlib.Path('problem-i')),
                PackageVariant(id='bare', path=pathlib.Path('problem-bare')),
            ],
        )

        assert (
            presets.pick_variant(preset, is_contest=False, variant=None)
            == 'interactive'
        )
        assert fake.values == ['interactive', 'bare']
        assert fake.calls[0].default == 'interactive'

    def test_aborting_the_prompt_exits(self, monkeypatch, fake_tty):
        _patch_select(monkeypatch, None)
        preset = _preset(
            problem=pathlib.Path('problem'),
            problemVariants=[
                PackageVariant(id='interactive', path=pathlib.Path('problem-i'))
            ],
        )

        with pytest.raises(typer.Exit):
            presets.pick_variant(preset, is_contest=False, variant=None)

    def test_contest_variants_are_independent(self, monkeypatch, fake_tty):
        fake = _patch_select(monkeypatch, 'div1')
        preset = _preset(
            problem=pathlib.Path('problem'),
            contest=pathlib.Path('contest'),
            problemVariants=[
                PackageVariant(id='interactive', path=pathlib.Path('problem-i'))
            ],
            contestVariants=[
                PackageVariant(id='div1', path=pathlib.Path('contest-div1'))
            ],
        )

        assert presets.pick_variant(preset, is_contest=True, variant=None) == 'div1'
        assert fake.values == ['default', 'div1']
        assert 'contest template' in fake.calls[0].message


class TestInstallEnsuresSomeTemplate:
    """`ensure_problem`/`ensure_contest` ask whether the preset can produce a
    package of that kind at all -- not whether it has a *canonical* template."""

    VARIANTS_ONLY = """---
name: "variants-only"
uri: "test/variants-only"
min_version: "1.0.0"
problemVariants:
  - id: interactive
    path: "problem-interactive"
"""

    NO_PROBLEM = """---
name: "contest-only"
uri: "test/contest-only"
min_version: "1.0.0"
contest: "contest"
"""

    def test_variants_only_preset_installs(self, tmp_path):
        src = _preset_with_dirs(
            tmp_path / 'src', self.VARIANTS_ONLY, ['problem-interactive']
        )
        (src / 'problem-interactive' / 'problem.rbx.yml').write_text(_PROBLEM_YML)
        dst = tmp_path / 'installed'

        presets.install_preset_from_dir(src, dst, ensure_problem=True)

        assert (dst / 'preset.rbx.yml').is_file()
        assert (dst / 'problem-interactive' / 'problem.rbx.yml').is_file()

    def test_variants_only_contest_preset_installs(self, tmp_path):
        src = _preset_with_dirs(
            tmp_path / 'src',
            """---
name: "variants-only"
uri: "test/variants-only"
min_version: "1.0.0"
contestVariants:
  - id: div1
    path: "contest-div1"
""",
            ['contest-div1'],
        )
        (src / 'contest-div1' / 'contest.rbx.yml').write_text(_CONTEST_YML)
        dst = tmp_path / 'installed'

        presets.install_preset_from_dir(src, dst, ensure_contest=True)

        assert (dst / 'contest-div1' / 'contest.rbx.yml').is_file()

    def test_preset_with_no_problem_template_still_fails(self, tmp_path, capsys):
        src = _preset_with_dirs(tmp_path / 'src', self.NO_PROBLEM, ['contest'])
        (src / 'contest' / 'contest.rbx.yml').write_text(_CONTEST_YML)
        dst = tmp_path / 'installed'

        with pytest.raises(typer.Exit) as exc_info:
            presets.install_preset_from_dir(src, dst, ensure_problem=True)

        assert exc_info.value.exit_code != 0
        out = _plain(capsys.readouterr().out)
        assert 'contest-only' in out
        assert 'problem template' in out
        # It failed early, before touching the destination.
        assert not dst.exists()

    def test_preset_with_no_contest_template_still_fails(self, tmp_path, capsys):
        src = _preset_with_dirs(
            tmp_path / 'src', self.VARIANTS_ONLY, ['problem-interactive']
        )
        dst = tmp_path / 'installed'

        with pytest.raises(typer.Exit):
            presets.install_preset_from_dir(src, dst, ensure_contest=True)

        assert 'contest template' in _plain(capsys.readouterr().out)
        assert not dst.exists()


_LS_PRESET = """---
name: "ls-preset"
uri: "test/ls-preset"
min_version: "1.0.0"
problem: "problem"
contest: "contest"
problemVariants:
  - id: interactive
    path: "problem-interactive"
    description: "Interactive"
  - id: gone
    path: "problem-gone"
    description: "Vanished"
contestVariants:
  - id: div1
    path: "contest-div1"
    description: "Division 1"
"""


def _package_for_ls(tmp_path: pathlib.Path, lock: Optional[str]) -> pathlib.Path:
    """A problem package with an installed preset that declares variants of
    both kinds -- one of them pointing at a directory that does not exist."""
    src = _preset_with_dirs(
        tmp_path / 'src',
        _LS_PRESET,
        ['problem', 'problem-interactive', 'contest', 'contest-div1'],
    )
    for inner in ('problem', 'problem-interactive'):
        (src / inner / 'problem.rbx.yml').write_text(_PROBLEM_YML)
    for inner in ('contest', 'contest-div1'):
        (src / inner / 'contest.rbx.yml').write_text(_CONTEST_YML)

    package_dir = tmp_path / 'package'
    package_dir.mkdir()
    presets.install_preset_from_dir(src, package_dir / '.local.rbx')
    (package_dir / 'problem.rbx.yml').write_text(_PROBLEM_YML)
    if lock is not None:
        (package_dir / '.preset-lock.yml').write_text(lock)
    return package_dir


class TestLsTemplates:
    def _run(self, tmp_path, monkeypatch, capsys, lock: Optional[str]) -> str:
        package_dir = _package_for_ls(tmp_path, lock)
        monkeypatch.chdir(package_dir)
        capsys.readouterr()
        presets.ls()
        return _plain(capsys.readouterr().out)

    def test_lists_both_kinds_with_ids_and_descriptions(
        self, tmp_path, monkeypatch, capsys
    ):
        out = self._run(tmp_path, monkeypatch, capsys, 'name: "ls-preset"\n')

        assert 'ls-preset' in out
        assert 'Problem templates' in out
        assert 'Contest templates' in out
        # The canonical template shows up under the id that selects it.
        assert 'default' in out
        for token in (
            'interactive',
            'Interactive',
            'problem-interactive',
            'div1',
            'Division 1',
            'contest-div1',
        ):
            assert token in out, token

    def test_flags_a_declared_template_whose_directory_is_missing(
        self, tmp_path, monkeypatch, capsys
    ):
        out = self._run(tmp_path, monkeypatch, capsys, 'name: "ls-preset"\n')

        # It is listed at all (`ls` inspects declarations, it does not filter
        # them), and it is called out as broken.
        assert 'gone' in out
        assert 'missing' in out

    def test_marks_the_locked_variant(self, tmp_path, monkeypatch, capsys):
        out = self._run(
            tmp_path,
            monkeypatch,
            capsys,
            'name: "ls-preset"\nvariant: interactive\n',
        )

        lines = [line for line in out.splitlines() if 'in use' in line]
        assert len(lines) == 1
        assert 'interactive' in lines[0]

    def test_marks_the_canonical_template_when_locked_to_it(
        self, tmp_path, monkeypatch, capsys
    ):
        # `variant: null` in the lock means the canonical template.
        out = self._run(tmp_path, monkeypatch, capsys, 'name: "ls-preset"\n')

        lines = [line for line in out.splitlines() if 'in use' in line]
        assert len(lines) == 1
        assert 'default' in lines[0]

    def test_omits_a_kind_the_preset_does_not_declare(
        self, tmp_path, monkeypatch, capsys
    ):
        src = _preset_with_dirs(
            tmp_path / 'src',
            """---
name: "problem-only"
uri: "test/problem-only"
min_version: "1.0.0"
problem: "problem"
""",
            ['problem'],
        )
        (src / 'problem' / 'problem.rbx.yml').write_text(_PROBLEM_YML)
        package_dir = tmp_path / 'package'
        package_dir.mkdir()
        presets.install_preset_from_dir(src, package_dir / '.local.rbx')
        (package_dir / 'problem.rbx.yml').write_text(_PROBLEM_YML)

        monkeypatch.chdir(package_dir)
        capsys.readouterr()
        presets.ls()
        out = _plain(capsys.readouterr().out)

        assert 'Problem templates' in out
        assert 'Contest templates' not in out

    def test_works_without_a_lock(self, tmp_path, monkeypatch, capsys):
        out = self._run(tmp_path, monkeypatch, capsys, None)

        assert 'interactive' in out
        # Nothing is claimed to be in use when nothing recorded it.
        assert 'in use' not in out

    def test_survives_a_malformed_lock(self, tmp_path, monkeypatch, capsys):
        out = self._run(tmp_path, monkeypatch, capsys, '{{ not yaml at all')

        # The listing is still produced...
        assert 'interactive' in out
        assert 'div1' in out
        # ...and the unreadable lock degrades to the canonical template, loudly.
        assert 'Could not read' in out
        lines = [line for line in out.splitlines() if 'in use' in line]
        assert len(lines) == 1
        assert 'default' in lines[0]
