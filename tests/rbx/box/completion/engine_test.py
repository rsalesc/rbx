import sys

from rbx.box.completion import registry
from rbx.box.completion._spec import SPEC
from rbx.box.completion.engine import resolve
from tests.rbx.box.completion.golden import typer_completions


def _values(items):
    return [i.value for i in items]


# ---------------------------------------------------------------------------
# A) Command-name completion offers each alias as its own candidate (so a typed
#    prefix completes to a single concrete name, never the raw 'name, alias').
# ---------------------------------------------------------------------------


def test_root_command_names_split_aliases():
    values = _values(resolve(SPEC, [], ''))
    # Canonical names AND their aliases appear as separate candidates...
    assert 'build' in values
    assert 'b' in values
    assert 'package' in values
    assert 'pkg' in values
    # ...and the unusable comma-joined string is never emitted.
    assert 'build, b' not in values
    assert 'package, pkg' not in values


def test_root_prefix_pac_completes_to_single_name():
    assert _values(resolve(SPEC, [], 'pac')) == ['package']


def test_root_prefix_pkg_completes_via_alias():
    # An improvement over Typer: Typer offered the raw 'package, pkg', so a 'pkg'
    # prefix matched nothing; we complete the alias to a single concrete name.
    assert _values(resolve(SPEC, [], 'pkg')) == ['pkg']


def test_ambiguous_alias_dedups_to_first_in_registration_order():
    # 't' is registered by both 'time, t' and 'testcases, tc, t'; descent resolves
    # it to the first (time), so the completion list must contain 't' exactly once.
    values = _values(resolve(SPEC, [], 't'))
    assert values.count('t') == 1


def test_package_group_children_via_canonical_and_alias():
    canonical = _values(resolve(SPEC, ['package'], ''))
    assert 'polygon' in canonical
    assert 'pkg' in canonical
    # Descending via the alias 'pkg' yields the SAME children set.
    alias = _values(resolve(SPEC, ['pkg'], ''))
    assert set(alias) == set(canonical)


def test_package_polygon_option_name_completion():
    assert _values(resolve(SPEC, ['package', 'polygon'], '--la')) == ['--language']


# ---------------------------------------------------------------------------
# B) Option/value completion still matches the golden Typer oracle exactly.
#    (Command-name completion intentionally diverges -- see differential_test.)
# ---------------------------------------------------------------------------


def test_golden_parity_package_polygon_option():
    ours = sorted(i.value for i in resolve(SPEC, ['package', 'polygon'], '--la'))
    golden = sorted(i.value for i in typer_completions(['package', 'polygon'], '--la'))
    assert ours == golden


# ---------------------------------------------------------------------------
# C) Synthetic specs exercising the value-kind resolution paths.
# ---------------------------------------------------------------------------


def _leaf(params):
    return {
        'name': 'root',
        'help': None,
        'panel': None,
        'is_group': False,
        'params': params,
    }


def test_choice_value_after_option():
    spec = _leaf(
        [
            {
                'kind': 'option',
                'names': ['--fmt'],
                'takes_value': True,
                'help': None,
                'value': {'kind': 'choice', 'choices': ['pdf', 'png', 'ps']},
            }
        ]
    )
    # After consuming --fmt, completing its value filters the choices.
    items = resolve(spec, ['--fmt'], 'p')
    assert _values(items) == ['pdf', 'png', 'ps']
    items = resolve(spec, ['--fmt'], 'pn')
    assert _values(items) == ['png']


def test_completer_value_is_lazily_loaded_and_invoked():
    module_name = 'tests.rbx.box.completion._fixture_completer'
    # Ensure a clean slate so we can assert the lazy import happens on resolve().
    sys.modules.pop(module_name, None)
    registry.register_completer_path('engine_demo', f'{module_name}:fixture_completer')
    assert module_name not in sys.modules

    spec = _leaf(
        [
            {
                'kind': 'argument',
                'names': [],
                'takes_value': True,
                'help': None,
                'value': {'kind': 'completer', 'completer': 'engine_demo'},
            }
        ]
    )
    items = resolve(spec, [], '')
    assert _values(items) == ['from-fixture']
    # Resolving triggered the lazy import of the completer's module.
    assert module_name in sys.modules


def test_none_value_kind_yields_file_directive():
    spec = _leaf(
        [
            {
                'kind': 'argument',
                'names': [],
                'takes_value': True,
                'help': None,
                'value': {'kind': 'none'},
            }
        ]
    )
    items = resolve(spec, [], '')
    assert len(items) == 1
    assert items[0].value == ''
    assert items[0].type == 'file'


def test_path_dir_value_kind_yields_dir_directive():
    spec = _leaf(
        [
            {
                'kind': 'argument',
                'names': [],
                'takes_value': True,
                'help': None,
                'value': {'kind': 'path', 'path': 'dir'},
            }
        ]
    )
    items = resolve(spec, [], '')
    assert len(items) == 1
    assert items[0].type == 'dir'


def test_positional_beyond_last_argument_yields_file_directive():
    spec = _leaf(
        [
            {
                'kind': 'argument',
                'names': [],
                'takes_value': True,
                'help': None,
                'value': {'kind': 'none'},
            }
        ]
    )
    # One argument defined, but two positionals already consumed.
    items = resolve(spec, ['first', 'second'], '')
    assert len(items) == 1
    assert items[0].type == 'file'


def test_malformed_spec_swallows_exception_and_returns_file_directive():
    # Missing 'params'/'children' keys -> resolver must degrade, not raise.
    items = resolve({'name': 'broken'}, ['x'], '')
    assert len(items) == 1
    assert items[0].type == 'file'


def test_completer_with_file_flag_appends_file_directive():
    module_name = 'tests.rbx.box.completion._fixture_completer'
    registry.register_completer_path('engine_fu', f'{module_name}:fixture_completer')
    spec = _leaf(
        [
            {
                'kind': 'argument',
                'names': [],
                'takes_value': True,
                'help': None,
                'variadic': True,
                'value': {
                    'kind': 'completer',
                    'completer': 'engine_fu',
                    'file': 'file',
                },
            }
        ]
    )
    items = resolve(spec, [], '')
    assert _values(items) == ['from-fixture', '']
    assert items[-1].type == 'file'


def test_variadic_argument_reoffered_on_later_positionals():
    module_name = 'tests.rbx.box.completion._fixture_completer'
    registry.register_completer_path('engine_fu2', f'{module_name}:fixture_completer')
    spec = _leaf(
        [
            {
                'kind': 'argument',
                'names': [],
                'takes_value': True,
                'help': None,
                'variadic': True,
                'value': {'kind': 'completer', 'completer': 'engine_fu2'},
            }
        ]
    )
    # Two positionals already consumed, but the (only) argument is variadic, so
    # the completer is still offered.
    items = resolve(spec, ['a', 'b'], '')
    assert _values(items) == ['from-fixture']


def test_zsh_source_adds_candidates_before_file_completion():
    # File-union: dynamic candidates (e.g. solutions) must be added BEFORE the
    # `_path_files` handoff so they rank ahead of the directory listing in the
    # zsh menu (issue #575 follow-up: "solutions first").
    from rbx.box.completion.engine import source_to_string

    src = source_to_string('zsh')
    assert 'compadd' in src and '_path_files' in src
    assert src.index('compadd') < src.index('_path_files'), (
        'zsh source must add candidates before _path_files'
    )
    # The file/dir handoff is deferred via flags rather than called in the parse loop.
    assert 'want_files' in src
    # Described candidates use `compadd -d` (order-preserving), NOT `_describe`
    # (which re-sorts items that share a description, e.g. several "ACCEPTED").
    assert '_describe' not in src
    assert '-d desc_displays' in src


def test_completer_values_are_prefix_filtered_by_incomplete():
    from click.shell_completion import CompletionItem

    from rbx.box.completion.registry import register_completer

    @register_completer('engine_prefix_demo')
    def _c(ctx, incomplete):  # registered as a live object (defined in <locals>)
        return [
            CompletionItem('@main'),
            CompletionItem('@boca/'),
            CompletionItem('sols/a.cpp'),
        ]

    spec = _leaf(
        [
            {
                'kind': 'argument',
                'names': [],
                'takes_value': True,
                'help': None,
                'value': {'kind': 'completer', 'completer': 'engine_prefix_demo'},
            }
        ]
    )
    # Empty incomplete -> all candidates, in order.
    assert _values(resolve(spec, [], '')) == ['@main', '@boca/', 'sols/a.cpp']
    # Typing a prefix narrows to the matching candidate(s).
    assert _values(resolve(spec, [], '@m')) == ['@main']
    assert _values(resolve(spec, [], 'sols/')) == ['sols/a.cpp']
