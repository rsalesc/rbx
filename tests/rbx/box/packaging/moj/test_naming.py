import fnmatch

import pytest

# Imported as a module: pytest's `python_functions` matches `test*`, so importing
# `testcase_name` by name would make pytest try to collect it as a test.
from rbx.box.packaging.moj import naming


def test_sample_names_start_with_sample():
    assert (
        naming.testcase_name('samples', group_index=0, index=1, is_sample=True)
        == 'sample001'
    )


def test_non_sample_names_carry_a_group_index():
    assert (
        naming.testcase_name('easy', group_index=1, index=3, is_sample=False)
        == 't01_easy_003'
    )


def test_samples_sort_before_other_tests():
    # MOJ's judging loop is a plain lexicographic glob over tests/input/*.
    names = sorted(
        [
            naming.testcase_name('easy', group_index=1, index=1, is_sample=False),
            naming.testcase_name('samples', group_index=0, index=1, is_sample=True),
        ]
    )
    assert names[0].startswith('sample')


def test_group_index_orders_groups_regardless_of_name():
    names = sorted(
        [
            naming.testcase_name('zebra', group_index=1, index=1, is_sample=False),
            naming.testcase_name('alpha', group_index=2, index=1, is_sample=False),
        ]
    )
    assert names[0].startswith('t01_zebra')


def test_group_names_are_sanitized():
    # A dash would break score-summary.sh, which splits the line on IFS='-'.
    assert naming.sanitize_group_name('main-group') == 'main_group'
    assert naming.sanitize_group_name('a b/c') == 'a_b_c'


def test_score_file_lists_groups_in_order():
    content = naming.build_score_file(
        [
            naming.ScoreGroup(glob=naming.SAMPLES_GLOB, weight=0),
            naming.ScoreGroup(glob='t01_easy_*', weight=40),
            naming.ScoreGroup(glob='t02_full_*', weight=60),
        ]
    )
    assert content == (
        'sample* - 0 pontos\nt01_easy_* - 40 pontos\nt02_full_* - 60 pontos\n'
    )


def test_score_file_rejects_non_integer_weights():
    # score-summary.sh extracts the weight with ${SCORE//[^0-9]/}, so 40.5 -> 405.
    with pytest.raises(naming.MojNamingError) as exc:
        naming.build_score_file([naming.ScoreGroup(glob='t01_easy_*', weight=40.5)])
    assert 'integer' in str(exc.value).lower()
    assert '405' in str(exc.value)


def test_glob_matches_mojs_strip_trailing_digits_heuristic():
    # score-summary.sh derives a group name by stripping the trailing '*' from the
    # glob, and matches a test by stripping its trailing digits. Both must agree.
    name = naming.testcase_name('easy', group_index=1, index=7, is_sample=False)
    glob = naming.group_glob('easy', 1)
    assert name.rstrip('0123456789') == glob[:-1]


def test_glob_matches_mojs_real_glob_fallback():
    name = naming.testcase_name('easy', group_index=1, index=7, is_sample=False)
    assert fnmatch.fnmatch(name, naming.group_glob('easy', 1))
    assert fnmatch.fnmatch('sample001', naming.SAMPLES_GLOB)


def test_distinct_groups_never_share_a_prefix():
    # Every test must match exactly one tests/score group or the submission is zeroed.
    a = naming.testcase_name('ab', group_index=1, index=1, is_sample=False)
    assert not fnmatch.fnmatch(a, naming.group_glob('a', 2))
    assert not fnmatch.fnmatch(a, naming.SAMPLES_GLOB)
