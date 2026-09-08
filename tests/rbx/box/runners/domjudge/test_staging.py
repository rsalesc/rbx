"""Preflight and staging: refusing what cannot work, before anything is uploaded.

Every precondition checked here shows up, when unmet, as a run that waits forever
rather than as an error -- a submission stored but never judged, a judgement list
filtered to empty. So what these tests pin is that each one is *refused by name*
instead of being discovered ten minutes into a poll.
"""

import time
from typing import Any, Dict, List, Optional

import pytest

from rbx.box.runners.base import RunnerCapabilityError, RunPurpose
from rbx.box.runners.domjudge import staging


def live_judgehost(id: str) -> Dict[str, Any]:
    """An enabled judgehost that polled just now -- what a working one looks like."""
    return {'id': id, 'enabled': True, 'polltime': str(time.time())}


class FakeApi:
    """A DOMjudge that answers whatever the test needs it to."""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        judgehosts: Optional[List[Dict[str, Any]]] = None,
        contests: Optional[List[Dict[str, Any]]] = None,
        teams: Optional[List[Dict[str, Any]]] = None,
        problems: Optional[List[Dict[str, Any]]] = None,
    ):
        self._config = config if config is not None else {}
        self._judgehosts = (
            judgehosts if judgehosts is not None else [live_judgehost('1')]
        )
        self._contests = contests if contests is not None else []
        self._teams = teams if teams is not None else [{'id': 'domjudge'}]
        self._problems = problems if problems is not None else []
        self.calls: List[str] = []
        self.created_contests: List[Dict[str, Any]] = []
        self.linked: List[Dict[str, Any]] = []

    async def version(self):
        self.calls.append('version')
        return {'api_version': 4}

    async def config(self):
        return self._config

    async def judgehosts(self):
        return self._judgehosts

    async def contests(self):
        return self._contests

    async def teams(self):
        return self._teams

    async def problems(self, contest):
        return self._problems

    async def create_contest(self, contest):
        self.calls.append('create_contest')
        self.created_contests.append(contest)
        self._contests.append({'id': contest['id']})
        return contest['id']

    async def add_problem_data(self, contest, problem_id, label, name):
        self.calls.append('add_problem_data')
        self._problems.append({'id': problem_id})
        return [problem_id]

    async def upload_problem(self, contest, problem_id, zip_path):
        self.calls.append('upload_problem')
        return {'problem_id': problem_id}

    async def unlink_problem(self, contest, problem_id):
        self.calls.append('unlink_problem')

    async def link_problem(self, contest, problem_id, label, lazy_eval_results):
        self.calls.append('link_problem')
        self.linked.append(
            {
                'problem_id': problem_id,
                'label': label,
                'lazy_eval_results': lazy_eval_results,
            }
        )
        return {'id': problem_id}


# -- preflight --------------------------------------------------------------------


async def test_a_healthy_instance_raises_nothing_and_warns_about_nothing():
    assert await staging.preflight(FakeApi()) == []


async def test_verification_required_is_refused_by_name():
    """With it on, `RunController` and `JudgementController` both filter on
    `j.verified = 1`, so a timing run polls an empty list until it gives up."""
    api = FakeApi(config={'verification_required': True})

    with pytest.raises(RunnerCapabilityError) as exc:
        await staging.preflight(api)

    assert 'verification_required' in str(exc.value.message)


async def test_a_disabled_judgehost_is_refused():
    """Submissions would be stored and never judged -- indistinguishable, from
    the outside, from a judge that is merely slow.

    `example-judgehost1` ships disabled on a stock install, so this is the shape
    of a server that has never had a real judgehost attached.
    """
    api = FakeApi(judgehosts=[{'id': '1', 'enabled': False, 'polltime': None}])

    with pytest.raises(RunnerCapabilityError) as exc:
        await staging.preflight(api)

    assert 'no enabled judgehost' in str(exc.value.message)


async def test_an_enabled_but_silent_judgehost_is_refused_differently():
    """Enabled is not alive. A judgehost whose daemon stopped never picks
    anything up, and the fix ("start the judgedaemon") is a different one from
    enabling it -- so the message has to be different too."""
    api = FakeApi(
        judgehosts=[{'id': '1', 'enabled': True, 'polltime': str(time.time() - 9999)}],
        config={'judgehost_critical': 120},
    )

    with pytest.raises(RunnerCapabilityError) as exc:
        await staging.preflight(api)

    assert 'polled for work' in str(exc.value.message)


async def test_a_judgehost_that_never_polled_is_not_live():
    api = FakeApi(judgehosts=[{'id': '1', 'enabled': True, 'polltime': None}])

    with pytest.raises(RunnerCapabilityError):
        await staging.preflight(api)


async def test_no_judgehosts_at_all_is_refused():
    with pytest.raises(RunnerCapabilityError):
        await staging.preflight(FakeApi(judgehosts=[]))


async def test_several_live_judgehosts_warn_rather_than_refuse():
    """The run still works; its timings just come from machines that may differ,
    and the API offers no way to choose one."""
    api = FakeApi(judgehosts=[live_judgehost('1'), live_judgehost('2')])

    warnings = await staging.preflight(api)

    assert len(warnings) == 1
    assert '2 live judgehosts' in warnings[0]


async def test_a_dead_judgehost_beside_a_live_one_neither_refuses_nor_warns():
    """The stock demo row is disabled, so every real install has one. Counting
    it would warn about incomparable timings on a single-judgehost server."""
    api = FakeApi(
        judgehosts=[
            {'id': '1', 'enabled': False, 'polltime': None},
            live_judgehost('2'),
        ]
    )

    assert await staging.preflight(api) == []


async def test_parallel_judging_warns():
    api = FakeApi(config={'enable_parallel_judging': 1})

    warnings = await staging.preflight(api)

    assert any('parallel' in warning for warning in warnings)


# -- the contest ------------------------------------------------------------------


async def test_the_probe_contest_is_created_once():
    api = FakeApi()

    assert await staging.ensure_contest(api) == staging.PROBE_CONTEST_ID
    assert await staging.ensure_contest(api) == staging.PROBE_CONTEST_ID

    assert api.calls.count('create_contest') == 1


async def test_an_existing_probe_contest_is_reused_untouched():
    api = FakeApi(contests=[{'id': staging.PROBE_CONTEST_ID}])

    await staging.ensure_contest(api)

    assert 'create_contest' not in api.calls


async def test_the_created_contest_never_sends_penalty_time():
    """`penalty_time` in this payload rewrites the *instance-wide* setting of the
    same name -- observed changing an unrelated contest from 20 to 0. Staging
    sends an allow-list precisely so a field like it cannot creep back in."""
    api = FakeApi()

    await staging.ensure_contest(api)

    assert 'penalty_time' not in api.created_contests[0]


async def test_the_created_contest_ends_far_in_the_future():
    """Past the end time DOMjudge stores submissions without judging them, and
    hides the runs from the list query. Both read as "still queued"."""
    api = FakeApi()

    await staging.ensure_contest(api)

    assert api.created_contests[0]['duration'] == staging.PROBE_CONTEST_DURATION


# -- the team ---------------------------------------------------------------------


async def test_the_builtin_domjudge_team_is_used():
    assert await staging.ensure_team(FakeApi()) == staging.PROBE_TEAM_ID


async def test_a_missing_team_is_refused_before_any_submission():
    """`POST /submissions` would answer "User does not belong to a team", which
    says nothing about what to do."""
    api = FakeApi(teams=[{'id': 'someone-else'}])

    with pytest.raises(RunnerCapabilityError) as exc:
        await staging.ensure_team(api)

    assert staging.PROBE_TEAM_ID in str(exc.value.message)


# -- staging the problem ----------------------------------------------------------


async def test_a_new_problem_is_created_uploaded_and_relinked_in_that_order(tmp_path):
    """The order is the whole subtlety: `PUT` refuses a problem that is still
    linked, so full judging can only be requested after an unlink."""
    api = FakeApi()

    await staging.stage_problem(api, 'rbx-timing', 'rbxt-abc-estimation', tmp_path)

    assert api.calls == [
        'add_problem_data',
        'upload_problem',
        'unlink_problem',
        'link_problem',
    ]


async def test_an_existing_problem_is_not_created_again(tmp_path):
    """Re-uploading must land on the same problem rather than making a second."""
    api = FakeApi(problems=[{'id': 'rbxt-abc-estimation'}])

    await staging.stage_problem(api, 'rbx-timing', 'rbxt-abc-estimation', tmp_path)

    assert 'add_problem_data' not in api.calls


async def test_the_problem_is_linked_for_full_judging(tmp_path):
    """Without this DOMjudge stops at the first failing testcase, and a solution
    that times out early reports one run instead of all of them."""
    api = FakeApi()

    await staging.stage_problem(api, 'rbx-timing', 'rbxt-abc-estimation', tmp_path)

    assert api.linked[0]['lazy_eval_results'] == staging.FULL_JUDGING


# -- ids and languages ------------------------------------------------------------


def test_each_purpose_gets_its_own_problem():
    """The two `rbx time` phases pin different limits, and the limits live in the
    package -- so one shared problem would be re-uploaded on every alternation."""
    ids = {
        staging.probe_problem_id('abc123', purpose)
        for purpose in (RunPurpose.ESTIMATION, RunPurpose.VALIDATION, RunPurpose.RUN)
    }

    assert len(ids) == 3


def test_a_probe_problem_id_is_marked_as_one():
    """The `rbxt-` prefix is what tells a reader (and a future guard) that the
    problem is rbx's to overwrite."""
    assert staging.probe_problem_id('abc123', RunPurpose.ESTIMATION).startswith('rbxt-')


LANGUAGES = [
    {'id': 'cpp', 'extensions': ['cpp', 'cc', 'cxx']},
    {'id': 'python3', 'extensions': ['py']},
]


@pytest.mark.parametrize(
    ('extension', 'expected'),
    [('.cpp', 'cpp'), ('cpp', 'cpp'), ('.CC', 'cpp'), ('.py', 'python3')],
)
def test_a_language_is_matched_on_extension(extension, expected):
    """Matched on extension rather than name: the ids are an instance's own
    business, while the extension is a property of the file being sent."""
    assert staging.language_id_for(LANGUAGES, extension) == expected


def test_an_unknown_extension_matches_nothing():
    assert staging.language_id_for(LANGUAGES, '.rs') is None


async def test_two_probe_problems_do_not_share_a_label(tmp_path):
    """DOMjudge requires the label to be unique within a contest and answers a
    duplicate with a bare `500 Internal Server Error` naming nothing.

    A fixed label would be *always* wrong rather than merely fragile: the
    estimation and validation problems share one contest by design, so the second
    phase would collide with the first on every run.
    """
    api = FakeApi()
    estimation = staging.probe_problem_id('abc123', RunPurpose.ESTIMATION)
    validation = staging.probe_problem_id('abc123', RunPurpose.VALIDATION)

    await staging.stage_problem(api, 'rbx-timing', estimation, tmp_path)
    await staging.stage_problem(api, 'rbx-timing', validation, tmp_path)

    labels = [link['label'] for link in api.linked]
    assert len(set(labels)) == 2
