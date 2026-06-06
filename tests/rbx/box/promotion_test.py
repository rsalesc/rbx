import fnmatch
import pathlib

import pytest

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


# --- fill_glob -------------------------------------------------------------


def test_fill_glob_simple_wildcard():
    assert promotion.fill_glob('tests/manual/*.in', '000') == pathlib.Path(
        'tests/manual/000.in'
    )


def test_fill_glob_prefixed_filename():
    assert promotion.fill_glob('manual_tests/manual-*.in', '000') == pathlib.Path(
        'manual_tests/manual-000.in'
    )


def test_fill_glob_fills_only_last_wildcard():
    # The first '*' is treated as fixed text; only the LAST is filled.
    assert promotion.fill_glob('a*/b-*.in', '000') == pathlib.Path('a*/b-000.in')


def test_fill_glob_without_wildcard_raises():
    with pytest.raises(ValueError):
        promotion.fill_glob('tests/manual/000.in', '000')


# --- stems_matching_glob ---------------------------------------------------


def test_stems_matching_glob_extracts_substring(tmp_path: pathlib.Path):
    (tmp_path / 'manual_tests').mkdir()
    (tmp_path / 'manual_tests/manual-000.in').write_text('a')
    (tmp_path / 'manual_tests/manual-007.in').write_text('b')

    stems = promotion.stems_matching_glob('manual_tests/manual-*.in', base_dir=tmp_path)

    assert stems == {'000', '007'}


def test_stems_matching_glob_simple_wildcard(tmp_path: pathlib.Path):
    (tmp_path / 'tests/manual').mkdir(parents=True)
    (tmp_path / 'tests/manual/000.in').write_text('a')
    (tmp_path / 'tests/manual/042.in').write_text('b')

    stems = promotion.stems_matching_glob('tests/manual/*.in', base_dir=tmp_path)

    assert stems == {'000', '042'}


def test_stems_matching_glob_ignores_non_matching_files(tmp_path: pathlib.Path):
    (tmp_path / 'manual_tests').mkdir()
    (tmp_path / 'manual_tests/manual-000.in').write_text('a')
    # Differently-prefixed .in file and a README should be ignored.
    (tmp_path / 'manual_tests/other-001.in').write_text('b')
    (tmp_path / 'manual_tests/README.txt').write_text('c')

    stems = promotion.stems_matching_glob('manual_tests/manual-*.in', base_dir=tmp_path)

    assert stems == {'000'}


def test_stems_matching_glob_empty_when_missing(tmp_path: pathlib.Path):
    assert (
        promotion.stems_matching_glob('manual_tests/manual-*.in', base_dir=tmp_path)
        == set()
    )


# --- next_testcase_name (glob-aware) ---------------------------------------


def test_next_testcase_name_on_empty_dir(tmp_path: pathlib.Path):
    assert promotion.next_testcase_name('tests/manual/*.in', base_dir=tmp_path) == '000'


def test_next_testcase_name_skips_existing_matching_glob(tmp_path: pathlib.Path):
    (tmp_path / 'manual_tests').mkdir()
    (tmp_path / 'manual_tests/manual-000.in').write_text('a')
    (tmp_path / 'manual_tests/manual-001.in').write_text('b')
    assert (
        promotion.next_testcase_name('manual_tests/manual-*.in', base_dir=tmp_path)
        == '002'
    )


def test_next_testcase_name_picks_lowest_free(tmp_path: pathlib.Path):
    (tmp_path / 'manual_tests').mkdir()
    (tmp_path / 'manual_tests/manual-000.in').write_text('a')
    (tmp_path / 'manual_tests/manual-002.in').write_text('c')
    assert (
        promotion.next_testcase_name('manual_tests/manual-*.in', base_dir=tmp_path)
        == '001'
    )


def test_next_testcase_name_ignores_non_matching_files(tmp_path: pathlib.Path):
    (tmp_path / 'manual_tests').mkdir()
    # A differently-prefixed file does not occupy the manual-* namespace.
    (tmp_path / 'manual_tests/other-000.in').write_text('a')
    assert (
        promotion.next_testcase_name('manual_tests/manual-*.in', base_dir=tmp_path)
        == '000'
    )


def test_next_testcase_name_honours_used_reserve_set(tmp_path: pathlib.Path):
    assert (
        promotion.next_testcase_name(
            'tests/manual/*.in', used={'000', '001'}, base_dir=tmp_path
        )
        == '002'
    )


# --- promote_input_to_group ------------------------------------------------


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


def test_promote_input_to_group_fills_prefixed_glob(tmp_path: pathlib.Path):
    """Regression: the destination must MATCH the group's own glob.

    The bug wrote ``manual_tests/000.in`` for a ``manual_tests/manual-*.in``
    group, so the promoted test did not match the glob and was silently dropped
    at build. The written path must satisfy the glob.
    """
    src = tmp_path / 'src.in'
    src.write_text('payload\n')
    group = TestcaseGroup(name='manual', testcaseGlob='manual_tests/manual-*.in')

    written = promotion.promote_input_to_group(src, group, base_dir=tmp_path)

    assert written == tmp_path / 'manual_tests/manual-000.in'
    # The written path matches the group's glob (the whole point of the fix).
    rel = written.relative_to(tmp_path).as_posix()
    assert fnmatch.fnmatch(rel, group.testcaseGlob)
    assert written.read_text() == 'payload\n'


def test_promote_input_to_group_explicit_name_fills_prefixed_glob(
    tmp_path: pathlib.Path,
):
    src = tmp_path / 'src.in'
    src.write_text('payload\n')
    group = TestcaseGroup(name='manual', testcaseGlob='manual_tests/manual-*.in')

    written = promotion.promote_input_to_group(
        src, group, name='edge', base_dir=tmp_path
    )

    assert written == tmp_path / 'manual_tests/manual-edge.in'
    rel = written.relative_to(tmp_path).as_posix()
    assert fnmatch.fnmatch(rel, group.testcaseGlob)


# --- batch helpers: default_stems / validate_stems -------------------------


def test_default_stems_sequential_on_empty_dir(tmp_path: pathlib.Path):
    stems = promotion.default_stems('manual_tests/manual-*.in', 3, base_dir=tmp_path)
    assert stems == ['000', '001', '002']


def test_default_stems_skips_existing_matching_files(tmp_path: pathlib.Path):
    (tmp_path / 'manual_tests').mkdir()
    (tmp_path / 'manual_tests/manual-000.in').write_text('a')
    (tmp_path / 'manual_tests/manual-002.in').write_text('b')

    stems = promotion.default_stems('manual_tests/manual-*.in', 2, base_dir=tmp_path)

    # 000 and 002 are taken on disk -> 001 then 003.
    assert stems == ['001', '003']


def test_default_stems_collision_free():
    stems = promotion.default_stems('tests/*.in', 5)
    assert len(set(stems)) == len(stems) == 5


def test_validate_stems_accepts_distinct():
    assert promotion.validate_stems(['000', '001', 'edge']) is None


def test_validate_stems_rejects_empty():
    msg = promotion.validate_stems(['000', ''])
    assert msg is not None
    assert 'empty' in msg.lower()


def test_validate_stems_rejects_whitespace_only():
    msg = promotion.validate_stems(['000', '   '])
    assert msg is not None
    assert 'empty' in msg.lower()


def test_validate_stems_rejects_duplicates():
    msg = promotion.validate_stems(['000', '000'])
    assert msg is not None
    assert 'duplicate' in msg.lower() or '000' in msg


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
