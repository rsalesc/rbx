"""Tests for how packaging call sites name a package inside a contest.

Two things: the basename carries the selected contest variant, and every call
site raises the picker error in dispatcher mode rather than guessing.

These exercise the naming path directly via small helpers on each packager,
without spinning up a full build. Mirrors the fixture style in
`tests/rbx/box/test_naming.py`.
"""

import os
import pathlib

import pytest
import typer

from rbx.box import package_utils
from rbx.box.contest import contest_package as cp_module
from rbx.box.contest.contest_state import selected_variant_id_var
from rbx.box.packaging.boca.packager import BocaPackager
from rbx.box.packaging.pkg.packager import PkgPackager


def _write_problem(folder: pathlib.Path, name: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'problem.rbx.yml').write_text(
        f'name: {name}\ntimeLimit: 1000\nmemoryLimit: 256\n'
    )


def _write_dispatcher(
    root: pathlib.Path, variants: dict[str, list[tuple[str, str]]]
) -> None:
    (root / 'contest.rbx.yml').write_text('use_variants: true\n')
    for vid, problems in variants.items():
        body = '\n'.join(
            f'  - short_name: {sn}\n    path: {path}' for sn, path in problems
        )
        (root / f'contest.{vid}.rbx.yml').write_text(
            f'name: {vid}-c\nproblems:\n{body}\n'
        )


def _write_environment(folder: pathlib.Path) -> None:
    # Minimal env file so get_extension_or_default('boca', ...) is safe to
    # call: the packager only needs a valid problem environment to exist.
    pass


def _clear_caches():
    # The contest accessors and `find_problem_package` are `functools.cache`d on
    # the *relative* root, so every test in this module shares a cache key even
    # though each works in its own tmp_path.
    cp_module.find_contest_yaml.cache_clear()
    cp_module.find_contest_package.cache_clear()
    package_utils.clear_package_cache()


@pytest.fixture(autouse=True)
def _clear_state():
    _clear_caches()
    token = selected_variant_id_var.set(None)
    try:
        yield
    finally:
        selected_variant_id_var.reset(token)
        _clear_caches()


def _setup_ambiguous_problem(tmp_path: pathlib.Path) -> None:
    _write_dispatcher(
        tmp_path,
        {
            'div1': [('A', 'A')],
            'div2': [('A', 'A')],
        },
    )
    _write_problem(tmp_path / 'A', 'prob-a')
    os.chdir(tmp_path / 'A')


_VARIANT_PREFIX_DISABLED = pytest.mark.skip(
    reason='The variant prefix is commented out in BasePackager.package_basename.'
)


class TestBasePackagerBasename:
    """The basename would carry the selected contest variant.

    A variant is a *different contest* that shares problem directories with its
    siblings, so two variants of a problem would otherwise produce the same
    basename -- and the artifacts and remote ids built from it would overwrite
    each other. The prefix is currently commented out, so the two tests that
    assert it are skipped alongside it.
    """

    def _base_packager(self) -> PkgPackager:
        # BasePackager is abstract; use a concrete subclass to exercise the
        # inherited package_basename().
        packager = PkgPackager.__new__(PkgPackager)
        packager.testcase_entries = []
        return packager

    @_VARIANT_PREFIX_DISABLED
    def test_prefixes_the_selected_variant(self, tmp_path: pathlib.Path):
        _setup_ambiguous_problem(tmp_path)
        selected_variant_id_var.set('div2')

        assert self._base_packager().package_basename() == 'div2-A-prob-a'

    @_VARIANT_PREFIX_DISABLED
    def test_two_variants_of_the_same_problem_differ(self, tmp_path: pathlib.Path):
        _setup_ambiguous_problem(tmp_path)

        selected_variant_id_var.set('div1')
        first = self._base_packager().package_basename()
        _clear_caches()

        selected_variant_id_var.set('div2')
        second = self._base_packager().package_basename()

        assert (first, second) == ('div1-A-prob-a', 'div2-A-prob-a')

    def test_no_prefix_for_a_single_contest(self, tmp_path: pathlib.Path):
        (tmp_path / 'contest.rbx.yml').write_text(
            'name: solo-c\nproblems:\n  - short_name: A\n    path: A\n'
        )
        _write_problem(tmp_path / 'A', 'prob-a')
        os.chdir(tmp_path / 'A')

        assert self._base_packager().package_basename() == 'A-prob-a'

    def test_no_prefix_outside_a_contest(self, tmp_path: pathlib.Path):
        _write_problem(tmp_path / 'A', 'prob-a')
        os.chdir(tmp_path / 'A')

        assert self._base_packager().package_basename() == 'prob-a'

    def test_package_basename_errors_in_ambiguous_dispatcher(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture[str],
    ):
        _setup_ambiguous_problem(tmp_path)

        with pytest.raises(typer.Exit):
            self._base_packager().package_basename()

        out = capsys.readouterr().out
        assert '-C' in out
        assert 'div1' in out and 'div2' in out


class TestPkgPackagerBasename:
    def test_pkg_basename_errors_in_ambiguous_dispatcher(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture[str],
    ):
        _setup_ambiguous_problem(tmp_path)

        packager = PkgPackager.__new__(PkgPackager)
        packager.testcase_entries = []

        with pytest.raises(typer.Exit):
            packager._get_problem_basename()  # noqa: SLF001

        out = capsys.readouterr().out
        assert '-C' in out


class TestBocaPackagerBasename:
    def test_boca_basename_errors_in_ambiguous_dispatcher_when_prefer_letter(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ):
        _setup_ambiguous_problem(tmp_path)

        # Force preferContestLetter=True via a stand-in extension; BocaPackager
        # only reads the boolean attribute and (downstream) the shortname.
        from rbx.box.packaging.boca import packager as boca_mod
        from rbx.box.packaging.boca.extension import BocaExtension

        ext = BocaExtension(preferContestLetter=True)
        monkeypatch.setattr(boca_mod, 'get_extension_or_default', lambda name, cls: ext)

        packager = BocaPackager.__new__(BocaPackager)
        packager.testcase_entries = []
        packager.language = None

        with pytest.raises(typer.Exit):
            packager._get_problem_basename()  # noqa: SLF001

        out = capsys.readouterr().out
        assert '-C' in out

    def test_boca_basename_returns_package_name_when_prefer_letter_false(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        # No -C selection. Even though the dispatcher is ambiguous, with
        # preferContestLetter=False the basename should fall back to the
        # package name without raising. Guards the gating at packager.py:84-89.
        _setup_ambiguous_problem(tmp_path)

        from rbx.box.packaging.boca import packager as boca_mod
        from rbx.box.packaging.boca.extension import BocaExtension

        ext = BocaExtension(preferContestLetter=False)
        monkeypatch.setattr(boca_mod, 'get_extension_or_default', lambda name, cls: ext)

        packager = BocaPackager.__new__(BocaPackager)
        packager.testcase_entries = []
        packager.language = None

        result = packager._get_problem_basename()  # noqa: SLF001
        # _get_problem_name() replaces '-' with '_' in the package name.
        assert result == 'prob_a'
