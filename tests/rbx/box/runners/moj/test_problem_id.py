"""What binds an rbx package to its problem on the MOJ server.

The binding is a file, `.moj-id`, and the file is meant to be committed. These
tests pin the two halves of that: the slug must survive across calls and across
setters, and a file the setter never wrote by hand must never be the thing that
stops a run.
"""

import json
import pathlib

from rbx.box.runners.moj.problem_id import ensure_moj_id, moj_id_path


def test_the_id_lives_at_the_package_root(tmp_path: pathlib.Path):
    assert moj_id_path(tmp_path) == tmp_path / '.moj-id'


def test_creates_an_id_that_does_not_change_when_asked_again(tmp_path: pathlib.Path):
    """The id must be stable, or every call would orphan a problem on the server."""
    first = ensure_moj_id('alice', tmp_path)
    second = ensure_moj_id('alice', tmp_path)

    assert first == second
    assert first.startswith('alice#rbxt-')


def test_reuses_a_committed_id_rather_than_generating_a_new_one(
    tmp_path: pathlib.Path,
):
    """Committing the file is what makes two setters reach the same problem."""
    (tmp_path / '.moj-id').write_text(json.dumps({'id': 'alice#rbxt-deadbeef'}))

    assert ensure_moj_id('alice', tmp_path) == 'alice#rbxt-deadbeef'


def test_a_different_login_reclaims_the_same_slug_under_its_own_org(
    tmp_path: pathlib.Path,
):
    """The slug is the stable half; the org is whoever is logged in.

    A co-setter cannot write under someone else's org, so keeping the committed
    org would fail on the server rather than reach their own copy.
    """
    (tmp_path / '.moj-id').write_text(json.dumps({'id': 'alice#rbxt-deadbeef'}))

    assert ensure_moj_id('bob', tmp_path) == 'bob#rbxt-deadbeef'


def test_reclaiming_keeps_the_fields_the_moj_cli_wrote(tmp_path: pathlib.Path):
    """`.moj-id` is the CLI's own file, and it holds more than the id."""
    (tmp_path / '.moj-id').write_text(
        json.dumps(
            {
                'id': 'alice#rbxt-deadbeef',
                'title': 'A plus B',
                'public': False,
                'collections': ['rbx'],
            }
        )
    )

    ensure_moj_id('bob', tmp_path)

    payload = json.loads((tmp_path / '.moj-id').read_text())
    assert payload == {
        'id': 'bob#rbxt-deadbeef',
        'title': 'A plus B',
        'public': False,
        'collections': ['rbx'],
    }


def test_a_corrupt_file_is_regenerated_rather_than_raising(tmp_path: pathlib.Path):
    """A half-written file must not be the thing that stops a run."""
    (tmp_path / '.moj-id').write_text('{ this is not json')

    moj_id = ensure_moj_id('alice', tmp_path)

    assert moj_id.startswith('alice#rbxt-')
    assert json.loads((tmp_path / '.moj-id').read_text())['id'] == moj_id


def test_a_file_holding_no_id_is_regenerated(tmp_path: pathlib.Path):
    (tmp_path / '.moj-id').write_text(json.dumps({'title': 'A plus B'}))

    assert ensure_moj_id('alice', tmp_path).startswith('alice#rbxt-')


def test_a_binding_to_a_real_problem_is_left_exactly_as_it_is(
    tmp_path: pathlib.Path,
):
    """Only the throwaway `rbxt-` problems are ours to rewrite.

    `.moj-id` is written by `moj upload` too, so a package may legitimately be
    bound to a real, published problem. Reclaiming that under the current login
    would point the run at a problem that does not exist.
    """
    (tmp_path / '.moj-id').write_text(json.dumps({'id': 'alice#somaditos'}))

    assert ensure_moj_id('bob', tmp_path) == 'alice#somaditos'
    assert json.loads((tmp_path / '.moj-id').read_text()) == {'id': 'alice#somaditos'}


def test_two_packages_do_not_share_a_slug(tmp_path: pathlib.Path):
    """Ids share one namespace on the server, across every setter and package."""
    (tmp_path / 'a').mkdir()
    (tmp_path / 'b').mkdir()

    assert ensure_moj_id('alice', tmp_path / 'a') != ensure_moj_id(
        'alice', tmp_path / 'b'
    )
