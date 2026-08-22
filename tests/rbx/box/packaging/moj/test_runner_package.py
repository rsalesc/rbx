"""The package a remote timing run uploads.

`rbx time -p moj --runner moj` measures solution timings on the MOJ judge park
instead of the setter's machine. What it uploads is a MOJ package like any other,
except in three ways, and all three are about *measuring* rather than judging:

- the time limits are the ones **this run asked to measure under** -- one cap for
  every language while estimating, one per language group while validating --
  instead of coming from the `moj` limits profile;
- only the model solution is shipped, since `moj testrun` sends the source of the
  solution being timed in the request body;
- the submission whitelist covers every language rbx may testrun, not the languages
  the package happens to ship -- the API refuses a submission outside it.

Design: `docs/plans/2026-08-20-moj-remote-runner-design.md`.
"""

import json
import re
from typing import List

import pytest

from rbx.box.packaging.moj.packager import (
    JudgeCalibrated,
    MojPackager,
    ProbePackage,
    ProbePinned,
    ProfilePinned,
    check_timing_setup,
)
from rbx.box.statements.schema import StatementType
from tests.rbx.box.packaging.moj.conftest import (
    CHECKER,
    PT_BLOCKS,
    SLOW_SOL,
    WRONG_SOL,
    build_entries,
    minimal_package,
    run_packager,
    with_limits_profile,
    with_statements,
)


def _conf_value(conf: str, key: str) -> str:
    for line in conf.splitlines():
        if line.startswith(f'{key}='):
            return line.split('=', 1)[1]
    raise AssertionError(f'{key} not found in conf:\n{conf}')


def _keys(conf: str) -> list:
    return [line.split('=', 1)[0] for line in conf.splitlines() if '=' in line]


def _overrides(conf: str) -> list:
    return [key for key in _keys(conf) if key.startswith('TLOVERRIDE[')]


# -- the probe timing mode ---------------------------------------------------


def test_probe_limit_pins_every_language_to_one_number(testing_pkg, tmp_path):
    minimal_package(testing_pkg)
    # A profile with per-language limits exists and is deliberately ignored: the
    # estimation phase caps every accepted solution at one `inferenceTimeout`, and
    # emitting the profile's entries beside it would measure java under 3s while
    # rbx asked for 2.5s, truncating the very timings the estimate rests on.
    with_limits_profile(testing_pkg, time_limit=1000, per_language={'java': 3000})
    testing_pkg.save()

    conf = (
        run_packager(
            testing_pkg,
            tmp_path,
            build_entries(tmp_path, ['samples']),
            timing_mode=ProbePinned(default_ms=2500),
        )
        / 'conf'
    ).read_text()

    assert _overrides(conf) == ['TLOVERRIDE[default]']
    assert _conf_value(conf, 'TLOVERRIDE[default]') == '2.500'
    # Nothing is handed to the judge to measure: the cap is rbx's.
    assert 'TLMOD[calibrafactor]' not in _keys(conf)


def test_probe_limit_needs_no_limits_profile(testing_pkg, tmp_path):
    # `_require_limits_profile` is about the `moj` profile, which a probe package
    # never consults -- the cap comes from the timing run itself.
    minimal_package(testing_pkg)
    (testing_pkg.root / '.limits' / 'moj.yml').unlink()
    testing_pkg.save()

    conf = (
        run_packager(
            testing_pkg,
            tmp_path,
            build_entries(tmp_path, ['samples']),
            timing_mode=ProbePinned(default_ms=1500),
            pin_limits=False,
        )
        / 'conf'
    ).read_text()

    assert _conf_value(conf, 'TLOVERRIDE[default]') == '1.500'


def test_probe_limit_passes_the_pre_build_timing_check(testing_pkg, tmp_path):
    # The check the CLI runs before paying for a full build. It guards the two modes
    # that depend on something the setter has to have done -- an estimated profile,
    # or `timing.multipliers` -- and a uniform pin depends on neither: it carries its
    # own number.
    minimal_package(testing_pkg)
    (testing_pkg.root / '.limits' / 'moj.yml').unlink()
    testing_pkg.save()

    check_timing_setup(ProbePinned(default_ms=1500))


def test_probe_limit_raises_the_calibration_limit(testing_pkg, tmp_path):
    # calibreitor.sh still runs, under its 5s dummy limit; a solution rbx is willing
    # to wait 15s for would time out during calibration and abort it.
    minimal_package(testing_pkg)
    testing_pkg.save()

    conf = (
        run_packager(
            testing_pkg,
            tmp_path,
            build_entries(tmp_path, ['samples']),
            timing_mode=ProbePinned(default_ms=15000),
        )
        / 'conf'
    ).read_text()

    assert _conf_value(conf, 'CALIBRATIONTL') == '15'


def test_probe_limit_rejects_a_non_positive_cap():
    # The runner derives this from `ctx.timelimit_override`, the kind of value that
    # arrives unset. MOJ greps TLOVERRIDE rather than evaluating it, so `0.000` or
    # `-1.500` would upload, calibrate, and TLE every run with nothing to show for it.
    for bad in [0, -1500]:
        with pytest.raises(ValueError, match='positive'):
            ProbePinned(default_ms=bad)
        with pytest.raises(ValueError, match='positive'):
            ProbePinned(default_ms=1500, per_rbx_language_ms=(('cpp', bad),))


def test_probe_limit_rejects_a_language_pinned_twice():
    # Keeping one of them would pin a language to a limit the caller did not choose,
    # and the emitted `conf` would look perfectly ordinary.
    with pytest.raises(ValueError, match='at most once'):
        ProbePinned(default_ms=1500, per_rbx_language_ms=(('cpp', 200), ('cpp', 300)))


def test_probe_limit_pins_each_language_the_run_named(testing_pkg, tmp_path):
    # The validation phase checks each slow solution against the bound ITS OWN
    # language group has to clear, so the limits genuinely differ per language and
    # the probe has to say so -- pinning one of them for everybody would check the
    # other languages against a bound nobody asked for.
    minimal_package(testing_pkg)
    testing_pkg.save()

    conf = (
        run_packager(
            testing_pkg,
            tmp_path,
            build_entries(tmp_path, ['samples']),
            timing_mode=ProbePinned(
                default_ms=3000, per_rbx_language_ms=(('cpp', 150), ('java', 3000))
            ),
        )
        / 'conf'
    ).read_text()

    assert _conf_value(conf, 'TLOVERRIDE[default]') == '3.000'
    assert _conf_value(conf, 'TLOVERRIDE[cpp]') == '0.150'
    # java asked for exactly the default, so it needs no entry of its own -- the
    # same rule `build_fixed_limits` applies to the profile's limits.
    assert 'TLOVERRIDE[java]' not in _keys(conf)


def test_probe_limit_ignores_a_language_the_package_cannot_run(testing_pkg, tmp_path):
    # `TLOVERRIDE[<lang>]` for a language MOJ has no scripts for is an entry nothing
    # reads. It cannot hide a real limit: `MojRunner` refuses up front to testrun a
    # solution whose language has no MOJ counterpart.
    minimal_package(testing_pkg)
    testing_pkg.save()

    conf = (
        run_packager(
            testing_pkg,
            tmp_path,
            build_entries(tmp_path, ['samples']),
            timing_mode=ProbePinned(
                default_ms=2000, per_rbx_language_ms=(('brainfuck', 150),)
            ),
        )
        / 'conf'
    ).read_text()

    assert _overrides(conf) == ['TLOVERRIDE[default]']
    assert _conf_value(conf, 'TLOVERRIDE[default]') == '2.000'


# -- where the emitted numbers say they came from ----------------------------
#
# `conf`'s comments are the only place a human debugging a timing run learns which
# of the three modes produced the limits below them. Nothing else can catch these
# going wrong: they are comments, so every mode still emits a valid package.


def test_a_probe_conf_does_not_claim_the_limits_came_from_the_profile(
    testing_pkg, tmp_path
):
    minimal_package(testing_pkg)
    testing_pkg.save()

    conf = (
        run_packager(
            testing_pkg,
            tmp_path,
            build_entries(tmp_path, ['samples']),
            timing_mode=ProbePinned(default_ms=2000),
            probe=ProbePackage(submission_languages=('cpp',)),
        )
        / 'conf'
    ).read_text()

    assert 'exists for rbx to' in conf
    # The profile's story, on a package that consulted no profile, would be a lie.
    assert 'limits profile' not in conf
    assert 'rbx time -p moj' not in conf


def test_a_profile_pinned_conf_says_the_limits_came_from_the_profile(
    testing_pkg, tmp_path
):
    minimal_package(testing_pkg)
    testing_pkg.save()

    conf = (
        run_packager(
            testing_pkg,
            tmp_path,
            build_entries(tmp_path, ['samples']),
            timing_mode=ProfilePinned(),
        )
        / 'conf'
    ).read_text()

    assert 'limits profile `rbx time -p moj` estimated' in conf
    assert 'exists for rbx to' not in conf


# -- the shipped solutions ---------------------------------------------------


def _package_with_every_solution_kind(testing_pkg):
    testing_pkg.add_file('check.cpp').write_text(CHECKER)
    testing_pkg.set_checker('check.cpp')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text('int main(){}\n')
    testing_pkg.add_solution('other.py', outcome='accepted').write_text('print(1)\n')
    testing_pkg.add_solution('pass.cpp', outcome='accepted-or-tle').write_text(
        'int main(){}\n'
    )
    testing_pkg.add_solution('slow.cpp', outcome='time-limit-exceeded').write_text(
        SLOW_SOL
    )
    testing_pkg.add_solution('wrong.cpp', outcome='wrong-answer').write_text(WRONG_SOL)
    with_limits_profile(testing_pkg)
    testing_pkg.save()


def test_probe_package_ships_only_the_model_solution(testing_pkg, tmp_path):
    # `moj testrun` sends the solution source in the request body, so the solutions
    # being timed never have to be in the package. Calibration only needs one
    # sols/good to succeed, and shipping just that one keeps the single calibration a
    # session pays for as short as it can be.
    _package_with_every_solution_kind(testing_pkg)

    into_path = run_packager(
        testing_pkg,
        tmp_path,
        build_entries(tmp_path, ['samples']),
        timing_mode=ProbePinned(default_ms=2000),
        probe=ProbePackage(submission_languages=('cpp',)),
    )

    assert [path.name for path in (into_path / 'sols' / 'good').iterdir()] == [
        'sol.cpp'
    ]
    for tag in ['pass', 'slow', 'wrong', 'upcoming']:
        assert not (into_path / 'sols' / tag).exists()


def test_a_real_package_still_ships_every_solution(testing_pkg, tmp_path):
    # The narrowing is the probe's alone: without one, a package is the setter's and
    # carries the whole solution set MOJ verifies against.
    _package_with_every_solution_kind(testing_pkg)

    into_path = run_packager(
        testing_pkg, tmp_path, build_entries(tmp_path, ['samples'])
    )

    assert sorted(path.name for path in (into_path / 'sols' / 'good').iterdir()) == [
        'other.py',
        'sol.cpp',
    ]
    for tag in ['pass', 'slow', 'wrong']:
        assert list((into_path / 'sols' / tag).iterdir())


# -- halting early would truncate the timings --------------------------------


def test_a_binary_probe_package_never_halts_early(testing_pkg, tmp_path):
    # A BINARY problem normally gets STOPWHEN_WA/TLE/RE=y, and build-and-test.sh
    # checks them *before* the RUNALL guard. But a probe exists to collect a timing
    # per test, and the solutions it times include the slow and wrong ones, which
    # fail by construction: the first failure would break out of the loop and rbx
    # would get back a prefix of the tests. It is also what makes the runner's
    # `supports_abort=False` -- "a testrun has already run every test" -- true.
    _package_with_every_solution_kind(testing_pkg)

    conf = (
        run_packager(
            testing_pkg,
            tmp_path,
            build_entries(tmp_path, ['samples']),
            timing_mode=ProbePinned(default_ms=2000),
            probe=ProbePackage(submission_languages=('cpp',)),
        )
        / 'conf'
    ).read_text()

    for key in ['STOPWHEN_WA=y', 'STOPWHEN_TLE=y', 'STOPWHEN_RE=y']:
        assert key not in conf


def _directives(conf: str) -> List[str]:
    """The lines `conf` actually sets, with comments and blanks dropped.

    Asserting `'X=n' in conf` is not enough: these comment blocks quote the very
    settings they explain, so a substring check happily matches the prose and
    passes against a `conf` that sets the opposite. Found by mutation -- flipping
    `TLERERUN=n` to `=y` left every test green.
    """
    return [
        line.strip()
        for line in conf.splitlines()
        if line.strip() and not line.lstrip().startswith('#')
    ]


def test_a_probe_package_runs_its_tests_one_at_a_time(testing_pkg, tmp_path):
    """A timing measured against 55 competing tests is not a timing.

    `build-and-test.sh` sets `NPROC=$(nproc)` and only drops to one job when
    `ALLOWPARALLELTEST` is exactly `n` (lines 434-436); the MOJ park reports 56 CPUs.
    mojtools agrees this matters when measuring -- `calibreitor.sh:125` exports the
    same value before running the accepted solutions.
    """
    _package_with_every_solution_kind(testing_pkg)

    conf = (
        run_packager(
            testing_pkg,
            tmp_path,
            build_entries(tmp_path, ['samples']),
            timing_mode=ProbePinned(default_ms=2000),
            probe=ProbePackage(submission_languages=('cpp',)),
        )
        / 'conf'
    ).read_text()

    directives = _directives(conf)
    assert 'ALLOWPARALLELTEST=n' in directives
    # Applied *after* ALLOWPARALLELTEST by build-and-test.sh, so it would override it.
    assert not [line for line in directives if line.startswith('MAXPARALLELTESTS')]


def test_a_probe_package_never_reruns_a_test_that_hit_the_limit(testing_pkg, tmp_path):
    """`TLERERUN` defaults to `y` and would replace a measured time with a second one.

    build-and-test.sh re-runs a TLE test and takes the *rerun's* verdict, and its own
    log line says why: "because got TLE while running parallel tests" -- it absorbs a
    false TLE caused by the contention `ALLOWPARALLELTEST=n` already removed. Left on
    for a probe it would measure the slowest solutions twice, and only until some test
    stayed TLE (the script latches `TLERERUN=n` from then on), so which tests got a
    second chance would depend on the order they happened to finish in.
    """
    _package_with_every_solution_kind(testing_pkg)

    conf = (
        run_packager(
            testing_pkg,
            tmp_path,
            build_entries(tmp_path, ['samples']),
            timing_mode=ProbePinned(default_ms=2000),
            probe=ProbePackage(submission_languages=('cpp',)),
        )
        / 'conf'
    ).read_text()

    assert 'TLERERUN=n' in _directives(conf)


def test_a_package_that_is_not_a_probe_keeps_mojs_parallel_default(
    testing_pkg, tmp_path
):
    """Serialising is the probe's alone.

    On a package students submit to, parallelism is a judging-speed feature and the
    limits are pinned through `TLOVERRIDE`, so what the judge measures decides nothing.
    """
    _package_with_every_solution_kind(testing_pkg)

    conf = (
        run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['samples']))
        / 'conf'
    ).read_text()

    directives = _directives(conf)
    assert not [line for line in directives if line.startswith('ALLOWPARALLELTEST')]
    # Same scope: rerunning a TLE is throughput tuning for a judge, and only a
    # measurement is harmed by taking the second time instead of the first.
    assert not [line for line in directives if line.startswith('TLERERUN')]


def test_a_binary_package_that_is_not_a_probe_still_halts_early(testing_pkg, tmp_path):
    # The suppression is the probe's alone; the judge-time saving still applies to a
    # package students actually submit to.
    _package_with_every_solution_kind(testing_pkg)

    conf = (
        run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['samples']))
        / 'conf'
    ).read_text()

    for key in ['STOPWHEN_WA=y', 'STOPWHEN_TLE=y', 'STOPWHEN_RE=y']:
        assert key in conf


# -- the submission whitelist ------------------------------------------------


def test_a_probe_package_must_whitelist_something():
    # Empty would "work" -- `_write_moj_meta` omits an empty `languages`, and the
    # server then preserves whatever the problem already had. That is luck in the
    # permissive direction: it means the caller enumerated no testrunnable language
    # and the package silently inherits an earlier run's whitelist.
    with pytest.raises(ValueError, match='at least one submission language'):
        ProbePackage(submission_languages=())


def test_probe_package_whitelists_languages_it_ships_no_solution_for(
    testing_pkg, tmp_path
):
    # THE bug this mode exists to avoid. `.moj-meta.json`'s `languages` is the
    # whitelist the MOJ API enforces on every submission, a testrun included. A probe
    # package ships only the C++ model solution, so deriving the whitelist from the
    # ACCEPTED solutions -- right for a real problem -- would collapse it to `cpp` and
    # every testrun of a Python or Java solution would be refused. In phase 2 that
    # includes the slow and wrong solutions, which are never accepted by construction.
    _package_with_every_solution_kind(testing_pkg)

    into_path = run_packager(
        testing_pkg,
        tmp_path,
        build_entries(tmp_path, ['samples']),
        timing_mode=ProbePinned(default_ms=2000),
        probe=ProbePackage(submission_languages=('cpp', 'java', 'py3')),
    )

    meta = json.loads((into_path / '.moj-meta.json').read_text())
    # `java` has no solution at all here, so an accepted-solutions derivation could
    # never produce this list. Legacy `py3` is folded and the list sorted, the way the
    # server canonicalizes it.
    assert meta['languages'] == ['cpp', 'java', 'py']
    # And the package really did ship only C++, so this cannot pass by accident.
    assert [path.name for path in (into_path / 'sols' / 'good').iterdir()] == [
        'sol.cpp'
    ]


def _plain(out: str) -> str:
    """`capsys` output with rich's escapes removed, whitespace collapsed.

    `[item]` renders as ANSI bold, so a value like `1350 ms` reaches capsys as
    `\x1b[1m1350\x1b[0m ms` and a naive substring assertion never matches.
    """
    out = re.sub(r'\x1b\]8;;[^\x1b]*\x1b\\?', '', out)  # hyperlinks
    out = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', out)  # colors
    return ' '.join(out.split())


def test_the_probe_report_says_which_languages_the_run_measures(
    testing_pkg, tmp_path, capsys
):
    """The line must not read as a claim about how MOJ would judge Java.

    Reported from a real package: its slow solutions were all C++, so the
    validation phase pinned C++ at 1350 ms and nothing else, and the report said
    "every other language under 1350 ms". The setter had deliberately given Java
    and Kotlin a much higher limit and read that as the packager dropping it.
    Nothing was dropped -- no Java solution is expected to be too slow, so the
    phase submits nothing in Java and the default binds no run at all. Only the
    sentence was wrong.
    """
    minimal_package(testing_pkg)
    testing_pkg.save()

    run_packager(
        testing_pkg,
        tmp_path,
        build_entries(tmp_path, ['samples']),
        timing_mode=ProbePinned(
            default_ms=1350,
            per_rbx_language_ms=(('cpp', 1350),),
            measuring='slow solutions',
        ),
    )

    out = _plain(capsys.readouterr().out)
    # Naming what is measured is what makes "only cpp" self-explanatory.
    assert 'MOJ will measure slow solutions in cpp at 1350 ms.' in out
    # The claim that misled. The fallback is not a limit anything runs under, so
    # it is not mentioned at all.
    assert 'every other language' not in out


def test_the_probe_report_names_every_pinned_language(testing_pkg, tmp_path, capsys):
    # And with several, the noun agrees and each is named with its own bound --
    # the shape a problem with slow solutions in two language groups produces.
    minimal_package(testing_pkg)
    testing_pkg.save()

    run_packager(
        testing_pkg,
        tmp_path,
        build_entries(tmp_path, ['samples']),
        timing_mode=ProbePinned(
            default_ms=3450,
            per_rbx_language_ms=(('cpp', 1350), ('java', 3450)),
            measuring='slow solutions',
        ),
    )

    out = _plain(capsys.readouterr().out)
    assert 'MOJ will measure slow solutions in cpp at 1350 ms and java at 3450 ms.' in (
        out
    )


def test_the_estimation_phase_report_names_the_accepted_solutions(
    testing_pkg, tmp_path, capsys
):
    # The other half of the same idea: one cap, and the line says whose. Without
    # the noun, "a single time limit of 10000 ms" invites the same question the
    # per-language line raised -- a single limit on *what*.
    minimal_package(testing_pkg)
    testing_pkg.save()

    run_packager(
        testing_pkg,
        tmp_path,
        build_entries(tmp_path, ['samples']),
        timing_mode=ProbePinned(default_ms=10000, measuring='accepted solutions'),
    )

    out = _plain(capsys.readouterr().out)
    assert (
        'MOJ will measure accepted solutions under a single time limit of 10000 ms.'
        in out
    )


def test_probe_package_does_not_warn_about_a_narrowed_whitelist(
    testing_pkg, tmp_path, capsys
):
    # The warning tells a setter their problem became single-language because they
    # shipped one accepted solution. A probe package is rbx's own throwaway `rbxt-`
    # problem, nobody submits to it, and its whitelist is authored rather than
    # derived -- there is no narrowing to report.
    _package_with_every_solution_kind(testing_pkg)

    run_packager(
        testing_pkg,
        tmp_path,
        build_entries(tmp_path, ['samples']),
        timing_mode=ProbePinned(default_ms=2000),
        probe=ProbePackage(submission_languages=('cpp', 'java', 'py')),
    )

    out = ' '.join(capsys.readouterr().out.split())
    assert 'no ACCEPTED solution' not in out
    assert 'MOJ will accept submissions in' not in out


def test_a_real_package_still_derives_the_whitelist_from_accepted_solutions(
    testing_pkg, tmp_path
):
    _package_with_every_solution_kind(testing_pkg)

    into_path = run_packager(
        testing_pkg, tmp_path, build_entries(tmp_path, ['samples'])
    )

    meta = json.loads((into_path / '.moj-meta.json').read_text())
    assert meta['languages'] == ['cpp', 'py']


# -- a probe must be buildable without a statement build ---------------------


def test_a_probe_package_carries_no_statement_at_all(
    testing_pkg, tmp_path, monkeypatch
):
    # The whole point: a probe must be buildable by a runner calling `package()`
    # directly. The real statement path reads `blocks.sub.yml` out of the v2 overlay,
    # which only the forced-externalize build writes -- so on a problem that declares
    # an rbxTeX statement it raises, and the runner's only escapes would be running
    # pdflatex locally for a document nobody reads, or going through `run_packager`
    # and paying for the full local verification run it exists to avoid.
    _package_with_every_solution_kind(testing_pkg)
    with_statements(testing_pkg, monkeypatch, PT_BLOCKS)

    into_path = run_packager(
        testing_pkg,
        tmp_path,
        build_entries(tmp_path, ['samples']),
        timing_mode=ProbePinned(default_ms=2000),
        probe=ProbePackage(submission_languages=('cpp',)),
    )

    # The dummy body, with MOJ's two hard-required headings and nothing from the
    # declared statement.
    text = (into_path / 'docs' / 'enunciado.md').read_text()
    assert 'ainda não disponível' in text
    assert 'Some os inteiros' not in text
    assert not (into_path / 'docs' / 'assets').exists()


def test_a_real_package_still_builds_its_statement(testing_pkg, tmp_path, monkeypatch):
    minimal_package(testing_pkg)
    with_statements(testing_pkg, monkeypatch, PT_BLOCKS)

    into_path = run_packager(
        testing_pkg, tmp_path, build_entries(tmp_path, ['samples'])
    )

    text = (into_path / 'docs' / 'enunciado.md').read_text()
    assert 'ainda não disponível' not in text


def test_a_probe_package_asks_for_no_statement_build(testing_pkg, tmp_path):
    # `run_packager` builds one statement per `statement_types()` entry and passes
    # `statement_export_params()` into that build. A probe consumes no blocks and
    # ships no statement, so it asks for neither -- nothing should ever run pdflatex
    # on behalf of a package whose statement is a fixed placeholder.
    minimal_package(testing_pkg)
    testing_pkg.save()

    probe_packager = MojPackager(
        testcase_entries=[],
        timing_mode=ProbePinned(default_ms=2000),
        probe=ProbePackage(submission_languages=('cpp',)),
    )
    assert probe_packager.statement_types() == []
    assert probe_packager.statement_export_params() == []

    # Unchanged for a package a setter builds; `test_statement_types.py` pins this too.
    real_packager = MojPackager(testcase_entries=[])
    assert real_packager.statement_types() == [StatementType.PDF]
    assert len(real_packager.statement_export_params()) == 2


# -- pairing timings back onto testcases -------------------------------------


def test_testcase_names_are_what_the_package_contains(testing_pkg, tmp_path):
    # The runner pairs a testrun's per-test results onto rbx testcases BY NAME, so
    # the public mapping and the emitted files must be the same thing. They are: both
    # come from `testcase_names()`. If they could drift, a timing would be attributed
    # to the wrong test, silently -- the one failure by-name pairing exists to prevent.
    minimal_package(testing_pkg)
    testing_pkg.add_testgroup_with_manual_testcases('samples', [])
    testing_pkg.add_testgroup_with_manual_testcases('easy', [])
    testing_pkg.save()

    entries = build_entries(tmp_path, ['samples', 'easy'])
    packager = MojPackager(testcase_entries=entries)
    into_path = run_packager(testing_pkg, tmp_path, entries)

    names = [name for _, name in packager.testcase_names()]
    assert sorted(names) == sorted(
        path.name for path in (into_path / 'tests' / 'input').iterdir()
    )


def test_testcase_names_count_from_one_per_group(testing_pkg, tmp_path):
    # The trap a caller reimplementing this would fall into: `index` is a 1-based
    # running counter over the BUILT entries of each group, while
    # `entry.group_entry.index` is 0-based. An off-by-one here still produces
    # well-formed names -- for the wrong tests.
    minimal_package(testing_pkg)
    testing_pkg.add_testgroup_with_manual_testcases('samples', [])
    testing_pkg.add_testgroup_with_manual_testcases('easy', [])
    testing_pkg.save()

    entries = build_entries(tmp_path, ['samples', 'easy'])
    named = MojPackager(testcase_entries=entries).testcase_names()

    assert [name for _, name in named] == [
        'sample001',
        'sample002',
        't01_easy_001',
        't01_easy_002',
    ]
    # The entries paired with them are the ones whose own indices start at 0.
    assert [entry.group_entry.index for entry, _ in named] == [0, 1, 0, 1]


# -- the two axes have exactly one legal pairing ------------------------------


def test_a_probe_package_must_pin_the_limits_the_run_asked_for():
    # Constructible-but-illegal is the failure to avoid: a profile-pinned probe would
    # measure under the limits of the PREVIOUS estimate -- the very thing this run
    # exists to replace -- and a calibrated one under whatever the judge decided.
    for mode in [ProfilePinned(), JudgeCalibrated()]:
        with pytest.raises(ValueError, match='limits the timing run asked for'):
            MojPackager(
                testcase_entries=[],
                timing_mode=mode,
                probe=ProbePackage(submission_languages=('cpp',)),
            )


def test_warns_about_whitelisting_a_language_with_no_scripts(
    testing_pkg, tmp_path, capsys
):
    # On the real path this cannot happen -- an accepted solution's language always
    # has a scripts/ dir. An authored whitelist loses that: MOJ accepts the submission
    # and runs it under its own scripts, which rbx never validated, so any timing
    # measured through them is not comparable to the rest.
    _package_with_every_solution_kind(testing_pkg)

    run_packager(
        testing_pkg,
        tmp_path,
        build_entries(tmp_path, ['samples']),
        timing_mode=ProbePinned(default_ms=2000),
        probe=ProbePackage(submission_languages=('cpp', 'rust')),
    )

    out = ' '.join(capsys.readouterr().out.split())
    assert 'rust' in out
    assert 'ships no scripts/' in out
    # The languages that DO have scripts are not named as a problem.
    assert 'cpp but ships no' not in out


# -- the two modes that must not have moved ----------------------------------


def test_profile_pinning_is_unchanged(testing_pkg, tmp_path):
    minimal_package(testing_pkg)
    with_limits_profile(testing_pkg, time_limit=1000, per_language={'java': 3000})
    testing_pkg.save()

    conf = (
        run_packager(
            testing_pkg,
            tmp_path,
            build_entries(tmp_path, ['samples']),
            timing_mode=ProfilePinned(),
        )
        / 'conf'
    ).read_text()

    assert _overrides(conf) == ['TLOVERRIDE[default]', 'TLOVERRIDE[java]']
    assert _conf_value(conf, 'TLOVERRIDE[default]') == '1.000'
    assert _conf_value(conf, 'TLOVERRIDE[java]') == '3.000'


def test_judge_calibration_is_unchanged(testing_pkg, tmp_path):
    minimal_package(testing_pkg)
    testing_pkg.save()

    conf = (
        run_packager(
            testing_pkg,
            tmp_path,
            build_entries(tmp_path, ['samples']),
            timing_mode=JudgeCalibrated(),
            pin_limits=False,
        )
        / 'conf'
    ).read_text()

    assert _conf_value(conf, 'TLMOD[calibrafactor]') == '2'
    assert not _overrides(conf)
