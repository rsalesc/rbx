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
