import fnmatch
import json
import shutil
import stat
import subprocess

import pytest
import typer

from rbx.box.packaging.moj.packager import JudgeCalibrated, MojPackager
from rbx.box.schema import ScoreType, TaskType
from rbx.box.statements.schema import ConversionType, StatementType
from rbx.config import get_default_app_path
from tests.rbx.box.packaging.moj.conftest import (
    CHECKER,
    EN_AND_PT_BLOCKS,
    PT_BLOCKS,
    SLOW_SOL,
    WRONG_SOL,
    build_entries,
    minimal_package,
    run_packager,
    with_statements,
)

# -- shape ------------------------------------------------------------------


def test_only_supports_batch_problems():
    # MOJ's interactive support uses its own arbiter protocol, not a testlib
    # interactor, so the legacy `moj` packager keeps those.
    assert MojPackager.task_types() == [TaskType.BATCH]


def test_builds_pdf_statements_even_though_it_consumes_blocks():
    # `statement_types()` names the OUTPUT a statement is built into, and v2 emits
    # only pdf/tex/md. Consuming blocks is declared by `statement_export_params()`
    # below, and the PDF build is what writes the artifacts it asks for -- both
    # externalization and demacro run inside `render.compile_pdf`.
    assert MojPackager(testcase_entries=[]).statement_types() == [StatementType.PDF]


def test_export_params_force_externalize_and_demacro():
    # Without these the overlay carries no blocks.sub.yml/macros.json and the
    # export pipeline has nothing to read. Mirrors PolygonPackager.
    steps = MojPackager(testcase_entries=[]).statement_export_params()
    assert [step.type for step in steps] == [
        ConversionType.rbxToTex,
        ConversionType.TexToPDF,
    ]
    assert all(step.externalize for step in steps)
    assert steps[1].demacro


def test_packager_is_named_moj():
    assert MojPackager.name() == 'moj'


# -- metadata ---------------------------------------------------------------


def test_writes_the_mandatory_metadata_files(moj_package):
    assert (moj_package / 'author').read_text().strip() != ''
    assert (moj_package / 'tags').exists()


def test_writes_the_author_from_vars(testing_pkg, tmp_path):
    minimal_package(testing_pkg)
    testing_pkg.yml.vars = {'author': 'Ada Lovelace'}
    testing_pkg.save()

    moj_package = run_packager(
        testing_pkg, tmp_path, build_entries(tmp_path, ['samples'])
    )

    assert (moj_package / 'author').read_text() == 'Ada Lovelace\n'


def test_falls_back_to_a_placeholder_author_without_the_var(testing_pkg, tmp_path):
    # MOJ requires a non-empty `author`, so a package that never declared one still
    # has to produce something validate-problem.sh accepts.
    minimal_package(testing_pkg)
    testing_pkg.save()

    moj_package = run_packager(
        testing_pkg, tmp_path, build_entries(tmp_path, ['samples'])
    )

    assert (moj_package / 'author').read_text() == 'Unknown\n'


def test_falls_back_to_a_placeholder_author_for_a_blank_var(testing_pkg, tmp_path):
    minimal_package(testing_pkg)
    testing_pkg.yml.vars = {'author': '   '}
    testing_pkg.save()

    moj_package = run_packager(
        testing_pkg, tmp_path, build_entries(tmp_path, ['samples'])
    )

    assert (moj_package / 'author').read_text() == 'Unknown\n'


def test_falls_back_to_the_dummy_statement_without_statements(moj_package):
    # MOJ requires the two headings, so a package that declares no statement at
    # all must still produce a valid enunciado.md.
    text = (moj_package / 'docs' / 'enunciado.md').read_text()
    assert 'ainda não disponível' in text


def test_writes_a_statement_with_the_mandatory_sections(moj_package):
    text = (moj_package / 'docs' / 'enunciado.md').read_text()
    # validate-problem.sh hard-fails without these two headings.
    assert '## Entrada' in text
    assert '## Saída' in text
    # A fence trips its soft "example written by hand" warning, and MOJ injects the
    # examples itself from tests/input/sample*.
    assert '```' not in text
    assert not text.lstrip().startswith('%')


def test_does_not_write_calibrated_files(moj_package):
    # MOJ measures the time limit; it is never authored.
    assert not (moj_package / 'tl').exists()
    # A scripts/testlib.h would take precedence over the mojtools-vendored one.
    assert not (moj_package / 'scripts' / 'testlib.h').exists()
    assert not (moj_package / 'scripts' / 'rbx.h').exists()


def test_scripts_in_the_package_tree_are_executable(moj_package):
    """The judge runs these, so their mode bits are part of the package.

    This is what forces `rbx package moj --upload` to hand `moj upload` the
    built *tree* rather than the `.zip` beside it: `zipfile.extract` does not
    restore mode bits, so a package rebuilt from the archive would arrive with
    every `compile.sh` and `run.sh` non-executable -- and would fail on the
    judge, not here.
    """
    scripts = sorted((moj_package / 'scripts').rglob('*.sh'))
    assert scripts, 'expected per-language scripts in the package tree'
    assert [
        script for script in scripts if not script.stat().st_mode & stat.S_IXUSR
    ] == []


def test_writes_moj_meta_with_a_display_title(moj_package):
    meta = json.loads((moj_package / '.moj-meta.json').read_text())
    assert meta['display_title']


def test_moj_meta_omits_server_owned_fields(moj_package):
    meta = json.loads((moj_package / '.moj-meta.json').read_text())
    # The server never accepts these from a tar upload, and `public` is additionally
    # fail-closed in gen-problem-json.sh -- emitting it risks publishing an
    # unpublished problem to anonymous users.
    for field in ['public', 'public_at', 'owner', 'gitea']:
        assert field not in meta
    # rbx has no notion of collections, and absent means the server keeps its own.
    assert 'collections' not in meta


def test_moj_meta_allows_every_language_the_environment_declares(moj_package):
    # The whitelist answers "what may a student write this in", which env.rbx.yml
    # decides -- not the languages the setter happened to write solutions in. The
    # fixture package ships a single C++ solution and still enables all of them.
    meta = json.loads((moj_package / '.moj-meta.json').read_text())
    # Sorted, and `py` rather than the legacy `py3` spelling.
    assert meta['languages'] == ['c', 'cpp', 'java', 'kt', 'py']


def test_moj_meta_languages_are_the_ones_scripts_were_emitted_for(moj_package):
    # Every whitelisted language is one MOJ can actually compile and run here: the
    # whitelist and the emitted script dirs come from the same list.
    meta = json.loads((moj_package / '.moj-meta.json').read_text())
    emitted = {
        path.name for path in (moj_package / 'scripts').iterdir() if path.is_dir()
    }
    assert set(meta['languages']) == emitted


def test_reports_which_languages_are_enabled(moj_package_output):
    out = ' '.join(moj_package_output.split())
    assert 'MOJ will accept submissions in' in out
    assert 'env.rbx.yml' in out
    for language in ['c', 'cpp', 'java', 'kt', 'py']:
        assert language in out


def test_says_nothing_about_calibration_when_the_limits_are_pinned(moj_package_output):
    # Every emitted language gets a TLOVERRIDE, so an accepted solution in it buys
    # the limits nothing and there is nothing to warn about.
    assert 'ACCEPTED' not in ' '.join(moj_package_output.split())


def test_calibrated_package_warns_about_languages_without_an_accepted_solution(
    testing_pkg, tmp_path, capsys
):
    # Under --calibrate MOJ measures the limits from sols/good, and a whitelisted
    # language with none falls back to TL[default] -- the tightest measured limit.
    # That is the one case the env-derived whitelist outruns, so it is said out loud.
    testing_pkg.add_file('check.cpp').write_text(CHECKER)
    testing_pkg.set_checker('check.cpp')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text('int main(){}\n')
    testing_pkg.save()

    run_packager(
        testing_pkg,
        tmp_path,
        build_entries(tmp_path, ['samples']),
        pin_limits=False,
        timing_mode=JudgeCalibrated(),
    )

    out = ' '.join(capsys.readouterr().out.split())
    assert 'No ACCEPTED solution in' in out
    for language in ['c', 'java', 'kt', 'py']:
        assert language in out
    assert 'rbx time -p moj' in out


def test_calibrated_package_says_nothing_when_every_language_has_a_solution(
    testing_pkg, tmp_path, capsys
):
    testing_pkg.add_file('check.cpp').write_text(CHECKER)
    testing_pkg.set_checker('check.cpp')
    for path, source in [
        ('sol.cpp', 'int main(){}\n'),
        ('sol.c', 'int main(){}\n'),
        ('sol.py', 'print(1)\n'),
        ('Main.java', 'public class Main { public static void main(String[] a){} }\n'),
        ('Main.kt', 'fun main() {}\n'),
    ]:
        testing_pkg.add_solution(path, outcome='accepted').write_text(source)
    testing_pkg.save()

    into_path = run_packager(
        testing_pkg,
        tmp_path,
        build_entries(tmp_path, ['samples']),
        pin_limits=False,
        timing_mode=JudgeCalibrated(),
    )

    # Asserted on the emitted whitelist too, so this cannot pass vacuously by simply
    # failing to resolve some language.
    meta = json.loads((into_path / '.moj-meta.json').read_text())
    assert meta['languages'] == ['c', 'cpp', 'java', 'kt', 'py']
    assert 'No ACCEPTED solution' not in ' '.join(capsys.readouterr().out.split())


def test_display_title_uses_the_package_title(testing_pkg, tmp_path):
    testing_pkg.add_file('check.cpp').write_text(CHECKER)
    testing_pkg.set_checker('check.cpp')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text('int main(){}\n')
    testing_pkg.yml.titles = {'pt': 'Soma de Dois'}
    testing_pkg.save()

    into_path = run_packager(
        testing_pkg, tmp_path, build_entries(tmp_path, ['samples'])
    )

    meta = json.loads((into_path / '.moj-meta.json').read_text())
    assert meta['display_title'] == 'Soma de Dois'


def test_display_title_reports_an_ambiguous_title(testing_pkg, tmp_path):
    # Resolution goes through naming.get_problem_title, so several titles with no
    # statement to disambiguate them is a clear error rather than an arbitrary pick --
    # the same behavior the BOCA packager has.
    testing_pkg.add_file('check.cpp').write_text(CHECKER)
    testing_pkg.set_checker('check.cpp')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text('int main(){}\n')
    testing_pkg.yml.titles = {'en': 'Sum of Two', 'pt': 'Soma de Dois'}
    testing_pkg.save()

    with pytest.raises(typer.Exit):
        run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['samples']))


def test_display_title_falls_back_to_the_problem_name(moj_package):
    # The fixture package declares no titles at all.
    meta = json.loads((moj_package / '.moj-meta.json').read_text())
    assert meta['display_title'] == 'test-problem'


def test_conf_uses_the_rss_memory_knob(moj_package):
    conf = (moj_package / 'conf').read_text()
    assert 'MEMLIMITMB=' in conf
    # ULIMITS[-v] is the legacy knob; MEMLIMITMB deliberately replaces it, and MOJ
    # drops the virtual-memory limit when it is set.
    assert 'ULIMITS[-v]' not in conf
    assert 'ULIMITS[-f]=' in conf
    # The time limits are pinned from the `moj` limits profile; see test_timing.py.
    assert 'TLOVERRIDE[default]=' in conf


def test_the_file_ulimit_is_fixed_and_does_not_track_the_output_limit(
    testing_pkg, tmp_path
):
    """MOJ applies `ULIMITS[-f]` to the **compile** step, not only to the solution.

    Observed on the judge on 2026-08-21: a package whose `outputLimit` was 100 KB
    made the linker die with `ld terminated with signal 25 [File size limit
    exceeded]`, so every submission came back `Compilation Error` without reaching a
    single test. Emitting the problem's own output limit here is therefore not a
    tighter-is-safer choice -- it is what makes a problem unjudgeable.

    So the number is fixed and generous, and this pins that it does not follow
    `outputLimit` even when that is set absurdly low.
    """
    testing_pkg.add_file('check.cpp').write_text(CHECKER)
    testing_pkg.set_checker('check.cpp')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text('int main(){}\n')
    testing_pkg.add_testgroup_with_manual_testcases('samples', [])
    testing_pkg.yml.outputLimit = 100
    testing_pkg.save()

    pkg_path = run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['samples']))
    conf = (pkg_path / 'conf').read_text()

    assert 'ULIMITS[-f]=102400' in conf
    assert 'ULIMITS[-f]=100\n' not in conf


def test_binary_problems_halt_at_the_first_failure(moj_binary_package):
    conf = (moj_binary_package / 'conf').read_text()
    assert 'STOPWHEN_WA=y' in conf
    assert 'STOPWHEN_TLE=y' in conf
    assert 'STOPWHEN_RE=y' in conf


def test_points_problems_never_halt_early(testing_pkg, tmp_path):
    # build-and-test.sh checks STOPWHEN_* before the RUNALL guard, so it breaks even
    # when every test was requested. score-summary.sh then scores an unexecuted group
    # as failed, and a submission would lose points it had actually earned.
    testing_pkg.add_file('check.cpp').write_text(CHECKER)
    testing_pkg.set_checker('check.cpp')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text('int main(){}\n')
    testing_pkg.yml.scoring = ScoreType.POINTS
    testing_pkg.add_testgroup_with_manual_testcases('samples', [])
    testing_pkg.add_testgroup_with_manual_testcases('easy', [])
    testing_pkg.yml.testcases[-1].score = 100
    testing_pkg.save()

    into_path = run_packager(
        testing_pkg, tmp_path, build_entries(tmp_path, ['samples', 'easy'])
    )

    conf = (into_path / 'conf').read_text()
    assert 'STOPWHEN_WA=y' not in conf
    assert 'STOPWHEN_TLE=y' not in conf
    assert 'STOPWHEN_RE=y' not in conf


# -- tests ------------------------------------------------------------------


def test_samples_are_named_sample_and_sort_first(moj_package):
    names = sorted(p.name for p in (moj_package / 'tests' / 'input').iterdir())
    assert names[0].startswith('sample')
    assert any(name.startswith('t') for name in names)


def test_every_input_has_a_paired_output(moj_package):
    inputs = {p.name for p in (moj_package / 'tests' / 'input').iterdir()}
    outputs = {p.name for p in (moj_package / 'tests' / 'output').iterdir()}
    # validate-problem.sh checks the pairing in both directions.
    assert inputs == outputs


def test_refuses_a_package_without_samples(testing_pkg, tmp_path):
    testing_pkg.add_file('check.cpp').write_text(CHECKER)
    testing_pkg.set_checker('check.cpp')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text('int main(){}\n')
    testing_pkg.save()

    with pytest.raises(typer.Exit):
        run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['easy']))


# -- checker ----------------------------------------------------------------


def test_checker_is_a_single_self_contained_file(moj_package):
    text = (moj_package / 'scripts' / 'checker.cpp').read_text()
    # The bridge binds only checker.cpp and testlib.h into the compile jail, so no
    # other quoted include can resolve there.
    assert '#include "testlib.h"' not in text
    assert '#include "rbx.h"' not in text
    assert 'registerTestlibCmd' in text


def test_compare_is_the_canonical_stub(moj_package):
    emitted = moj_package / 'scripts' / 'compare.sh'
    bundled = get_default_app_path() / 'packagers' / 'moj' / 'scripts' / 'compare.sh'
    assert emitted.read_bytes() == bundled.read_bytes()
    # Without +x the judge gets "Permission denied" and every test is a judge error.
    assert emitted.stat().st_mode & 0o111


@pytest.mark.skipif(shutil.which('g++') is None, reason='g++ not available')
def test_amalgamated_checker_compiles_the_way_moj_compiles_it(moj_package, tmp_path):
    proc = subprocess.run(
        [
            'g++',
            '-O2',
            '-std=gnu++17',
            '-include',
            'cassert',
            '-include',
            'cstring',
            '-include',
            'cstdint',
            '-o',
            str(tmp_path / 'checker'),
            str(moj_package / 'scripts' / 'checker.cpp'),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_partial_scoring_warning_ignores_inlined_testlib(testing_pkg, tmp_path, capsys):
    # testlib declares quitp/_points itself, so checking the amalgamated output would
    # warn for every checker, the builtin one included.
    testing_pkg.add_file('check.cpp').write_text(CHECKER)
    testing_pkg.set_checker('check.cpp')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text('int main(){}\n')
    testing_pkg.save()

    run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['samples']))

    assert 'quitp' not in capsys.readouterr().out


def test_warns_about_a_partial_scoring_checker(testing_pkg, tmp_path, capsys):
    testing_pkg.add_file('check.cpp').write_text(
        '#include "testlib.h"\nint main(){ quitp(0.5, "half"); }\n'
    )
    testing_pkg.set_checker('check.cpp')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text('int main(){}\n')
    testing_pkg.save()

    run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['samples']))

    assert 'quitp' in capsys.readouterr().out


def test_refuses_an_unresolvable_checker_include(testing_pkg, tmp_path):
    testing_pkg.add_file('check.cpp').write_text(
        '#include "../outside/lib.h"\n#include "testlib.h"\nint main(){}\n'
    )
    testing_pkg.set_checker('check.cpp')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text('int main(){}\n')
    testing_pkg.save()

    with pytest.raises(typer.Exit):
        run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['samples']))


# -- solutions --------------------------------------------------------------


def test_accepted_solutions_go_to_good(moj_package):
    # MOJ calibrates the time limit from sols/good; without one it cannot calibrate.
    assert list((moj_package / 'sols' / 'good').iterdir())


def test_outcomes_map_to_their_directories(testing_pkg, tmp_path):
    testing_pkg.add_file('check.cpp').write_text(CHECKER)
    testing_pkg.set_checker('check.cpp')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text('int main(){}\n')
    testing_pkg.add_solution('wrong.cpp', outcome='wrong-answer').write_text(WRONG_SOL)
    testing_pkg.add_solution('slow.cpp', outcome='time-limit-exceeded').write_text(
        SLOW_SOL
    )
    testing_pkg.add_solution('maybe.cpp', outcome='any').write_text('int main(){}\n')
    testing_pkg.save()

    root = (
        run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['samples']))
        / 'sols'
    )
    assert (root / 'good' / 'sol.cpp').is_file()
    assert (root / 'wrong' / 'wrong.cpp').is_file()
    assert (root / 'slow' / 'slow.cpp').is_file()
    # `any` asserts nothing about the outcome, so it is a draft rather than a claim
    # that it passes or fails -- and shipping it beats dropping it.
    assert (root / 'upcoming' / 'maybe.cpp').is_file()


def test_any_solutions_do_not_count_as_calibratable(testing_pkg, tmp_path, capsys):
    testing_pkg.add_file('check.cpp').write_text(CHECKER)
    testing_pkg.set_checker('check.cpp')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text('int main(){}\n')
    testing_pkg.add_solution('draft.py', outcome='any').write_text('print(1)\n')
    testing_pkg.save()

    into_path = run_packager(
        testing_pkg,
        tmp_path,
        build_entries(tmp_path, ['samples']),
        pin_limits=False,
        timing_mode=JudgeCalibrated(),
    )

    # `calibreitor.sh` never runs `sols/upcoming`, so a draft buys Python no measured
    # time limit -- the language is still whitelisted, and still warned about.
    assert (into_path / 'sols' / 'upcoming' / 'draft.py').is_file()
    out = ' '.join(capsys.readouterr().out.split())
    assert 'No ACCEPTED solution in' in out
    assert 'py' in out


def test_refuses_a_package_without_an_accepted_solution(testing_pkg, tmp_path):
    testing_pkg.add_file('check.cpp').write_text(CHECKER)
    testing_pkg.set_checker('check.cpp')
    testing_pkg.add_solution('wrong.cpp', outcome='wrong-answer').write_text(WRONG_SOL)
    testing_pkg.save()

    with pytest.raises(typer.Exit):
        run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['samples']))


def test_reference_only_ships_just_the_reference_solution(
    testing_pkg, tmp_path, capsys
):
    testing_pkg.add_file('check.cpp').write_text(CHECKER)
    testing_pkg.set_checker('check.cpp')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text('int main(){}\n')
    testing_pkg.add_solution('other.cpp', outcome='accepted').write_text(
        'int main(){return 0;}\n'
    )
    testing_pkg.add_solution('wrong.cpp', outcome='wrong-answer').write_text(WRONG_SOL)
    testing_pkg.add_solution('slow.cpp', outcome='time-limit-exceeded').write_text(
        SLOW_SOL
    )
    testing_pkg.save()

    root = (
        run_packager(
            testing_pkg,
            tmp_path,
            build_entries(tmp_path, ['samples']),
            reference_only=True,
        )
        / 'sols'
    )

    # `calibreitor.sh` needs exactly one `sols/good`, and nothing else runs.
    assert [path.name for path in (root / 'good').iterdir()] == ['sol.cpp']
    assert not (root / 'wrong').exists()
    assert not (root / 'slow').exists()

    # And the setter is told, because calibration is what would have checked the
    # verdicts of everything just dropped.
    out = ' '.join(capsys.readouterr().out.split())
    assert '--reference-only' in out


def test_reference_only_still_refuses_a_package_without_an_accepted_solution(
    testing_pkg, tmp_path
):
    testing_pkg.add_file('check.cpp').write_text(CHECKER)
    testing_pkg.set_checker('check.cpp')
    testing_pkg.add_solution('wrong.cpp', outcome='wrong-answer').write_text(WRONG_SOL)
    testing_pkg.save()

    with pytest.raises(typer.Exit):
        run_packager(
            testing_pkg,
            tmp_path,
            build_entries(tmp_path, ['samples']),
            reference_only=True,
        )


def test_reference_only_warns_about_the_languages_it_drops(
    testing_pkg, tmp_path, capsys
):
    testing_pkg.add_file('check.cpp').write_text(CHECKER)
    testing_pkg.set_checker('check.cpp')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text('int main(){}\n')
    testing_pkg.add_solution('sol.py', outcome='accepted').write_text('print(1)\n')
    testing_pkg.save()

    run_packager(
        testing_pkg,
        tmp_path,
        build_entries(tmp_path, ['samples']),
        pin_limits=False,
        timing_mode=JudgeCalibrated(),
        reference_only=True,
    )

    out = ' '.join(capsys.readouterr().out.split())
    assert 'No ACCEPTED solution in' in out
    assert 'py' in out
    # The fix here is dropping the flag, not writing a solution that already exists.
    assert 'Drop --reference-only' in out


def test_solutions_are_amalgamated(testing_pkg, tmp_path):
    testing_pkg.add_file('lib.h').write_text('#pragma once\nint k(){return 1;}\n')
    testing_pkg.add_file('check.cpp').write_text(CHECKER)
    testing_pkg.set_checker('check.cpp')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text(
        '#include "lib.h"\nint main(){return k()-1;}\n'
    )
    testing_pkg.save()

    into_path = run_packager(
        testing_pkg, tmp_path, build_entries(tmp_path, ['samples'])
    )

    # A solution is compiled from a single file inside MOJ's jail.
    text = (into_path / 'sols' / 'good' / 'sol.cpp').read_text()
    assert 'int k()' in text
    assert '#include "lib.h"' not in text


# -- language scripts -------------------------------------------------------


def test_emits_a_script_dir_per_declared_language(moj_package):
    scripts = moj_package / 'scripts'
    for language in ['c', 'cpp', 'py', 'java', 'kt']:
        assert (scripts / language / 'compile.sh').is_file()
        assert (scripts / language / 'run.sh').is_file()


def test_emitted_scripts_are_executable(moj_package):
    for path in (moj_package / 'scripts').rglob('*.sh'):
        assert path.stat().st_mode & 0o111, path


def test_flags_are_substituted(moj_package):
    text = (moj_package / 'scripts' / 'cpp' / 'compile.sh').read_text()
    assert '{{rbxFlags}}' not in text
    assert '-std=c++20' in text


def test_no_placeholder_survives_anywhere(moj_package):
    for path in (moj_package / 'scripts').rglob('*.sh'):
        assert '{{' not in path.read_text(), path


# -- scoring ----------------------------------------------------------------


def test_binary_problems_emit_no_score_file(moj_binary_package):
    # Without tests/score MOJ scores by percentage of tests and still requires all of
    # them to pass, which is the correct ICPC semantics.
    assert not (moj_binary_package / 'tests' / 'score').exists()


def test_points_problems_emit_a_score_file(testing_pkg, tmp_path):
    testing_pkg.add_file('check.cpp').write_text(CHECKER)
    testing_pkg.set_checker('check.cpp')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text('int main(){}\n')
    testing_pkg.yml.scoring = ScoreType.POINTS
    testing_pkg.add_testgroup_with_manual_testcases('samples', [])
    testing_pkg.add_testgroup_with_manual_testcases('easy', [])
    testing_pkg.yml.testcases[-1].score = 40
    testing_pkg.add_testgroup_with_manual_testcases('full', [])
    testing_pkg.yml.testcases[-1].score = 60
    testing_pkg.save()

    into_path = run_packager(
        testing_pkg, tmp_path, build_entries(tmp_path, ['samples', 'easy', 'full'])
    )

    content = (into_path / 'tests' / 'score').read_text()
    assert content.startswith('sample* - 0 pontos')
    assert '- 40 pontos' in content
    assert '- 60 pontos' in content

    # Every test must match exactly one group, or MOJ zeroes the submission.
    globs = [line.split(' - ')[0] for line in content.splitlines() if line.strip()]
    for path in (into_path / 'tests' / 'input').iterdir():
        matched = [g for g in globs if fnmatch.fnmatch(path.name, g)]
        assert len(matched) == 1, f'{path.name} matched {matched}'


# -- statements -------------------------------------------------------------


def test_package_writes_a_real_enunciado(testing_pkg, tmp_path, monkeypatch):
    minimal_package(testing_pkg)
    with_statements(testing_pkg, monkeypatch, PT_BLOCKS)

    into_path = run_packager(
        testing_pkg, tmp_path, build_entries(tmp_path, ['samples'])
    )

    text = (into_path / 'docs' / 'enunciado.md').read_text()
    assert 'Some os inteiros' in text
    assert '## Entrada' in text
    assert '## Saída' in text
    assert 'ainda não disponível' not in text
    # The reference was rewritten to where the asset actually landed, relative to
    # the document's own directory.
    assert '![](assets/fig.png)' in text
    assert (into_path / 'docs' / 'assets' / 'fig.png').exists()


def test_package_writes_sample_notes_by_test_name(testing_pkg, tmp_path, monkeypatch):
    minimal_package(testing_pkg)
    with_statements(
        testing_pkg,
        monkeypatch,
        PT_BLOCKS,
        explanations={0: 'Veja \\includegraphics{diagram}.'},
    )

    into_path = run_packager(
        testing_pkg, tmp_path, build_entries(tmp_path, ['samples'])
    )

    note = (into_path / 'docs' / 'notes' / 'sample001.md').read_text()
    assert 'Veja' in note
    # gen-problem-json.sh renders the note with --resource-path=<pkg>/docs, so the
    # reference is relative to docs/, NOT to the note's own directory.
    # The sample ASSET root is keyed by the 0-based explanation index, not by the
    # test name -- it only has to be unique per sample and agree with the derived
    # reference, which it does.
    assert '![](samples/000/diagram.png)' in note
    assert (into_path / 'docs' / 'samples' / '000' / 'diagram.png').exists()
    # And the note pairs by name with a test that exists.
    assert (into_path / 'tests' / 'input' / 'sample001').exists()


def test_language_option_selects_the_statement(testing_pkg, tmp_path, monkeypatch):
    minimal_package(testing_pkg)
    with_statements(
        testing_pkg,
        monkeypatch,
        EN_AND_PT_BLOCKS,
        languages=('pt', 'en'),
        titles={'pt': 'Soma', 'en': 'Sum'},
    )

    into_path = run_packager(
        testing_pkg, tmp_path, build_entries(tmp_path, ['samples']), main_language='en'
    )

    text = (into_path / 'docs' / 'enunciado.md').read_text()
    assert 'In English.' in text
    assert '## Input' in text


def test_display_title_comes_from_the_selected_statement(
    testing_pkg, tmp_path, monkeypatch
):
    # The body and the injected <h1> must never come from different languages.
    minimal_package(testing_pkg)
    with_statements(
        testing_pkg,
        monkeypatch,
        EN_AND_PT_BLOCKS,
        languages=('pt', 'en'),
        titles={'pt': 'Soma', 'en': 'Sum'},
    )

    into_path = run_packager(
        testing_pkg, tmp_path, build_entries(tmp_path, ['samples']), main_language='en'
    )

    meta = json.loads((into_path / '.moj-meta.json').read_text())
    assert meta['display_title'] == 'Sum'
    assert 'In English.' in (into_path / 'docs' / 'enunciado.md').read_text()


def test_an_unknown_language_is_an_error(testing_pkg, tmp_path, monkeypatch):
    minimal_package(testing_pkg)
    with_statements(testing_pkg, monkeypatch, PT_BLOCKS)

    with pytest.raises(typer.Exit):
        run_packager(
            testing_pkg,
            tmp_path,
            build_entries(tmp_path, ['samples']),
            main_language='fr',
        )
