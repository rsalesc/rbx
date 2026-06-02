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


def test_render_fragments_shows_three_states():
    # cpp -> group 3, java -> unbucketed (0), python -> singleton (-1)
    s = GroupPickerState(['cpp', 'java', 'python'], {'cpp': 3, 'python': -1})
    text = ''.join(t for _, t in s.render_fragments())
    assert '[3] cpp' in text
    assert '[ ] java' in text
    assert '[X] python' in text
    assert text.count('❯') == 1


def test_toggle_singleton_cycles():
    s = GroupPickerState(['cpp'], {'cpp': 0})
    s.toggle_singleton()
    assert s.assignment() == {'cpp': -1}  # unbucketed -> singleton
    s.toggle_singleton()
    assert s.assignment() == {'cpp': 0}  # singleton -> unbucketed


def test_toggle_singleton_from_group_goes_to_singleton():
    s = GroupPickerState(['cpp'], {'cpp': 2})
    s.toggle_singleton()
    assert s.assignment() == {'cpp': -1}


async def test_picker_toggle_and_group_then_confirm():
    with create_pipe_input() as inp:
        inp.send_text('1')  # cpp -> group 1
        inp.send_text('\x1b[B')  # down -> java
        inp.send_text(' ')  # space -> java singleton [X]
        inp.send_text('\x1b[B')  # down -> python (stays unbucketed [ ])
        inp.send_text('\r')  # enter -> confirm
        result = await prompt_group_assignment(
            ['cpp', 'java', 'python'],
            {'cpp': 0, 'java': 0, 'python': 0},
            input=inp,
            output=DummyOutput(),
        )
    assert result == {'cpp': 1, 'java': -1, 'python': 0}


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


def test_legend_describes_three_states():
    from rbx.box.timing_group_picker import LEGEND_LINES

    text = '\n'.join(LEGEND_LINES)
    assert '[N]' in text and 'grouped' in text
    assert '[X]' in text and 'singleton' in text
    assert '[ ]' in text and 'leftover' in text
    # key hint still present
    assert 'confirm' in text and 'cancel' in text
