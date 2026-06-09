import pytest

from rbx.box.completion import _spec, engine
from tests.rbx.box.completion.corpus import command_lines
from tests.rbx.box.completion.golden import typer_completions

_DIRECTIVES = {('', 'file'), ('', 'dir')}


def _pairs(items):
    return sorted((i.value, i.type) for i in items)


@pytest.mark.parametrize('args,incomplete', command_lines(_spec.SPEC))
def test_engine_matches_typer(args, incomplete):
    ours = _pairs(engine.resolve(_spec.SPEC, args, incomplete))
    gold = _pairs(typer_completions(args, incomplete))
    if gold:
        # Where Typer produces completions, we must match EXACTLY.
        assert ours == gold, f'args={args} inc={incomplete!r}: ours={ours} gold={gold}'
    else:
        # Allowed divergence: where Typer is empty, we may be empty OR hand off to
        # the shell's default file/dir completion.
        assert ours == [] or set(ours) <= _DIRECTIVES, (
            f'args={args} inc={incomplete!r}: ours={ours} (expected empty or file/dir directive)'
        )
