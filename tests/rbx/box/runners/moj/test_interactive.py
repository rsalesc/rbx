"""`MojRunner` on an interactive (`communication`) problem.

The runner used to declare `supports_interactive=False`, from before
`MojPackager` could package an interactive problem at all, so
`_check_capabilities` refused every such problem before anything was uploaded.
The probe is an ordinary `MojPackager` build, so it now ships exactly what
`rbx package moj` ships for one: the interactor as the arbiter and rbx's own
driver as every language's `run.sh`.
"""

import pytest

from rbx.box.runners.moj.runner import MojRunner
from rbx.box.schema import TaskType
from tests.rbx.box.packaging.moj.conftest import with_limits_profile
from tests.rbx.box.packaging.moj.test_interactive import INTERACTOR
from tests.rbx.box.runners.moj.test_runner import FakeMoj, _conf, _context

pytestmark = pytest.mark.shared_cache


def test_interactive_problems_are_supported():
    assert MojRunner.caps.supports_interactive


def _interactive_package(testing_pkg) -> None:
    testing_pkg.set_type(TaskType.COMMUNICATION)
    testing_pkg.add_file('interactor.cpp').write_text(INTERACTOR)
    testing_pkg.set_interactor('interactor.cpp')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text('int main(){}\n')
    with_limits_profile(testing_pkg)


async def test_the_probe_of_an_interactive_problem_ships_the_driver(
    testing_pkg, tmp_path, monkeypatch
):
    _interactive_package(testing_pkg)
    fake = FakeMoj(tmp_path / 'snapshots').install(monkeypatch)

    await MojRunner().prepare(_context(tmp_path, timelimit_override=2500))

    scripts = fake.uploaded / 'scripts'
    # The arbiter and the pipe runner the driver needs, and no batch checker.
    assert (scripts / 'arbitro.cpp').is_file()
    assert (scripts / 'pipe.c').is_file()
    assert not (scripts / 'checker.cpp').exists()
    # Every language's run.sh is the driver, carrying the batch run.sh inside.
    run = (scripts / 'cpp' / 'run.sh').read_text()
    assert '/tmp/dir/arbitro' in run
    assert '{{batchRun}}' not in run
    assert (scripts / 'cpp' / 'prep.sh').is_file()

    conf = _conf(fake.uploaded)
    assert conf['TLOVERRIDE[default]'] == '2.500'
    assert conf['ULIMITS[-u]'] == '10000'
