"""The package a remote timing run uploads.

`rbx time -p moj --runner moj` measures solution timings on the MOJ judge park
instead of the setter's machine. What it uploads is a MOJ package like any other,
except in three ways, and all three are about *measuring* rather than judging:

- the time limits are pinned **uniformly**, to the single cap rbx is measuring
  under, instead of coming from the `moj` limits profile;
- only the model solution is shipped, since `moj testrun` sends the source of the
  solution being timed in the request body;
- the submission whitelist covers every language rbx may testrun, not the languages
  the package happens to ship -- the API refuses a submission outside it.

Design: `docs/plans/2026-08-20-moj-remote-runner-design.md`.
"""

import json

from rbx.box.packaging.moj import timing
from rbx.box.packaging.moj.packager import (
    JudgeCalibrated,
    ProbePackage,
    ProfilePinned,
    UniformPinned,
    check_timing_setup,
)
from tests.rbx.box.packaging.moj.conftest import (
    CHECKER,
    SLOW_SOL,
    WRONG_SOL,
    build_entries,
    minimal_package,
    run_packager,
    with_limits_profile,
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


# -- the uniform timing mode -------------------------------------------------


def test_uniform_limits_carry_no_per_language_entries():
    limits = timing.build_uniform_limits(2500)
    assert limits.base_ms == 2500
    # The point of the mode: one cap, and nothing that could tighten it per language.
    assert limits.per_language_ms == {}


def test_uniform_limit_pins_every_language_to_one_number(testing_pkg, tmp_path):
    minimal_package(testing_pkg)
    # A profile with per-language limits exists and is deliberately ignored: emitting
    # its entries alongside the uniform cap would measure java under 3s while rbx
    # asked for 2.5s, truncating the very timings the estimate rests on.
    with_limits_profile(testing_pkg, time_limit=1000, per_language={'java': 3000})
    testing_pkg.save()

    conf = (
        run_packager(
            testing_pkg,
            tmp_path,
            build_entries(tmp_path, ['samples']),
            timing_mode=UniformPinned(limit_ms=2500),
        )
        / 'conf'
    ).read_text()

    assert _overrides(conf) == ['TLOVERRIDE[default]']
    assert _conf_value(conf, 'TLOVERRIDE[default]') == '2.500'
    # Nothing is handed to the judge to measure: the cap is rbx's.
    assert 'TLMOD[calibrafactor]' not in _keys(conf)


def test_uniform_limit_needs_no_limits_profile(testing_pkg, tmp_path):
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
            timing_mode=UniformPinned(limit_ms=1500),
            pin_limits=False,
        )
        / 'conf'
    ).read_text()

    assert _conf_value(conf, 'TLOVERRIDE[default]') == '1.500'


def test_uniform_limit_passes_the_pre_build_timing_check(testing_pkg, tmp_path):
    # The check the CLI runs before paying for a full build. It guards the two modes
    # that depend on something the setter has to have done -- an estimated profile,
    # or `timing.multipliers` -- and a uniform pin depends on neither: it carries its
    # own number.
    minimal_package(testing_pkg)
    (testing_pkg.root / '.limits' / 'moj.yml').unlink()
    testing_pkg.save()

    check_timing_setup(UniformPinned(limit_ms=1500))


def test_uniform_limit_raises_the_calibration_limit(testing_pkg, tmp_path):
    # calibreitor.sh still runs, under its 5s dummy limit; a solution rbx is willing
    # to wait 15s for would time out during calibration and abort it.
    minimal_package(testing_pkg)
    testing_pkg.save()

    conf = (
        run_packager(
            testing_pkg,
            tmp_path,
            build_entries(tmp_path, ['samples']),
            timing_mode=UniformPinned(limit_ms=15000),
        )
        / 'conf'
    ).read_text()

    assert _conf_value(conf, 'CALIBRATIONTL') == '15'


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
        timing_mode=UniformPinned(limit_ms=2000),
        probe=ProbePackage(submission_languages=['cpp']),
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


# -- the submission whitelist ------------------------------------------------


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
        timing_mode=UniformPinned(limit_ms=2000),
        probe=ProbePackage(submission_languages=['cpp', 'java', 'py3']),
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
        timing_mode=UniformPinned(limit_ms=2000),
        probe=ProbePackage(submission_languages=['cpp', 'java', 'py']),
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
