"""The runner names, and nothing else.

A leaf module **with no imports at all**, because two very different places need
these names and one of them is the shell-completion fast path: every TAB press
loads `completion/completers.py`, and anything it imports is latency a setter
feels. `runners/registry.py` cannot be that import -- it names `RbxException`,
which pulls `rbx.console` and therefore `rich` (~36ms measured, roughly doubling
TAB latency), and that is before the lazy backend imports it exists to defer.

So the names live here, where importing them costs nothing, and the registry and
the completer both read the same tuple. There is no second copy to drift.
"""

# What `--runner` defaults to, and what every caller that passes nothing gets.
# `run_solutions` itself falls back to `LocalRunner` when handed no runner at
# all, so this name and that fallback have to keep saying the same thing.
DEFAULT_RUNNER = 'local'

# (name, one-line description). The description is what shell completion offers
# beside the name, so it has to read as an answer to "where does this run?".
#
# A table rather than a bare list because both readers want both halves: the CLI
# names the valid ones when it refuses an unknown one, and the completer shows
# them. Kept next to `registry._FACTORIES` in spirit -- a backend added without a
# description is a visible omission there rather than a nameless entry here.
RUNNERS = (
    ('local', 'Run the solutions in the sandbox on this machine.'),
    ('moj', 'Run the solutions on the MOJ judge park, through the `moj` CLI.'),
)


def runner_names():
    """Just the names, in table order. What an error message lists, and what the
    `--runner` help text spells out -- neither of which may hard-code them."""
    return tuple(name for name, _ in RUNNERS)
