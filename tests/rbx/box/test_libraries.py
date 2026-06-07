import pathlib

from rbx.box import libraries
from rbx.grading import steps


def _write_preset(root: pathlib.Path, extra_yaml: str) -> None:
    (root / '.local.rbx').mkdir(parents=True, exist_ok=True)
    (root / '.local.rbx' / 'preset.rbx.yml').write_text(
        'name: pre\nuri: owner/repo\n' + extra_yaml
    )


def test_add_always_include_injects_into_internal(tmp_path, monkeypatch):
    _write_preset(
        tmp_path,
        'libraries:\n'
        '  problem:\n'
        '    - name: mylib\n'
        '      source: x\n'
        '      path: mylib.h\n'
        '      dest: subdir/mylib.h\n'
        '      always_include: true\n',
    )
    (tmp_path / 'subdir').mkdir()
    (tmp_path / 'subdir' / 'mylib.h').write_text('// mylib')
    monkeypatch.chdir(tmp_path)
    libraries.get_declared_libraries.cache_clear()

    artifacts = steps.GradingArtifacts()
    added = libraries.add_always_include_libraries(artifacts)

    assert added is True
    dests = {str(i.dest) for i in artifacts.inputs}
    assert '__internal__/mylib.h' in dests


def test_add_always_include_dedups_existing(tmp_path, monkeypatch):
    _write_preset(
        tmp_path,
        'libraries:\n'
        '  problem:\n'
        '    - name: mylib\n'
        '      source: x\n'
        '      path: mylib.h\n'
        '      dest: mylib.h\n'
        '      always_include: true\n',
    )
    (tmp_path / 'mylib.h').write_text('// mylib')
    monkeypatch.chdir(tmp_path)
    libraries.get_declared_libraries.cache_clear()

    artifacts = steps.GradingArtifacts()
    artifacts.inputs.append(
        steps.GradingFileInput(
            src=tmp_path / 'mylib.h', dest=steps.INTERNAL_DIR / 'mylib.h'
        )
    )
    added = libraries.add_always_include_libraries(artifacts)

    assert added is False  # already present => not added again
    internal_mylib = [
        i for i in artifacts.inputs if str(i.dest) == '__internal__/mylib.h'
    ]
    assert len(internal_mylib) == 1


def test_no_preset_returns_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    libraries.get_declared_libraries.cache_clear()
    assert libraries.get_always_include_libraries() == []
    artifacts = steps.GradingArtifacts()
    assert libraries.add_always_include_libraries(artifacts) is False
