# tests/rbx/box/completion/_fixture_completer.py
from click.shell_completion import CompletionItem

from rbx.box.completion.registry import register_completer


@register_completer('fixture_demo')
def fixture_completer(ctx, incomplete):
    return [CompletionItem('from-fixture')]
