"""Resolving a `--runner` name to a backend.

The name is the whole selection surface (see `runners/registry.py`), so what it
resolves to, and what it does with a name it does not know, is what these pin.
"""

import pytest

from rbx.box.runners import registry
from rbx.box.runners.local import LocalRunner
from rbx.box.runners.moj.runner import MojRunner


def test_the_default_name_is_the_local_sandbox():
    """`--runner` defaults to this name, and `run_solutions` falls back to the
    same backend when handed no runner at all. The two must not drift."""
    assert registry.DEFAULT_RUNNER == 'local'
    assert isinstance(registry.get_runner(registry.DEFAULT_RUNNER), LocalRunner)


def test_moj_resolves_to_the_moj_runner():
    assert isinstance(registry.get_runner('moj'), MojRunner)


def test_every_named_runner_resolves():
    """A name offered by the table (and by shell completion) that no factory
    answers would be advertised and then refused."""
    for name in registry.runner_names():
        assert registry.get_runner(name).name == name


def test_each_call_builds_a_fresh_backend():
    """A runner holds a whole run's state -- `MojRunner` keeps the remote problem
    id, the packager and every testrun it dispatched -- so a shared instance would
    let one run's leftovers decide the next one's behaviour."""
    assert registry.get_runner('moj') is not registry.get_runner('moj')


def test_an_unknown_name_is_refused_naming_the_known_ones():
    """The message is the only place a setter can learn what to type instead.

    Asserted whole, because it is read by a human: `main.py` prints an
    `RbxException` with a bare builtin `print`, so rich markup would arrive as
    literal `[item]` tags.
    """
    with pytest.raises(registry.UnknownRunnerError) as exc:
        registry.get_runner('mog')

    assert str(exc.value) == (
        'There is no runner called `mog`. The runners rbx knows are: `local`, `moj`.'
    )


def test_the_completion_table_offers_exactly_the_runners_that_exist():
    """Shell completion carries its own copy of the names, to stay off the heavy
    imports the backends pull in. This is what keeps the copy honest."""
    from rbx.box.completion import completers

    assert completers._RUNNER_TABLE == registry.RUNNERS  # noqa: SLF001
