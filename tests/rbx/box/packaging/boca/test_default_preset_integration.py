"""Integration tests pinning the cc/cpp aliasing contract end-to-end against the
default preset.

These tests load `rbx/resources/presets/default/env.rbx.yml` directly (no mocks
of the env), so they exercise the real schema, the union helper, and the
template-name resolution as a real user would on the default preset. They are
the behavioral counterpart to the unit tests in `test_language_utils.py`.
"""

from rbx.box.environment import Environment
from rbx.box.packaging.boca import boca_language_utils
from rbx.box.yaml_validation import load_yaml_model
from rbx.config import get_default_app_path


def _load_default_env() -> Environment:
    preset_path = get_default_app_path() / 'presets' / 'default' / 'env.rbx.yml'
    return load_yaml_model(preset_path, Environment)


def test_default_preset_emits_cc_and_cpp(monkeypatch):
    env = _load_default_env()
    monkeypatch.setattr(boca_language_utils, 'get_environment', lambda: env)

    emitted = boca_language_utils.get_emitted_boca_languages()
    # The default preset must emit both 'cc' (legacy BOCA) and 'cpp' (new BOCA
    # default), plus the rest of the configured languages.
    assert set(emitted) == {'cc', 'cpp', 'c', 'py3', 'java', 'kt'}
    # cpp is declared first in env.languages with languages=['cc', 'cpp'],
    # so 'cc' comes first, 'cpp' second — order pins the aliasing intent.
    assert emitted[:2] == ['cc', 'cpp']


def test_default_preset_cc_and_cpp_share_cc_template(monkeypatch):
    env = _load_default_env()
    monkeypatch.setattr(boca_language_utils, 'get_environment', lambda: env)

    # Both emitted BOCA names must source from the SAME on-disk template, so
    # compile/cc and compile/cpp end up with identical content in the BOCA
    # package — that's the whole point of the aliasing.
    assert boca_language_utils.get_boca_template_name('cc') == 'cc'
    assert boca_language_utils.get_boca_template_name('cpp') == 'cc'


def test_default_preset_other_languages_use_their_own_template(monkeypatch):
    env = _load_default_env()
    monkeypatch.setattr(boca_language_utils, 'get_environment', lambda: env)

    assert boca_language_utils.get_boca_template_name('c') == 'c'
    assert boca_language_utils.get_boca_template_name('py3') == 'py3'
    assert boca_language_utils.get_boca_template_name('java') == 'java'
    assert boca_language_utils.get_boca_template_name('kt') == 'kt'


def test_default_preset_template_dirs_exist_on_disk():
    """Every template the default preset relies on must exist under
    rbx/resources/packagers/boca/{compile,run,interactive}/ — otherwise the
    packager would error out at emission time."""
    templates = {'cc', 'c', 'py3', 'java', 'kt'}
    boca_resources = get_default_app_path() / 'packagers' / 'boca'
    for sub in ('compile', 'run', 'interactive'):
        for name in templates:
            template_path = boca_resources / sub / name
            assert template_path.is_file(), (
                f'expected {sub}/{name} template at {template_path}'
            )
