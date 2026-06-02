from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.output import DummyOutput

from rbx.box.timing_group_picker import GroupPickerState, prompt_group_assignment


def test_state_move_clamps():
    s = GroupPickerState(['a', 'b', 'c'], {})
    s.move(-1)
    assert s.cursor == 0
    s.move(1)
    s.move(1)
    s.move(1)
    s.move(1)
    assert s.cursor == 2


def test_state_set_group_and_assignment():
    s = GroupPickerState(['cpp', 'java'], {'cpp': 1})
    assert s.assignment() == {'cpp': 1, 'java': 0}
    s.move(1)
    s.set_group(2)
    assert s.assignment() == {'cpp': 1, 'java': 2}


def test_render_fragments_marks_cursor_and_numbers():
    s = GroupPickerState(['cpp', 'java'], {'cpp': 3})
    text = ''.join(t for _, t in s.render_fragments())
    assert '[3] cpp' in text
    assert '[ ] java' in text
    # the cursor pointer appears once for the selected (first) row
    assert text.count('❯') == 1


async def test_picker_assigns_and_confirms():
    with create_pipe_input() as inp:
        inp.send_text('2')  # set first lang (cpp) -> group 2
        inp.send_text('\x1b[B')  # down arrow -> cursor to java
        inp.send_text('2')  # set java -> group 2
        inp.send_text('\r')  # enter -> confirm
        result = await prompt_group_assignment(
            ['cpp', 'java'], {'cpp': 0, 'java': 0}, input=inp, output=DummyOutput()
        )
    assert result == {'cpp': 2, 'java': 2}


async def test_picker_cancel_returns_none():
    with create_pipe_input() as inp:
        inp.send_text('q')
        result = await prompt_group_assignment(
            ['cpp', 'java'], {}, input=inp, output=DummyOutput()
        )
    assert result is None
