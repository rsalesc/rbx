import pathlib
import re
import zipfile

import pytest
import yaml

from rbx.box import header
from rbx.box.generation_schema import GenerationMetadata, GenerationTestcaseEntry
from rbx.box.packaging.domjudge.packager import DomjudgePackager
from rbx.box.packaging.domjudge.testlib_patch import patch_testlib_for_domjudge
from rbx.box.packaging.packager import BuiltStatement
from rbx.box.schema import CodeItem, ExpectedOutcome, Testcase
from rbx.box.statements.schema import Statement, StatementType
from rbx.box.testcase_schema import TestcaseEntry
from rbx.config import get_builtin_checker
from rbx.testing_utils import get_resources_path


@pytest.fixture
def bundled_testlib() -> str:
    return (get_resources_path() / 'predownloaded' / 'testlib.h').read_text()


def test_patch_testlib_patches_bundled_testlib(bundled_testlib):
    patched = patch_testlib_for_domjudge(bundled_testlib)

    # Exit codes follow the Kattis/DOMjudge output validator protocol.
    expected_codes = {
        'OK_EXIT_CODE': '42',
        'WA_EXIT_CODE': '43',
        'PE_EXIT_CODE': '43',
        'DIRT_EXIT_CODE': '43',
        'UNEXPECTED_EOF_EXIT_CODE': '43',
    }
    for name, value in expected_codes.items():
        define_lines = [
            line
            for line in patched.splitlines()
            if re.fullmatch(rf'# *define +{name} +\S+ *', line)
        ]
        assert define_lines, f'no #define for {name}'
        for line in define_lines:
            assert line.rstrip().endswith(f' {value}'), line

    # Checker reads team output from stdin and writes to the feedback dir.
    assert 'ouf.init(stdin, _output);' in patched
    assert 'judgemessage.txt' in patched
    assert 'teammessage.txt' in patched

    # skipBom seeks the stream, which fails on stdin pipes.
    assert not any(
        line.strip() in ('skipBom();', 'ouf.skipBom();')
        for line in patched.splitlines()
    )


def test_patch_testlib_requires_anchors():
    with pytest.raises(ValueError):
        patch_testlib_for_domjudge('int main() { return 0; }\n')


def test_ini_contents(testing_pkg):
    testing_pkg.yml.timeLimit = 2500
    testing_pkg.yml.titles = {'en': "It's a problem"}
    testing_pkg.save()

    packager = DomjudgePackager(testcase_entries=[])
    ini = packager._get_ini()  # noqa: SLF001

    lines = ini.splitlines()
    # No contest: short-name falls back to the package name.
    assert f'short-name = {testing_pkg.yml.name}' in lines
    assert 'name = It`s a problem' in lines
    # Exact fractional seconds, no float rounding.
    assert 'timelimit = 2.500' in lines
    # No contest: no color line.
    assert not any(line.startswith('color') for line in lines)


def test_problem_yaml_default_checker(testing_pkg):
    testing_pkg.yml.memoryLimit = 256
    testing_pkg.yml.outputLimit = 4 * 1024
    testing_pkg.save()

    packager = DomjudgePackager(testcase_entries=[])
    data = yaml.safe_load(packager._get_problem_yaml())  # noqa: SLF001

    assert data['validation'] == 'default'
    assert 'validator_flags' not in data
    assert data['limits'] == {'memory': 256, 'output': 4}


def test_problem_yaml_float_checker_maps_to_validator_flags(testing_pkg):
    testing_pkg.yml.checker = CodeItem(path=get_builtin_checker('dcmp.cpp').absolute())
    testing_pkg.save()

    packager = DomjudgePackager(testcase_entries=[])
    data = yaml.safe_load(packager._get_problem_yaml())  # noqa: SLF001

    assert data['validation'] == 'default'
    assert data['validator_flags'] == 'float_tolerance 1e-6'


def test_problem_yaml_custom_checker(testing_pkg):
    testing_pkg.set_checker('chk.cpp').write_text(
        '#include "testlib.h"\nint main(){}\n'
    )
    testing_pkg.save()

    packager = DomjudgePackager(testcase_entries=[])
    data = yaml.safe_load(packager._get_problem_yaml())  # noqa: SLF001

    assert data['validation'] == 'custom'
    assert 'validator_flags' not in data


def test_local_copy_of_builtin_checker_is_custom(testing_pkg):
    # A wcmp.cpp living in the package may have been edited by the user;
    # it must not silently map to the default validator.
    testing_pkg.set_checker('wcmp.cpp').write_text(
        '#include "testlib.h"\nint main(){}\n'
    )
    testing_pkg.save()

    packager = DomjudgePackager(testcase_entries=[])
    data = yaml.safe_load(packager._get_problem_yaml())  # noqa: SLF001

    assert data['validation'] == 'custom'


def test_output_validators_flatten(testing_pkg, tmp_path):
    testing_pkg.add_file('common/lib.h').write_text('#pragma once\nint N=1;\n')
    testing_pkg.set_checker('checkers/check.cpp').write_text(
        '#include "../common/lib.h"\n#include "testlib.h"\nint main(){}\n'
    )
    testing_pkg.save()
    header.generate_header()

    packager = DomjudgePackager(testcase_entries=[])
    validators_dir = tmp_path / 'output_validators'
    packager._write_output_validators(validators_dir)  # noqa: SLF001

    assert (validators_dir / 'checker.cpp').is_file()
    assert (validators_dir / 'lib.h').is_file()
    assert (validators_dir / 'rbx.h').is_file()

    checker_text = (validators_dir / 'checker.cpp').read_text()
    assert '#include "lib.h"' in checker_text
    assert '#include "../common/lib.h"' not in checker_text

    # The shipped testlib speaks the DOMjudge validator protocol.
    testlib_text = (validators_dir / 'testlib.h').read_text()
    assert 'define OK_EXIT_CODE 42' in testlib_text


def test_submissions_mapping(testing_pkg, tmp_path):
    testing_pkg.add_solution('sols/ac.cpp', ExpectedOutcome.ACCEPTED).write_text('AC')
    testing_pkg.add_solution('sols/wa.cpp', ExpectedOutcome.WRONG_ANSWER).write_text(
        'WA'
    )
    testing_pkg.add_solution(
        'sols/tle.cpp', ExpectedOutcome.TIME_LIMIT_EXCEEDED
    ).write_text('TLE')
    testing_pkg.add_solution('sols/rte.cpp', ExpectedOutcome.RUNTIME_ERROR).write_text(
        'RTE'
    )
    testing_pkg.add_solution(
        'sols/mle.cpp', ExpectedOutcome.MEMORY_LIMIT_EXCEEDED
    ).write_text('MLE')
    testing_pkg.add_solution('sols/any.cpp', ExpectedOutcome.ANY).write_text('ANY')
    testing_pkg.save()

    packager = DomjudgePackager(testcase_entries=[])
    submissions_dir = tmp_path / 'submissions'
    packager._write_submissions(submissions_dir)  # noqa: SLF001

    assert (submissions_dir / 'accepted' / 'ac.cpp').read_text() == 'AC'
    assert (submissions_dir / 'wrong_answer' / 'wa.cpp').read_text() == 'WA'
    assert (submissions_dir / 'time_limit_exceeded' / 'tle.cpp').read_text() == 'TLE'
    assert (submissions_dir / 'run_time_error' / 'rte.cpp').read_text() == 'RTE'
    # DOMjudge reports MLE as RTE by default.
    assert (submissions_dir / 'run_time_error' / 'mle.cpp').read_text() == 'MLE'
    # Ambiguous outcomes are not packaged.
    assert not list(submissions_dir.rglob('any.cpp'))


def test_submissions_basename_collision(testing_pkg, tmp_path):
    testing_pkg.add_solution('a/sol.cpp', ExpectedOutcome.ACCEPTED).write_text('A')
    testing_pkg.add_solution('b/sol.cpp', ExpectedOutcome.ACCEPTED).write_text('B')
    testing_pkg.save()

    packager = DomjudgePackager(testcase_entries=[])
    submissions_dir = tmp_path / 'submissions'
    packager._write_submissions(submissions_dir)  # noqa: SLF001

    accepted = sorted(p.name for p in (submissions_dir / 'accepted').iterdir())
    assert accepted == ['b__sol.cpp', 'sol.cpp']


def _make_entry(
    tmp_path: pathlib.Path, group: str, index: int, content: str
) -> GenerationTestcaseEntry:
    in_path = tmp_path / 'built' / group / f'{index}.in'
    out_path = in_path.with_suffix('.out')
    in_path.parent.mkdir(parents=True, exist_ok=True)
    in_path.write_text(content)
    out_path.write_text(content.upper())
    return GenerationTestcaseEntry(
        group_entry=TestcaseEntry(group=group, index=index),
        subgroup_entry=TestcaseEntry(group=group, index=index),
        metadata=GenerationMetadata(
            copied_to=Testcase(inputPath=in_path, outputPath=out_path)
        ),
    )


def test_write_testcases_routes_samples_and_secret(testing_pkg, tmp_path):
    entries = [
        _make_entry(tmp_path, 'samples', 0, 'sample0'),
        _make_entry(tmp_path, 'main', 0, 'main0'),
        _make_entry(tmp_path, 'samples', 1, 'sample1'),
        _make_entry(tmp_path, 'main', 1, 'main1'),
    ]

    packager = DomjudgePackager(testcase_entries=entries)
    data_path = tmp_path / 'data'
    packager._write_testcases(data_path)  # noqa: SLF001

    assert (data_path / 'sample' / '001.in').read_text() == 'sample0'
    assert (data_path / 'sample' / '001.ans').read_text() == 'SAMPLE0'
    assert (data_path / 'sample' / '002.in').read_text() == 'sample1'
    assert (data_path / 'secret' / '001.in').read_text() == 'main0'
    assert (data_path / 'secret' / '002.in').read_text() == 'main1'
    assert (data_path / 'secret' / '002.ans').read_text() == 'MAIN1'


def test_package_smoke(testing_pkg, tmp_path):
    testing_pkg.yml.statements = [
        Statement(file=pathlib.Path('st.pdf'), type=StatementType.PDF)
    ]
    testing_pkg.add_solution('sols/ac.cpp', ExpectedOutcome.ACCEPTED).write_text('AC')
    testing_pkg.save()
    header.generate_header()

    pdf_path = testing_pkg.add_file('st.pdf')
    pdf_path.write_bytes(b'%PDF-fake')

    packager = DomjudgePackager(testcase_entries=[])
    built_statement = BuiltStatement(
        statement=testing_pkg.yml.expanded_statements[0],
        path=pdf_path,
        output_type=StatementType.PDF,
    )

    build_path = tmp_path / 'build'
    into_path = tmp_path / 'into'
    build_path.mkdir()
    into_path.mkdir()

    result = packager.package(build_path, into_path, [built_statement])

    assert result.is_file()
    with zipfile.ZipFile(result) as zf:
        names = set(zf.namelist())
        assert 'domjudge-problem.ini' in names
        assert 'problem.yaml' in names
        assert 'problem.pdf' in names
        assert 'submissions/accepted/ac.cpp' in names
        assert zf.read('problem.pdf') == b'%PDF-fake'
