from rbx.box import code
from rbx.box.environment import LinterConfig
from rbx.box.linters.asset_kind import AssetKind
from rbx.box.sanitizers import warning_stack
from rbx.box.schema import CodeItem
from rbx.box.testing import testing_package

_OFFENDING_GENERATOR = """#include <cstdio>
int rnd_next() { return 0; }
struct Rnd { int next(int a, int b) { return a; } } rnd;
int main() {
    printf("%d %d", rnd.next(0, 9), rnd.next(0, 9));
    return 0;
}
"""


def _cpp_language_with_linters(configs):
    """Return a copy of the cpp env language with the given linters set."""
    base = code.find_language(CodeItem(path='x.cpp', language='cpp'))
    return base.model_copy(update={'linters': configs})


async def _compile_lenient(code_item, **kwargs):
    """Compile, tolerating compiler/sandbox failures (lint runs first)."""
    try:
        await code.compile_item(code_item, **kwargs)
    except Exception:
        # The lint step runs before the compiler in compile_item; even if the
        # actual compile/sandbox step fails on this machine, the lint warnings
        # were already recorded on the warning stack.
        pass


async def test_testlib_warning_lands_on_generator(
    testing_pkg: testing_package.TestingPackage, monkeypatch
):
    cpp_file = testing_pkg.add_file('gen.cpp')
    cpp_file.write_text(_OFFENDING_GENERATOR)
    code_item = CodeItem(path=cpp_file, language='cpp')

    language = _cpp_language_with_linters([LinterConfig(name='testlib')])
    monkeypatch.setattr('rbx.box.code.find_language', lambda _: language)

    warning_stack.get_warning_stack().clear()
    await _compile_lenient(code_item, kind=AssetKind.GENERATOR)

    stack = warning_stack.get_warning_stack()
    assert code_item.path in stack.linter_warnings
    messages = stack.linter_warnings[code_item.path]
    assert len(messages) == 1
    assert 'side-effecting' in messages[0].message


async def test_testlib_not_flagged_when_scoped_to_solutions(
    testing_pkg: testing_package.TestingPackage, monkeypatch
):
    cpp_file = testing_pkg.add_file('gen.cpp')
    cpp_file.write_text(_OFFENDING_GENERATOR)
    code_item = CodeItem(path=cpp_file, language='cpp')

    # Interface restricts to generators; config restricts to solutions. The
    # disjoint intersection means the linter must not run on this generator.
    language = _cpp_language_with_linters(
        [LinterConfig(name='testlib', applies_to=[AssetKind.SOLUTION])]
    )
    monkeypatch.setattr('rbx.box.code.find_language', lambda _: language)

    warning_stack.get_warning_stack().clear()
    await _compile_lenient(code_item, kind=AssetKind.GENERATOR)

    stack = warning_stack.get_warning_stack()
    assert code_item.path not in stack.linter_warnings
