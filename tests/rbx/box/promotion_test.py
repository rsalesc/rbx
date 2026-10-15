import pathlib

import pytest

from rbx.box import promotion
from rbx.box.generation_schema import (
    GenerationMetadata,
    GenerationTestcaseEntry,
)
from rbx.box.schema import Testcase
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


def test_validate_stems_rejects_embedded_whitespace():
    msg = promotion.validate_stems(['000', 'ed ge'])
    assert msg is not None
    assert 'whitespace' in msg.lower()


def test_validate_stems_rejects_trailing_whitespace():
    msg = promotion.validate_stems(['000 '])
    assert msg is not None
    assert 'whitespace' in msg.lower()


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
