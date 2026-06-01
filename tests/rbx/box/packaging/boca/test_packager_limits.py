"""Regression tests for BOCA per-language limit resolution.

When the default preset aliases the rbx ``cpp`` language onto both BOCA variants
``cc`` and ``cpp`` (see #453), the package's ``cpp`` limit modifier must apply to
*both* emitted variants. Looking the limit up by the raw BOCA name made ``cc``
miss the modifier and fall back to the base limit (#493).
"""

from unittest import mock

from rbx.box.packaging.boca import boca_language_utils
from rbx.box.packaging.boca.extension import BocaLanguageExtension
from rbx.box.packaging.boca.packager import BocaPackager
from rbx.box.schema import LimitModifiers


def _env_aliasing_cpp_to_cc_and_cpp():
    cpp_lang = mock.MagicMock()
    cpp_lang.name = 'cpp'
    cpp_lang.get_extension_or_default.return_value = BocaLanguageExtension(
        languages=['cc', 'cpp']
    )
    env = mock.MagicMock()
    env.languages = [cpp_lang]
    return env


def test_cc_inherits_cpp_limit_modifier(testing_pkg, monkeypatch):
    env = _env_aliasing_cpp_to_cc_and_cpp()
    monkeypatch.setattr(boca_language_utils, 'get_environment', lambda: env)
    monkeypatch.setattr(
        boca_language_utils, 'get_language_by_extension_or_nil', lambda _: None
    )

    testing_pkg.yml.timeLimit = 1000
    testing_pkg.yml.memoryLimit = 256
    testing_pkg.yml.modifiers = {'cpp': LimitModifiers(time=2000, memory=512)}
    testing_pkg.save()

    packager = BocaPackager(testcase_entries=[])

    # cpp resolves its own modifier; cc must resolve the same underlying rbx
    # entry rather than falling back to the base limit.
    assert packager._get_pkg_timelimit('cpp') == 2000  # noqa: SLF001
    assert packager._get_pkg_timelimit('cc') == 2000  # noqa: SLF001
    assert packager._get_pkg_memorylimit('cpp') == 512  # noqa: SLF001
    assert packager._get_pkg_memorylimit('cc') == 512  # noqa: SLF001
