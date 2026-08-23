import pathlib

from rbx.box.vscode import extension


def test_bundled_vsix_is_none_when_directory_is_absent(tmp_path: pathlib.Path):
    assert extension.bundled_vsix(tmp_path / 'nope') is None


def test_bundled_vsix_reads_version_from_filename(tmp_path: pathlib.Path):
    (tmp_path / 'rbx-vscode-0.2.0.vsix').touch()

    found = extension.bundled_vsix(tmp_path)

    assert found is not None
    assert found.version == '0.2.0'
    assert found.path == tmp_path / 'rbx-vscode-0.2.0.vsix'


def test_bundled_vsix_picks_the_newest_when_several_are_present(
    tmp_path: pathlib.Path,
):
    # A checkout that built the extension twice keeps both files around; the
    # newest is the one this rbx is meant to ship. Note 0.10.0 > 0.2.0 only
    # under semver -- lexicographically it is the other way around.
    (tmp_path / 'rbx-vscode-0.2.0.vsix').touch()
    (tmp_path / 'rbx-vscode-0.10.0.vsix').touch()

    found = extension.bundled_vsix(tmp_path)

    assert found is not None
    assert found.version == '0.10.0'


def test_bundled_vsix_ignores_files_it_cannot_version(tmp_path: pathlib.Path):
    (tmp_path / 'something-else.vsix').touch()
    (tmp_path / 'rbx-vscode-not-a-version.vsix').touch()

    assert extension.bundled_vsix(tmp_path) is None
