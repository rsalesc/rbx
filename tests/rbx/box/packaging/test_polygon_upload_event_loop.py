"""Regression coverage for #591: ``rbx package polygon -u`` (a full upload)
crashed during generator collection with ``RuntimeError: asyncio.run() cannot
be called from a running event loop``.

``upload_problem`` is async and runs inside the event loop driven by ``syncer``.
It used to call the sync helpers ``_build_upload_namespace`` /
``_collect_generators`` / ``_upload_testcases``, which each invoked
``asyncio.run(extract_generation_testcases_from_groups())`` -- illegal from
within an already-running loop. The fix extracts the testcase entries once on
the async path and threads them down into the sync helpers.

These tests drive ``upload_problem`` through a *real* running event loop (via
``asyncio.run``), which is exactly the context the unit tests in
``test_polygon_upload_flatten.py`` never exercise (they call the sync helpers
directly, where ``asyncio.run`` is legal).
"""

import asyncio
from unittest import mock

from rbx.box.packaging.polygon import upload


def _bare_checker(testing_pkg) -> None:
    testing_pkg.add_file('check.cpp').write_text('#include "testlib.h"\nint main(){}\n')
    testing_pkg.set_checker('check.cpp')


def _mock_polygon_api():
    """A ``_get_polygon_api`` replacement whose problem records nothing and
    performs no network I/O. ``solutions()`` must be iterable (it is consumed by
    ``_upload_solutions``)."""
    problem = mock.Mock(name='RecordingProblem')
    problem.solutions.return_value = []
    api = mock.Mock(name='Polygon')
    api.problems_list.return_value = []
    api.problem_create.return_value = problem
    return api, problem


def test_full_upload_does_not_call_asyncio_run_inside_loop(testing_pkg):
    # A package with a generator + a testgroup that calls it: the full upload
    # path walks the testcase groups (the crash site in #591).
    _bare_checker(testing_pkg)
    testing_pkg.add_file('gen.cpp').write_text('int main(){}\n')
    testing_pkg.add_generator('gen.cpp', alias='gen')
    testing_pkg.add_testgroup_with_generators(
        'main', generators=[{'name': 'gen', 'args': '1'}]
    )
    testing_pkg.save()

    api, problem = _mock_polygon_api()
    with mock.patch.object(upload, '_get_polygon_api', return_value=api):
        # Before the #591 fix this raised
        # "RuntimeError: asyncio.run() cannot be called from a running event
        # loop" inside _collect_generators, driven from this running loop.
        asyncio.run(
            upload.upload_problem(
                name='prob',
                main_language=None,
                upload_only={'tests'},
            )
        )

    # The upload reached its commit step instead of crashing mid-way, and the
    # generator source was shipped (proving generator collection ran).
    assert problem.commit_changes.called
    saved_names = {c.kwargs.get('name') for c in problem.save_file.call_args_list}
    assert 'gen.cpp' in saved_names
