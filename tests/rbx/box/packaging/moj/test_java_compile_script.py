"""Exercises the Java `compile.sh` template that ships inside a MOJ package.

The script runs in MOJ's jail against hard-coded `/tmp` paths, so the fixture rewrites
those onto a temp dir and puts stubbed `javac`/`jar` on PATH. The `javac` stub
reproduces the one rule this script exists to satisfy -- a source declaring a public
type must be named after it -- and fails outright on a source marked `SYNTAX_ERROR`, so
a genuinely broken submission stays broken.
"""

import pathlib
import subprocess

import pytest

from rbx.config import get_default_app_path

JAVAC_STUB = r"""#!/bin/bash
for src in "$@"; do
  grep -q SYNTAX_ERROR "$src" && { echo "$src:1: error: ';' expected" >&2; exit 1; }
  klass=$(sed -n -E 's/^[[:space:]]*public[[:space:]]+([a-z]+[[:space:]]+)*(class|interface) ([A-Za-z_$][A-Za-z0-9_$]*).*/\3/p' "$src" | head -1)
  base=$(basename "$src" .java)
  if [[ -n "$klass" && "$klass" != "$base" ]]; then
    echo "$src:1: error: class $klass is public, should be declared in a file named $klass.java" >&2
    exit 1
  fi
  touch "$base.class"
done
exit 0
"""

JAR_STUB = r"""#!/bin/bash
# `jar cfm <jar> <manifest> <files...>`: keep the manifest around and emit a stand-in.
cp "$3" manifest-seen.txt
touch "$2"
exit 0
"""

MAIN_CLASS = 'public class Main {\n  public static void main(String[] a) {}\n}\n'


@pytest.fixture
def jail(tmp_path: pathlib.Path):
    """A stand-in for MOJ's jail. Returns a runner taking the sources to compile and
    handing back `(process, rwdir, stdout_of_the_script)`."""
    rwdir = tmp_path / 'rwdir'
    rwdir.mkdir()

    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    for name, body in [('javac', JAVAC_STUB), ('jar', JAR_STUB)]:
        stub = bin_dir / name
        stub.write_text(body)
        stub.chmod(0o755)

    template = (
        get_default_app_path() / 'packagers' / 'moj' / 'scripts' / 'java' / 'compile.sh'
    )
    script = tmp_path / 'compile.sh'
    script.write_text(
        template.read_text()
        .replace('/tmp/rwdir', str(rwdir))
        .replace('/tmp/stderrlog', str(tmp_path / 'stderrlog'))
        .replace('/tmp/out', str(tmp_path / 'out'))
    )

    def run(sources):
        for name, content in sources.items():
            (rwdir / name).write_text(content)
        proc = subprocess.run(
            ['bash', str(script)],
            capture_output=True,
            text=True,
            env={'PATH': f'{bin_dir}:/usr/bin:/bin'},
        )
        return proc, rwdir, (tmp_path / 'out').read_text()

    return run


def _manifest(rwdir: pathlib.Path) -> str:
    return (rwdir / 'manifest-seen.txt').read_text()


def test_source_named_after_its_public_class_is_left_alone(jail):
    proc, rwdir, out = jail({'Main.java': MAIN_CLASS})

    assert proc.returncode == 0
    assert 'BIN=prog.jar' in out
    assert (rwdir / 'Main.java').is_file()
    assert _manifest(rwdir) == 'Main-Class: Main\n'


def test_source_named_after_the_solution_is_renamed_to_its_public_class(jail):
    # The shape rbx ships: `sols/good/<solution>.java` declaring `public class Main`.
    proc, rwdir, out = jail({'vinicius_gpt_fastIO.java': MAIN_CLASS})

    assert proc.returncode == 0
    assert 'BIN=prog.jar' in out
    assert not (rwdir / 'vinicius_gpt_fastIO.java').exists()
    assert (rwdir / 'Main.java').read_text() == MAIN_CLASS
    # The entry point follows the file, so `java -jar` still finds it.
    assert _manifest(rwdir) == 'Main-Class: Main\n'


def test_rename_follows_a_public_class_that_is_not_called_main(jail):
    proc, rwdir, out = jail(
        {'sol.java': 'public class Solucao {\n  static void main(String[] a) {}\n}\n'}
    )

    assert proc.returncode == 0
    assert 'BIN=prog.jar' in out
    assert (rwdir / 'Solucao.java').is_file()
    assert _manifest(rwdir) == 'Main-Class: Solucao\n'


def test_source_with_no_public_class_keeps_its_name(jail):
    # A package-private class needs no agreement with the file name, and renaming it
    # would point the manifest at a class javac never emits.
    proc, rwdir, out = jail(
        {'sol.java': 'class Sol {\n  public static void main(String[] a) {}\n}\n'}
    )

    assert proc.returncode == 0
    assert 'BIN=prog.jar' in out
    assert (rwdir / 'sol.java').is_file()
    assert _manifest(rwdir) == 'Main-Class: sol\n'


def test_a_public_class_mentioned_in_a_comment_does_not_drive_the_rename(jail):
    proc, rwdir, _ = jail(
        {'Main.java': '// see public class Helper for the details\n' + MAIN_CLASS}
    )

    assert proc.returncode == 0
    assert (rwdir / 'Main.java').is_file()
    assert not (rwdir / 'Helper.java').exists()


def test_helper_sources_are_renamed_too_without_stealing_the_entry_point(jail):
    proc, rwdir, out = jail(
        {'a_main.java': MAIN_CLASS, 'z_helper.java': 'public final class Helper {}\n'}
    )

    assert proc.returncode == 0
    assert 'BIN=prog.jar' in out
    assert (rwdir / 'Main.java').is_file()
    assert (rwdir / 'Helper.java').is_file()
    # `a_main.java` sorted first, so it stays the entry point under its new name.
    assert _manifest(rwdir) == 'Main-Class: Main\n'


def test_a_real_compile_error_still_fails(jail):
    # Renaming must not paper over a source that simply does not compile.
    proc, _, out = jail({'sol.java': 'public class Main { SYNTAX_ERROR }\n'})

    assert proc.returncode != 0
    assert 'BIN=' not in out


def test_no_java_source_at_all_is_a_compile_error(jail):
    proc, _, out = jail({})

    assert proc.returncode != 0
    assert 'BIN=' not in out
