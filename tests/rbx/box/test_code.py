from rbx.box.code import _add_internal_include


def test_add_internal_include_only_affects_cxx_commands():
    # C++ commands get -I__internal__; non-C++ commands (e.g. javac) must be
    # preserved unchanged so the command list is never emptied.
    out = _add_internal_include(['g++ -c a.cpp -o a', 'javac A.java'])
    assert out == ['g++ -c a.cpp -o a -I__internal__', 'javac A.java']


def test_add_internal_include_non_cxx_only_unchanged():
    # A purely non-C++ compile (the regression case: always_include libs present
    # while compiling Java) keeps all its commands.
    cmds = ['javac A.java']
    assert _add_internal_include(cmds) == ['javac A.java']
