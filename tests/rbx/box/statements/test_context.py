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

    def test_group_var_shorthand_resolves_the_group_set(self):
        groups = _group_views()

        # The override wins through the shorthand...
        assert groups['sub2'].AB['min'] == 100
        # ...and inherited keys still resolve, exactly as g.vars does.
        assert groups['sub2'].AB['max'] == 200
        assert groups['sub1'].AB['max'] == 10

    def test_model_fields_win_over_shorthand(self):
        # The schema rejects a var named `score`; the view must not depend on it.
        from rbx.box.schema import TestcaseGroup

        view = GroupView(TestcaseGroup(name='sub1', score=40), {'score': 999})

        assert view.score == 40

    def test_unknown_group_attribute_keeps_the_var_hint(self):
        groups = _group_views()

        with pytest.raises(jinja2.UndefinedError) as exc_info:
            str(groups['sub2'].NOPE)
        message = str(exc_info.value)
        assert 'NOPE' in message
        assert 'groups.sub2.vars' in message


class TestVarShorthand:
    """`\\VAR{N.max}` is shorthand for `\\VAR{vars.N.max}` (#630)."""

    def test_problem_root_binds_var_keys_directly(self):
        kwargs = context.problem_jinja_kwargs(
            lang='en',
            languages=_langs(),
            problem=_problem_ctx(vars={'N.max': 100, 'MAXV': 7}),
            contest=_contest_ctx(),
        )

        assert kwargs['N']['max'] == 100
        assert kwargs['MAXV'] == 7
        # The long form keeps working.
        assert kwargs['vars']['N']['max'] == 100

    def test_contest_root_binds_var_keys_directly(self):
        kwargs = context.contest_jinja_kwargs(
            lang='en',
            languages=_langs(),
            contest=_contest_ctx(vars={'year': 2026}),
            problems=[],
        )

        assert kwargs['year'] == 2026
        assert kwargs['vars']['year'] == 2026

    def test_real_root_names_win_over_vars(self):
        # The schema rejects this, but the merge must not depend on that.
        kwargs = context.problem_jinja_kwargs(
            lang='en',
            languages=_langs(),
            problem=_problem_ctx(vars={'lang': 'nope'}),
            contest=_contest_ctx(),
        )

        assert kwargs['lang'] == 'en'

    def test_shorthand_miss_keeps_the_var_hint(self):
        kwargs = context.problem_jinja_kwargs(
            lang='en',
            languages=_langs(),
            problem=_problem_ctx(vars={'N.max': 100}),
            contest=_contest_ctx(),
        )

        with pytest.raises(jinja2.UndefinedError) as exc_info:
            str(kwargs['N']['mim'])
        message = str(exc_info.value)
        assert 'N.mim' in message
        assert 'vars' in message

    def test_problem_namespace_binds_var_keys(self):
        ns = _problem_ctx(vars={'N.max': 100}).namespace()

        assert ns['N']['max'] == 100
        assert ns['vars']['N']['max'] == 100

    def test_contest_namespace_binds_var_keys(self):
        ns = _contest_ctx(vars={'year': 2026}).namespace()

        assert ns['year'] == 2026
        assert ns['vars']['year'] == 2026

    def test_join_member_problems_bind_var_keys(self):
        kwargs = context.contest_jinja_kwargs(
            lang='en',
            languages=_langs(),
            contest=_contest_ctx(),
            problems=[_problem_ctx(vars={'N.max': 100})],
        )

        assert kwargs['problems'][0]['N']['max'] == 100

    def test_real_namespace_names_win_in_problem(self):
        ns = _problem_ctx(title='Real', vars={'title': 'nope'}).namespace()

        assert ns['title'] == 'Real'

    def test_contest_metadata_vars_reach_the_contest_namespace(self):
        # `date`/`location` used to be dedicated ContestStatement fields that
        # nothing read; they are ordinary contest vars now, and the shorthand
        # gives them the spelling the fields would have had.
        ns = _contest_ctx(
            vars={'date': '2026-06-21', 'location': 'Campinas'}
        ).namespace()

        assert ns['date'] == '2026-06-21'
        assert ns['location'] == 'Campinas'

    def test_contest_namespace_hint_still_names_contest_vars(self):
        ns = _contest_ctx(vars={'year': 2026}).namespace()

        with pytest.raises(jinja2.UndefinedError) as exc_info:
            str(ns['vars']['yaer'])
        assert 'contest.vars' in str(exc_info.value)


class TestReservedListCoversTheNamespaceSurface:
    """RESERVED_STATEMENT_VAR_NAMES is hand-written; this proves it still covers
    every name a var could shadow. If this fails, add the new key to the
    frozenset in rbx/box/fields.py (and to the docs table)."""

    def _surface(self):
        from rbx.box.schema import TestcaseGroup

        problem_kwargs = context.problem_jinja_kwargs(
            lang='en',
            languages=_langs(),
            problem=_problem_ctx(vars={}),
            contest=_contest_ctx(vars={}),
        )
        contest_kwargs = context.contest_jinja_kwargs(
            lang='en',
            languages=_langs(),
            contest=_contest_ctx(vars={}),
            problems=[],
        )
        problem_ns = _problem_ctx(
            vars={},
            short_name='A',
            import_dir='.problems/A',
            import_file='statement.tex',
            blocks={'legend': 'x'},
        ).namespace()
        contest_ns = _contest_ctx(vars={}, blocks={'foo': 'x'}).namespace()
        return (
            set(problem_kwargs)
            | set(contest_kwargs)
            | set(problem_ns)
            | set(contest_ns)
            | set(TestcaseGroup.model_fields)
        )

    def test_every_namespace_key_is_reserved(self):
        from rbx.box.fields import RESERVED_STATEMENT_VAR_NAMES

        surface = self._surface()

        assert surface <= RESERVED_STATEMENT_VAR_NAMES, (
            f'unreserved template names: {sorted(surface - RESERVED_STATEMENT_VAR_NAMES)}'
        )

    def test_no_stale_reservations(self):
        # The other direction, so the list does not accumulate dead names.
        from rbx.box.fields import RESERVED_STATEMENT_VAR_NAMES

        surface = self._surface()

        assert RESERVED_STATEMENT_VAR_NAMES <= surface, (
            'reserved but no longer exposed: '
            f'{sorted(RESERVED_STATEMENT_VAR_NAMES - surface)}'
        )
