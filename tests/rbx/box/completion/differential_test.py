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
    diverges from Typer (it offers ONE deduped candidate per command, not Typer's
    comma-joined string), so we check it against a spec-derived expectation
    instead of the Typer oracle."""
    node, _command, _opts, pending, _positional, _seen = _walk(_spec.SPEC, list(args))
    return (
        pending is None
        and not incomplete.startswith('-')
        and bool(node.get('is_group'))
    )


def _is_option_name_position(args, incomplete):
    """True when the cursor completes an option NAME (not its value). Here the
    engine intentionally dedupes aliases to ONE candidate per option."""
    node, _command, _opts, pending, _positional, _seen = _walk(_spec.SPEC, list(args))
    if pending is not None or not incomplete.startswith('-'):
        return False
    if '=' in incomplete:
        name = incomplete.split('=', 1)[0]
        for p in node['params']:
            if p['kind'] == 'option' and name in p['names'] and p['takes_value']:
                return False  # completing `--opt=<value>`, not a name
    return True


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
        # Stripping directives is safe because the dynamic completers only ever
        # emit `plain` items with non-empty values -- never directive-shaped
        # (empty value + file/dir type) candidates that this would mask.
        non_dir = [p for p in ours if p not in _DIRECTIVES]
        assert non_dir == gold, f'args={args} inc={incomplete!r}: {non_dir} vs {gold}'
        assert set(ours) & _DIRECTIVES, (
            f'args={args} inc={incomplete!r}: no file directive'
        )
        return

    if _is_command_name_position(args, incomplete):
        # Command-name completion: ONE deduped candidate per command (not one per
        # alias). `_command_name_items` IS the engine's own helper, so this asserts
        # the node it resolved to yields exactly those names. Cross-check against
        # Typer: every name we offer is a REAL Typer command name (we never invent
        # one), though we intentionally offer FEWER (deduped) than Typer's aliases.
        node, *_ = _walk(_spec.SPEC, list(args))
        expected = _pairs(_command_name_items(node, incomplete))
        assert ours == expected, f'args={args} inc={incomplete!r}: ours={ours}'

        typer_names = set()
        for value, _t in _pairs(typer_completions(args, incomplete)):
            for name in _match_names(value):
                if name.startswith(incomplete):
                    typer_names.add(name)
        ours_names = {v for v, _t in ours}
        assert ours_names <= typer_names, (
            f'args={args} inc={incomplete!r}: invented names {ours_names - typer_names}'
        )
        return

    if _is_option_name_position(args, incomplete):
        # Option-name completion: ONE deduped candidate per option (not Typer's
        # every-alias). Verify against Typer that (a) we never invent a name,
        # (b) every name starts with the incomplete, and (c) for each option Typer
        # would offer we show EXACTLY one name -- its first matching (canonical)
        # alias -- and none for options Typer drops (e.g. already-supplied).
        node, *_ = _walk(_spec.SPEC, list(args))
        gold = {v for v, _t in _pairs(typer_completions(args, incomplete))}
        ours_vals = [v for v, _t in ours]
        assert set(ours_vals) <= gold, (
            f'args={args} inc={incomplete!r}: invented option names {set(ours_vals) - gold}'
        )
        assert all(v.startswith(incomplete) for v in ours_vals)
        for p in node['params']:
            if p['kind'] != 'option':
                continue
            p_gold = [n for n in p['names'] if n in gold]
            p_ours = [v for v in ours_vals if v in p['names']]
            if p_gold:
                assert p_ours == [p_gold[0]], (
                    f'args={args} inc={incomplete!r}: option {p["names"]} -> {p_ours}, '
                    f'expected [{p_gold[0]!r}] (one deduped candidate)'
                )
            else:
                assert not p_ours, (
                    f'args={args} inc={incomplete!r}: option {p["names"]} shown but Typer drops it'
                )
        return

    # Everywhere else (option values, positional values) the engine must match
    # Typer EXACTLY (only NAME completion is deduped, never values).
    gold = _pairs(typer_completions(args, incomplete))
    if gold:
        assert ours == gold, f'args={args} inc={incomplete!r}: ours={ours} gold={gold}'
    else:
        # Allowed divergence: where Typer is empty, we may be empty OR hand off to
        # the shell's default file/dir completion.
        assert ours == [] or set(ours) <= _DIRECTIVES, (
            f'args={args} inc={incomplete!r}: ours={ours} (expected empty or file/dir directive)'
        )
