"""Tests for rbx.box.creation (the `rbx create` command)."""

import pathlib
from types import SimpleNamespace
from unittest import mock

import pytest
import ruyaml
import typer

from rbx import utils
from rbx.box import creation
from rbx.box.schema import Package

# Stands in for the ResolvedTemplate that install_problem returns, so the test
# can check it is the one handed to generate_lock.
_STUB_TEMPLATE = SimpleNamespace(variant_id='interactive')


def _install_problem_stub(
    dest_pkg: pathlib.Path,
    fetch_info=None,
    materialize=True,
    variant=None,
    languages=None,
    inherit_languages=False,
):
    """Mimic presets.install_problem: create the folder and a minimal package,
    and return the template that was installed."""
    dest_pkg.mkdir(parents=True, exist_ok=True)
    (dest_pkg / 'problem.rbx.yml').write_text(
        'name: "placeholder"\ntimeLimit: 1000\nmemoryLimit: 256\n'
    )
    return _STUB_TEMPLATE


def _read_name(dest: pathlib.Path) -> str:
    yaml = ruyaml.YAML()
    data = yaml.load((dest / 'problem.rbx.yml').read_text())
    return data['name']


@pytest.fixture
def mock_presets():
    with (
        mock.patch.object(
            creation.presets,
            'get_preset_fetch_info_with_fallback',
            return_value=SimpleNamespace(),
        ),
        mock.patch.object(
            creation.presets, 'install_problem', side_effect=_install_problem_stub
        ) as install_problem,
        mock.patch.object(creation.presets, 'generate_lock') as generate_lock,
    ):
        yield SimpleNamespace(
            generate_lock=generate_lock, install_problem=install_problem
        )


def test_create_with_plain_name(cleandir, mock_presets):
    creation.create('my-problem')

    dest = pathlib.Path('my-problem')
    assert dest.is_dir()
    assert _read_name(dest) == 'my-problem'


def test_create_with_relative_path_uses_basename_as_name(cleandir, mock_presets):
    creation.create('problems/my-problem')

    # Folder is created at the full relative path...
    dest = pathlib.Path('problems/my-problem')
    assert dest.is_dir()

    # ...but the problem name is only the basename, and it is a valid name.
    name = _read_name(dest)
    assert name == 'my-problem'
    utils.validate_field(Package, 'name', name)


def test_create_locks_the_template_it_installed(cleandir, mock_presets):
    # The lock must describe the template that was actually installed, never a
    # separately-resolved one.
    creation.create('my-problem')

    mock_presets.generate_lock.assert_called_once_with(
        pathlib.Path('my-problem'), template=_STUB_TEMPLATE
    )


def test_create_with_invalid_derived_name_fails_fast(cleandir, mock_presets):
    # Basename `ab` is too short (min 3 chars): fail before creating anything.
    with pytest.raises(typer.Exit):
        creation.create('problems/ab')

    assert not pathlib.Path('problems/ab').exists()
    assert not pathlib.Path('problems').exists()


def test_create_passes_languages_through(cleandir, mock_presets):
    creation.create('my-problem', languages=['en', 'pt'])

    kwargs = mock_presets.install_problem.call_args.kwargs
    assert kwargs['languages'] == ['en', 'pt']
    assert kwargs['inherit_languages'] is False


def test_create_inside_contest_inherits_its_languages(cleandir, mock_presets):
    # `rbx contest add` lands here: the problem follows the contest's list and
    # carries no list of its own.
    (cleandir / 'contest.rbx.yml').write_text(
        'name: "contest"\nlanguages: ["en", "pt"]\n'
    )

    creation.create('my-problem')

    kwargs = mock_presets.install_problem.call_args.kwargs
    assert kwargs['languages'] == ['en', 'pt']
    assert kwargs['inherit_languages'] is True


def test_create_inside_contest_without_list_keeps_everything(cleandir, mock_presets):
    (cleandir / 'contest.rbx.yml').write_text('name: "contest"\n')

    creation.create('my-problem')

    kwargs = mock_presets.install_problem.call_args.kwargs
    assert kwargs['languages'] is None
    assert kwargs['inherit_languages'] is True


@pytest.mark.parametrize(
    'raw, expected',
    [
        (None, None),
        (['en'], ['en']),
        (['en,pt', 'es'], ['en', 'pt', 'es']),
        ([' en , pt '], ['en', 'pt']),
    ],
)
def test_split_languages(raw, expected):
    assert creation.split_languages(raw) == expected
