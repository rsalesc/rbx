"""Status of a single command in a `rbxCommandApp` pane.

Lives in its own module because both the app (`command_app.py`) and the run
history it persists (`run_history.py`) need it, and the app imports the history.
"""

import enum


class CommandStatus(enum.Enum):
    PENDING = 'pending'
    RUNNING = 'running'
    SUCCESS = 'success'
    FAILED = 'failed'
    SKIPPED = 'skipped'
    # Was running when the app went away. Its output was dumped on the way out,
    # but it never reported an exit code, so it is neither a success nor a
    # failure -- only a candidate for resuming.
    INTERRUPTED = 'interrupted'


STATUS_MARKUP = {
    CommandStatus.PENDING: '[dim]○[/dim]',
    CommandStatus.RUNNING: '[yellow]●[/yellow]',
    CommandStatus.SUCCESS: '[green]✓[/green]',
    CommandStatus.FAILED: '[red]✗[/red]',
    CommandStatus.SKIPPED: '[dim]⊘[/dim]',
    CommandStatus.INTERRUPTED: '[yellow]⚡[/yellow]',
}

STATUS_ICON = {
    CommandStatus.PENDING: '○',
    CommandStatus.RUNNING: '●',
    CommandStatus.SUCCESS: '✓',
    CommandStatus.FAILED: '✗',
    CommandStatus.SKIPPED: '⊘',
    CommandStatus.INTERRUPTED: '⚡',
}

FINISHED_STATUSES = (
    CommandStatus.SUCCESS,
    CommandStatus.FAILED,
    CommandStatus.SKIPPED,
    CommandStatus.INTERRUPTED,
)

# Order in which a tab's aggregate status is decided: the first one present wins.
AGGREGATE_PRECEDENCE = (
    CommandStatus.FAILED,
    CommandStatus.INTERRUPTED,
    CommandStatus.SKIPPED,
    CommandStatus.RUNNING,
    CommandStatus.PENDING,
)


def is_resumable(status: CommandStatus) -> bool:
    """Should `resume` re-queue a command in this state?

    Everything that did not succeed, `FAILED` included -- you resume precisely
    because you fixed what failed, so starting after the failure point would
    skip the command you wanted re-run.
    """
    return status is not CommandStatus.SUCCESS


def on_load(status: CommandStatus) -> CommandStatus:
    """Map a persisted status to what it means once the run is reopened.

    Nothing is executing when a run is loaded, so neither `RUNNING` nor
    `PENDING` can survive as-is: they would leave a tab reporting itself busy
    forever. Both become terminal, but stay distinguishable -- an interrupted
    command has (partial) output on disk, a skipped one never started.
    """
    if status is CommandStatus.RUNNING:
        return CommandStatus.INTERRUPTED
    if status is CommandStatus.PENDING:
        return CommandStatus.SKIPPED
    return status
