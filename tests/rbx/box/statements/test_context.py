import jinja2
import pytest

from rbx.box.statements import context
from rbx.box.statements.context import (
    ContestRenderContext,
    GroupView,
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


def _group_views():
    """The three groups of the per-group-vars fixture, as the build sites wire them."""
    from rbx.box.schema import Package

    pkg = Package.model_validate(
        {
            'name': 'test',
            'timeLimit': 1000,
            'memoryLimit': 256,
            'scoring': 'points',
            'vars': {'AB': {'min': 1, 'max': 200}},
            'testcases': [
                {'name': 'sub1', 'score': 30, 'vars': {'AB': {'max': 10}}},
                {'name': 'sub2', 'score': 40, 'vars': {'AB': {'min': 100}}},
                {'name': 'sub3', 'score': 30},
            ],
        }
    )
    return {
        g.name: GroupView(g, pkg.expanded_vars_for_group(g.name)) for g in pkg.testcases
    }


class TestGroupViews:
    def test_group_vars_are_resolved_not_raw_overrides(self):
        groups = context.ProblemRenderContext(
            title='A', groups=_group_views()
        ).namespace()['groups']

        # The override wins...
        assert groups['sub2'].vars['AB']['min'] == 100
        # ...and every key the group did not override is inherited, rather than
        # rendering blank as a raw override block would.
        assert groups['sub2'].vars['AB']['max'] == 200
        assert groups['sub1'].vars['AB']['max'] == 10
        assert groups['sub1'].vars['AB']['min'] == 1
        # A group that overrides nothing still sees the full package var set.
        assert groups['sub3'].vars['AB']['min'] == 1
        assert groups['sub3'].vars['AB']['max'] == 200

    def test_view_vars_are_the_resolved_set(self):
        # The model's raw override for sub1 is only `{'AB': {'max': 10}}`, but
        # the view serves the resolved set it was constructed with.
        from rbx.box.schema import TestcaseGroup

        group = TestcaseGroup(name='sub1', vars={'AB': {'max': 10}})
        view = GroupView(group, {'AB.min': 1, 'AB.max': 10})
        assert dict(view.vars['AB']) == {'min': 1, 'max': 10}
        assert view.vars is not group.vars

    def test_repr_delegates_to_the_model(self):
        view = _group_views()['sub2']
        assert "name='sub2'" in repr(view)

    def test_model_attributes_pass_through(self):
        groups = _group_views()
        assert groups['sub2'].name == 'sub2'
        assert groups['sub2'].score == 40

    def test_dunder_probes_do_not_recurse(self):
        import copy

        view = _group_views()['sub1']
        with pytest.raises(AttributeError):
            view.__deepcopy__  # noqa: B018
        assert copy.copy(view) is not None

    def test_iteration_preserves_declaration_order(self):
        groups = context.ProblemRenderContext(
            title='A', groups=_group_views()
        ).namespace()['groups']
        assert [g.name for g in groups] == ['sub1', 'sub2', 'sub3']

    def test_missing_var_raises_strict_undefined_with_a_hint(self):
        groups = _group_views()
        undefined = groups['sub2'].vars['AB']['mim']
        with pytest.raises(jinja2.UndefinedError) as exc_info:
            str(undefined)
        message = str(exc_info.value)
        assert 'AB.mim' in message
        assert 'groups.sub2.vars' in message
