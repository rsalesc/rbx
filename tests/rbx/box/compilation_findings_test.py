import pathlib

import pytest
import yaml

from rbx import utils
from rbx.box import compilation_findings, solutions
from rbx.box.environment import VerificationLevel
from rbx.box.sanitizers import warning_stack
from rbx.box.schema import ExpectedOutcome, Solution
from rbx.grading.steps import CompilationError, PreprocessLog

WARNING_LOG = (
    'sol.cpp: In function ‘int main()’:\n'
    'sol.cpp:4:14: warning: comparison of integer expressions of different '
    'signedness [-Wsign-compare]\n'
    "sol.cpp:7:9: warning: unused variable 'k' [-Wunused-variable]\n"
)


def _solution(
    path: str, outcome: ExpectedOutcome = ExpectedOutcome.ACCEPTED
) -> Solution:
    return Solution(path=pathlib.Path(path), outcome=outcome)


def _warned(path: str, log: str = WARNING_LOG) -> None:
    stack = warning_stack.get_warning_stack()
    stack.add_warning(
        _solution(path),
        logs=[PreprocessLog(cmd=['g++', path], log=log, warnings=True)],
    )


@pytest.fixture(autouse=True)
def clean_warning_stack():
    warning_stack.get_warning_stack().clear()
    yield
    warning_stack.get_warning_stack().clear()


def test_clean_solutions_get_no_record(cleandir: pathlib.Path):
    records = compilation_findings.build_solution_compilations(
        [_solution('sols/main.cpp')], {}, cleandir
    )

    assert records == []
    assert not (cleandir / compilation_findings.COMPILATION_DIR).exists()


def test_warning_solution_carries_its_parsed_warnings(cleandir: pathlib.Path):
    _warned('sols/main.cpp')

    (record,) = compilation_findings.build_solution_compilations(
        [_solution('sols/main.cpp')], {}, cleandir
    )

    assert record.path == pathlib.Path('sols/main.cpp')
    assert record.status == 'WARNINGS'
    assert record.outcome == ExpectedOutcome.ACCEPTED
    assert record.reason is None
    assert [(w.line, w.flag) for w in record.warnings] == [
        (4, '-Wsign-compare'),
        (7, '-Wunused-variable'),
    ]
    assert record.warnings[1].msg == "unused variable 'k'"


def test_compiler_output_is_written_beside_the_skeleton_not_inlined(
    cleandir: pathlib.Path,
):
    _warned('sols/main.cpp')

    (record,) = compilation_findings.build_solution_compilations(
        [_solution('sols/main.cpp')], {}, cleandir
    )

    assert record.log == pathlib.Path('compilation/0.log')
    assert not record.log.is_absolute()
    assert (cleandir / record.log).read_text() == WARNING_LOG


def test_ansi_is_stripped_from_the_written_log(cleandir: pathlib.Path):
    _warned(
        'sols/main.cpp',
        log='\x1b[01m\x1b[Ksol.cpp:4:14:\x1b[m\x1b[K warning: x [-Wall]\n',
    )

    (record,) = compilation_findings.build_solution_compilations(
        [_solution('sols/main.cpp')], {}, cleandir
    )

    assert '\x1b[' not in (cleandir / record.log).read_text()


def test_failed_solution_is_recorded_though_it_never_entered_the_run(
    cleandir: pathlib.Path,
):
    error = CompilationError()
    error.logs = [
        PreprocessLog(
            cmd=['g++', 'sols/wrong.cpp'],
            log="sols/wrong.cpp:3:5: error: 'x' was not declared in this scope\n",
            exitcode=1,
        )
    ]
    solution = _solution('sols/wrong.cpp', ExpectedOutcome.WRONG_ANSWER)

    (record,) = compilation_findings.build_solution_compilations(
        [solution], {pathlib.Path('sols/wrong.cpp'): error}, cleandir
    )

    assert record.status == 'FAILED'
    # The declaration travels with the record: the solution is absent from the
    # skeleton's `solutions`, so this is the only place it can be read from.
    assert record.outcome == ExpectedOutcome.WRONG_ANSWER
    assert record.warnings == []
    assert "'x' was not declared" in (cleandir / record.log).read_text()


def test_missing_compiler_is_named_as_the_reason(cleandir: pathlib.Path):
    error = CompilationError()
    error.not_found_executable = 'g++'

    (record,) = compilation_findings.build_solution_compilations(
        [_solution('sols/wrong.cpp')],
        {pathlib.Path('sols/wrong.cpp'): error},
        cleandir,
    )

    assert record.status == 'FAILED'
    assert record.reason == "'g++' was not found"


def test_records_survive_the_skeleton_round_trip(cleandir: pathlib.Path):
    """The serialized shape is a contract: the VS Code extension reads it.

    `path`, `outcome`, `status`, `log`, `warnings[].line/flag/msg` and `reason`
    are the keys `parseCompilation` in vscode/src/rbx/model.ts looks for, and a
    field renamed here without being renamed there fails silently -- the panel
    just never appears.
    """
    _warned('sols/main.cpp')
    records = compilation_findings.build_solution_compilations(
        [_solution('sols/main.cpp')], {}, cleandir
    )
    skeleton = solutions.SolutionReportSkeleton(
        solutions=[],
        entries=[],
        groups=[],
        limits={},
        compiled_solutions={},
        compilation=records,
        verification=VerificationLevel.NONE,
    )

    dumped = utils.model_to_yaml(skeleton)
    raw = yaml.safe_load(dumped)

    (entry,) = raw['compilation']
    assert entry['path'] == 'sols/main.cpp'
    assert entry['outcome'] == 'ACCEPTED'
    assert entry['status'] == 'WARNINGS'
    assert entry['log'] == 'compilation/0.log'
    assert entry['warnings'][0]['line'] == 4
    assert entry['warnings'][0]['flag'] == '-Wsign-compare'
    assert 'msg' in entry['warnings'][0]

    reloaded = utils.model_from_yaml(solutions.SolutionReportSkeleton, dumped)
    assert reloaded.compilation == records


def test_a_skeleton_without_the_field_still_loads(cleandir: pathlib.Path):
    """An older skeleton reads as a clean compile rather than failing to load."""
    skeleton = utils.model_from_yaml(
        solutions.SolutionReportSkeleton,
        utils.model_to_yaml(
            solutions.SolutionReportSkeleton(
                solutions=[],
                entries=[],
                groups=[],
                limits={},
                compiled_solutions={},
                verification=VerificationLevel.NONE,
            )
        ),
    )
    assert skeleton.compilation == []


def test_log_names_index_the_record_list_not_the_solution_list(
    cleandir: pathlib.Path,
):
    """A clean solution takes no log name with it.

    The log file is named after the record's position, so a package whose first
    solution compiled cleanly must not leave a hole at `compilation/0.log`.
    """
    _warned('sols/second.cpp')
    _warned('sols/third.cpp')

    records = compilation_findings.build_solution_compilations(
        [
            _solution('sols/clean.cpp'),
            _solution('sols/second.cpp'),
            _solution('sols/third.cpp'),
        ],
        {},
        cleandir,
    )

    assert [str(record.path) for record in records] == [
        'sols/second.cpp',
        'sols/third.cpp',
    ]
    assert [str(record.log) for record in records] == [
        'compilation/0.log',
        'compilation/1.log',
    ]
    for record in records:
        assert (cleandir / record.log).is_file()
