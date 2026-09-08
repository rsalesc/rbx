"""The probe package: what `rbx time --runner domjudge` uploads to measure on.

Three differences from a real package, each of which was found by running
against a live DOMjudge and each of which fails *silently* if it regresses --
the package still imports, and the run still produces numbers.
"""

from rbx.box import header
from rbx.box.packaging.domjudge.packager import DomjudgePackager, ProbePackage
from rbx.box.schema import ExpectedOutcome
from rbx.box.statements.schema import StatementType

PROBE = ProbePackage(problem_id='rbxt-abc123-estimation', timelimit_ms=10_000)


def with_a_solution(testing_pkg):
    """A package with something to ship, so "ships none" is a real contrast."""
    testing_pkg.add_solution('sol.cpp', ExpectedOutcome.ACCEPTED).write_text(
        'int main() { return 0; }\n'
    )
    testing_pkg.save()
    header.generate_header()


def test_the_ini_declares_the_external_id(testing_pkg):
    """DOMjudge decides which problem an upload overwrites by comparing this key
    against the target, and refuses the mismatch. Without it the id comes from
    the *zip filename* instead, which is pol2dom's workaround.
    """
    testing_pkg.save()

    packager = DomjudgePackager(testcase_entries=[], probe=PROBE)
    lines = packager._get_ini().splitlines()  # noqa: SLF001

    assert f'externalid = {PROBE.problem_id}' in lines
    assert f'short-name = {PROBE.problem_id}' in lines


def test_the_probe_pins_the_limit_the_run_asked_for_not_the_profile(testing_pkg):
    """The profile's limit is precisely the thing a timing run exists to
    replace, so reading it here would measure against the answer."""
    testing_pkg.yml.timeLimit = 1000
    testing_pkg.save()

    packager = DomjudgePackager(testcase_entries=[], probe=PROBE)
    lines = packager._get_ini().splitlines()  # noqa: SLF001

    assert 'timelimit = 10.000' in lines
    assert 'timelimit = 1.000' not in lines


def test_a_probe_builds_no_statement(testing_pkg):
    """The PDF is the bulk of a DOMjudge zip and is re-uploaded on every limit
    change, for a document nobody opens on a private probe problem."""
    testing_pkg.save()

    assert DomjudgePackager(testcase_entries=[], probe=PROBE).statement_types() == []


def test_a_real_package_still_builds_its_statement(testing_pkg):
    """The probe path must not become the default by accident."""
    testing_pkg.save()

    assert DomjudgePackager(testcase_entries=[]).statement_types() == [
        StatementType.PDF
    ]


def test_a_probe_ships_no_submissions(testing_pkg, tmp_path):
    """The finding that is easiest to miss and costliest to miss.

    DOMjudge *submits* everything under `submissions/` for real on import -- it
    answers "Added N jury solution(s)" and queues them as team `domjudge`. Those
    judgings then compete with rbx's own measured runs for the judgehost and
    inflate the very timings the run exists to take, while the package still
    imports perfectly cleanly.
    """
    with_a_solution(testing_pkg)

    packager = DomjudgePackager(testcase_entries=[], probe=PROBE)
    into_path = tmp_path / 'package'
    packager.package(tmp_path, into_path, [])

    assert not (into_path / 'submissions').exists()


def test_a_real_package_still_ships_submissions(testing_pkg, tmp_path):
    with_a_solution(testing_pkg)

    packager = DomjudgePackager(testcase_entries=[])
    into_path = tmp_path / 'package'
    packager.package(tmp_path, into_path, [])

    assert (into_path / 'submissions' / 'accepted' / 'sol.cpp').is_file()
