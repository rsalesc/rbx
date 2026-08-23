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


def test_detect_editor_is_none_outside_an_integrated_terminal():
    assert extension.detect_editor({}) is None
    assert extension.detect_editor({'TERM_PROGRAM': 'iTerm.app'}) is None


def test_detect_editor_defaults_to_vscode_without_an_app_path():
    found = extension.detect_editor({'TERM_PROGRAM': 'vscode'})

    assert found is not None
    assert found.key == 'code'


def test_detect_editor_recognizes_forks_by_their_app_path():
    # Every fork reports TERM_PROGRAM=vscode, so the app path is the only thing
    # that tells them apart -- and each of these paths contains 'code' too.
    cases = {
        '/Applications/Cursor.app/Contents/Resources/app/out/node': 'cursor',
        '/usr/share/cursor/resources/app/out/node': 'cursor',
        '/Applications/Windsurf.app/Contents/Resources/app/out/node': 'windsurf',
        '/usr/share/codium/resources/app/out/node': 'codium',
        '/Applications/Visual Studio Code - Insiders.app/Contents/Resources/app/out/node': 'code-insiders',
        '/Applications/Visual Studio Code.app/Contents/Resources/app/out/node': 'code',
    }
    for path, expected in cases.items():
        found = extension.detect_editor(
            {'TERM_PROGRAM': 'vscode', 'VSCODE_GIT_ASKPASS_NODE': path}
        )
        assert found is not None, path
        assert found.key == expected, path


def test_detect_editor_falls_back_to_the_askpass_main_path():
    found = extension.detect_editor(
        {
            'TERM_PROGRAM': 'vscode',
            'VSCODE_GIT_ASKPASS_MAIN': '/Applications/Cursor.app/Contents/x.js',
        }
    )

    assert found is not None
    assert found.key == 'cursor'


def test_editor_by_key_allows_an_explicit_override():
    cursor = extension.editor_by_key('cursor')

    assert cursor is not None
    assert cursor.binary == 'cursor'
    assert extension.editor_by_key('nope') is None
