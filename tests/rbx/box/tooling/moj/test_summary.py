"""`rbx tooling moj summary`: the contest's problems as MOJ would receive them.

The point of the command is that it agrees with `rbx package moj` without
building anything, so the assertions here are about the three values it borrows
from the packager -- the title, the `<org>#<slug>` id, and which statement the
title came from -- plus the contest-level color, which is the one thing the
packager knows nothing about.
"""

import pathlib
from unittest import mock

import pytest
import typer

from rbx.box.contest.schema import Contest, ContestProblem
from rbx.box.statements.schema import Statement
from rbx.box.tooling.moj import summary


def _declare_statements(testing_pkg, languages, titles=None):
    """Declare statements without building them.

    Nothing here renders a statement: picking the main one only reads
    `problem.rbx.yml`, so an empty (but existing) source file is enough.
    """
    statement_dir = testing_pkg.root / 'statement'
    statement_dir.mkdir(parents=True, exist_ok=True)
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


def _contest(*problems: ContestProblem) -> Contest:
    return Contest(name='contest', problems=list(problems))


class TestSummarizeProblem:
    def test_reports_the_title_the_id_and_the_color(self, testing_pkg):
        testing_pkg.yml.titles = {'en': 'Sum of Two'}
        testing_pkg.save()

        entry = summary.summarize_problem(
            ContestProblem(short_name='A', color='red'), 'unicamp'
        )

        assert entry.short_name == 'A'
        assert entry.title == 'Sum of Two'
        # The package is not inside a contest tree here, so `package_basename`
        # resolves to the bare package name -- the same one the packager uses.
        assert entry.problem_id == 'unicamp#test-problem'
        assert entry.color_name == 'red'
        assert entry.error is None

    def test_reports_no_color_when_the_contest_configures_none(self, testing_pkg):
        entry = summary.summarize_problem(ContestProblem(short_name='A'), 'unicamp')

        assert entry.color is None
        assert entry.color_name is None

    def test_falls_back_to_the_package_name_as_the_title(self, testing_pkg):
        entry = summary.summarize_problem(ContestProblem(short_name='A'), 'unicamp')

        assert entry.title == 'test-problem'

    def test_the_title_comes_from_the_statement_that_would_be_uploaded(
        self, testing_pkg
    ):
        # A MOJ package ships one statement, so the reported title has to be the
        # one belonging to the statement the packager would pick -- the topmost
        # declared one, unless a language is named.
        _declare_statements(
            testing_pkg, ('pt', 'en'), titles={'pt': 'Soma', 'en': 'Sum'}
        )

        assert (
            summary.summarize_problem(ContestProblem(short_name='A'), 'unicamp').title
            == 'Soma'
        )
        assert (
            summary.summarize_problem(
                ContestProblem(short_name='A'), 'unicamp', main_language='en'
            ).title
            == 'Sum'
        )

    def test_an_unknown_language_is_an_error(self, testing_pkg):
        _declare_statements(testing_pkg, ('pt',), titles={'pt': 'Soma'})

        with pytest.raises(typer.Exit):
            summary.summarize_problem(
                ContestProblem(short_name='A'), 'unicamp', main_language='fr'
            )


class TestCollectMojSummary:
    def _patch_org(self, org, is_personal):
        return mock.patch(
            'rbx.box.tooling.moj.summary.upload.resolve_org',
            new=mock.AsyncMock(return_value=(org, is_personal)),
        )

    async def test_summarizes_every_problem_in_the_contest(self, testing_pkg):
        testing_pkg.yml.titles = {'en': 'Sum of Two'}
        testing_pkg.save()
        contest = _contest(
            ContestProblem(short_name='A', path=pathlib.Path('.'), color='red')
        )

        with self._patch_org('unicamp', False):
            entries = await summary.collect_moj_summary(contest)

        assert entries == [
            summary.MojProblemSummary(
                short_name='A',
                title='Sum of Two',
                problem_id='unicamp#test-problem',
                color='#ff0000',
                color_name='red',
            )
        ]

    async def test_warns_when_the_ids_land_on_the_personal_org(
        self, testing_pkg, capsys
    ):
        contest = _contest(ContestProblem(short_name='A', path=pathlib.Path('.')))

        with self._patch_org('alice', True):
            entries = await summary.collect_moj_summary(contest)

        assert entries[0].problem_id == 'alice#test-problem'
        # On the single word, not a phrase: rich wraps the warning at the console
        # width and a phrase can straddle the break.
        assert 'personal' in capsys.readouterr().out

    async def test_does_not_warn_when_an_org_is_configured(self, testing_pkg, capsys):
        contest = _contest(ContestProblem(short_name='A', path=pathlib.Path('.')))

        with self._patch_org('unicamp', False):
            await summary.collect_moj_summary(contest)

        assert 'personal' not in capsys.readouterr().out

    async def test_an_unreadable_problem_still_gets_a_row(self, testing_pkg):
        # A listing that silently drops a problem reads as a contest with one
        # fewer problem, which is exactly the mistake this command exists to
        # prevent. `probs/missing` holds no package at all.
        contest = _contest(
            ContestProblem(short_name='A', path=pathlib.Path('.')),
            ContestProblem(short_name='B', path=pathlib.Path('probs/missing')),
        )

        with self._patch_org('unicamp', False):
            entries = await summary.collect_moj_summary(contest)

        assert [entry.short_name for entry in entries] == ['A', 'B']
        assert entries[0].error is None
        assert entries[1].error is not None
        assert entries[1].problem_id is None


class TestRenderMojSummary:
    def _render(self, entries) -> str:
        # rbx's own theme, since the rows carry rbx style tags (`error`, `dim`)
        # that a bare rich console does not know.
        import rich.console

        import rbx.console

        console = rich.console.Console(theme=rbx.console.theme, record=True, width=200)
        console.print(summary.render_moj_summary(_contest(), entries))
        return console.export_text()

    def test_renders_a_row_per_problem(self):
        text = self._render(
            [
                summary.MojProblemSummary(
                    short_name='A',
                    title='Sum of Two',
                    problem_id='unicamp#a-aplusb',
                    color='#ff0000',
                    color_name='red',
                ),
            ]
        )

        assert 'Sum of Two' in text
        assert 'unicamp#a-aplusb' in text
        assert 'red' in text

    def test_marks_a_problem_that_could_not_be_read_in_the_table(self):
        text = self._render(
            [summary.MojProblemSummary(short_name='B', error='boom')],
        )

        assert 'B' in text
        assert 'failed' in text


class TestRenderMojSummaryPorcelain:
    def _entry(self, short_name, **kwargs):
        return summary.MojProblemSummary(short_name=short_name, **kwargs)

    def test_renders_one_tab_separated_line_per_problem(self):
        text = summary.render_moj_summary_porcelain(
            [
                self._entry(
                    'A',
                    title='Sum of Two',
                    problem_id='unicamp#a-aplusb',
                    color='#ff0000',
                    color_name='red',
                ),
                self._entry(
                    'B',
                    title='Chocolate',
                    problem_id='unicamp#b-choco',
                    color='#0000ff',
                    color_name='blue',
                ),
            ]
        )

        assert text.splitlines() == [
            'A\tSum of Two\tunicamp#a-aplusb\t#ff0000\tred',
            'B\tChocolate\tunicamp#b-choco\t#0000ff\tblue',
        ]

    def test_a_problem_without_a_color_keeps_its_empty_fields(self):
        # Five fields on every line, so a `cut -f3` reads the id regardless of
        # which problems configure a color.
        text = summary.render_moj_summary_porcelain(
            [self._entry('A', title='Sum of Two', problem_id='unicamp#a-aplusb')]
        )

        assert text == 'A\tSum of Two\tunicamp#a-aplusb\t\t'
        assert text.count('\t') == 4

    def test_carries_no_styling(self):
        text = summary.render_moj_summary_porcelain(
            [
                self._entry(
                    'A',
                    title='Sum of Two',
                    problem_id='unicamp#a-aplusb',
                    color='#ff0000',
                    color_name='red',
                )
            ]
        )

        assert '●' not in text
        assert '[' not in text

    def test_omits_a_problem_that_could_not_be_read(self):
        # Unlike the table, which marks it: a line naming the problem with an
        # empty id would be consumed as a problem that uploads to nothing. The
        # failure is reported on stderr instead.
        text = summary.render_moj_summary_porcelain(
            [
                self._entry('A', title='Sum of Two', problem_id='unicamp#a-aplusb'),
                self._entry('B', error='boom'),
            ]
        )

        assert text.splitlines() == ['A\tSum of Two\tunicamp#a-aplusb\t\t']

    def test_renders_nothing_for_a_contest_with_no_problems(self):
        assert summary.render_moj_summary_porcelain([]) == ''


class TestPrintMojSummary:
    def _patch_org(self, org, is_personal):
        return mock.patch(
            'rbx.box.tooling.moj.summary.upload.resolve_org',
            new=mock.AsyncMock(return_value=(org, is_personal)),
        )

    async def test_porcelain_leaves_stdout_as_pure_data(self, testing_pkg, capsys):
        # The warning is what would break a `| cut -f3`, so it has to be on
        # stderr while stdout carries the lines and nothing else.
        contest = _contest(ContestProblem(short_name='A', path=pathlib.Path('.')))

        with self._patch_org('alice', True):
            await summary.print_moj_summary(contest, porcelain=True)

        captured = capsys.readouterr()
        assert captured.out == 'A\ttest-problem\talice#test-problem\t\t\n'
        assert 'personal' in captured.err

    async def test_prints_the_table_by_default(self, testing_pkg, capsys):
        contest = _contest(ContestProblem(short_name='A', path=pathlib.Path('.')))

        with self._patch_org('unicamp', False):
            await summary.print_moj_summary(contest)

        out = capsys.readouterr().out
        assert 'MOJ upload summary' in out
        assert 'unicamp#test-problem' in out
