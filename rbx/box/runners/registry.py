"""Which backend a command runs its solutions on, by name.

The name comes from `rbx time --runner <name>`. A *flag*, and deliberately not
the limits profile: a profile is just the `limits/<name>.yml` file `rbx time`
writes, so letting its name pick a backend would couple an output to a transport
-- and would leave no way to estimate MOJ limits from a local machine, which is
exactly what a setter without judge access has to be able to do.

The design also sketches an `env.rbx.yml` `runners:`/`profiles:` block that would
configure backends and give a profile a default one. It is **not** built here: no
backend has a knob worth configuring yet (`MAX_INFLIGHT_TESTRUNS` is a constant
precisely because a value nobody can reach is a value nobody has tested), and a
config surface invented ahead of its first user is a compatibility promise made
about guesses. The flag is the whole surface until something needs more.

Every backend is imported **lazily**, inside `get_runner`. Naming a backend must
not cost the import of everything it talks to: `runners.moj.runner` pulls in the
packager, the MOJ CLI wrapper and the environment, and a run on the local sandbox
-- which is every run today -- has no business paying for that.
"""

from typing import TYPE_CHECKING, Callable, Dict

from rbx.box.exception import RbxException
from rbx.box.runners.names import DEFAULT_RUNNER, RUNNERS, runner_names

if TYPE_CHECKING:
    from rbx.box.runners.base import SolutionRunner

# Re-exported so the names and the factories read as one module from the outside;
# they live in `names.py` only because shell completion cannot afford this
# module's imports. See that module.
__all__ = [
    'DEFAULT_RUNNER',
    'RUNNERS',
    'UnknownRunnerError',
    'get_runner',
    'runner_names',
]


class UnknownRunnerError(RbxException):
    """`--runner` named a backend that does not exist.

    Message is **plain text with backticks**, never rich markup: `main.py`
    prints an `RbxException` with a bare builtin `print`, so `[item]` tags would
    reach the setter literally.
    """

    def __init__(self, message: str):
        super().__init__()
        self.message = message
        self.msg.append(message)


def _local() -> 'SolutionRunner':
    from rbx.box.runners.local import LocalRunner

    return LocalRunner()


def _moj() -> 'SolutionRunner':
    from rbx.box.runners.moj.runner import MojRunner

    return MojRunner()


_FACTORIES: Dict[str, Callable[[], 'SolutionRunner']] = {
    'local': _local,
    'moj': _moj,
}


def get_runner(name: str) -> 'SolutionRunner':
    """The backend called `name`, freshly constructed.

    A new instance per call, never a shared one: a runner holds a whole run's
    state (`MojRunner` keeps the remote problem id, the packager and every
    testrun it dispatched), so handing two runs the same object would let the
    first one's leftovers decide the second one's behaviour.
    """
    factory = _FACTORIES.get(name)
    if factory is None:
        listed = ', '.join(f'`{known}`' for known in runner_names())
        raise UnknownRunnerError(
            f'There is no runner called `{name}`. The runners rbx knows are: {listed}.'
        )
    return factory()
