"""`RunProgress`: the slot each backend says what it is doing in.

The board exists because the two ends cannot be wired together directly -- the
reporter is built from a `RunSolutionResult`, so it does not exist yet when
`run_solutions` hands the backend its `RunContext`. What is pinned here is the
shape that makes a *pull* reader safe: whole-line writes, immutable reads, and an
unwritten solution reading back empty rather than raising.
"""

from rbx.box.runners.base import RunnerChip, RunProgress


def test_an_unwritten_solution_reads_back_empty():
    """A backend that never writes -- `LocalRunner` -- costs the reader nothing.

    Empty rather than `None`, so the reporter can iterate the result without a
    guard at the one place that reads it.
    """
    board = RunProgress()

    assert board.get('sols/never-written.cpp') == ()


def test_set_replaces_the_whole_line_rather_than_appending():
    """A backend says what is true *now*; it does not accumulate.

    Half a solution's state from one moment beside half from another is exactly
    the kind of line that reads as a bug in whatever it describes -- a `queued`
    chip still sitting beside a `done` one.
    """
    board = RunProgress()

    board.set('sol.cpp', RunnerChip('moj rbxt-a1b2'), RunnerChip('queued'))
    board.set('sol.cpp', RunnerChip('moj rbxt-a1b2'), RunnerChip('done'))

    assert [chip.text for chip in board.get('sol.cpp')] == ['moj rbxt-a1b2', 'done']


def test_slots_are_per_solution():
    """The point of the board: a poll writes where nobody else is reading.

    Up to `MAX_INFLIGHT_TESTRUNS` background tasks write at once while the
    reporter reads exactly one slot, so a write for a solution the report has not
    reached must not disturb the one it is drawing.
    """
    board = RunProgress()

    board.set('first.cpp', RunnerChip('running'))
    board.set('second.cpp', RunnerChip('queued'))

    assert [chip.text for chip in board.get('first.cpp')] == ['running']
    assert [chip.text for chip in board.get('second.cpp')] == ['queued']


def test_a_reader_cannot_be_handed_something_a_later_write_mutates():
    """Chips come back as a tuple, so a read is a snapshot.

    The reporter reads on one turn of the loop and renders on the same one, but a
    list handed out here would still be a live reference into the board -- and the
    backend writing between the two is the normal case, not a rare one.
    """
    board = RunProgress()
    board.set('sol.cpp', RunnerChip('queued'))

    held = board.get('sol.cpp')
    board.set('sol.cpp', RunnerChip('done'))

    assert [chip.text for chip in held] == ['queued']


def test_clearing_a_solution_leaves_the_others_alone():
    """A finished solution's slot is dropped once it has a real verdict to show.

    A stale `running` chip beside a finished verdict is worse than no chip at
    all -- but the solutions still in flight have to keep theirs.
    """
    board = RunProgress()
    board.set('first.cpp', RunnerChip('done'))
    board.set('second.cpp', RunnerChip('running'))

    board.clear('first.cpp')

    assert board.get('first.cpp') == ()
    assert [chip.text for chip in board.get('second.cpp')] == ['running']


def test_clearing_something_never_written_is_not_an_error():
    """`clear` runs on a path the consumer reached; nothing promises a write."""
    board = RunProgress()

    board.clear('sols/never-written.cpp')

    assert board.get('sols/never-written.cpp') == ()


def test_a_chip_defaults_to_the_dim_style():
    """Chips are annotations on a header, not the header. The backend opts in to
    anything louder -- MOJ colours `cached` and `done` green, nothing else."""
    assert RunnerChip('queued').style == 'bright_black'
    assert RunnerChip('cached', style='green').style == 'green'
