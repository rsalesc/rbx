import pytest

from rbx.box.completion import _spec, engine
from rbx.box.completion.engine import _command_name_items, _match_names, _walk
from tests.rbx.box.completion.corpus import command_lines
from tests.rbx.box.completion.golden import typer_completions

_DIRECTIVES = {('', 'file'), ('', 'dir')}


def _pairs(items):
    return sorted((i.value, i.type) for i in items)


def _is_command_name_position(args, incomplete):
    """True when the cursor completes a subcommand NAME (a group node, not an
    option or an option value). At those positions the engine intentionally
    diverges from Typer (it splits 'name, alias' into separate candidates), so we
    check it against a spec-derived expectation instead of the Typer oracle."""
    node, _command, _opts, pending, _positional, _seen = _walk(_spec.SPEC, list(args))
    return (
        pending is None
        and not incomplete.startswith('-')
        and bool(node.get('is_group'))
    )


def _cursor_value(args, incomplete):
    """The spec 'value' dict the cursor is completing, or None (option-name,
    group, or past-the-end position)."""
    node, _cmd, _opts, pending, positional, _seen = _walk(_spec.SPEC, list(args))
    if pending is not None:
        return pending['value']
    if incomplete.startswith('-') and '=' in incomplete:
        name = incomplete.split('=', 1)[0]
        for p in node['params']:
            if p['kind'] == 'option' and name in p['names'] and p['takes_value']:
                return p['value']
        return None
    if incomplete.startswith('-') or node.get('is_group'):
        return None
    arguments = [p for p in node['params'] if p['kind'] == 'argument']
    if positional < len(arguments):
        return arguments[positional]['value']
    if arguments and arguments[-1].get('variadic'):
        return arguments[-1]['value']
    return None


@pytest.mark.parametrize('args,incomplete', command_lines(_spec.SPEC))
def test_engine_matches_typer(args, incomplete):
    ours = _pairs(engine.resolve(_spec.SPEC, args, incomplete))

    value = _cursor_value(args, incomplete)
    if value is not None and value.get('kind') == 'completer' and value.get('file'):
        # File-union: the engine intentionally appends a shell file/dir directive
        # that Typer's callback contract can never emit. Assert the dynamic part
        # matches Typer exactly and that the directive IS appended.
        gold = _pairs(typer_completions(args, incomplete))
        non_dir = [p for p in ours if p not in _DIRECTIVES]
        assert non_dir == gold, f'args={args} inc={incomplete!r}: {non_dir} vs {gold}'
        assert set(ours) & _DIRECTIVES, (
            f'args={args} inc={incomplete!r}: no file directive'
        )
        return

    if _is_command_name_position(args, incomplete):
        # Command-name completion: each alias is its own prefix-filtered candidate.
        # `_command_name_items` IS the engine's own helper, so this asserts the
        # node it resolved to yields exactly those names -- and, as a cross-check,
        # that every name the real CLI would offer (its comma-joined values, split)
        # is covered.
        node, *_ = _walk(_spec.SPEC, list(args))
        expected = _pairs(_command_name_items(node, incomplete))
        assert ours == expected, f'args={args} inc={incomplete!r}: ours={ours}'

        typer_names = set()
        for value, _t in _pairs(typer_completions(args, incomplete)):
            for name in _match_names(value):
                if name.startswith(incomplete):
                    typer_names.add((name, 'plain'))
        assert typer_names <= set(ours), (
            f'args={args} inc={incomplete!r}: missing Typer commands {typer_names - set(ours)}'
        )
        return

    # Everywhere else (option names, option values, positional values) the engine
    # must match Typer EXACTLY.
    gold = _pairs(typer_completions(args, incomplete))
    if gold:
        assert ours == gold, f'args={args} inc={incomplete!r}: ours={ours} gold={gold}'
    else:
        # Allowed divergence: where Typer is empty, we may be empty OR hand off to
        # the shell's default file/dir completion.
        assert ours == [] or set(ours) <= _DIRECTIVES, (
            f'args={args} inc={incomplete!r}: ours={ours} (expected empty or file/dir directive)'
        )
