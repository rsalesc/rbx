import pathlib

from rbx.box.sanitizers.compilation_warnings import _parse_cpp_warnings

TESTDATA = pathlib.Path(__file__).parent / 'testdata'


def _read(name: str) -> str:
    return (TESTDATA / name).read_text()


def test_parses_gcc_warning():
    parsed = _parse_cpp_warnings(_read('gcc_unused.txt'))
    assert len(parsed) == 1
    assert parsed[0].file == 'sol.cpp'
    assert parsed[0].line == 5
    assert parsed[0].flag == '-Wunused-variable'
    assert 'unused variable' in parsed[0].msg


def test_parses_multiple_clang_warnings():
    parsed = _parse_cpp_warnings(_read('clang_mixed.txt'))
    flags = sorted(p.flag for p in parsed)
    assert flags == ['-Wsign-compare', '-Wunused-variable', '-Wunused-variable']


def test_filters_testlib_paths():
    parsed = _parse_cpp_warnings(_read('with_testlib.txt'))
    assert len(parsed) == 1
    assert parsed[0].file == 'sol.cpp'


def test_warning_without_flag():
    parsed = _parse_cpp_warnings(_read('noflag.txt'))
    assert len(parsed) == 1
    assert parsed[0].flag is None
    assert 'control reaches end' in parsed[0].msg


def test_ignores_notes_and_carets_and_in_file_included_from():
    log = (
        'In file included from sol.cpp:1:\n'
        "sol.cpp:5:9: warning: unused variable 'x' [-Wunused-variable]\n"
        '    5 |     int x = 0;\n'
        '      |         ^\n'
        'sol.cpp:6:1: note: previous declaration here\n'
    )
    parsed = _parse_cpp_warnings(log)
    assert len(parsed) == 1
    assert parsed[0].flag == '-Wunused-variable'


def test_strips_ansi_color_codes():
    log = "\x1b[1msol.cpp:5:9:\x1b[m \x1b[35mwarning:\x1b[m unused variable 'x' [-Wunused-variable]"
    parsed = _parse_cpp_warnings(log)
    assert len(parsed) == 1
    assert parsed[0].flag == '-Wunused-variable'
