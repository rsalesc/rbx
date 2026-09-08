"""Get a DOMjudge instance ready to time solutions on, or refuse by name.

Two jobs, and the first one is the important one.

**Preflight.** Every precondition DOMjudge does not enforce for us shows up, when
unmet, as a run that waits forever rather than as an error -- a submission stored
but never judged, a judgement list filtered to empty. Each check here converts
one of those into a sentence naming the cause. That is most of this module's
value.

**Staging.** The probe contest and problem, created once and reused. Idempotent
throughout: a session that dies halfway leaves the next one closer to ready
rather than leaving garbage behind.
"""

import datetime
import time
from typing import Any, Dict, List, Optional

from rbx.box.runners.base import RunnerCapabilityError, RunPurpose
from rbx.box.runners.domjudge.api import DomjudgeApi
from rbx.box.runners.problem_id import RBXT_PREFIX

# The contest every probe problem lives in. One contest, many problems: a
# problem is per package and per purpose, while the contest is just the place
# they hang.
PROBE_CONTEST_ID = 'rbx-timing'
PROBE_CONTEST_NAME = 'rbx timing probes'

# Ten years. The end time is load-bearing twice over: past it DOMjudge stores a
# submission without ever judging it (`SubmissionService` only logs "the contest
# is closed"), and `RunController` filters the runs list on
# `s.submittime < c.endtime`, so the timings would be invisible even if they
# existed. Both failures look like "still queued" from the outside.
PROBE_CONTEST_DURATION = '87600:00:00.000'

# Start the contest an hour ago. A jury account may submit to a contest that has
# not started, but nothing is gained by relying on that.
PROBE_CONTEST_BACKDATE = datetime.timedelta(hours=1)

# The team every probe submission is made as. Present on every DOMjudge install
# (hidden, in the `system` group) and already what DOMjudge itself uses for jury
# submissions, so rbx creates no team of its own.
PROBE_TEAM_ID = 'domjudge'

# DOMjudge's `lazy_eval_results` value for "judge every testcase". Set on the
# contest-problem, where it overrides the global setting for this problem alone
# -- which is how a timing run gets full judging without reconfiguring a shared
# instance.
FULL_JUDGING = 2


def probe_label(problem_id: str) -> str:
    """The label this probe problem is linked into the contest under.

    **The problem id itself**, which is unique by construction, because DOMjudge
    requires the label to be unique within a contest and answers a duplicate with
    a bare `500 Internal Server Error` that names nothing.

    A fixed label would not merely be fragile here, it would be *always* wrong:
    the estimation and validation problems share one contest by design, so the
    second one `rbx time` staged would collide with the first every time. The
    label is invisible anyway -- the probe contest has no scoreboard anyone
    reads.
    """
    return problem_id


def probe_problem_id(slug: str, purpose: RunPurpose) -> str:
    """The remote problem this package, for this purpose, belongs to.

    `slug` is the package's one identity on any remote judge, out of `.rbx-id` --
    the same slug MOJ renders `<login>#rbxt-<slug>` from. It used to be a hash of
    the package name and its testcase count, which moved every time a testcase
    was added: the run then staged a fresh problem and left the previous one
    behind, and two packages that happened to agree on both collided.

    Purpose is part of the id because the two `rbx time` phases pin *different*
    time limits, and the limits live in the package. Sharing one remote problem
    would make every alternation between phases a fresh upload -- exactly the
    thrash `RunPurpose` was introduced to prevent.
    """
    return f'{RBXT_PREFIX}{slug}-{_purpose_suffix(purpose)}'


def _purpose_suffix(purpose: RunPurpose) -> str:
    if purpose is RunPurpose.VALIDATION:
        return 'validation'
    if purpose is RunPurpose.ESTIMATION:
        return 'estimation'
    return 'run'


async def preflight(api: DomjudgeApi) -> List[str]:
    """Refuse what cannot work; return warnings about what merely degrades.

    Ordered cheapest-first, and by how badly the failure reads: an unreachable
    server should not be reported as a configuration problem.
    """
    warnings: List[str] = []

    # Also the reachability and credentials check -- `version` is the one
    # endpoint that needs neither a contest nor a role.
    await api.version()

    config = await api.config()

    if config.get('verification_required'):
        raise RunnerCapabilityError(
            'This DOMjudge has `verification_required` turned on, which hides every '
            'judgement and run until a human verifies it in the jury interface. A '
            'timing run would poll an empty list until it gave up.\n'
            'Turn the setting off for the instance, or time the solutions locally '
            'with `rbx time`.'
        )

    judgehosts = await api.judgehosts()
    enabled = [host for host in judgehosts if host.get('enabled')]
    if not enabled:
        raise RunnerCapabilityError(
            'This DOMjudge has no enabled judgehost, so submissions are stored and '
            'never judged. Enable one in the jury interface (Judgehosts) before '
            'timing solutions on it.'
        )

    # Enabled is not the same as alive. A judgehost that is enabled but whose
    # daemon has stopped never picks anything up, and DOMjudge's own definition
    # of "this one is in trouble" is how long ago it last polled --
    # `judgehost_critical`, which is why that threshold is read from the server
    # rather than invented here.
    critical = float(config.get('judgehost_critical') or 120)
    live = [host for host in enabled if _polled_recently(host, critical)]
    if not live:
        raise RunnerCapabilityError(
            f'This DOMjudge has {len(enabled)} enabled judgehost(s), but none of them '
            f'has polled for work in the last {critical:.0f}s, so nothing would judge '
            f'a submission. Check that the judgedaemon is running.'
        )

    if len(live) > 1:
        warnings.append(
            f'This DOMjudge has {len(live)} live judgehosts. Solutions are judged '
            f'on whichever one picks them up, and the API offers no way to choose, so '
            f'timings may not be comparable across solutions.'
        )

    if config.get('enable_parallel_judging'):
        warnings.append(
            'This DOMjudge has parallel judging enabled, so a measured solution may '
            'share a judgehost with another submission. That inflates timings.'
        )

    return warnings


def _polled_recently(host: Dict[str, Any], critical_seconds: float) -> bool:
    """Whether this judgehost has asked for work recently enough to count.

    `polltime` is a unix timestamp, as a string, and `null` on a judgehost that
    has never polled at all -- the shape of the demo `example-judgehost1` row
    that ships with a stock install. Both of those are "not alive".
    """
    polltime = host.get('polltime')
    if polltime is None:
        return False
    try:
        last = float(polltime)
    except (TypeError, ValueError):
        # An unreadable timestamp is not evidence the daemon is down, and
        # refusing the run over a field rbx failed to parse would be worse than
        # letting the poll's own bound catch a judge that never answers.
        return True
    return (time.time() - last) <= critical_seconds


async def ensure_contest(api: DomjudgeApi) -> str:
    """The probe contest's external id, creating it if this is the first run."""
    contests = await api.contests()
    for contest in contests:
        if contest.get('id') == PROBE_CONTEST_ID:
            return PROBE_CONTEST_ID

    start = datetime.datetime.now(datetime.timezone.utc) - PROBE_CONTEST_BACKDATE

    # An explicit allow-list, never a dict assembled from something wider.
    # `penalty_time` here would rewrite the *instance-wide* setting of the same
    # name -- observed silently changing an unrelated contest from 20 to 0 -- so
    # the safe fields are enumerated rather than filtered.
    await api.create_contest(
        {
            'id': PROBE_CONTEST_ID,
            'name': PROBE_CONTEST_NAME,
            'formal_name': PROBE_CONTEST_NAME,
            'shortname': PROBE_CONTEST_ID,
            'start_time': start.replace(microsecond=0).isoformat(),
            'duration': PROBE_CONTEST_DURATION,
        }
    )
    return PROBE_CONTEST_ID


async def ensure_team(api: DomjudgeApi) -> str:
    """The team probe submissions are made as.

    Looked up rather than assumed: `POST /submissions` rejects a submission whose
    user has no team, and "User does not belong to a team" is a much worse
    message than this one.
    """
    teams = await api.teams()
    for team in teams:
        if team.get('id') == PROBE_TEAM_ID:
            return PROBE_TEAM_ID
    raise RunnerCapabilityError(
        f'This DOMjudge has no `{PROBE_TEAM_ID}` team, which is the account rbx '
        f'submits probe solutions as. It is present on a stock install; recreate it '
        f'in the jury interface, or point the runner at an instance that has it.'
    )


async def stage_problem(
    api: DomjudgeApi,
    contest: str,
    problem_id: str,
    zip_path,
) -> None:
    """Put `zip_path` on the server as `problem_id`, judged in full.

    Three calls in a fixed order, and the order is the whole subtlety:

    1. `add-data` creates the problem and links it, but cannot say anything
       about lazy evaluation. Skipped when the problem already exists.
    2. the upload replaces its content. It must come before the relink, because
       an import resets nothing about the link but a missing problem cannot be
       uploaded to.
    3. `DELETE` then `PUT` is the only way to set `lazy_eval_results` on an
       existing contest-problem -- `PUT` refuses a problem that is still linked.

    Without step 3 DOMjudge stops judging at the first failing testcase, and a
    solution that times out early reports one run instead of all of them.
    """
    existing = {problem.get('id') for problem in await api.problems(contest)}
    if problem_id not in existing:
        await api.add_problem_data(
            contest,
            problem_id,
            probe_label(problem_id),
            f'rbx timing probe ({problem_id})',
        )

    await api.upload_problem(contest, problem_id, zip_path)

    await api.unlink_problem(contest, problem_id)
    await api.link_problem(contest, problem_id, probe_label(problem_id), FULL_JUDGING)


def language_id_for(languages: List[Dict[str, Any]], extension: str) -> Optional[str]:
    """The DOMjudge language whose extensions include `extension`.

    Matched on extension rather than on name: the ids are an instance's own
    business (`cpp` here, `cxx` elsewhere), while the extension is a property of
    the file rbx is about to send.
    """
    wanted = extension.lstrip('.').lower()
    for language in languages:
        extensions = [str(item).lower() for item in language.get('extensions') or []]
        if wanted in extensions:
            return language.get('id')
    return None
