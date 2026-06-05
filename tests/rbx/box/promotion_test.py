import pathlib

from rbx.box import package, promotion
from rbx.box.generation_schema import (
    GenerationMetadata,
    GenerationTestcaseEntry,
    GeneratorScriptEntry,
)
from rbx.box.schema import GeneratorCall, Testcase, TestcaseGroup
from rbx.box.testcase_schema import TestcaseEntry
from rbx.box.testing import testing_package


def _entry(metadata):
    return GenerationTestcaseEntry(
        group_entry=TestcaseEntry(group='g', index=0),
        subgroup_entry=TestcaseEntry(group='g', index=0),
        metadata=metadata,
    )


def _md(**kw):
    return GenerationMetadata(copied_to=Testcase(inputPath=pathlib.Path('x.in')), **kw)


SCRIPT = pathlib.Path('tests/plan.txt')
FORMATS = {SCRIPT: 'rbx'}


def test_promotable_rbx_generator_call():
    md = _md(
        generator_call=GeneratorCall(name='g'),
        generator_script=GeneratorScriptEntry(path=SCRIPT, line=1),
    )
    assert promotion.is_promotable(_entry(md), FORMATS) is True


def test_promotable_input_content():
    md = _md(
        content='1 2 3',
        generator_script=GeneratorScriptEntry(path=SCRIPT, line=1),
    )
    assert promotion.is_promotable(_entry(md), FORMATS) is True


def test_not_promotable_copy():
    md = _md(
        copied_from=Testcase(inputPath=pathlib.Path('a.in')),
        generator_script=GeneratorScriptEntry(path=SCRIPT, line=1),
    )
    assert promotion.is_promotable(_entry(md), FORMATS) is False


def test_not_promotable_no_script():
    md = _md(generator_call=GeneratorCall(name='g'))
    assert promotion.is_promotable(_entry(md), FORMATS) is False


def test_not_promotable_box_format():
    md = _md(
        generator_call=GeneratorCall(name='g'),
        generator_script=GeneratorScriptEntry(path=SCRIPT, line=1),
    )
    assert promotion.is_promotable(_entry(md), {SCRIPT: 'box'}) is False


def test_script_format_by_path(testing_pkg: testing_package.TestingPackage):
    testing_pkg.add_testgroup_from_plan('main', 'gen 1\ngen 2\n')

    formats = promotion.script_format_by_path()

    plan_path = testing_pkg.root / 'testplan' / 'main.txt'
    assert formats[plan_path] == 'rbx'


def test_remove_script_entries_removes_originating_statement(
    testing_pkg: testing_package.TestingPackage,
):
    testing_pkg.add_testgroup_from_plan('main', 'gen 1\ngen 2\n')
    plan_path = testing_pkg.root / 'testplan' / 'main.txt'

    md = _md(
        generator_call=GeneratorCall(name='gen', args='1'),
        generator_script=GeneratorScriptEntry(path=plan_path, line=1),
    )
    promotion.remove_script_entries([_entry(md)])

    remaining = plan_path.read_text()
    assert 'gen 1' not in remaining
    assert 'gen 2' in remaining


def test_manual_group_dir_returns_directory_of_glob():
    group = TestcaseGroup(name='corner', testcaseGlob='tests/manual/corner/*.in')
    assert promotion.manual_group_dir(group) == pathlib.Path('tests/manual/corner')


def test_manual_group_dir_with_flat_glob():
    group = TestcaseGroup(name='manual', testcaseGlob='tests/*.in')
    assert promotion.manual_group_dir(group) == pathlib.Path('tests')


def test_next_testcase_name_on_empty_folder(tmp_path: pathlib.Path):
    assert promotion.next_testcase_name(tmp_path) == '000'


def test_next_testcase_name_on_nonexistent_folder(tmp_path: pathlib.Path):
    assert promotion.next_testcase_name(tmp_path / 'missing') == '000'


def test_next_testcase_name_skips_existing(tmp_path: pathlib.Path):
    (tmp_path / '000.in').write_text('a')
    (tmp_path / '001.in').write_text('b')
    assert promotion.next_testcase_name(tmp_path) == '002'


def test_next_testcase_name_picks_lowest_free(tmp_path: pathlib.Path):
    (tmp_path / '000.in').write_text('a')
    (tmp_path / '002.in').write_text('c')
    assert promotion.next_testcase_name(tmp_path) == '001'


def test_next_testcase_name_ignores_non_in_files(tmp_path: pathlib.Path):
    (tmp_path / '000.out').write_text('a')
    (tmp_path / '000.ans').write_text('a')
    assert promotion.next_testcase_name(tmp_path) == '000'


def test_promote_input_to_group_writes_input(tmp_path: pathlib.Path):
    src = tmp_path / 'src.in'
    src.write_text('1 2 3\n')
    group = TestcaseGroup(name='corner', testcaseGlob='tests/manual/corner/*.in')

    written = promotion.promote_input_to_group(src, group, base_dir=tmp_path)

    assert written == tmp_path / 'tests/manual/corner/000.in'
    assert written.read_text() == '1 2 3\n'
    # INPUT only: no .out / .ans written.
    assert not (tmp_path / 'tests/manual/corner/000.out').exists()
    assert not (tmp_path / 'tests/manual/corner/000.ans').exists()


def test_promote_input_to_group_with_explicit_name(tmp_path: pathlib.Path):
    src = tmp_path / 'src.in'
    src.write_bytes(b'binary\x00content')
    group = TestcaseGroup(name='corner', testcaseGlob='tests/manual/corner/*.in')

    written = promotion.promote_input_to_group(
        src, group, name='custom', base_dir=tmp_path
    )

    assert written == tmp_path / 'tests/manual/corner/custom.in'
    assert written.read_bytes() == b'binary\x00content'


def test_promote_input_to_group_auto_increments(tmp_path: pathlib.Path):
    src = tmp_path / 'src.in'
    src.write_text('x')
    group = TestcaseGroup(name='corner', testcaseGlob='tests/manual/corner/*.in')

    first = promotion.promote_input_to_group(src, group, base_dir=tmp_path)
    second = promotion.promote_input_to_group(src, group, base_dir=tmp_path)

    assert first.name == '000.in'
    assert second.name == '001.in'


def test_get_manual_groups_by_name_only_glob_groups(
    testing_pkg: testing_package.TestingPackage,
):
    (testing_pkg.root / 'tests/manual/corner').mkdir(parents=True, exist_ok=True)
    testing_pkg.add_testgroup_from_glob('corner', 'tests/manual/corner/*.in')
    testing_pkg.add_testgroup_with_generators('generated', [{'name': 'gen'}])

    groups = promotion.get_manual_groups_by_name()

    assert 'corner' in groups
    assert 'generated' not in groups
    assert groups['corner'].testcaseGlob == 'tests/manual/corner/*.in'


def test_create_manual_group_writes_folder_and_yaml(
    testing_pkg: testing_package.TestingPackage,
):
    group = promotion.create_manual_group('corner', 'tests/manual/corner/*.in')

    assert group.name == 'corner'
    assert group.testcaseGlob == 'tests/manual/corner/*.in'
    # Folder is created.
    assert (testing_pkg.root / 'tests/manual/corner').is_dir()
    # Group is appended and visible after cache clear.
    groups = package.get_test_groups_by_name()
    assert 'corner' in groups
    assert groups['corner'].testcaseGlob == 'tests/manual/corner/*.in'
