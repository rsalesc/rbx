from rbx.grading.steps import _is_first_party_warning_file


def test_first_party_paths_pass():
    assert _is_first_party_warning_file('sol.cpp')
    assert _is_first_party_warning_file('src/Solution.cc')


def test_third_party_libraries_filtered():
    assert not _is_first_party_warning_file('testlib.h')
    assert not _is_first_party_warning_file('vendor/jngen/jngen.h')
    assert not _is_first_party_warning_file('include/tgen/tgen.h')
    assert not _is_first_party_warning_file('stresslib.cpp')


def test_header_files_filtered():
    assert not _is_first_party_warning_file('foo.h')
    assert not _is_first_party_warning_file('Foo.H')


def test_case_insensitive_and_trimmed():
    assert not _is_first_party_warning_file('  TESTLIB.cpp  ')
