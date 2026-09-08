"""The one identity a package has on any remote judge.

Each backend used to answer "what is this package called on the server?" its own
way, so one package had two unrelated identities -- and DOMjudge's moved whenever
a testcase was added, stranding the problem it had been using. These pin the
shared slug both now render from: that it is stable, that it is not derived from
anything that changes, and that a package which predates the file keeps the
problem it is already bound to.
"""

import json
import pathlib

from rbx.box.runners.moj.problem_id import ensure_moj_id
from rbx.box.runners.problem_id import (
    adopt_slug,
    ensure_slug,
    rbx_id_path,
    read_slug,
)


def test_the_slug_lives_at_the_package_root(tmp_path: pathlib.Path):
    """Beside `problem.rbx.yml`, not under `.rbx/`. The cache is regenerated
    freely, and a slug that vanished with it would leave a dead problem on the
    server after every clean."""
    assert rbx_id_path(tmp_path) == tmp_path / '.rbx-id'


def test_a_slug_does_not_change_when_asked_again(tmp_path: pathlib.Path):
    """The whole contract. Two calls, two runs, two backends and two commands all
    have to get the same answer, or each binds to a problem of its own."""
    assert ensure_slug(tmp_path) == ensure_slug(tmp_path)


def test_two_packages_do_not_share_a_slug(tmp_path: pathlib.Path):
    """Ids share one namespace on the server, across every setter and package.

    Random rather than derived from the package name: rbx names are not unique,
    so two setters working through the same tutorial package would otherwise
    collide, and one would be writing over the other's problem.
    """
    (tmp_path / 'a').mkdir()
    (tmp_path / 'b').mkdir()

    assert ensure_slug(tmp_path / 'a') != ensure_slug(tmp_path / 'b')


def test_nothing_is_recorded_until_a_slug_is_asked_for(tmp_path: pathlib.Path):
    """A package nobody has run remotely carries no binding."""
    assert read_slug(tmp_path) is None
    assert not rbx_id_path(tmp_path).is_file()


def test_a_corrupt_file_is_regenerated_rather_than_raising(tmp_path: pathlib.Path):
    """A half-written binding must not be the thing that stops a run.

    This file names a disposable `rbxt-` problem, never authored content. Nothing
    is lost by rebinding -- the old remote problem is simply left behind.
    """
    rbx_id_path(tmp_path).write_text('{ this is not json')

    slug = ensure_slug(tmp_path)

    assert slug
    assert json.loads(rbx_id_path(tmp_path).read_text())['slug'] == slug


def test_a_file_holding_no_slug_is_regenerated(tmp_path: pathlib.Path):
    rbx_id_path(tmp_path).write_text(json.dumps({'note': 'hello'}))

    assert ensure_slug(tmp_path)


def test_regenerating_keeps_the_fields_somebody_else_wrote(tmp_path: pathlib.Path):
    rbx_id_path(tmp_path).write_text(json.dumps({'note': 'hello'}))

    ensure_slug(tmp_path)

    payload = json.loads(rbx_id_path(tmp_path).read_text())
    assert payload['note'] == 'hello'


# -- adoption --------------------------------------------------------------------


def test_adopting_records_a_slug_when_there_is_none(tmp_path: pathlib.Path):
    assert adopt_slug('deadbeef', tmp_path) == 'deadbeef'
    assert ensure_slug(tmp_path) == 'deadbeef'


def test_an_existing_slug_wins_over_an_adopted_one(tmp_path: pathlib.Path):
    """Overwriting would move whichever backend had already bound to it, which is
    the one outcome this file exists to prevent."""
    existing = ensure_slug(tmp_path)

    assert adopt_slug('deadbeef', tmp_path) == existing
    assert read_slug(tmp_path) == existing


# -- what the backends make of it ------------------------------------------------


def test_moj_and_domjudge_name_the_same_package_from_the_same_slug(
    tmp_path: pathlib.Path,
):
    """THE test. One package, one identity, however it is reached.

    The two spellings differ because the servers do -- MOJ scopes ids by org, and
    DOMjudge's are flat and per-phase -- but the half that identifies the
    *package* is one value, decided in one place.
    """
    from rbx.box.runners.base import RunPurpose
    from rbx.box.runners.domjudge.staging import probe_problem_id

    moj_id = ensure_moj_id('alice', tmp_path)
    slug = read_slug(tmp_path)

    assert slug is not None
    assert moj_id == f'alice#rbxt-{slug}'
    assert probe_problem_id(slug, RunPurpose.ESTIMATION) == f'rbxt-{slug}-estimation'


def test_a_package_bound_before_the_shared_file_keeps_its_problem(
    tmp_path: pathlib.Path,
):
    """Migration, and it has to be this direction.

    A `.moj-id` written months ago names a problem MOJ already holds. Minting a
    fresh slug beside it would move the package to a new problem on the next run
    and leave the old one orphaned, so the existing slug is adopted instead --
    and DOMjudge then lands on the same identity.
    """
    (tmp_path / '.moj-id').write_text(json.dumps({'id': 'alice#rbxt-deadbeef'}))

    assert ensure_moj_id('alice', tmp_path) == 'alice#rbxt-deadbeef'
    assert read_slug(tmp_path) == 'deadbeef'


def test_a_foreign_binding_is_not_adopted(tmp_path: pathlib.Path):
    """A real, published problem's id is the other server's naming, not an
    identity rbx may hand to another judge -- and rbx never created it, so it is
    not rbx's to spread."""
    (tmp_path / '.moj-id').write_text(json.dumps({'id': 'alice#somaditos'}))

    assert ensure_moj_id('bob', tmp_path) == 'alice#somaditos'
    assert read_slug(tmp_path) is None
