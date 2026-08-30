"""Polygon rejects empty test inputs.

``problem.saveTest`` answers ``testInput: Test input can't be empty.`` for an
empty input -- and also for one that is only whitespace, since it strips before
checking. A package with a legitimately empty test could therefore not be
uploaded at all. The uploader substitutes a placeholder input and warns about
every test it touched.
"""

from unittest import mock

from rbx.box.packaging.polygon import upload


def _bare_checker(testing_pkg) -> None:
    testing_pkg.add_file('check.cpp').write_text('#include "testlib.h"\nint main(){}\n')
    testing_pkg.set_checker('check.cpp')


def test_empty_content_is_replaced_by_placeholder():
    substituted = []

    assert (
        upload._substitute_empty_test_input('', 'main/0', substituted)  # noqa: SLF001
        == upload.EMPTY_TEST_PLACEHOLDER
    )
    assert substituted == ['main/0']


def test_whitespace_only_content_is_replaced_by_placeholder():
    # Polygon strips before checking, so '\n' is just as empty as ''.
    substituted = []

    assert (
        upload._substitute_empty_test_input(' \n\t\n', 'main/1', substituted)  # noqa: SLF001
        == upload.EMPTY_TEST_PLACEHOLDER
    )
    assert substituted == ['main/1']


def test_non_empty_content_is_passed_through_untouched():
    substituted = []

    assert (
        upload._substitute_empty_test_input('1 2\n', 'main/0', substituted) == '1 2\n'  # noqa: SLF001
    )
    assert substituted == []


def test_upload_testcases_sends_placeholder_for_empty_manual_test(testing_pkg):
    _bare_checker(testing_pkg)
    testing_pkg.add_file('tests/000.in').write_text('')
    testing_pkg.add_file('tests/001.in').write_text('42\n')
    testing_pkg.add_testgroup_with_manual_testcases(
        'main',
        testcases=[{'inputPath': 'tests/000.in'}, {'inputPath': 'tests/001.in'}],
    )
    testing_pkg.save()

    problem = mock.Mock(name='RecordingProblem')

    ns = upload._build_upload_namespace()  # noqa: SLF001
    upload._upload_testcases(problem, ns)  # noqa: SLF001

    inputs = [call.kwargs['test_input'] for call in problem.save_test.call_args_list]
    assert inputs == [upload.EMPTY_TEST_PLACEHOLDER, '42\n']


def test_upload_testcases_raw_sends_placeholder_for_empty_manual_test(testing_pkg):
    _bare_checker(testing_pkg)
    testing_pkg.add_file('tests/000.in').write_text('')
    testing_pkg.add_testgroup_with_manual_testcases(
        'main', testcases=[{'inputPath': 'tests/000.in'}]
    )
    testing_pkg.save()

    problem = mock.Mock(name='RecordingProblem')

    upload._upload_testcases_raw(problem)  # noqa: SLF001

    inputs = [call.kwargs['test_input'] for call in problem.save_test.call_args_list]
    assert inputs == [upload.EMPTY_TEST_PLACEHOLDER]
