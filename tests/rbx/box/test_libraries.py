import pathlib

from rbx.box import libraries
from rbx.box.presets.schema import Library
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


def test_no_preset_still_declares_testlib(tmp_path, monkeypatch):
    """A package with no preset still gets testlib. rbx's own builtin checkers
    include it and live outside the package root, where the dependency scanner
    does not reach, so this injection is what resolves their include."""
    monkeypatch.chdir(tmp_path)
    libraries.get_declared_libraries.cache_clear()

    assert [lib.name for lib in libraries.get_always_include_libraries()] == ['testlib']


def test_no_preset_falls_back_to_the_bundled_testlib(tmp_path, monkeypatch):
    """The package never materialized testlib.h, so the copy rbx keeps in its
    app dir is injected instead."""
    bundled = tmp_path / 'app' / 'testlib.h'
    bundled.parent.mkdir()
    bundled.write_text('// bundled testlib')
    monkeypatch.setattr('rbx.config.get_testlib', lambda: bundled)
    monkeypatch.chdir(tmp_path)
    libraries.get_declared_libraries.cache_clear()

    artifacts = steps.GradingArtifacts()
    added = libraries.add_always_include_libraries(artifacts)

    assert added is True
    injected = [i for i in artifacts.inputs if str(i.dest) == '__internal__/testlib.h']
    assert len(injected) == 1
    assert injected[0].src == bundled


def test_no_preset_prefers_the_package_testlib(tmp_path, monkeypatch):
    """A testlib.h sitting in the package wins over the bundled copy, so a
    setter pinning their own version keeps it."""
    bundled = tmp_path / 'app' / 'testlib.h'
    bundled.parent.mkdir()
    bundled.write_text('// bundled testlib')
    (tmp_path / 'testlib.h').write_text("// the package's own testlib")
    monkeypatch.setattr('rbx.config.get_testlib', lambda: bundled)
    monkeypatch.chdir(tmp_path)
    libraries.get_declared_libraries.cache_clear()

    artifacts = steps.GradingArtifacts()
    libraries.add_always_include_libraries(artifacts)

    injected = [i for i in artifacts.inputs if str(i.dest) == '__internal__/testlib.h']
    assert injected[0].src == pathlib.Path('testlib.h')


def test_declared_library_without_a_fallback_is_skipped(tmp_path, monkeypatch, capsys):
    """Only the implicit builtin has a fallback. A declared library that was
    never materialized still warns, because there the missing file means the
    package is out of sync with its preset rather than never configured."""
    declared = Library(
        name='mylib',
        source='x',
        path=pathlib.Path('mylib.h'),
        dest=pathlib.Path('mylib.h'),
        always_include=True,
    )
    monkeypatch.setattr(libraries, 'get_declared_libraries', lambda: [declared])
    monkeypatch.chdir(tmp_path)

    artifacts = steps.GradingArtifacts()

    assert libraries.add_always_include_libraries(artifacts) is False
    assert 'declared but not materialized' in capsys.readouterr().out


def test_testing_package_declares_standard_libraries(testing_pkg):
    # The TestingPackage chokepoint must PERSIST testlib/jngen/tgen as
    # always_include libraries (the exclude_unset trap means a nested mutation
    # would be silently dropped). This proves the library mechanism provides
    # them independently of the hardcoded maybe_add_* injection (removed next).
    libraries.get_declared_libraries.cache_clear()
    names = {lib.name for lib in libraries.get_declared_libraries()}
    assert {'testlib', 'jngen', 'tgen'} <= names

    artifacts = steps.GradingArtifacts()
    added = libraries.add_always_include_libraries(artifacts)
    assert added is True
    dests = {str(i.dest) for i in artifacts.inputs}
    assert {
        '__internal__/testlib.h',
        '__internal__/jngen.h',
        '__internal__/tgen.h',
    } <= dests
