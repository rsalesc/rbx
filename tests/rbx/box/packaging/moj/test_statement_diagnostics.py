"""`rbx package moj` says what a statement may lose on MOJ (#1012, #1013)."""

import pytest
import typer

from rbx import testing_utils
from rbx.box.packaging.moj.statement_diagnostics import (
    Finding,
    FindingKind,
    StatementDiagnostics,
)
from rbx.box.statements.markdown_export import PandocDiagnostic
from tests.rbx.box.packaging.moj.conftest import (
    build_entries,
    minimal_package,
    run_packager,
    with_statements,
)

BLOCKS_WITH_UNKNOWN = {
    'pt': {
        'legend': r'Uma lista \textbar\space separada \foo{x}.',
        'input': 'Entrada.',
        'output': r'Saída \section{Oi}.',
    }
}

CLEAN_BLOCKS = {
    'pt': {
        'legend': r'Leia $n$ \textbar{} imprima \textless{}x\textgreater{}.',
        'input': r'Uma linha\quad com $a$.',
        'output': 'A soma.',
    }
}


def _package(testing_pkg, tmp_path, monkeypatch, blocks, **kwargs):
    minimal_package(testing_pkg)
    with_statements(testing_pkg, monkeypatch, blocks, **kwargs)
    return run_packager(
        testing_pkg,
        tmp_path,
        build_entries(tmp_path, ['samples']),
        strict_statement=kwargs.pop('strict', False),
    )


def test_warns_naming_the_block_and_the_construct_and_still_packages(
    testing_pkg, tmp_path, monkeypatch, capsys
):
    into_path = _package(testing_pkg, tmp_path, monkeypatch, BLOCKS_WITH_UNKNOWN)

    out = capsys.readouterr().out
    assert 'pt (default) statement uses TeX that MOJ may not show' in out
    assert 'Block legend' in out
    assert '\\foo{x}: dropped by pandoc' in out
    # Outside the subset but converted by pandoc: reported, with its position.
    assert 'Block output' in out
    assert '\\section at 1:6' in out
    # Translated, so neither the validator nor pandoc complains.
    assert 'textbar' not in out
    assert 'space' not in out.replace('may not show', '')

    text = (into_path / 'docs' / 'enunciado.md').read_text()
    assert 'Uma lista \\| separada' in text


def test_a_clean_statement_prints_nothing(testing_pkg, tmp_path, monkeypatch, capsys):
    _package(testing_pkg, tmp_path, monkeypatch, CLEAN_BLOCKS)
    assert 'may not show' not in capsys.readouterr().out


def test_explanations_are_reported_by_index(testing_pkg, tmp_path, monkeypatch, capsys):
    _package(
        testing_pkg,
        tmp_path,
        monkeypatch,
        CLEAN_BLOCKS,
        explanations={0: r'Veja \foo e \foo.'},
    )
    out = capsys.readouterr().out
    assert 'Block explanation_0' in out
    assert '\\foo x2: dropped by pandoc' in out


def test_strict_mode_fails_before_anything_is_packaged(
    testing_pkg, tmp_path, monkeypatch, capsys
):
    minimal_package(testing_pkg)
    with_statements(testing_pkg, monkeypatch, BLOCKS_WITH_UNKNOWN)
    with pytest.raises(typer.Exit) as exc:
        run_packager(
            testing_pkg,
            tmp_path,
            build_entries(tmp_path, ['samples']),
            strict_statement=True,
        )
    assert exc.value.exit_code == 1
    assert 'Strict statement mode is on' in capsys.readouterr().out


def test_strict_mode_passes_a_clean_statement(testing_pkg, tmp_path, monkeypatch):
    minimal_package(testing_pkg)
    with_statements(testing_pkg, monkeypatch, CLEAN_BLOCKS)
    run_packager(
        testing_pkg,
        tmp_path,
        build_entries(tmp_path, ['samples']),
        strict_statement=True,
    )


def test_strict_mode_can_come_from_the_env(testing_pkg, tmp_path, monkeypatch):
    env_path = testing_pkg.preset.path('env.rbx.yml')
    env = env_path.read_text()
    assert 'unifiedTimeLimit: true' in env
    env_path.write_text(
        env.replace(
            'unifiedTimeLimit: true',
            'unifiedTimeLimit: true\n    strictStatement: true',
        )
    )
    testing_utils.clear_all_functools_cache()

    minimal_package(testing_pkg)
    with_statements(testing_pkg, monkeypatch, BLOCKS_WITH_UNKNOWN)
    with pytest.raises(typer.Exit):
        run_packager(testing_pkg, tmp_path, build_entries(tmp_path, ['samples']))


def test_a_main_statement_filling_its_own_slot_is_reported_once(
    testing_pkg, tmp_path, monkeypatch, capsys
):
    # An English main statement fills `enunciado.md` and `enunciado.en.md`.
    _package(
        testing_pkg,
        tmp_path,
        monkeypatch,
        {'pt': BLOCKS_WITH_UNKNOWN['pt'], 'en': BLOCKS_WITH_UNKNOWN['pt']},
        languages=('en',),
    )
    assert capsys.readouterr().out.count('may not show') == 1


# -- the collector ---------------------------------------------------------------


def test_an_unsupported_construct_pandoc_dropped_is_said_once():
    diagnostics = StatementDiagnostics('pt (main)')
    diagnostics.validate_block('legend', r'a \foo{x} \section{y}')
    diagnostics.add_pandoc(
        'legend', [PandocDiagnostic(message='...', snippet=r'\foo{x}')]
    )
    assert diagnostics.effective_findings() == [
        Finding(
            block='legend',
            kind=FindingKind.UNSUPPORTED,
            construct=r'\section',
            location=(1, 10),
            reason='Unsupported command or environment: section',
        ),
        Finding(block='legend', kind=FindingKind.DROPPED, construct=r'\foo{x}'),
    ]


def test_a_dropped_environment_folds_its_validator_finding():
    diagnostics = StatementDiagnostics('pt (main)')
    diagnostics.validate_block('legend', r'\begin{foo}x\end{foo}')
    diagnostics.add_pandoc(
        'legend',
        [
            PandocDiagnostic(message='...', snippet=r'\begin{foo}'),
            PandocDiagnostic(message='...', snippet=r'\end{foo}'),
        ],
    )
    kinds = [f.kind for f in diagnostics.effective_findings()]
    assert kinds == [FindingKind.DROPPED, FindingKind.DROPPED]


def test_the_same_construct_in_another_block_is_not_folded():
    diagnostics = StatementDiagnostics('pt (main)')
    diagnostics.validate_block('legend', r'\foo')
    diagnostics.add_pandoc('notes', [PandocDiagnostic(message='...', snippet=r'\foo')])
    assert len(diagnostics.effective_findings()) == 2


def test_repeats_are_grouped(capsys):
    diagnostics = StatementDiagnostics('pt (main)')
    diagnostics.add_pandoc(
        'explanation_0',
        [PandocDiagnostic(message='...', snippet=r'\foo', line=i) for i in range(6)],
    )
    diagnostics.report(strict=False)
    assert '\\foo x6: dropped by pandoc' in capsys.readouterr().out


def test_pandoc_warnings_are_shown_in_pandocs_words(capsys):
    diagnostics = StatementDiagnostics('pt (main)')
    diagnostics.add_pandoc(
        'legend', [PandocDiagnostic(message='Could not convert TeX math x')]
    )
    diagnostics.report(strict=False)
    assert 'pandoc: Could not convert TeX math x' in capsys.readouterr().out


def test_an_empty_report_is_falsy_and_silent(capsys):
    diagnostics = StatementDiagnostics('pt (main)')
    diagnostics.validate_block('legend', 'plain $x$')
    assert not diagnostics
    diagnostics.report(strict=True)
    assert capsys.readouterr().out == ''
