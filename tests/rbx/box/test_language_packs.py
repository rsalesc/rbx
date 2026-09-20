"""Tests for rbx.box.language_packs: the per-language files a template's
wildcard statements resolve to, and pruning/adding/removing them in a
package (design 2026-09-20 §2-§3)."""

import pathlib
import shutil

import pytest
import ruyaml
import typer

from rbx.box import language_packs as lp


@pytest.fixture
def preset(testdata_path: pathlib.Path) -> pathlib.Path:
    return testdata_path / 'presets' / 'multilang'


@pytest.fixture
def problem(cleandir: pathlib.Path, preset: pathlib.Path) -> pathlib.Path:
    dest = cleandir / 'prob'
    shutil.copytree(preset / 'problem', dest)
    return dest


@pytest.fixture
def contest(cleandir: pathlib.Path, preset: pathlib.Path) -> pathlib.Path:
    dest = cleandir / 'contest'
    shutil.copytree(preset / 'contest', dest)
    return dest


def _load(root: pathlib.Path, is_contest: bool = False):
    name = 'contest.rbx.yml' if is_contest else 'problem.rbx.yml'
    return ruyaml.YAML().load((root / name).read_text())


class TestTemplateIntrospection:
    def test_template_languages(self, preset):
        assert lp.template_languages(preset / 'problem', is_contest=False) == [
            'en',
            'pt',
            'es',
        ]
        assert lp.template_languages(preset / 'contest', is_contest=True) == [
            'en',
            'pt',
            'es',
        ]

    def test_template_without_list_has_no_languages(self, cleandir):
        (cleandir / 'problem.rbx.yml').write_text(
            'name: "prob"\ntimeLimit: 1000\nmemoryLimit: 256\n'
        )
        assert lp.template_languages(cleandir, is_contest=False) == []

    def test_problem_pack_files_are_the_wildcard_expansions(self, preset):
        assert lp.pack_files(preset / 'problem', 'pt', is_contest=False) == [
            pathlib.Path('statement/statement-pt.rbx.tex'),
            pathlib.Path('statement/editorial-pt.rbx.tex'),
        ]

    def test_contest_pack_is_empty_when_chrome_is_shared(self, preset):
        # Every contest wildcard points at a language-neutral file.
        assert lp.pack_files(preset / 'contest', 'pt', is_contest=True) == []

    def test_contest_pack_includes_lang_specific_templates(self, contest):
        (contest / 'contest.rbx.yml').write_text(
            'name: "contest"\nlanguages: ["en", "pt"]\nstatements:\n'
            '  - name: "st-{lang}"\n    language: "*"\n'
            '    file: "statements/sheet-{lang}.rbx.tex"\n'
            '    standaloneProblemTemplate: "statements/problem.rbx.tex"\n'
            '    contestProblemTemplate: "statements/fragment-{lang}.rbx.tex"\n'
        )
        assert lp.pack_files(contest, 'pt', is_contest=True) == [
            pathlib.Path('statements/sheet-pt.rbx.tex'),
            pathlib.Path('statements/fragment-pt.rbx.tex'),
        ]


class TestPrune:
    def test_rewrites_list_deletes_files_and_titles(self, problem):
        lp.prune_languages(problem, ['en'], is_contest=False)

        data = _load(problem)
        assert list(data['languages']) == ['en']
        assert dict(data['titles']) == {'en': 'New problem'}
        assert not (problem / 'statement/statement-pt.rbx.tex').exists()
        assert not (problem / 'statement/editorial-es.rbx.tex').exists()
        assert (problem / 'statement/statement-en.rbx.tex').exists()
        assert (problem / 'statement/editorial-en.rbx.tex').exists()

    def test_keeps_comments_and_order(self, problem):
        lp.prune_languages(problem, ['pt', 'en'], is_contest=False)

        text = (problem / 'problem.rbx.yml').read_text()
        assert '# Titles per language.' in text
        assert '# Per-language statement.' in text
        # Selection order is honoured: it becomes the default-language order.
        assert list(_load(problem)['languages']) == ['pt', 'en']

    def test_inherit_drops_the_list(self, problem):
        lp.prune_languages(problem, ['en'], is_contest=False, inherit=True)

        data = _load(problem)
        assert 'languages' not in data
        assert dict(data['titles']) == {'en': 'New problem'}
        assert not (problem / 'statement/statement-pt.rbx.tex').exists()

    def test_contest_prune(self, contest):
        lp.prune_languages(contest, ['es'], is_contest=True)

        data = _load(contest, is_contest=True)
        assert list(data['languages']) == ['es']
        assert dict(data['titles']) == {'es': 'Nuevo contest'}
        # Shared chrome is untouched.
        assert (contest / 'statements/problem-sheet.rbx.tex').exists()

    def test_unknown_language_is_kept_but_warned(self, problem, capsys):
        lp.prune_languages(problem, ['en', 'fr'], is_contest=False)

        assert list(_load(problem)['languages']) == ['en', 'fr']


class TestAdd:
    def test_copies_pack_and_title_from_template(self, problem, preset):
        lp.prune_languages(problem, ['en'], is_contest=False)

        created = lp.add_language(problem, preset / 'problem', 'pt', is_contest=False)

        assert created == [
            pathlib.Path('statement/statement-pt.rbx.tex'),
            pathlib.Path('statement/editorial-pt.rbx.tex'),
        ]
        data = _load(problem)
        assert list(data['languages']) == ['en', 'pt']
        assert data['titles']['pt'] == 'Novo problema'
        assert (problem / 'statement/statement-pt.rbx.tex').read_text() == (
            preset / 'problem/statement/statement-pt.rbx.tex'
        ).read_text()

    def test_is_idempotent_and_never_overwrites(self, problem, preset):
        lp.prune_languages(problem, ['en'], is_contest=False)
        lp.add_language(problem, preset / 'problem', 'pt', is_contest=False)
        (problem / 'statement/statement-pt.rbx.tex').write_text('edited')
        (problem / 'statement/editorial-pt.rbx.tex').unlink()

        created = lp.add_language(problem, preset / 'problem', 'pt', is_contest=False)

        assert created == [pathlib.Path('statement/editorial-pt.rbx.tex')]
        assert (problem / 'statement/statement-pt.rbx.tex').read_text() == 'edited'
        assert list(_load(problem)['languages']) == ['en', 'pt']

    def test_inheriting_problem_gets_no_list(self, cleandir, problem, preset):
        (cleandir / 'contest.rbx.yml').write_text(
            'name: "contest"\nlanguages: ["en", "pt"]\n'
            'problems:\n  - short_name: "A"\n    path: "prob"\n'
        )
        lp.prune_languages(problem, ['en'], is_contest=False, inherit=True)

        lp.add_language(problem, preset / 'problem', 'pt', is_contest=False)

        data = _load(problem)
        assert 'languages' not in data
        assert data['titles']['pt'] == 'Novo problema'
        assert (problem / 'statement/statement-pt.rbx.tex').exists()

    def test_from_existing_language_clones_files_and_title(self, problem, preset):
        lp.prune_languages(problem, ['en'], is_contest=False)

        created = lp.add_language(
            problem, preset / 'problem', 'fr', is_contest=False, from_lang='en'
        )

        assert created == [
            pathlib.Path('statement/statement-fr.rbx.tex'),
            pathlib.Path('statement/editorial-fr.rbx.tex'),
        ]
        assert (problem / 'statement/statement-fr.rbx.tex').read_text() == (
            problem / 'statement/statement-en.rbx.tex'
        ).read_text()
        data = _load(problem)
        assert data['titles']['fr'] == 'New problem'
        assert list(data['languages']) == ['en', 'fr']

    def test_unshipped_language_without_from_errors(self, problem, preset):
        with pytest.raises(typer.Exit):
            lp.add_language(problem, preset / 'problem', 'fr', is_contest=False)

    def test_invalid_language_code_errors(self, problem, preset):
        with pytest.raises(typer.Exit):
            lp.add_language(problem, preset / 'problem', 'french', is_contest=False)

    def test_contest_add(self, contest, preset):
        lp.prune_languages(contest, ['en'], is_contest=True)

        created = lp.add_language(contest, preset / 'contest', 'pt', is_contest=True)

        assert created == []
        data = _load(contest, is_contest=True)
        assert list(data['languages']) == ['en', 'pt']
        assert data['titles']['pt'] == 'Novo contest'


class TestRemove:
    def test_keeps_files_and_reports_them_as_orphaned(self, problem):
        orphaned = lp.remove_language(problem, 'pt', is_contest=False)

        assert orphaned == [
            pathlib.Path('statement/statement-pt.rbx.tex'),
            pathlib.Path('statement/editorial-pt.rbx.tex'),
        ]
        assert (problem / 'statement/statement-pt.rbx.tex').exists()
        data = _load(problem)
        assert list(data['languages']) == ['en', 'es']
        assert 'pt' not in data['titles']

    def test_delete_files(self, problem):
        removed = lp.remove_language(problem, 'pt', is_contest=False, delete_files=True)

        assert removed == [
            pathlib.Path('statement/statement-pt.rbx.tex'),
            pathlib.Path('statement/editorial-pt.rbx.tex'),
        ]
        assert not (problem / 'statement/statement-pt.rbx.tex').exists()

    def test_missing_language_is_a_noop(self, problem):
        before = (problem / 'problem.rbx.yml').read_text()

        assert lp.remove_language(problem, 'fr', is_contest=False) == []

        assert (problem / 'problem.rbx.yml').read_text() == before


class TestList:
    def test_lists_effective_languages_with_file_presence(self, problem):
        (problem / 'statement/editorial-pt.rbx.tex').unlink()

        listing = lp.list_languages(problem, is_contest=False)

        assert listing == [
            (
                'en',
                [
                    (pathlib.Path('statement/statement-en.rbx.tex'), True),
                    (pathlib.Path('statement/editorial-en.rbx.tex'), True),
                ],
            ),
            (
                'pt',
                [
                    (pathlib.Path('statement/statement-pt.rbx.tex'), True),
                    (pathlib.Path('statement/editorial-pt.rbx.tex'), False),
                ],
            ),
            (
                'es',
                [
                    (pathlib.Path('statement/statement-es.rbx.tex'), True),
                    (pathlib.Path('statement/editorial-es.rbx.tex'), True),
                ],
            ),
        ]
