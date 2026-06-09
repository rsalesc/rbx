from rbx.box.statements import context
from rbx.box.statements.context import (
    ContestRenderContext,
    ProblemRenderContext,
    SampleHandle,
    StatementCodeLanguage,
)


def _langs():
    return [StatementCodeLanguage(id='cpp', name='C++', command='g++')]


def _contest_ctx(**kwargs):
    return ContestRenderContext(
        title=kwargs.pop('title', 'My Contest'),
        vars=kwargs.pop('vars', {'year': 2026}),
        params=kwargs.pop('params', {}),
        **kwargs,
    )


def _problem_ctx(**kwargs):
    return ProblemRenderContext(
        title=kwargs.pop('title', 'My Problem'),
        vars=kwargs.pop('vars', {'author': 'alice'}),
        params=kwargs.pop('params', {'show_limits': True}),
        **kwargs,
    )


class TestProblemNamespaces:
    def test_params_vars_contest_are_separate_namespaces(self):
        kwargs = context.problem_jinja_kwargs(
            lang='en',
            languages=_langs(),
            problem=_problem_ctx(
                params={'show_limits': True}, vars={'author': 'alice'}
            ),
            contest=_contest_ctx(vars={'year': 2026}),
        )
        # Distinct, unmerged.
        assert kwargs['params']['show_limits'] is True
        assert kwargs['vars']['author'] == 'alice'
        assert kwargs['contest']['vars']['year'] == 2026
        # No cross-contamination.
        assert 'author' not in kwargs['params']
        assert 'show_limits' not in kwargs['vars']
        assert 'year' not in kwargs['vars']

    def test_problem_namespace_exposes_title_and_samples(self):
        sample = SampleHandle(
            index=0, input='.samples/000/in', output='.samples/000/out'
        )
        kwargs = context.problem_jinja_kwargs(
            lang='en',
            languages=_langs(),
            problem=_problem_ctx(samples=[sample], short_name='A'),
            contest=_contest_ctx(),
        )
        assert kwargs['problem']['title'] == 'My Problem'
        assert kwargs['problem']['short_name'] == 'A'
        assert kwargs['problem']['samples'][0].input == '.samples/000/in'

    def test_import_handles_present_when_set(self):
        kwargs = context.problem_jinja_kwargs(
            lang='en',
            languages=_langs(),
            problem=_problem_ctx(import_dir='.problems/A/', import_file='statement'),
            contest=_contest_ctx(),
        )
        assert kwargs['problem']['import_dir'] == '.problems/A/'
        assert kwargs['problem']['import_file'] == 'statement'

    def test_import_handles_absent_by_default(self):
        kwargs = context.problem_jinja_kwargs(
            lang='en',
            languages=_langs(),
            problem=_problem_ctx(),
            contest=_contest_ctx(),
        )
        assert 'import_dir' not in kwargs['problem']
        assert 'import_file' not in kwargs['problem']


class TestContestNamespaces:
    def test_contest_render_exposes_problems_list(self):
        problems = [
            _problem_ctx(title='A', import_dir='.problems/A/', import_file='statement'),
            _problem_ctx(title='B', import_dir='.problems/B/', import_file='statement'),
        ]
        kwargs = context.contest_jinja_kwargs(
            lang='en',
            languages=_langs(),
            contest=_contest_ctx(vars={'year': 2026}, params={'cover': True}),
            problems=problems,
        )
        assert kwargs['contest']['title'] == 'My Contest'
        assert kwargs['contest']['vars']['year'] == 2026
        # For a contest render, params is the contest statement's own params.
        assert kwargs['params']['cover'] is True
        assert [p['title'] for p in kwargs['problems']] == ['A', 'B']
        assert kwargs['problems'][0]['import_dir'] == '.problems/A/'

    def test_keyed_languages_present(self):
        kwargs = context.contest_jinja_kwargs(
            lang='en',
            languages=_langs(),
            contest=_contest_ctx(),
            problems=[],
        )
        assert 'cpp' in kwargs['keyed_languages']
