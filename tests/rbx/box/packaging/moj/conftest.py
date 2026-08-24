import base64
import pathlib
from typing import Dict, List, Optional

import pytest

from rbx import utils
from rbx.box.generation_schema import GenerationMetadata, GenerationTestcaseEntry
from rbx.box.packaging.moj.packager import (
    MojPackager,
    ProbePackage,
    ProfilePinned,
    TimingMode,
)
from rbx.box.schema import LimitModifiers, LimitsProfile, Testcase
from rbx.box.statements import export
from rbx.box.statements.render import StatementBlocks
from rbx.box.statements.schema import Statement
from rbx.box.testcase_schema import TestcaseEntry

CHECKER = '#include "testlib.h"\nint main(){ quitf(_ok, "ok"); }\n'
ACCEPTED_SOL = '#include <cstdio>\nint main(){ int a,b; scanf("%d %d",&a,&b); printf("%d\\n",a+b); }\n'
WRONG_SOL = '#include <cstdio>\nint main(){ printf("0\\n"); }\n'
SLOW_SOL = '#include <cstdio>\nint main(){ while(1); }\n'


def _entry(
    tmp_path: pathlib.Path, group: str, index: int, content: str
) -> GenerationTestcaseEntry:
    """A built testcase entry backed by real files.

    `find_built_testcases` only requires that `copied_to.inputPath` exists, so the
    packager can be exercised without a full sandboxed build.
    """
    group_dir = tmp_path / 'built' / group
    group_dir.mkdir(parents=True, exist_ok=True)
    input_path = group_dir / f'{index:03d}.in'
    output_path = group_dir / f'{index:03d}.out'
    input_path.write_text(content)
    output_path.write_text('42\n')
    entry = TestcaseEntry(group=group, index=index)
    return GenerationTestcaseEntry(
        group_entry=entry,
        subgroup_entry=entry,
        metadata=GenerationMetadata(
            copied_to=Testcase(inputPath=input_path, outputPath=output_path)
        ),
    )


def build_entries(
    tmp_path: pathlib.Path, groups: List[str]
) -> List[GenerationTestcaseEntry]:
    entries = []
    for group in groups:
        for index in range(2):
            entries.append(_entry(tmp_path, group, index, f'{group} {index}\n'))
    return entries


def with_limits_profile(
    testing_pkg,
    time_limit: int = 1000,
    per_language: Optional[Dict[str, int]] = None,
) -> None:
    """Save the `moj` limits profile `rbx time -p moj` would have written.

    Packaging requires it: MOJ would otherwise measure the limits itself, and the
    packager refuses to pick between pinning and calibrating on the setter's behalf.
    """
    profile = LimitsProfile(
        timeLimit=time_limit,
        modifiers={
            language: LimitModifiers(time=limit)
            for language, limit in (per_language or {}).items()
        },
    )
    limits_path = testing_pkg.root / '.limits' / 'moj.yml'
    limits_path.parent.mkdir(parents=True, exist_ok=True)
    limits_path.write_text(utils.model_to_yaml(profile))


def run_packager(
    testing_pkg,
    tmp_path: pathlib.Path,
    entries: List[GenerationTestcaseEntry],
    main_language: Optional[str] = None,
    pin_limits: bool = True,
    timing_mode: Optional[TimingMode] = None,
    probe: Optional[ProbePackage] = None,
    main_solution_only: bool = False,
) -> pathlib.Path:
    # Packaging needs the time limits settled one way or the other, so the default
    # profile is written here for the tests that are about something else. The tests
    # that ARE about it (test_timing.py) write their own or pass pin_limits=False.
    if pin_limits and not (testing_pkg.root / '.limits' / 'moj.yml').is_file():
        with_limits_profile(testing_pkg)
    if timing_mode is None:
        # What `rbx package moj` does without `--calibrate`. Every other mode is
        # passed explicitly, so this helper has exactly one way to say each thing.
        timing_mode = ProfilePinned()
    into_path = tmp_path / 'package'
    build_path = tmp_path / 'build'
    build_path.mkdir(parents=True, exist_ok=True)
    MojPackager(
        testcase_entries=entries,
        main_language=main_language,
        timing_mode=timing_mode,
        probe=probe,
        main_solution_only=main_solution_only,
    ).package(build_path, into_path, [])
    return into_path


# A 1x1 PNG. A real one, because the end-to-end test hands it to pandoc's
# `--embed-resources`, which reads the file to base64 it.
TINY_PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAE'
    'hQGAhKmMIQAAAABJRU5ErkJggg=='
)


def minimal_package(testing_pkg) -> None:
    """The smallest package MOJ accepts: a checker and one accepted solution."""
    testing_pkg.add_file('check.cpp').write_text(CHECKER)
    testing_pkg.set_checker('check.cpp')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text('int main(){}\n')
    with_limits_profile(testing_pkg)


def with_statements(
    testing_pkg,
    monkeypatch,
    blocks,
    explanations=None,
    languages=('pt',),
    titles=None,
) -> None:
    """Declare statements and fake the artifacts a statement build would leave.

    The export pipeline reads `blocks.sub.yml` and the TikZ PDFs out of the v2
    standalone overlay, which only a real statement build (pdflatex included)
    writes. Faking those three reads keeps these tests about the packager.
    """
    statement_dir = testing_pkg.root / 'statement'
    statement_dir.mkdir(parents=True, exist_ok=True)
    (statement_dir / 'fig.png').write_bytes(TINY_PNG)

    overlay = testing_pkg.root / 'overlay'
    (overlay / '.samples' / '000').mkdir(parents=True, exist_ok=True)
    (overlay / '.samples' / '000' / 'diagram.png').write_bytes(TINY_PNG)

    statements = []
    for language in languages:
        path = statement_dir / f'statement-{language}.rbx.tex'
        path.touch()
        statements.append(
            Statement(
                language=language,
                title=(titles or {}).get(language),
                file=pathlib.Path('statement') / path.name,
            )
        )
    testing_pkg.yml.statements = statements
    testing_pkg.save()

    def _blocks(statement, normalize=True):
        return StatementBlocks(
            blocks=dict(blocks.get(statement.language, blocks['pt'])),
            explanations=dict(explanations or {}),
        )

    monkeypatch.setattr(export, 'get_statement_dir', lambda statement: overlay)
    monkeypatch.setattr(export, 'get_produced_tikz_pdfs', lambda statement: [])
    monkeypatch.setattr(export, 'get_processed_statement_blocks', _blocks)


PT_BLOCKS = {
    'pt': {
        'legend': 'Some os inteiros $a$ e $b$. \\includegraphics{fig}',
        'input': 'Uma linha com $a$ e $b$.',
        'output': 'A soma.',
    }
}

EN_AND_PT_BLOCKS = {
    'pt': {'legend': 'Em português.', 'input': 'Entrada.', 'output': 'Saída.'},
    'en': {'legend': 'In English.', 'input': 'Input.', 'output': 'Output.'},
}


@pytest.fixture
def moj_binary_package(testing_pkg, tmp_path) -> pathlib.Path:
    testing_pkg.add_file('check.cpp').write_text(CHECKER)
    testing_pkg.set_checker('check.cpp')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text(ACCEPTED_SOL)
    testing_pkg.add_testgroup_with_manual_testcases('samples', [])
    testing_pkg.add_testgroup_with_manual_testcases('easy', [])
    testing_pkg.save()

    return run_packager(
        testing_pkg, tmp_path, build_entries(tmp_path, ['samples', 'easy'])
    )


@pytest.fixture
def moj_package(moj_binary_package) -> pathlib.Path:
    return moj_binary_package


@pytest.fixture
def moj_package_output(testing_pkg, tmp_path, capsys) -> str:
    """Console output of packaging a problem whose only accepted solution is C++."""
    testing_pkg.add_file('check.cpp').write_text(CHECKER)
    testing_pkg.set_checker('check.cpp')
    testing_pkg.add_solution('sol.cpp', outcome='accepted').write_text(ACCEPTED_SOL)
    testing_pkg.save()

    run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['samples']))
    return capsys.readouterr().out
