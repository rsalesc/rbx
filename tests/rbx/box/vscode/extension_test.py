import json
import pathlib
from typing import Any, List

from rbx.box.vscode import extension


def _write_extensions_json(root: pathlib.Path, entries: List[Any]) -> pathlib.Path:
    extensions = root / 'extensions'
    extensions.mkdir(parents=True, exist_ok=True)
    (extensions / 'extensions.json').write_text(json.dumps(entries))
    return root


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


def test_installed_version_is_none_without_an_extensions_file(tmp_path: pathlib.Path):
    assert extension.installed_version(tmp_path) is None


def test_installed_version_reads_the_entry_for_our_extension(tmp_path: pathlib.Path):
    _write_extensions_json(
        tmp_path,
        [
            {'identifier': {'id': 'ms-python.python'}, 'version': '2024.1.0'},
            {'identifier': {'id': 'rsalesc.rbx-vscode'}, 'version': '0.1.0'},
        ],
    )

    assert extension.installed_version(tmp_path) == '0.1.0'


def test_installed_version_is_none_when_our_extension_is_absent(
    tmp_path: pathlib.Path,
):
    _write_extensions_json(
        tmp_path, [{'identifier': {'id': 'ms-python.python'}, 'version': '2024.1.0'}]
    )

    assert extension.installed_version(tmp_path) is None


def test_installed_version_is_none_when_the_file_is_malformed(tmp_path: pathlib.Path):
    # A half-written extensions.json must never break `rbx run`.
    extensions = tmp_path / 'extensions'
    extensions.mkdir(parents=True)
    (extensions / 'extensions.json').write_text('{not json')

    assert extension.installed_version(tmp_path) is None


def test_installed_version_tolerates_entries_of_the_wrong_shape(
    tmp_path: pathlib.Path,
):
    _write_extensions_json(
        tmp_path,
        [
            'not-a-dict',
            {'identifier': 'not-a-dict'},
            {'identifier': {'id': 'rsalesc.rbx-vscode'}, 'version': '0.1.0'},
        ],
    )

    assert extension.installed_version(tmp_path) == '0.1.0'


def test_installed_version_matches_the_id_case_insensitively(tmp_path: pathlib.Path):
    _write_extensions_json(
        tmp_path, [{'identifier': {'id': 'rsalesc.RBX-VSCode'}, 'version': '0.3.0'}]
    )

    assert extension.installed_version(tmp_path) == '0.3.0'


def test_editor_home_picks_the_first_existing_directory(tmp_path: pathlib.Path):
    editor = extension.editor_by_key('code')
    assert editor is not None
    (tmp_path / '.vscode').mkdir()

    assert extension.editor_home(editor, tmp_path) == tmp_path / '.vscode'


def test_editor_home_prefers_the_remote_directory(tmp_path: pathlib.Path):
    # Over SSH or in a devcontainer the extensions live under *-server, and that
    # is where the extension has to be for it to see .rbx/runs/ at all.
    editor = extension.editor_by_key('code')
    assert editor is not None
    (tmp_path / '.vscode').mkdir()
    (tmp_path / '.vscode-server').mkdir()

    assert extension.editor_home(editor, tmp_path) == tmp_path / '.vscode-server'


def test_editor_home_is_none_when_nothing_exists(tmp_path: pathlib.Path):
    editor = extension.editor_by_key('code')
    assert editor is not None

    assert extension.editor_home(editor, tmp_path) is None


def _bundled(tmp_path: pathlib.Path, version: str) -> pathlib.Path:
    directory = tmp_path / 'resources'
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f'rbx-vscode-{version}.vsix').touch()
    return directory


def _installed(tmp_path: pathlib.Path, version: str) -> pathlib.Path:
    _write_extensions_json(
        tmp_path / 'home' / '.vscode',
        [{'identifier': {'id': 'rsalesc.rbx-vscode'}, 'version': version}],
    )
    return tmp_path / 'home'


def test_no_hint_outside_an_integrated_terminal(tmp_path: pathlib.Path):
    assert (
        extension.outdated_hint(
            env={'TERM_PROGRAM': 'iTerm.app'},
            home=_installed(tmp_path, '0.1.0'),
            vsix_directory=_bundled(tmp_path, '0.2.0'),
        )
        is None
    )


def test_hint_when_the_installed_extension_is_older(tmp_path: pathlib.Path):
    hint = extension.outdated_hint(
        env={'TERM_PROGRAM': 'vscode'},
        home=_installed(tmp_path, '0.1.0'),
        vsix_directory=_bundled(tmp_path, '0.2.0'),
    )

    assert hint is not None
    assert '0.1.0' in hint
    assert '0.2.0' in hint
    assert 'rbx vscode install' in hint


def test_no_hint_when_nothing_is_installed(tmp_path: pathlib.Path):
    # Someone who never opted into the extension is not nagged into it.
    _write_extensions_json(tmp_path / 'home' / '.vscode', [])

    assert (
        extension.outdated_hint(
            env={'TERM_PROGRAM': 'vscode'},
            home=tmp_path / 'home',
            vsix_directory=_bundled(tmp_path, '0.2.0'),
        )
        is None
    )


def test_no_hint_when_the_installed_extension_is_current(tmp_path: pathlib.Path):
    assert (
        extension.outdated_hint(
            env={'TERM_PROGRAM': 'vscode'},
            home=_installed(tmp_path, '0.2.0'),
            vsix_directory=_bundled(tmp_path, '0.2.0'),
        )
        is None
    )


def test_no_hint_when_the_installed_extension_is_newer(tmp_path: pathlib.Path):
    # A newer extension from a marketplace is a fine state to be in.
    assert (
        extension.outdated_hint(
            env={'TERM_PROGRAM': 'vscode'},
            home=_installed(tmp_path, '0.9.0'),
            vsix_directory=_bundled(tmp_path, '0.2.0'),
        )
        is None
    )


def test_no_hint_when_no_vsix_is_bundled(tmp_path: pathlib.Path):
    assert (
        extension.outdated_hint(
            env={'TERM_PROGRAM': 'vscode'},
            home=_installed(tmp_path, '0.1.0'),
            vsix_directory=tmp_path / 'empty',
        )
        is None
    )


def test_print_outdated_hint_is_silent_when_there_is_nothing_to_say(capsys):
    extension.print_outdated_hint(env={'TERM_PROGRAM': 'iTerm.app'})

    assert capsys.readouterr().out == ''
