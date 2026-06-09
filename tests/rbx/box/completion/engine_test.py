import sys

from rbx.box.completion import registry
from rbx.box.completion._spec import SPEC
from rbx.box.completion.engine import resolve
from tests.rbx.box.completion.golden import typer_completions


def _values(items):
    return [i.value for i in items]


# ---------------------------------------------------------------------------
# A) Mini-differential against the real committed spec (values only).
# ---------------------------------------------------------------------------


def test_root_command_names_include_known_groups():
    values = _values(resolve(SPEC, [], ''))
    assert 'build, b' in values
    assert 'package, pkg' in values


def test_root_prefix_pac_matches_package_group():
    assert _values(resolve(SPEC, [], 'pac')) == ['package, pkg']


def test_root_prefix_pkg_matches_nothing():
    # The raw name 'package, pkg' does not START with 'pkg', so prefix filter
    # on the raw string yields nothing -- matching Typer.
    assert _values(resolve(SPEC, [], 'pkg')) == []


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
# B) Direct cross-check against the golden Typer oracle (non-empty cases).
# ---------------------------------------------------------------------------


def _assert_matches_golden(args, incomplete):
    ours = sorted(i.value for i in resolve(SPEC, args, incomplete))
    golden = sorted(i.value for i in typer_completions(args, incomplete))
    assert ours == golden


def test_golden_parity_root_prefix():
    _assert_matches_golden([], 'pac')


def test_golden_parity_package_children():
    _assert_matches_golden(['package'], '')


def test_golden_parity_package_polygon_option():
    _assert_matches_golden(['package', 'polygon'], '--la')


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
