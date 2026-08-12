import fnmatch
import shutil
import subprocess

import pytest
import typer

from rbx.box.packaging.moj_next.packager import MojNextPackager
from rbx.box.schema import ScoreType, TaskType
from rbx.config import get_default_app_path
from tests.rbx.box.packaging.moj_next.conftest import (
    CHECKER,
    SLOW_SOL,
    WRONG_SOL,
    build_entries,
    run_packager,
)

# -- shape ------------------------------------------------------------------


def test_only_supports_batch_problems():
    # MOJ's interactive support uses its own arbiter protocol, not a testlib
    # interactor, so the legacy `moj` packager keeps those.
    assert MojNextPackager.task_types() == [TaskType.BATCH]


def test_builds_no_statements():
    assert MojNextPackager(testcase_entries=[]).statement_types() == []


def test_packager_is_named_moj_next():
    assert MojNextPackager.name() == 'moj-next'


# -- metadata ---------------------------------------------------------------


def test_writes_the_mandatory_metadata_files(moj_next_package):
    assert (moj_next_package / 'author').read_text().strip() != ''
    assert (moj_next_package / 'tags').exists()


def test_writes_a_statement_with_the_mandatory_sections(moj_next_package):
    text = (moj_next_package / 'docs' / 'enunciado.md').read_text()
    # validate-problem.sh hard-fails without these two headings.
    assert '## Entrada' in text
    assert '## Saída' in text
    # A fence trips its soft "example written by hand" warning, and MOJ injects the
    # examples itself from tests/input/sample*.
    assert '```' not in text
    assert not text.lstrip().startswith('%')


def test_does_not_write_calibrated_or_server_owned_files(moj_next_package):
    # MOJ measures the time limit; it is never authored.
    assert not (moj_next_package / 'tl').exists()
    # .moj-meta.json is written by the server, never by the author.
    assert not (moj_next_package / '.moj-meta.json').exists()
    # A scripts/testlib.h would take precedence over the mojtools-vendored one.
    assert not (moj_next_package / 'scripts' / 'testlib.h').exists()
    assert not (moj_next_package / 'scripts' / 'rbx.h').exists()


def test_conf_uses_the_rss_memory_knob(moj_next_package):
    conf = (moj_next_package / 'conf').read_text()
    assert 'MEMLIMITMB=' in conf
    # ULIMITS[-v] is the legacy knob; MEMLIMITMB deliberately replaces it, and MOJ
    # drops the virtual-memory limit when it is set.
    assert 'ULIMITS[-v]' not in conf
    assert 'ULIMITS[-f]=' in conf
    assert 'TLMOD[calibrafactor]=1.35' in conf


# -- tests ------------------------------------------------------------------


def test_samples_are_named_sample_and_sort_first(moj_next_package):
    names = sorted(p.name for p in (moj_next_package / 'tests' / 'input').iterdir())
    assert names[0].startswith('sample')
    assert any(name.startswith('t') for name in names)


def test_every_input_has_a_paired_output(moj_next_package):
    inputs = {p.name for p in (moj_next_package / 'tests' / 'input').iterdir()}
    outputs = {p.name for p in (moj_next_package / 'tests' / 'output').iterdir()}
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


def test_checker_is_a_single_self_contained_file(moj_next_package):
    text = (moj_next_package / 'scripts' / 'checker.cpp').read_text()
    # The bridge binds only checker.cpp and testlib.h into the compile jail, so no
    # other quoted include can resolve there.
    assert '#include "testlib.h"' not in text
    assert '#include "rbx.h"' not in text
    assert 'registerTestlibCmd' in text


def test_compare_is_the_canonical_stub(moj_next_package):
    emitted = moj_next_package / 'scripts' / 'compare.sh'
    bundled = (
        get_default_app_path() / 'packagers' / 'moj_next' / 'scripts' / 'compare.sh'
    )
    assert emitted.read_bytes() == bundled.read_bytes()
    # Without +x the judge gets "Permission denied" and every test is a judge error.
    assert emitted.stat().st_mode & 0o111


@pytest.mark.skipif(shutil.which('g++') is None, reason='g++ not available')
def test_amalgamated_checker_compiles_the_way_moj_compiles_it(
    moj_next_package, tmp_path
):
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
            str(moj_next_package / 'scripts' / 'checker.cpp'),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


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


def test_accepted_solutions_go_to_good(moj_next_package):
    # MOJ calibrates the time limit from sols/good; without one it cannot calibrate.
    assert list((moj_next_package / 'sols' / 'good').iterdir())


def test_outcomes_map_to_their_directories(testing_pkg, tmp_path):
    testing_pkg.add_file('check.cpp').write_text(CHECKER)
    testing_pkg.set_checker('check.cpp')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text('int main(){}\n')
    testing_pkg.add_solution('wrong.cpp', outcome='wrong-answer').write_text(WRONG_SOL)
    testing_pkg.add_solution('slow.cpp', outcome='time-limit-exceeded').write_text(
        SLOW_SOL
    )
    testing_pkg.save()

    root = (
        run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['samples']))
        / 'sols'
    )
    assert (root / 'good' / 'sol.cpp').is_file()
    assert (root / 'wrong' / 'wrong.cpp').is_file()
    assert (root / 'slow' / 'slow.cpp').is_file()


def test_refuses_a_package_without_an_accepted_solution(testing_pkg, tmp_path):
    testing_pkg.add_file('check.cpp').write_text(CHECKER)
    testing_pkg.set_checker('check.cpp')
    testing_pkg.add_solution('wrong.cpp', outcome='wrong-answer').write_text(WRONG_SOL)
    testing_pkg.save()

    with pytest.raises(typer.Exit):
        run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['samples']))


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


def test_emits_a_script_dir_per_declared_language(moj_next_package):
    scripts = moj_next_package / 'scripts'
    for language in ['c', 'cpp', 'py', 'java', 'kt']:
        assert (scripts / language / 'compile.sh').is_file()
        assert (scripts / language / 'run.sh').is_file()


def test_emitted_scripts_are_executable(moj_next_package):
    for path in (moj_next_package / 'scripts').rglob('*.sh'):
        assert path.stat().st_mode & 0o111, path


def test_flags_are_substituted(moj_next_package):
    text = (moj_next_package / 'scripts' / 'cpp' / 'compile.sh').read_text()
    assert '{{rbxFlags}}' not in text
    assert '-std=c++20' in text


def test_no_placeholder_survives_anywhere(moj_next_package):
    for path in (moj_next_package / 'scripts').rglob('*.sh'):
        assert '{{' not in path.read_text(), path


# -- scoring ----------------------------------------------------------------


def test_binary_problems_emit_no_score_file(moj_next_binary_package):
    # Without tests/score MOJ scores by percentage of tests and still requires all of
    # them to pass, which is the correct ICPC semantics.
    assert not (moj_next_binary_package / 'tests' / 'score').exists()


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
