from rbx.box.completion import _spec, engine
from tests.rbx.box.completion.golden import typer_completions


def _find_language_option_path(spec):
    """Return (args, incomplete) that lands on a --language value position."""

    def walk(node, path):
        for p in node.get('params', []):
            if (
                p['kind'] == 'option'
                and '--language' in p['names']
                and p['value'].get('kind') == 'completer'
            ):
                return (path + ['--language'], '')
        for c in node.get('children', []):
            r = walk(c, path + [c['name'].split(',')[0].strip()])
            if r:
                return r
        return None

    return walk(spec, [])


def test_language_value_completes_and_matches_typer():
    pos = _find_language_option_path(_spec.SPEC)
    assert pos is not None, (
        'expected at least one --language option wired to the language completer'
    )
    args, inc = pos
    ours = sorted(i.value for i in engine.resolve(_spec.SPEC, args, inc))
    assert ours, 'engine returned no language completions'
    gold = sorted(i.value for i in typer_completions(args, inc))
    assert ours == gold, f'ours={ours} gold={gold}'
