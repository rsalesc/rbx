from unittest import mock

import pytest
import requests

from rbx.box.packaging.moj import mojtools
from rbx.box.schema import TaskType
from tests.rbx.box.packaging.moj.conftest import (
    build_entries,
    minimal_package,
    run_packager,
)

# The real fetch, captured before the conftest's autouse fixture stubs it out.
REAL_FETCH_UPSTREAM = mojtools.fetch_upstream

ALL_FILES = [
    mojtools.CHECKER_COMPARE_STUB,
    mojtools.INTERACTIVE_COMPARE_STUB,
    mojtools.INTERACTIVE_PREP_STUB,
    mojtools.INTERACTIVE_RUN,
]


def _upstream(overrides=None, missing=()):
    """A fake mojtools `master`: the bundled copy, except for `overrides`, with the
    files in `missing` unreachable."""

    def fetch(path):
        if path in missing:
            return None
        return (overrides or {}).get(path, mojtools.vendored(path))

    return fetch


# -- the bundled snapshot -------------------------------------------------------


def test_every_file_is_bundled():
    for path in ALL_FILES:
        assert mojtools.vendored(path)


def test_bundled_commit_is_a_full_sha():
    commit = mojtools.vendored_commit()
    assert len(commit) == 40
    int(commit, 16)


# -- resolve --------------------------------------------------------------------


def test_uses_upstream_silently_when_it_matches_the_bundled_copy(monkeypatch, capsys):
    monkeypatch.setattr(mojtools, 'fetch_upstream', _upstream())

    files = mojtools.resolve(ALL_FILES)

    assert files == mojtools.MojtoolsFiles(
        {path: mojtools.vendored(path) for path in ALL_FILES}, upstream=True
    )
    assert capsys.readouterr().out == ''


def test_prefers_upstream_and_names_what_changed(monkeypatch, capsys):
    monkeypatch.setattr(
        mojtools,
        'fetch_upstream',
        _upstream(overrides={mojtools.INTERACTIVE_RUN: b'#!/bin/bash\n# newer\n'}),
    )

    files = mojtools.resolve(ALL_FILES)

    assert files.upstream
    assert files.files[mojtools.INTERACTIVE_RUN] == b'#!/bin/bash\n# newer\n'
    out = capsys.readouterr().out
    assert mojtools.INTERACTIVE_RUN in out
    assert mojtools.CHECKER_COMPARE_STUB not in out


def test_falls_back_to_the_bundled_copy_for_every_file_when_one_fails(
    monkeypatch, capsys
):
    # Never a mix of two mojtools versions in one package.
    monkeypatch.setattr(
        mojtools,
        'fetch_upstream',
        _upstream(
            overrides={mojtools.INTERACTIVE_RUN: b'newer'},
            missing={mojtools.INTERACTIVE_PREP_STUB},
        ),
    )

    files = mojtools.resolve(ALL_FILES)

    assert files == mojtools.MojtoolsFiles(
        {path: mojtools.vendored(path) for path in ALL_FILES}, upstream=False
    )
    out = capsys.readouterr().out
    assert mojtools.vendored_commit()[:8] in out


def test_fetches_from_mojtools_master():
    response = mock.Mock(content=b'data')
    with mock.patch.object(requests, 'get', return_value=response) as get:
        assert REAL_FETCH_UPSTREAM(mojtools.INTERACTIVE_RUN) == b'data'
    get.assert_called_once_with(
        'https://raw.githubusercontent.com/cd-moj/mojtools/master/interactive/run.sh',
        timeout=mojtools.FETCH_TIMEOUT_SECONDS,
    )


@pytest.mark.parametrize(
    'failure',
    [requests.ConnectionError('offline'), requests.Timeout('slow')],
)
def test_a_network_failure_is_no_file(failure):
    with mock.patch.object(requests, 'get', side_effect=failure):
        assert REAL_FETCH_UPSTREAM(mojtools.INTERACTIVE_RUN) is None


def test_an_http_error_is_no_file():
    response = mock.Mock()
    response.raise_for_status.side_effect = requests.HTTPError('404')
    with mock.patch.object(requests, 'get', return_value=response):
        assert REAL_FETCH_UPSTREAM(mojtools.INTERACTIVE_RUN) is None


# -- the packager ships what resolve picked -------------------------------------


def test_batch_package_ships_the_upstream_compare_stub(
    testing_pkg, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        mojtools,
        'fetch_upstream',
        _upstream(overrides={mojtools.CHECKER_COMPARE_STUB: b'#!/bin/bash\n'}),
    )
    minimal_package(testing_pkg)
    testing_pkg.save()

    into = run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['tests']))

    compare = into / 'scripts' / 'compare.sh'
    assert compare.read_bytes() == b'#!/bin/bash\n'
    assert compare.stat().st_mode & 0o111


def test_interactive_package_ships_the_upstream_driver(
    testing_pkg, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        mojtools,
        'fetch_upstream',
        _upstream(overrides={mojtools.INTERACTIVE_RUN: b'#!/bin/bash\n# newer\n'}),
    )
    testing_pkg.set_type(TaskType.COMMUNICATION)
    testing_pkg.add_file('interactor.cpp').write_text(
        '#include "testlib.h"\nint main(int c, char **v){ registerInteraction(c, v);'
        ' quitf(_ok, "ok"); }\n'
    )
    testing_pkg.set_interactor('interactor.cpp')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text('int main(){}\n')
    testing_pkg.save()

    into = run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['tests']))

    runs = list((into / 'scripts').glob('*/run.sh'))
    assert runs
    for run in runs:
        assert run.read_bytes() == b'#!/bin/bash\n# newer\n'


def test_a_package_fetches_only_what_it_needs(testing_pkg, tmp_path, monkeypatch):
    fetched = []

    def fetch(path):
        fetched.append(path)
        return mojtools.vendored(path)

    monkeypatch.setattr(mojtools, 'fetch_upstream', fetch)
    minimal_package(testing_pkg)
    testing_pkg.save()

    run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['tests']))

    assert fetched == [mojtools.CHECKER_COMPARE_STUB]
