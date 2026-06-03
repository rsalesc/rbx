from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.output import DummyOutput

from rbx.box.environment import LanguageGroupFallback
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


def test_preview_text_suppressed_once_done():
    s = GroupPickerState(['cpp'], {})
    assert s.preview_text(lambda a: 'TABLE') == 'TABLE'
    s.done = True
    assert s.preview_text(lambda a: 'TABLE') == ''


def test_preview_text_empty_without_callback():
    s = GroupPickerState(['cpp'], {})
    assert s.preview_text(None) == ''


async def test_picker_invokes_preview_with_current_assignment():
    from prompt_toolkit.formatted_text import ANSI

    seen = []

    def preview(assignment):
        seen.append(dict(assignment))
        return ANSI('preview')

    with create_pipe_input() as inp:
        inp.send_text('1')  # cpp -> group 1
        inp.send_text('\r')  # confirm
        result = await prompt_group_assignment(
            ['cpp', 'java'],
            {'cpp': 0, 'java': 0},
            input=inp,
            output=DummyOutput(),
            preview=preview,
        )
    assert result == {'cpp': 1, 'java': 0}
    # The picker rendered the live preview from the current assignment...
    assert {'cpp': 0, 'java': 0} in seen
    # ...but suppressed it on the confirming (final) paint, so the post-enter
    # assignment never reaches the preview.
    assert {'cpp': 1, 'java': 0} not in seen


def test_group_key_per_state():
    s = GroupPickerState(['cpp', 'py', 'go'], {'cpp': 2, 'py': -1, 'go': 0})
    assert s.group_key('cpp') == 'g2'
    assert s.group_key('py') == 's:py'
    assert s.group_key('go') == 'leftover'


def test_start_edit_seeds_defaults_and_commit():
    s = GroupPickerState(['cpp', 'py'], {'cpp': 1, 'py': 2})
    s.move(1)  # cursor -> py
    s.start_edit()
    assert s.editing
    s.set_ref('cpp')
    s.set_a('2.5')
    s.set_b('100')
    assert s.commit_edit() is True
    assert not s.editing
    assert s.relatives['g2'] == LanguageGroupFallback(
        relativeTo='cpp', multiplier=2.5, increment=100
    )


def test_cancel_edit_discards():
    s = GroupPickerState(['cpp', 'py'], {'cpp': 1, 'py': 2})
    s.move(1)
    s.start_edit()
    s.set_a('9')
    s.cancel_edit()
    assert not s.editing
    assert 'g2' not in s.relatives


def test_clear_relative_removes_spec():
    s = GroupPickerState(
        ['cpp', 'py'],
        {'cpp': 1, 'py': 2},
        relatives={'g2': LanguageGroupFallback(relativeTo='cpp', multiplier=2.0)},
    )
    s.move(1)
    s.start_edit()
    s.clear_relative()
    assert 'g2' not in s.relatives
    assert not s.editing


def test_invalid_a_keeps_editing():
    s = GroupPickerState(['cpp', 'py'], {'cpp': 1, 'py': 2})
    s.move(1)
    s.start_edit()
    s.set_ref('cpp')
    s.set_a('abc')  # not a positive float
    assert s.commit_edit() is False  # rejected
    assert s.editing  # stays in editor


def test_nonpositive_a_rejected():
    s = GroupPickerState(['cpp', 'py'], {'cpp': 1, 'py': 2})
    s.move(1)
    s.start_edit()
    s.set_a('0')
    assert s.commit_edit() is False
    s.set_a('-3')
    assert s.commit_edit() is False
    assert s.editing


def test_invalid_b_rejected_but_empty_ok():
    s = GroupPickerState(['cpp', 'py'], {'cpp': 1, 'py': 2})
    s.move(1)
    s.start_edit()
    s.set_ref('cpp')
    s.set_a('2.0')
    s.set_b('xx')
    assert s.commit_edit() is False
    s.set_b('')  # empty increment is allowed (None)
    assert s.commit_edit() is True
    assert s.relatives['g2'].increment is None


def test_reference_options_exclude_own_group_and_include_base():
    s = GroupPickerState(['cpp', 'py', 'go'], {'cpp': 1, 'py': 2, 'go': 2})
    s.move(1)  # cursor on py (group g2)
    refs = s.reference_options()
    assert None in refs  # base estimate
    assert 'cpp' in refs  # representative of the other group
    assert 'py' not in refs and 'go' not in refs  # own group excluded


def test_cycle_ref_wraps():
    s = GroupPickerState(['cpp', 'py', 'go'], {'cpp': 1, 'py': 2, 'go': 3})
    s.move(1)  # py
    s.start_edit()
    opts = s.reference_options()  # e.g. [None, 'cpp', 'go']
    start = s.edit_ref
    s.cycle_ref(1)
    assert s.edit_ref == opts[(opts.index(start) + 1) % len(opts)]


def test_reset_restores_initial_numbers_and_relatives():
    s = GroupPickerState(
        ['cpp', 'py'],
        {'cpp': 1, 'py': 2},
        relatives={'g2': LanguageGroupFallback(relativeTo='cpp', multiplier=2.0)},
    )
    s.set_group(5)  # mutate cpp
    s.move(1)
    s.start_edit()
    s.clear_relative()
    s.reset_to_initial()
    assert s.assignment() == {'cpp': 1, 'py': 2}
    assert s.relatives == {
        'g2': LanguageGroupFallback(relativeTo='cpp', multiplier=2.0)
    }


def test_prune_relatives_drops_orphans():
    s = GroupPickerState(
        ['cpp', 'py'],
        {'cpp': 1, 'py': 2},
        relatives={
            'g2': LanguageGroupFallback(relativeTo='cpp', multiplier=2.0),
            's:rust': LanguageGroupFallback(relativeTo='cpp', multiplier=3.0),
        },
    )
    # 's:rust' has no corresponding language/group -> pruned; 'g2' kept (py in bucket 2)
    pruned = s.prune_relatives()
    assert 'g2' in pruned
    assert 's:rust' not in pruned


def test_render_annotates_relative_group():
    s = GroupPickerState(
        ['cpp', 'py'],
        {'cpp': 1, 'py': 2},
        relatives={
            'g2': LanguageGroupFallback(relativeTo='cpp', multiplier=2.0, increment=100)
        },
    )
    text = ''.join(t for _, t in s.render_fragments())
    assert 'py' in text
    assert '→ cpp' in text or '-> cpp' in text  # reference shown
    assert '2' in text  # multiplier shown
    assert '100' in text  # increment shown


def test_render_annotates_relative_to_base():
    s = GroupPickerState(
        ['cpp', 'py'],
        {'cpp': 1, 'py': 2},
        relatives={'g2': LanguageGroupFallback(relativeTo=None, multiplier=3.0)},
    )
    text = ''.join(t for _, t in s.render_fragments())
    assert 'base' in text  # relativeTo=None shown as 'base'


def test_render_shows_inline_editor_when_editing():
    s = GroupPickerState(['cpp', 'py'], {'cpp': 1, 'py': 2})
    s.move(1)
    s.start_edit()
    s.set_ref('cpp')
    text = ''.join(t for _, t in s.render_fragments())
    assert 'relative-to' in text
    assert 'A:' in text and 'B:' in text


def test_render_no_editor_when_not_editing():
    s = GroupPickerState(['cpp', 'py'], {'cpp': 1, 'py': 2})
    text = ''.join(t for _, t in s.render_fragments())
    assert 'relative-to' not in text


def test_legend_mentions_relative_and_reset():
    from rbx.box.timing_group_picker import LEGEND_LINES

    text = '\n'.join(LEGEND_LINES)
    assert 'relative' in text
    assert 'reset' in text


def test_legend_describes_three_states():
    from rbx.box.timing_group_picker import LEGEND_LINES

    text = '\n'.join(LEGEND_LINES)
    assert '[N]' in text and 'grouped' in text
    assert '[X]' in text and 'singleton' in text
    assert '[ ]' in text and 'leftover' in text
    # key hint still present
    assert 'confirm' in text and 'cancel' in text
