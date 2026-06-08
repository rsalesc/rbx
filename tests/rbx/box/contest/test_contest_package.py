"""Tests for contest_package validation helpers."""

import pathlib

import pytest
import typer

from rbx.box.contest import contest_package as cp_module
from rbx.box.contest.contest_package import (
    validate_problem_folders_are_packages,
    validate_problem_folders_exist,
)
from rbx.box.contest.schema import Contest, ContestProblem


def _make_contest(*problems: ContestProblem) -> Contest:
    return Contest(name='ctt', problems=list(problems))


class TestValidateProblemFoldersExist:
    def test_all_folders_exist_does_not_raise(self, tmp_path: pathlib.Path):
        (tmp_path / 'A').mkdir()
        (tmp_path / 'B').mkdir()
        contest = _make_contest(
            ContestProblem(short_name='A'),
            ContestProblem(short_name='B'),
        )

        validate_problem_folders_exist(contest, tmp_path)

    def test_missing_folder_exits_and_names_short_name(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ):
        (tmp_path / 'A').mkdir()
        # B has no folder.
        contest = _make_contest(
            ContestProblem(short_name='A'),
            ContestProblem(short_name='B'),
        )

        with pytest.raises(typer.Exit):
            validate_problem_folders_exist(contest, tmp_path)

        out = capsys.readouterr().out
        assert '- B:' in out
        assert '- A:' not in out

    def test_multiple_missing_folders_listed_together(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ):
        (tmp_path / 'B').mkdir()
        contest = _make_contest(
            ContestProblem(short_name='A'),
            ContestProblem(short_name='B'),
            ContestProblem(short_name='C'),
        )

        with pytest.raises(typer.Exit):
            validate_problem_folders_exist(contest, tmp_path)

        out = capsys.readouterr().out
        assert '- A:' in out
        assert '- C:' in out
        assert '- B:' not in out

    def test_custom_relative_path_resolved_against_contest_root(
        self, tmp_path: pathlib.Path
    ):
        (tmp_path / 'probs' / 'alpha').mkdir(parents=True)
        contest = _make_contest(
            ContestProblem(short_name='A', path=pathlib.Path('probs') / 'alpha'),
        )

        validate_problem_folders_exist(contest, tmp_path)

    def test_absolute_path_used_as_is(self, tmp_path: pathlib.Path):
        problem_dir = tmp_path / 'somewhere' / 'else'
        problem_dir.mkdir(parents=True)
        contest = _make_contest(
            ContestProblem(short_name='A', path=problem_dir),
        )

        # Passing a different `contest_root` must not affect validation
        # because the path is absolute.
        other_root = tmp_path / 'unrelated'
        other_root.mkdir()
        validate_problem_folders_exist(contest, other_root)

    def test_path_pointing_to_file_is_reported_as_missing(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ):
        # A is a file, not a directory.
        (tmp_path / 'A').write_text('not a folder')
        contest = _make_contest(ContestProblem(short_name='A'))

        with pytest.raises(typer.Exit):
            validate_problem_folders_exist(contest, tmp_path)

        assert '- A:' in capsys.readouterr().out


class TestValidateProblemFoldersArePackages:
    def test_folder_with_yaml_does_not_raise(self, tmp_path: pathlib.Path):
        (tmp_path / 'A').mkdir()
        (tmp_path / 'A' / 'problem.rbx.yml').write_text('name: a\n')
        contest = _make_contest(ContestProblem(short_name='A'))

        validate_problem_folders_are_packages(contest, tmp_path)

    def test_folder_without_yaml_exits(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ):
        (tmp_path / 'A').mkdir()
        contest = _make_contest(ContestProblem(short_name='A'))

        with pytest.raises(typer.Exit):
            validate_problem_folders_are_packages(contest, tmp_path)

        assert '- A:' in capsys.readouterr().out

    def test_multiple_folders_without_yaml_listed_together(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ):
        (tmp_path / 'A').mkdir()
        (tmp_path / 'A' / 'problem.rbx.yml').write_text('name: a\n')
        (tmp_path / 'B').mkdir()
        (tmp_path / 'C').mkdir()
        contest = _make_contest(
            ContestProblem(short_name='A'),
            ContestProblem(short_name='B'),
            ContestProblem(short_name='C'),
        )

        with pytest.raises(typer.Exit):
            validate_problem_folders_are_packages(contest, tmp_path)

        out = capsys.readouterr().out
        assert '- B:' in out
        assert '- C:' in out
        assert '- A:' not in out


class TestFindContestPackageValidation:
    @pytest.fixture(autouse=True)
    def _clear_caches(self):
        cp_module.find_contest_yaml.cache_clear()
        cp_module.find_contest_package.cache_clear()
        yield
        cp_module.find_contest_yaml.cache_clear()
        cp_module.find_contest_package.cache_clear()

    def _write_contest(self, root: pathlib.Path, problems: list[str]) -> None:
        problems_yaml = '\n'.join(f'  - short_name: {p}' for p in problems)
        (root / 'contest.rbx.yml').write_text(
            f'name: ctt\nproblems:\n{problems_yaml}\n'
        )

    def test_returns_contest_when_all_problem_folders_valid(
        self, tmp_path: pathlib.Path
    ):
        self._write_contest(tmp_path, ['A', 'B'])
        for short_name in ['A', 'B']:
            (tmp_path / short_name).mkdir()
            (tmp_path / short_name / 'problem.rbx.yml').write_text('name: p\n')

        result = cp_module.find_contest_package(tmp_path)

        assert result is not None
        assert [p.short_name for p in result.problems] == ['A', 'B']

    def test_exits_when_a_problem_folder_is_missing(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ):
        self._write_contest(tmp_path, ['A', 'B'])
        (tmp_path / 'A').mkdir()
        (tmp_path / 'A' / 'problem.rbx.yml').write_text('name: a\n')
        # No B folder.

        with pytest.raises(typer.Exit):
            cp_module.find_contest_package(tmp_path)

        assert '- B:' in capsys.readouterr().out

    def test_exits_when_problem_folder_lacks_yaml(
        self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
    ):
        self._write_contest(tmp_path, ['A'])
        (tmp_path / 'A').mkdir()
        # No problem.rbx.yml in A.

        with pytest.raises(typer.Exit):
            cp_module.find_contest_package(tmp_path)

        out = capsys.readouterr().out
        assert '- A:' in out
        assert 'problem.rbx.yml' in out


class TestDiscoverVariants:
    def test_single_mode_returns_default(self, tmp_path):
        (tmp_path / 'contest.rbx.yml').write_text('name: my-contest\n')
        variants = cp_module.discover_contest_variants(tmp_path)
        assert variants == {None: tmp_path / 'contest.rbx.yml'}

    def test_dispatcher_mode_lists_siblings(self, tmp_path):
        (tmp_path / 'contest.rbx.yml').write_text('use_variants: true\n')
        (tmp_path / 'contest.div1.rbx.yml').write_text('name: div1-contest\n')
        (tmp_path / 'contest.div2.rbx.yml').write_text('name: div2-contest\n')
        variants = cp_module.discover_contest_variants(tmp_path)
        assert set(variants.keys()) == {'div1', 'div2'}
        assert variants['div1'].name == 'contest.div1.rbx.yml'

    def test_dispatcher_with_invalid_id_skipped_with_warning(
        self, tmp_path, capsys: pytest.CaptureFixture[str]
    ):
        (tmp_path / 'contest.rbx.yml').write_text('use_variants: true\n')
        (tmp_path / 'contest.bad name.rbx.yml').write_text('name: bad-id-contest\n')
        variants = cp_module.discover_contest_variants(tmp_path)
        # Files with invalid ids are skipped, with a warning printed.
        assert variants == {}
        out = capsys.readouterr().out
        assert 'Skipping contest.bad name.rbx.yml' in out
        assert 'not a valid contest variant id' in out

    def test_no_yaml_returns_empty(self, tmp_path):
        assert cp_module.discover_contest_variants(tmp_path) == {}

    def test_real_contest_with_siblings_returns_default_plus_variants(self, tmp_path):
        (tmp_path / 'contest.rbx.yml').write_text('name: my-contest\n')
        (tmp_path / 'contest.div1.rbx.yml').write_text('name: div1-contest\n')
        variants = cp_module.discover_contest_variants(tmp_path)
        assert variants == {
            None: tmp_path / 'contest.rbx.yml',
            'div1': tmp_path / 'contest.div1.rbx.yml',
        }


class TestFindContestYamlVariantAware:
    def test_single_mode_returns_canonical(self, tmp_path):
        (tmp_path / 'contest.rbx.yml').write_text('name: my-contest\n')
        cp_module.find_contest_yaml.cache_clear()
        assert cp_module.find_contest_yaml(tmp_path) == tmp_path / 'contest.rbx.yml'

    def test_dispatcher_with_explicit_selection(self, tmp_path):
        (tmp_path / 'contest.rbx.yml').write_text('use_variants: true\n')
        (tmp_path / 'contest.div1.rbx.yml').write_text('name: div1-contest\n')
        cp_module.find_contest_yaml.cache_clear()
        assert (
            cp_module.find_contest_yaml(tmp_path, contest_id='div1')
            == tmp_path / 'contest.div1.rbx.yml'
        )

    def test_dispatcher_unknown_id_errors(self, tmp_path):
        (tmp_path / 'contest.rbx.yml').write_text('use_variants: true\n')
        cp_module.find_contest_yaml.cache_clear()
        with pytest.raises(typer.Exit):
            cp_module.find_contest_yaml(tmp_path, contest_id='ghost')

    def test_dispatcher_no_selection_returns_none(self, tmp_path):
        (tmp_path / 'contest.rbx.yml').write_text('use_variants: true\n')
        (tmp_path / 'contest.div1.rbx.yml').write_text('name: div1-contest\n')
        cp_module.find_contest_yaml.cache_clear()
        assert cp_module.find_contest_yaml(tmp_path) is None

    def test_single_mode_with_unknown_id_errors(self, tmp_path):
        (tmp_path / 'contest.rbx.yml').write_text('name: my-contest\n')
        cp_module.find_contest_yaml.cache_clear()
        with pytest.raises(typer.Exit):
            cp_module.find_contest_yaml(tmp_path, contest_id='ghost')

    def test_single_mode_with_known_id_resolves_to_sibling(self, tmp_path):
        (tmp_path / 'contest.rbx.yml').write_text('name: my-contest\n')
        (tmp_path / 'contest.div1.rbx.yml').write_text('name: div1-c\n')
        cp_module.find_contest_yaml.cache_clear()
        assert (
            cp_module.find_contest_yaml(tmp_path, contest_id='div1')
            == tmp_path / 'contest.div1.rbx.yml'
        )

    def test_real_canonical_with_siblings_no_id_returns_canonical(self, tmp_path):
        (tmp_path / 'contest.rbx.yml').write_text('name: my-contest\n')
        (tmp_path / 'contest.div1.rbx.yml').write_text('name: div1-c\n')
        cp_module.find_contest_yaml.cache_clear()
        assert cp_module.find_contest_yaml(tmp_path) == tmp_path / 'contest.rbx.yml'

    def test_uses_contextvar_when_no_arg(self, tmp_path):
        from rbx.box.contest.contest_state import selected_variant_id_var

        (tmp_path / 'contest.rbx.yml').write_text('use_variants: true\n')
        (tmp_path / 'contest.div2.rbx.yml').write_text('name: div2-contest\n')
        cp_module.find_contest_yaml.cache_clear()
        token = selected_variant_id_var.set('div2')
        try:
            assert (
                cp_module.find_contest_yaml(tmp_path)
                == tmp_path / 'contest.div2.rbx.yml'
            )
        finally:
            selected_variant_id_var.reset(token)
            cp_module.find_contest_yaml.cache_clear()


class TestContestBuildPaths:
    @pytest.fixture(autouse=True)
    def _clear_caches(self):
        cp_module.find_contest_yaml.cache_clear()
        cp_module.get_contest_build_path.cache_clear()
        cp_module.get_contest_statements_build_path.cache_clear()
        yield
        cp_module.find_contest_yaml.cache_clear()
        cp_module.get_contest_build_path.cache_clear()
        cp_module.get_contest_statements_build_path.cache_clear()

    def test_build_path_uses_default_build_dir(self, tmp_path: pathlib.Path):
        (tmp_path / 'contest.rbx.yml').write_text('name: my-contest\n')

        assert cp_module.get_contest_build_path(tmp_path) == tmp_path / 'build'

    def test_statements_build_path_under_build(self, tmp_path: pathlib.Path):
        (tmp_path / 'contest.rbx.yml').write_text('name: my-contest\n')

        assert (
            cp_module.get_contest_statements_build_path(tmp_path)
            == tmp_path / 'build' / 'statements'
        )

    def test_build_path_honors_custom_build_dir(self, tmp_path: pathlib.Path):
        from unittest import mock

        (tmp_path / 'contest.rbx.yml').write_text('name: my-contest\n')

        with mock.patch.object(
            cp_module.environment, 'get_build_dir', return_value=pathlib.Path('out')
        ):
            cp_module.get_contest_build_path.cache_clear()
            cp_module.get_contest_statements_build_path.cache_clear()
            assert cp_module.get_contest_build_path(tmp_path) == tmp_path / 'out'
            assert (
                cp_module.get_contest_statements_build_path(tmp_path)
                == tmp_path / 'out' / 'statements'
            )

    def test_statement_build_dir_uses_statements_folder(self, tmp_path: pathlib.Path):
        from rbx.box.contest import build_contest_statements
        from rbx.box.contest.schema import ContestStatement

        (tmp_path / 'contest.rbx.yml').write_text('name: my-contest\n')
        statement = ContestStatement(name='main')

        with cp_module.cd.new_package_cd(tmp_path):
            result = build_contest_statements.get_statement_build_dir(statement)

        assert result == tmp_path / 'build' / 'statements' / 'main'


class TestFindContestPackageOrDieDispatcher:
    def test_die_lists_available_variants(self, tmp_path, capsys):
        (tmp_path / 'contest.rbx.yml').write_text('use_variants: true\n')
        (tmp_path / 'contest.div1.rbx.yml').write_text('name: div1-contest\n')
        (tmp_path / 'contest.div2.rbx.yml').write_text('name: div2-contest\n')
        cp_module.find_contest_yaml.cache_clear()
        cp_module.find_contest_package.cache_clear()
        with pytest.raises(typer.Exit):
            cp_module.find_contest_package_or_die(tmp_path)
        out = capsys.readouterr().out
        assert 'div1' in out
        assert 'div2' in out
        assert '-C' in out  # picker hint
