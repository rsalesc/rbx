"""Tests for `rbx contest` Typer commands."""

import os
import pathlib
from unittest import mock

import pytest
from typer.testing import CliRunner

from rbx.box.contest import contest_state, contest_utils
from rbx.box.contest import main as contest_main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _write_single_contest(root: pathlib.Path) -> None:
    (root / 'contest.rbx.yml').write_text('name: ctt\nproblems: []\n')


@pytest.fixture
def clear_package_caches():
    # `find_contest_package` and friends are lru_cached on the resolved paths,
    # so a test that runs a command inside a temporary contest would otherwise
    # leave that contest visible to whatever runs next.
    contest_utils.clear_all_caches()
    yield
    contest_utils.clear_all_caches()


@pytest.fixture
def clean_contest_env(monkeypatch: pytest.MonkeyPatch):
    # `rbx on`/`rbx each` export the selection into the real process env, so
    # swap in a copy that the rest of the suite cannot see.
    monkeypatch.setattr(os, 'environ', dict(os.environ))
    os.environ.pop(contest_state.ENV_VAR, None)


def _write_minimal_problem(dest: pathlib.Path, name: str) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    (dest / 'problem.rbx.yml').write_text(
        f'name: {name}\ntimeLimit: 1000\nmemoryLimit: 256\n'
    )


def _write_dispatcher(root: pathlib.Path, *variant_ids: str) -> None:
    (root / 'contest.rbx.yml').write_text('use_variants: true\n')
    for vid in variant_ids:
        (root / f'contest.{vid}.rbx.yml').write_text(f'name: ctt-{vid}\nproblems: []\n')


def _make_minimal_preset(dest: pathlib.Path, *, invalid: bool = False) -> pathlib.Path:
    """Create a minimal preset directory tree at ``dest`` and return it.

    The bundled ``simple-preset`` has a ``contest/contest.rbx.yml`` with fields
    (``duration``, ``startTime``, ``problems[].label``) that do not validate
    against the ``Contest`` schema, so we build a tiny valid one here.

    When ``invalid`` is set, the ``contest/contest.rbx.yml`` carries an unknown
    ``duration`` field, which ``Contest`` (``extra='forbid'``) rejects -- useful
    for exercising the post-scaffold validation rollback path.
    """
    dest.mkdir(parents=True, exist_ok=True)
    (dest / 'preset.rbx.yml').write_text(
        'name: "minimal-preset"\n'
        'uri: "test/minimal-preset"\n'
        'contest: "contest"\n'
        'env: "env.rbx.yml"\n'
    )
    (dest / 'env.rbx.yml').write_text(
        '---\n'
        'languages:\n'
        '  - name: cpp\n'
        '    readableName: C++\n'
        '    extension: .cpp\n'
        '    compilation:\n'
        '      command: g++ -o {executable} {compilable}\n'
        '    execution:\n'
        '      command: ./{executable}\n'
    )
    (dest / 'contest').mkdir(parents=True, exist_ok=True)
    contest_yml = 'name: "placeholder"\nproblems: []\n'
    if invalid:
        contest_yml += 'duration: 180\n'
    (dest / 'contest' / 'contest.rbx.yml').write_text(contest_yml)
    return dest


class TestContestList:
    def test_list_in_single_contest_dir(
        self,
        runner: CliRunner,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.chdir(tmp_path)
        _write_single_contest(tmp_path)

        result = runner.invoke(contest_main.app, ['list'])

        assert result.exit_code == 0, result.output
        assert 'contest.rbx.yml' in result.output
        assert 'single' in result.output

    def test_list_in_dispatcher_dir(
        self,
        runner: CliRunner,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.chdir(tmp_path)
        _write_dispatcher(tmp_path, 'div1', 'div2')

        result = runner.invoke(contest_main.app, ['list'])

        assert result.exit_code == 0, result.output
        assert 'div1' in result.output
        assert 'div2' in result.output

    def test_list_marks_active_selection_via_flag(
        self,
        runner: CliRunner,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.chdir(tmp_path)
        _write_dispatcher(tmp_path, 'div1', 'div2')

        result = runner.invoke(contest_main.app, ['-C', 'div1', 'list'])

        assert result.exit_code == 0, result.output
        assert 'div1' in result.output
        assert 'div2' in result.output
        # 'div1' line should have a marker; 'div2' line should not.
        div1_line = next(line for line in result.output.splitlines() if 'div1' in line)
        div2_line = next(line for line in result.output.splitlines() if 'div2' in line)
        assert '*' in div1_line
        assert '*' not in div2_line

    def test_list_marks_active_selection_via_env(
        self,
        runner: CliRunner,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.chdir(tmp_path)
        _write_dispatcher(tmp_path, 'div1', 'div2')
        monkeypatch.setenv('RBX_CONTEST', 'div2')

        result = runner.invoke(contest_main.app, ['list'])

        assert result.exit_code == 0, result.output
        div1_line = next(line for line in result.output.splitlines() if 'div1' in line)
        div2_line = next(line for line in result.output.splitlines() if 'div2' in line)
        assert '*' in div2_line
        assert '*' not in div1_line

    def test_list_no_contest_dir_warns(
        self,
        runner: CliRunner,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(contest_main.app, ['list'])

        assert result.exit_code == 0, result.output
        assert 'No contests found' in result.output

    def test_list_in_real_contest_with_siblings_lists_default_and_variants(
        self,
        runner: CliRunner,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.chdir(tmp_path)
        (tmp_path / 'contest.rbx.yml').write_text('name: main-c\nproblems: []\n')
        (tmp_path / 'contest.div1.rbx.yml').write_text('name: div1-c\nproblems: []\n')

        result = runner.invoke(contest_main.app, ['list'])

        assert result.exit_code == 0, result.output
        # The default contest is listed, plus the sibling variant.
        assert 'contest.rbx.yml' in result.output
        assert 'default' in result.output
        assert 'div1' in result.output

    def test_list_real_contest_with_siblings_marks_default_when_no_selection(
        self,
        runner: CliRunner,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.chdir(tmp_path)
        (tmp_path / 'contest.rbx.yml').write_text('name: main-c\nproblems: []\n')
        (tmp_path / 'contest.div1.rbx.yml').write_text('name: div1-c\nproblems: []\n')

        result = runner.invoke(contest_main.app, ['list'])

        assert result.exit_code == 0, result.output
        default_line = next(
            line for line in result.output.splitlines() if 'default' in line
        )
        div1_line = next(line for line in result.output.splitlines() if 'div1' in line)
        assert '*' in default_line
        assert '*' not in div1_line

    def test_list_real_contest_with_siblings_marks_active_variant(
        self,
        runner: CliRunner,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.chdir(tmp_path)
        (tmp_path / 'contest.rbx.yml').write_text('name: main-c\nproblems: []\n')
        (tmp_path / 'contest.div1.rbx.yml').write_text('name: div1-c\nproblems: []\n')

        result = runner.invoke(contest_main.app, ['-C', 'div1', 'list'])

        assert result.exit_code == 0, result.output
        default_line = next(
            line for line in result.output.splitlines() if 'default' in line
        )
        div1_line = next(line for line in result.output.splitlines() if 'div1' in line)
        assert '*' not in default_line
        assert '*' in div1_line


class TestContestAddVariant:
    def test_invalid_id_rejected(self, runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_dispatcher(tmp_path)

        result = runner.invoke(contest_main.app, ['add_variant', 'bad id'])

        assert result.exit_code != 0, result.output
        assert not (tmp_path / 'contest.bad id.rbx.yml').exists()

    def test_invalid_id_leading_digit_rejected(self, runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_dispatcher(tmp_path)

        result = runner.invoke(contest_main.app, ['add_variant', '1abc'])

        assert result.exit_code != 0, result.output

    def test_not_in_contest_dir_rejected(self, runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(contest_main.app, ['add_variant', 'div3'])

        assert result.exit_code != 0, result.output

    def test_existing_variant_rejected(self, runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_dispatcher(tmp_path, 'div1')
        original = (tmp_path / 'contest.div1.rbx.yml').read_text()

        result = runner.invoke(contest_main.app, ['add_variant', 'div1'])

        assert result.exit_code != 0, result.output
        assert (tmp_path / 'contest.div1.rbx.yml').read_text() == original

    def test_scaffold_in_dispatcher_mode(self, runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_dispatcher(tmp_path)
        from rbx.box import presets

        presets.install_preset_from_dir(
            _make_minimal_preset(tmp_path / '_src_preset'), tmp_path / '.local.rbx'
        )

        result = runner.invoke(contest_main.app, ['add_variant', 'div3'])

        assert result.exit_code == 0, result.output
        dest = tmp_path / 'contest.div3.rbx.yml'
        assert dest.exists()
        from rbx.box.contest.schema import Contest
        from rbx.utils import model_from_yaml

        contest = model_from_yaml(Contest, dest.read_text())
        assert contest.name == 'div3-c'
        assert contest.problems == []
        # contest.rbx.yml (the dispatcher sentinel) is untouched.
        assert (tmp_path / 'contest.rbx.yml').read_text() == 'use_variants: true\n'

    def test_preset_flag_is_honored(self, runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_dispatcher(tmp_path)
        # No active preset in cwd; pass one explicitly as a local dir path. This
        # exercises the `fetch_info is not None` branch of `add_variant`.
        preset_dir = _make_minimal_preset(tmp_path / '_src_preset')

        result = runner.invoke(
            contest_main.app, ['add_variant', 'div3', '--preset', str(preset_dir)]
        )

        assert result.exit_code == 0, result.output
        dest = tmp_path / 'contest.div3.rbx.yml'
        assert dest.exists()
        from rbx.box.contest.schema import Contest
        from rbx.utils import model_from_yaml

        contest = model_from_yaml(Contest, dest.read_text())
        assert contest.name == 'div3-c'
        assert contest.problems == []
        # contest.rbx.yml (the dispatcher sentinel) is untouched.
        assert (tmp_path / 'contest.rbx.yml').read_text() == 'use_variants: true\n'

    def test_add_variant_skips_library_materialization(
        self, runner, tmp_path, monkeypatch
    ):
        # add_variant installs the contest into a throwaway scratch dir only to
        # read its templated contest.rbx.yml, so it must NOT fetch/materialize
        # the preset's libraries. Declaring a library with a bogus source (which
        # would raise on fetch, offline) proves the scratch install skips it.
        monkeypatch.chdir(tmp_path)
        _write_dispatcher(tmp_path)
        preset_dir = _make_minimal_preset(tmp_path / '_src_preset')
        (preset_dir / 'preset.rbx.yml').write_text(
            (preset_dir / 'preset.rbx.yml').read_text() + 'libraries:\n'
            '  contest:\n'
            '    - name: bogus\n'
            '      source: "not a valid source"\n'
            '      dest: bogus.h\n'
        )

        result = runner.invoke(
            contest_main.app, ['add_variant', 'div3', '--preset', str(preset_dir)]
        )

        assert result.exit_code == 0, result.output
        assert (tmp_path / 'contest.div3.rbx.yml').exists()

    def test_invalid_scaffold_rolls_back(self, runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_dispatcher(tmp_path)
        original = (tmp_path / 'contest.rbx.yml').read_text()
        from rbx.box import presets

        presets.install_preset_from_dir(
            _make_minimal_preset(tmp_path / '_src_preset', invalid=True),
            tmp_path / '.local.rbx',
        )

        result = runner.invoke(contest_main.app, ['add_variant', 'div3'])

        assert result.exit_code != 0, result.output
        # The scaffolded file was unlinked by the rollback.
        assert not (tmp_path / 'contest.div3.rbx.yml').exists()
        # The dispatcher sentinel is untouched.
        assert (tmp_path / 'contest.rbx.yml').read_text() == original

    def test_scaffold_in_real_contest_mode(self, runner, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write_single_contest(tmp_path)
        original = (tmp_path / 'contest.rbx.yml').read_text()
        from rbx.box import presets

        presets.install_preset_from_dir(
            _make_minimal_preset(tmp_path / '_src_preset'), tmp_path / '.local.rbx'
        )

        result = runner.invoke(contest_main.app, ['add_variant', 'extra'])

        assert result.exit_code == 0, result.output
        assert (tmp_path / 'contest.extra.rbx.yml').exists()
        assert (tmp_path / 'contest.rbx.yml').read_text() == original
        from rbx.box.contest import contest_package

        contest_package.find_contest_yaml.cache_clear()
        variants = contest_package.discover_contest_variants(tmp_path)
        assert 'extra' in variants


class TestContestOn:
    """`rbx on` dispatch: inline fast path vs. the queued command app."""

    @pytest.fixture
    def contest_dir(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        clear_package_caches,
    ) -> pathlib.Path:
        monkeypatch.chdir(tmp_path)
        (tmp_path / 'contest.rbx.yml').write_text(
            'name: ctt\nproblems:\n  - short_name: A\n    path: probs/a\n'
        )
        _write_minimal_problem(tmp_path / 'probs' / 'a', 'prob-a')
        return tmp_path

    @pytest.fixture
    def variant_contest_dir(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        clear_package_caches,
    ) -> pathlib.Path:
        # A real canonical contest that does NOT list the problem, plus a
        # `warmup` variant that does -- the shape that made `-C` mandatory.
        monkeypatch.chdir(tmp_path)
        (tmp_path / 'contest.rbx.yml').write_text('name: ctt\nproblems: []\n')
        (tmp_path / 'contest.warmup.rbx.yml').write_text(
            'name: warmup\nproblems:\n  - short_name: A\n    path: probs/a\n'
        )
        _write_minimal_problem(tmp_path / 'probs' / 'a', 'prob-a')
        return tmp_path

    def test_single_command_on_single_problem_runs_inline(
        self, runner: CliRunner, contest_dir: pathlib.Path
    ):
        with (
            mock.patch.object(contest_main.subprocess, 'call', return_value=0) as call,
            mock.patch('rbx.box.ui.command_app.start_command_app') as start_app,
        ):
            result = runner.invoke(contest_main.app, ['on', 'A', 'build'])

        assert result.exit_code == 0, result.output
        start_app.assert_not_called()
        assert call.call_args.args[0] == 'rbx build'

    def test_chained_commands_on_single_problem_open_the_app(
        self, runner: CliRunner, contest_dir: pathlib.Path
    ):
        with (
            mock.patch.object(contest_main.subprocess, 'call', return_value=0) as call,
            mock.patch('rbx.box.ui.command_app.start_command_app') as start_app,
        ):
            result = runner.invoke(
                contest_main.app, ['on', 'A', 'build', '::', 'run', '-s']
            )

        assert result.exit_code == 0, result.output
        call.assert_not_called()
        (commands,), kwargs = start_app.call_args
        assert len(commands) == 1
        assert commands[0].argvs == [['rbx', 'build'], ['rbx', 'run', '-s']]
        assert kwargs['keep_going'] is False

    def test_keep_going_flag_precedes_the_problem_selector(
        self, runner: CliRunner, contest_dir: pathlib.Path
    ):
        with mock.patch('rbx.box.ui.command_app.start_command_app') as start_app:
            result = runner.invoke(
                contest_main.app, ['on', '-k', 'A', 'build', '::', 'run']
            )

        assert result.exit_code == 0, result.output
        assert start_app.call_args.kwargs['keep_going'] is True

    def test_flags_after_the_selector_belong_to_the_chained_command(
        self, runner: CliRunner, contest_dir: pathlib.Path
    ):
        # `-k` here is `rbx run`'s business, not `rbx on`'s.
        with mock.patch('rbx.box.ui.command_app.start_command_app') as start_app:
            result = runner.invoke(
                contest_main.app, ['on', 'A', 'build', '::', 'run', '-k']
            )

        assert result.exit_code == 0, result.output
        (commands,), kwargs = start_app.call_args
        assert commands[0].argvs == [['rbx', 'build'], ['rbx', 'run', '-k']]
        assert kwargs['keep_going'] is False

    def test_selection_is_exported_to_the_inline_child(
        self,
        runner: CliRunner,
        variant_contest_dir: pathlib.Path,
        clean_contest_env,
    ):
        # `-C` only lives in a contextvar, so the child would otherwise resolve
        # the canonical contest and not find itself in its `problems[]`.
        with (
            mock.patch.object(contest_main.subprocess, 'call', return_value=0) as call,
            mock.patch('rbx.box.ui.command_app.start_command_app'),
        ):
            result = runner.invoke(
                contest_main.app, ['-C', 'warmup', 'on', 'A', 'build']
            )

        assert result.exit_code == 0, result.output
        call.assert_called_once()
        assert os.environ[contest_state.ENV_VAR] == 'warmup'

    def test_selection_is_exported_before_the_app_starts(
        self,
        runner: CliRunner,
        variant_contest_dir: pathlib.Path,
        clean_contest_env,
    ):
        seen = {}
        with mock.patch(
            'rbx.box.ui.command_app.start_command_app',
            side_effect=lambda *a, **k: seen.update(
                env=os.environ.get(contest_state.ENV_VAR)
            ),
        ):
            result = runner.invoke(
                contest_main.app, ['-C', 'warmup', 'on', 'A', 'build', '::', 'run']
            )

        assert result.exit_code == 0, result.output
        assert seen['env'] == 'warmup'

    def test_no_selection_leaves_the_env_alone(
        self,
        runner: CliRunner,
        contest_dir: pathlib.Path,
        clean_contest_env,
    ):
        with (
            mock.patch.object(contest_main.subprocess, 'call', return_value=0),
            mock.patch('rbx.box.ui.command_app.start_command_app'),
        ):
            result = runner.invoke(contest_main.app, ['on', 'A', 'build'])

        assert result.exit_code == 0, result.output
        assert contest_state.ENV_VAR not in os.environ

    def test_empty_command_in_chain_is_an_error(
        self, runner: CliRunner, contest_dir: pathlib.Path
    ):
        with mock.patch('rbx.box.ui.command_app.start_command_app') as start_app:
            result = runner.invoke(contest_main.app, ['on', 'A', 'build', '::'])

        assert result.exit_code == 1
        start_app.assert_not_called()


class TestContestEach:
    @pytest.fixture
    def contest_dir(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        clear_package_caches,
    ) -> pathlib.Path:
        monkeypatch.chdir(tmp_path)
        (tmp_path / 'contest.rbx.yml').write_text(
            'name: ctt\n'
            'problems:\n'
            '  - short_name: A\n    path: probs/a\n'
            '  - short_name: B\n    path: probs/b\n'
        )
        for name in ('a', 'b'):
            _write_minimal_problem(tmp_path / 'probs' / name, f'prob-{name}')
        return tmp_path

    def test_each_queues_the_chain_in_every_problem(
        self, runner: CliRunner, contest_dir: pathlib.Path
    ):
        with mock.patch('rbx.box.ui.command_app.start_command_app') as start_app:
            result = runner.invoke(
                contest_main.app, ['each', 'build', '::', 'package', 'build']
            )

        assert result.exit_code == 0, result.output
        (commands,), _ = start_app.call_args
        assert len(commands) == 2
        for command in commands:
            assert command.argvs == [['rbx', 'build'], ['rbx', 'package', 'build']]

    def test_each_exports_the_selection_before_the_app_starts(
        self,
        runner: CliRunner,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        clear_package_caches,
        clean_contest_env,
    ):
        monkeypatch.chdir(tmp_path)
        (tmp_path / 'contest.rbx.yml').write_text('name: ctt\nproblems: []\n')
        (tmp_path / 'contest.warmup.rbx.yml').write_text(
            'name: warmup\nproblems:\n  - short_name: A\n    path: probs/a\n'
        )
        _write_minimal_problem(tmp_path / 'probs' / 'a', 'prob-a')

        seen = {}
        with mock.patch(
            'rbx.box.ui.command_app.start_command_app',
            side_effect=lambda *a, **k: seen.update(
                env=os.environ.get(contest_state.ENV_VAR)
            ),
        ):
            result = runner.invoke(contest_main.app, ['-C', 'warmup', 'each', 'build'])

        assert result.exit_code == 0, result.output
        assert seen['env'] == 'warmup'

    def test_each_without_args_opens_an_empty_app(
        self, runner: CliRunner, contest_dir: pathlib.Path
    ):
        """With no history recorded, a blank session -- the long-standing behaviour."""
        with mock.patch('rbx.box.ui.command_app.start_command_app') as start_app:
            result = runner.invoke(contest_main.app, ['each'])

        assert result.exit_code == 0, result.output
        (commands,), _ = start_app.call_args
        assert all(command.argvs == [] for command in commands)
        assert all(command.placeholder_prefix == 'rbx' for command in commands)

    def test_each_without_args_offers_the_run_history(
        self, runner: CliRunner, contest_dir: pathlib.Path
    ):
        with (
            mock.patch(
                'rbx.box.ui.run_picker.open_run_history', return_value='done'
            ) as history,
            mock.patch('rbx.box.ui.command_app.start_command_app') as start_app,
        ):
            result = runner.invoke(contest_main.app, ['each'])

        assert result.exit_code == 0, result.output
        history.assert_called_once_with(None)
        # The picker handled it; no session was started behind it.
        start_app.assert_not_called()

    def test_each_falls_back_to_a_blank_session_when_asked_for_a_new_one(
        self, runner: CliRunner, contest_dir: pathlib.Path
    ):
        with (
            mock.patch('rbx.box.ui.run_picker.open_run_history', return_value='new'),
            mock.patch('rbx.box.ui.command_app.start_command_app') as start_app,
        ):
            result = runner.invoke(contest_main.app, ['each'])

        assert result.exit_code == 0, result.output
        (commands,), _ = start_app.call_args
        assert all(command.argvs == [] for command in commands)

    def test_on_with_a_selector_and_no_command_filters_the_history(
        self, runner: CliRunner, contest_dir: pathlib.Path
    ):
        with mock.patch(
            'rbx.box.ui.run_picker.open_run_history', return_value='done'
        ) as history:
            result = runner.invoke(contest_main.app, ['on', 'A'])

        assert result.exit_code == 0, result.output
        (problem_names,), _ = history.call_args
        # The same label the run manifest stores as the tab name, so the filter
        # matches on exactly what was recorded.
        assert problem_names == ['A. prob-a']

    def test_on_without_a_selector_and_no_history_explains_itself(
        self, runner: CliRunner, contest_dir: pathlib.Path
    ):
        with mock.patch('rbx.box.ui.run_picker.open_run_history', return_value='none'):
            result = runner.invoke(contest_main.app, ['on'])

        assert result.exit_code == 1
        assert 'No recorded runs' in result.output


class TestContestInline:
    """`--inline`: the whole chain runs in this terminal, TUI untouched."""

    @pytest.fixture
    def contest_dir(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        clear_package_caches,
    ) -> pathlib.Path:
        monkeypatch.chdir(tmp_path)
        (tmp_path / 'contest.rbx.yml').write_text(
            'name: ctt\n'
            'problems:\n'
            '  - short_name: A\n    path: probs/a\n'
            '  - short_name: B\n    path: probs/b\n'
        )
        for name in ('a', 'b'):
            _write_minimal_problem(tmp_path / 'probs' / name, f'prob-{name}')
        return tmp_path

    def test_each_inline_runs_every_chain_in_the_terminal(
        self, runner: CliRunner, contest_dir: pathlib.Path
    ):
        with (
            mock.patch.object(contest_main.subprocess, 'call', return_value=0) as call,
            mock.patch('rbx.box.ui.command_app.start_command_app') as start_app,
        ):
            result = runner.invoke(
                contest_main.app, ['each', '--inline', 'build', '::', 'run', '-s']
            )

        assert result.exit_code == 0, result.output
        start_app.assert_not_called()
        assert [c.args[0] for c in call.call_args_list] == [
            'rbx build',
            'rbx run -s',
            'rbx build',
            'rbx run -s',
        ]
        assert [str(c.kwargs['cwd']) for c in call.call_args_list] == [
            'probs/a',
            'probs/a',
            'probs/b',
            'probs/b',
        ]

    def test_on_inline_runs_a_chain_over_a_range_of_problems(
        self, runner: CliRunner, contest_dir: pathlib.Path
    ):
        with (
            mock.patch.object(contest_main.subprocess, 'call', return_value=0) as call,
            mock.patch('rbx.box.ui.command_app.start_command_app') as start_app,
        ):
            result = runner.invoke(
                contest_main.app, ['on', '-i', 'A..B', 'build', '::', 'run']
            )

        assert result.exit_code == 0, result.output
        start_app.assert_not_called()
        assert [c.args[0] for c in call.call_args_list] == [
            'rbx build',
            'rbx run',
            'rbx build',
            'rbx run',
        ]

    def test_a_failing_command_skips_the_rest_of_its_own_chain_only(
        self, runner: CliRunner, contest_dir: pathlib.Path
    ):
        # `rbx build` fails in the first problem; its `rbx run` is skipped, but
        # the second problem still runs its whole chain.
        codes = {'rbx build': 1}
        with mock.patch.object(
            contest_main.subprocess,
            'call',
            side_effect=lambda cmd, **kwargs: codes.pop(cmd, 0),
        ) as call:
            result = runner.invoke(
                contest_main.app, ['each', '--inline', 'build', '::', 'run']
            )

        assert result.exit_code == 1, result.output
        assert [c.args[0] for c in call.call_args_list] == [
            'rbx build',
            'rbx build',
            'rbx run',
        ]
        assert 'failed' in result.output

    def test_keep_going_runs_the_rest_of_a_failing_chain(
        self, runner: CliRunner, contest_dir: pathlib.Path
    ):
        codes = {'rbx build': 1}
        with mock.patch.object(
            contest_main.subprocess,
            'call',
            side_effect=lambda cmd, **kwargs: codes.pop(cmd, 0),
        ) as call:
            result = runner.invoke(
                contest_main.app, ['each', '-k', '--inline', 'build', '::', 'run']
            )

        # The chain kept going, but the failure still shows in the exit code.
        assert result.exit_code == 1, result.output
        assert [c.args[0] for c in call.call_args_list] == [
            'rbx build',
            'rbx run',
            'rbx build',
            'rbx run',
        ]

    def test_inline_without_a_command_is_an_error(
        self, runner: CliRunner, contest_dir: pathlib.Path
    ):
        with (
            mock.patch('rbx.box.ui.run_picker.open_run_history') as history,
            mock.patch('rbx.box.ui.command_app.start_command_app') as start_app,
        ):
            result = runner.invoke(contest_main.app, ['each', '--inline'])

        assert result.exit_code == 1
        assert 'No command to run' in result.output
        # Neither the history picker nor a blank session may open in this mode.
        history.assert_not_called()
        start_app.assert_not_called()

    def test_on_inline_without_a_command_is_an_error(
        self, runner: CliRunner, contest_dir: pathlib.Path
    ):
        with (
            mock.patch('rbx.box.ui.run_picker.open_run_history') as history,
            mock.patch('rbx.box.ui.command_app.start_command_app') as start_app,
        ):
            result = runner.invoke(contest_main.app, ['on', '-i', 'A'])

        assert result.exit_code == 1
        assert 'No command to run' in result.output
        history.assert_not_called()
        start_app.assert_not_called()

    def test_a_shell_command_stays_unprefixed_inline(
        self, runner: CliRunner, contest_dir: pathlib.Path
    ):
        with mock.patch.object(contest_main.subprocess, 'call', return_value=0) as call:
            result = runner.invoke(contest_main.app, ['each', '--inline', 'bash', '-c'])

        assert result.exit_code == 0, result.output
        assert [c.args[0] for c in call.call_args_list] == ['bash -c', 'bash -c']
