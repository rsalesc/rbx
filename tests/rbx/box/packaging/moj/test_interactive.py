import pathlib

import pytest
import typer

from rbx.box.packaging.moj import packager as moj_packager
from rbx.box.packaging.moj.packager import MojPackager
from rbx.box.schema import TaskType
from rbx.box.testcase_sample_utils import SampleTestcaseInteraction, StatementSample
from rbx.box.testcase_utils import TestcaseInteractionEntry
from tests.rbx.box.packaging.moj.conftest import (
    PT_BLOCKS,
    build_entries,
    run_packager,
    with_statements,
)

# Reads the hidden number from the input and one guess from the contestant.
INTERACTOR = """#include "testlib.h"
int main(int argc, char *argv[]) {
  registerInteraction(argc, argv);
  int x = inf.readInt();
  int guess = ouf.readInt();
  if (guess != x)
    quitf(_wa, "expected %d, got %d", x, guess);
  quitf(_ok, "guessed %d", x);
}
"""


def _interactive_package(testing_pkg, interactor: str = INTERACTOR) -> None:
    testing_pkg.set_type(TaskType.COMMUNICATION)
    testing_pkg.add_file('interactor.cpp').write_text(interactor)
    testing_pkg.set_interactor('interactor.cpp')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text('int main(){}\n')
    testing_pkg.save()


@pytest.fixture
def moj_interactive_package(testing_pkg, tmp_path) -> pathlib.Path:
    _interactive_package(testing_pkg)
    return run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['tests']))


def test_supports_interactive_problems():
    assert TaskType.COMMUNICATION in MojPackager.task_types()


def test_conf_allows_the_extra_processes_and_hides_the_example_box(
    moj_interactive_package,
):
    lines = (moj_interactive_package / 'conf').read_text().splitlines()
    assert 'ULIMITS[-u]=10000' in lines
    assert 'SAMPLE=no' in lines


def test_batch_conf_is_untouched(moj_package):
    lines = (moj_package / 'conf').read_text().splitlines()
    assert not any(line.startswith('ULIMITS[-u]') for line in lines)
    assert not any(line.startswith('SAMPLE=') for line in lines)
    assert not (moj_package / 'scripts' / 'arbitro.cpp').exists()


def test_warns_that_the_pinned_limits_include_the_interactor(
    testing_pkg, tmp_path, capsys
):
    _interactive_package(testing_pkg)
    run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['tests']))
    assert 'interactor' in capsys.readouterr().out


def test_refuses_a_legacy_interactor(testing_pkg, tmp_path, capsys):
    _interactive_package(testing_pkg)
    testing_pkg.yml.interactor.legacy = True
    testing_pkg.add_file('check.cpp').write_text(
        '#include "testlib.h"\nint main(int c, char**v){ registerTestlibCmd(c, v);'
        ' quitf(_ok, "ok"); }\n'
    )
    testing_pkg.set_checker('check.cpp')
    testing_pkg.save()

    with pytest.raises(typer.Exit):
        run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['tests']))

    assert 'legacy interactors' in capsys.readouterr().out


def test_refuses_a_non_cpp_interactor(testing_pkg, tmp_path, capsys):
    testing_pkg.set_type(TaskType.COMMUNICATION)
    testing_pkg.add_file('interactor.py').write_text('print(1)\n')
    testing_pkg.set_interactor('interactor.py')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text('int main(){}\n')
    testing_pkg.save()

    with pytest.raises(typer.Exit):
        run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['tests']))

    assert 'must be C++' in capsys.readouterr().out


# -- the samples, written into the statement ----------------------------------


def _statement_sample(entry, interaction):
    testcase = entry.metadata.copied_to
    return StatementSample(
        entry=entry,
        inputPath=testcase.inputPath,
        outputPath=testcase.outputPath,
        interaction=SampleTestcaseInteraction(
            entries=[
                TestcaseInteractionEntry(data=data, pipe=pipe)
                for pipe, data in interaction
            ],
            chunks=[],
        ),
    )


@pytest.fixture
def interactive_with_samples(testing_pkg, tmp_path, monkeypatch):
    """Package an interactive problem whose two samples have recorded
    interactions and the first an explanation. Returns the package tree."""
    _interactive_package(testing_pkg)
    with_statements(testing_pkg, monkeypatch, PT_BLOCKS, explanations={0: 'Primeiro.'})
    entries = build_entries(tmp_path, ['samples', 'tests'])
    samples = [
        _statement_sample(entries[0], [(0, '10'), (1, '! 10')]),
        _statement_sample(entries[1], [(0, '7'), (1, '3'), (0, '>='), (1, '! 7')]),
    ]

    async def get_statement_samples():
        return samples

    monkeypatch.setattr(moj_packager, 'get_statement_samples', get_statement_samples)
    return run_packager(testing_pkg, tmp_path, entries)


def test_samples_are_written_into_the_statement(interactive_with_samples):
    text = (interactive_with_samples / 'docs' / 'enunciado.md').read_text()

    assert '## Exemplo' in text
    assert '### Exemplo 1\n\n```\n     10\n! 10\n```\n\nPrimeiro.' in text
    assert '### Exemplo 2\n\n```\n    7\n3\n    >=\n! 7\n```' in text


def test_samples_ship_no_notes(interactive_with_samples):
    # With SAMPLE=no MOJ renders no sample notes; the explanation is in the text.
    assert not (interactive_with_samples / 'docs' / 'notes').exists()
