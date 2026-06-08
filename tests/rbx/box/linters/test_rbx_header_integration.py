import pytest

from rbx.box import code
from rbx.box.environment import LinterConfig
from rbx.box.exception import RbxException
from rbx.box.linters import runner
from rbx.box.linters.asset_kind import AssetKind
from rbx.box.linters.cpp.rbx_header import RbxHeaderLinter
from rbx.box.schema import CodeItem
from rbx.box.testing import testing_package

_OFFENDING = '#include "rbx.h"\nint main() { return 0; }\n'


def _cpp_language_with_linters(configs):
    base = code.find_language(CodeItem(path='x.cpp', language='cpp'))
    return base.model_copy(update={'linters': configs})


async def test_error_blocks_compile_for_generator(
    testing_pkg: testing_package.TestingPackage, monkeypatch
):
    cpp_file = testing_pkg.add_file('gen.cpp')
    cpp_file.write_text(_OFFENDING)
    code_item = CodeItem(path=cpp_file, language='cpp')

    language = _cpp_language_with_linters([LinterConfig(name='rbx-header')])
    monkeypatch.setattr('rbx.box.code.find_language', lambda _: language)

    with pytest.raises(RbxException) as exc_info:
        await runner.run_linters(code_item, AssetKind.GENERATOR)
    assert 'rbx.h' in str(exc_info.value)


def test_not_flagged_for_non_generator_kind():
    msgs = runner.run_linters_for_messages(
        configs=[LinterConfig(name='rbx-header', applies_to=None)],
        linters=[RbxHeaderLinter()],
        kind=AssetKind.VALIDATOR,
        code=CodeItem(path='val.cpp'),
        source=_OFFENDING,
    )
    assert msgs == []


def test_suppressed_by_disable_directive_on_include_line():
    src = '#include "rbx.h"  // rbx-header-linter: disable\nint main() {}\n'
    msgs = runner.run_linters_for_messages(
        configs=[LinterConfig(name='rbx-header', applies_to=None)],
        linters=[RbxHeaderLinter()],
        kind=AssetKind.GENERATOR,
        code=CodeItem(path='gen.cpp'),
        source=src,
    )
    assert msgs == []
