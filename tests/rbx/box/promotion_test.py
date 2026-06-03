import pathlib

from rbx.box import package, promotion
from rbx.box.schema import TestcaseGroup
from rbx.box.testing import testing_package


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
