"""Preset-created packages carry a version-pinned schema header.

Preset templates (including third-party ones) hardcode a schema URL, so
materialization has to normalize it.
"""

import contextlib
import pathlib
from unittest import mock

import pytest

from rbx import testing_utils
from rbx.box import presets, schema_urls

UNVERSIONED = 'https://rsalesc.github.io/rbx/schemas/Package.json'
VERSIONED = 'https://rsalesc.github.io/rbx-schemas'


@pytest.fixture(autouse=True)
def _clear_cache():
    schema_urls.preset_min_version.cache_clear()
    yield
    schema_urls.preset_min_version.cache_clear()


def _make_local_preset(
    dest: pathlib.Path,
    *,
    kind: str,
    min_version: str = '1.4.0',
) -> None:
    """Lay out `dest/.local.rbx` as an installed preset with one template."""
    local = dest / '.local.rbx'
    template_dir = local / kind
    template_dir.mkdir(parents=True, exist_ok=True)
    (local / 'preset.rbx.yml').write_text(
        f'name: "test-preset"\n'
        f'uri: "rsalesc/test-preset"\n'
        f'min_version: "{min_version}"\n'
        f'{kind}: "{kind}"\n'
    )
    filename = 'problem.rbx.yml' if kind == 'problem' else 'contest.rbx.yml'
    (template_dir / filename).write_text(
        f'---\n# yaml-language-server: $schema={UNVERSIONED}\nname: "template"\n'
    )


@contextlib.contextmanager
def _installed_version(version: str):
    """Pretend rbx is at `version`.

    A preset whose `min_version` exceeds the installed version is rejected
    outright by the compatibility gate, so a pinning test has to run as a
    version that can actually install the preset.
    """
    with mock.patch('rbx.utils.get_version', return_value=version):
        # The compatibility verdict is cached per (name, version), so the
        # faked version has to be visible before anything consults it.
        testing_utils.clear_all_functools_cache()
        try:
            yield
        finally:
            testing_utils.clear_all_functools_cache()


def test_install_problem_pins_schema_header(cleandir):
    dest = pathlib.Path('problem-pkg')
    dest.mkdir()
    _make_local_preset(dest, kind='problem')

    with _installed_version('1.4.0'):
        presets.install_problem(dest, materialize=False)

    content = (dest / 'problem.rbx.yml').read_text()
    assert f'$schema={VERSIONED}/1.4/Package.json' in content
    assert UNVERSIONED not in content


def test_install_contest_pins_schema_header(cleandir):
    dest = pathlib.Path('contest-pkg')
    dest.mkdir()
    _make_local_preset(dest, kind='contest')

    with _installed_version('1.4.0'):
        presets.install_contest(dest, materialize=False)

    content = (dest / 'contest.rbx.yml').read_text()
    assert f'$schema={VERSIONED}/1.4/Contest.json' in content
    assert UNVERSIONED not in content


def test_install_problem_keeps_unversioned_below_floor(cleandir):
    dest = pathlib.Path('old-preset-pkg')
    dest.mkdir()
    _make_local_preset(dest, kind='problem', min_version='1.0.0')

    with _installed_version('1.0.0'):
        presets.install_problem(dest, materialize=False)

    content = (dest / 'problem.rbx.yml').read_text()
    assert UNVERSIONED in content
    assert VERSIONED not in content
