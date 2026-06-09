import sys

from click.shell_completion import CompletionItem

from rbx.box.completion import registry


def test_register_and_load_roundtrip():
    @registry.register_completer('dummy_xyz')
    def _c(ctx, incomplete):
        return [CompletionItem('hello')]

    loaded = registry.load_completer('dummy_xyz')
    items = loaded(
        registry.CompletionContext(
            args=[], command=(), option_values={}, package_root=None
        ),
        '',
    )
    assert [i.value for i in items] == ['hello']


def test_reverse_lookup_by_function():
    @registry.register_completer('dummy_rev')
    def _c(ctx, incomplete):
        return []

    assert registry.key_for_function(_c) == 'dummy_rev'


def test_load_completer_is_lazy():
    # Registering by dotted path must NOT import the target module eagerly.
    registry.register_completer_path(
        'lazy_demo', 'rbx.box.completion._never_imported:fn'
    )
    assert 'rbx.box.completion._never_imported' not in sys.modules


def test_module_level_completer_stored_as_dotted_path():
    from tests.rbx.box.completion import _fixture_completer as fixture_module

    # A module-level completer is stored as an importable dotted path, not a
    # live callable, so load_completer stays lazy and import-order independent.
    assert (
        registry._REGISTRY['fixture_demo']  # noqa: SLF001
        == 'tests.rbx.box.completion._fixture_completer:fixture_completer'
    )

    loaded = registry.load_completer('fixture_demo')
    items = loaded(
        registry.CompletionContext(
            args=[], command=(), option_values={}, package_root=None
        ),
        '',
    )
    assert [i.value for i in items] == ['from-fixture']

    assert registry.key_for_function(fixture_module.fixture_completer) == 'fixture_demo'
