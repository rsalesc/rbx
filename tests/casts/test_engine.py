import json
import pathlib
import time

import pytest

from scripts.casts.engine import (
    CastBuilder,
    RecordingError,
    build_env,
    key_bytes,
    parse_duration,
    run_recording,
)
from scripts.casts.postprocess import cast_text
from scripts.casts.spec import RecordingSpec, Tagged


def _spec(**kwargs) -> RecordingSpec:
    base = dict(name='t', fixture='f', instructions=['echo hi'], width=80, height=24)
    base.update(kwargs)
    return RecordingSpec(**base)


def _run(spec: RecordingSpec, tmp_path: pathlib.Path) -> str:
    home = tmp_path / 'home'
    home.mkdir(exist_ok=True)
    return run_recording(spec, workdir=str(tmp_path), home=str(home))


# -- pure helpers ---------------------------------------------------------


@pytest.mark.parametrize(
    ('text', 'expected'),
    [('1s', 1.0), ('2.5s', 2.5), ('150ms', 0.15), ('900us', 0.0009)],
)
def test_parse_duration_accepts_the_autocast_grammar(text, expected):
    assert parse_duration(text) == pytest.approx(expected)


def test_parse_duration_rejects_a_bare_number():
    with pytest.raises(ValueError):
        parse_duration('3')


def test_key_bytes_translates_control_codes():
    assert key_bytes('^C') == b'\x03'
    assert key_bytes('^D') == b'\x04'
    assert key_bytes('j') == b'j'


def test_cast_builder_emits_a_valid_v2_header():
    builder = CastBuilder(100, 30, title='Demo')
    builder.output('hi')

    header = json.loads(builder.to_text().splitlines()[0])

    assert header['version'] == 2
    assert header['width'] == 100
    assert header['height'] == 30
    assert header['title'] == 'Demo'


# -- recording ------------------------------------------------------------


def test_a_command_is_typed_then_its_output_recorded(tmp_path: pathlib.Path):
    text = cast_text(_run(_spec(instructions=['echo hello-world']), tmp_path))

    assert '$ echo hello-world' in text
    assert 'hello-world' in text


def test_setup_commands_run_but_are_not_shown(tmp_path: pathlib.Path):
    spec = _spec(setup=['echo secret-setup > made.txt'], instructions=['cat made.txt'])

    text = cast_text(_run(spec, tmp_path))

    assert 'secret-setup' in text  # the file was really created, then cat'ed
    assert '$ echo secret-setup' not in text  # but the setup was never shown


def test_commands_run_in_the_working_directory(tmp_path: pathlib.Path):
    (tmp_path / 'marker.txt').write_text('found-me\n')

    text = cast_text(_run(_spec(instructions=['cat marker.txt']), tmp_path))

    assert 'found-me' in text


def test_the_environment_is_normalized(tmp_path: pathlib.Path):
    text = cast_text(
        _run(_spec(instructions=['echo "[$TZ|$LC_ALL|$COLUMNS]"']), tmp_path)
    )

    assert '[UTC|C.UTF-8|80]' in text


def test_home_is_redirected_away_from_the_real_one(tmp_path: pathlib.Path):
    text = cast_text(_run(_spec(instructions=['echo $HOME']), tmp_path))

    assert str(tmp_path / 'home') in text


def test_wait_advances_the_timeline_without_output(tmp_path: pathlib.Path):
    raw = _run(_spec(instructions=['echo a', Tagged('Wait', '5s'), 'echo b']), tmp_path)

    events = [json.loads(line) for line in raw.splitlines()[1:]]
    gaps = [events[index + 1][0] - events[index][0] for index in range(len(events) - 1)]
    assert max(gaps) >= 5.0


def test_marker_instructions_become_marker_events(tmp_path: pathlib.Path):
    raw = _run(
        _spec(instructions=[Tagged('Marker', 'Chapter one')], end_pause='0s'), tmp_path
    )

    events = [json.loads(line) for line in raw.splitlines()[1:]]
    assert [event[1:] for event in events] == [['m', 'Chapter one']]


def test_interactive_keys_are_fed_to_the_command(tmp_path: pathlib.Path):
    spec = _spec(
        instructions=[
            Tagged(
                'Interactive',
                {'command': 'cat', 'keys': ['h', 'i', '^M', '200ms', '^D']},
            )
        ]
    )

    text = cast_text(_run(spec, tmp_path))

    assert 'hi' in text


def test_a_command_that_never_exits_times_out(tmp_path: pathlib.Path):
    spec = _spec(instructions=['sleep 30'], timeout='1s')

    with pytest.raises(RecordingError, match='timed out'):
        _run(spec, tmp_path)


def test_an_unknown_instruction_tag_is_rejected(tmp_path: pathlib.Path):
    spec = _spec(instructions=[Tagged('Nonsense', 'x')])

    with pytest.raises(RecordingError, match='unknown instruction tag'):
        _run(spec, tmp_path)


# -- trailing hold --------------------------------------------------------


def _duration(raw: str) -> float:
    events = [json.loads(line) for line in raw.splitlines()[1:]]
    return events[-1][0]


def test_the_cast_does_not_hold_its_final_frame_by_default(tmp_path: pathlib.Path):
    # The dwell before a loop restarts belongs to the player, which pauses in
    # wall-clock time; a hold baked in here would be clamped by
    # `idleTimeLimit`, scaled by `speed`, and then added on top of it.
    # Asserted structurally rather than by duration: the hold is the only
    # zero-byte output event the engine emits, so its absence is exact, while
    # comparing two real runs would carry their spawn jitter.
    raw = _run(_spec(instructions=['echo done']), tmp_path)

    events = [json.loads(line) for line in raw.splitlines()[1:]]
    assert events[-1][2] != ''


def test_the_hold_is_configurable(tmp_path: pathlib.Path):
    short = _duration(_run(_spec(instructions=['echo x'], end_pause='1s'), tmp_path))
    long = _duration(_run(_spec(instructions=['echo x'], end_pause='6s'), tmp_path))

    assert long - short == pytest.approx(5.0, abs=0.5)


def test_the_hold_adds_no_visible_output(tmp_path: pathlib.Path):
    held = cast_text(_run(_spec(instructions=['echo x'], end_pause='4s'), tmp_path))
    bare = cast_text(_run(_spec(instructions=['echo x'], end_pause='0s'), tmp_path))

    assert held == bare


def test_the_hold_extends_the_last_event_not_just_the_clock(tmp_path: pathlib.Path):
    # A player reads duration from the final event, so advancing the internal
    # clock without emitting anything would be a no-op.
    raw = _run(_spec(instructions=['echo x'], end_pause='5s'), tmp_path)

    events = [json.loads(line) for line in raw.splitlines()[1:]]
    assert events[-1][1] == 'o'
    assert events[-1][2] == ''
    assert events[-1][0] - events[-2][0] >= 5.0


def test_cast_duration_tracks_real_elapsed_time(tmp_path: pathlib.Path):
    # Regression: the clock used to advance by a fixed amount per loop
    # iteration. At EOF the pty read returns instantly, so a recording that
    # waited on remaining keys spun thousands of times per second and claimed
    # a duration of hours.
    started = time.monotonic()
    raw = _run(
        _spec(
            instructions=[
                Tagged('Interactive', {'command': 'cat', 'keys': ['^D', '1s']})
            ],
            end_pause='0s',
        ),
        tmp_path,
    )
    real = time.monotonic() - started

    assert _duration(raw) <= real + 1.0


# -- environment ----------------------------------------------------------


def test_build_env_pins_the_values_that_must_not_vary():
    env = build_env(_spec(), home='/tmp/h', base={'PATH': '/bin'})

    assert env['HOME'] == '/tmp/h'
    assert env['TERM'] == 'xterm-256color'
    assert env['COLUMNS'] == '80'
    assert env['LC_ALL'] == 'C.UTF-8'
    assert env['TZ'] == 'UTC'


def test_build_env_silences_the_prompt_toolkit_cursor_position_warning():
    # Our pty never answers a cursor-position request, so without this every
    # recording of an interactive prompt opens with prompt_toolkit's CPR
    # warning printed over the question.
    env = build_env(_spec(), home='/tmp/h', base={'PATH': '/bin'})

    assert env['PROMPT_TOOLKIT_NO_CPR'] == '1'


def test_build_env_inherits_the_toolchain_variables():
    # Dropping TMPDIR/SDKROOT breaks the C++ compiler, which would make every
    # `rbx run` recording a wall of compile errors.
    env = build_env(
        _spec(), home='/tmp/h', base={'PATH': '/bin', 'TMPDIR': '/t', 'SDKROOT': '/s'}
    )

    assert env['TMPDIR'] == '/t'
    assert env['SDKROOT'] == '/s'


def test_build_env_drops_ambient_overrides_that_would_change_the_recording():
    env = build_env(
        _spec(),
        home='/tmp/h',
        base={'PATH': '/bin', 'NO_COLOR': '1', 'RBX_CONTEST': 'x'},
    )

    assert 'NO_COLOR' not in env
    assert 'RBX_CONTEST' not in env


# -- fast-forward ---------------------------------------------------------


def test_speed_compresses_a_commands_elapsed_time(tmp_path: pathlib.Path):
    # The cast clock advances by real elapsed time, so a slow command costs its
    # full duration in playback. `speed` scales that window down without
    # dropping a single frame.
    # The command has to print *after* sleeping: a cast's duration comes from
    # its last event, so a silent sleep would leave the clock unmeasured.
    slow = _duration(
        _run(
            _spec(instructions=[Tagged('Command', {'command': 'sleep 1; echo done'})]),
            tmp_path,
        )
    )
    fast = _duration(
        _run(
            _spec(
                instructions=[
                    Tagged('Command', {'command': 'sleep 1; echo done', 'speed': 4})
                ]
            ),
            tmp_path,
        )
    )

    assert slow >= 1.0
    # Only the measured second is scaled: the typing animation and the pause
    # after a command are authored, not measured, so they are a fixed floor
    # under both runs. A 1s sleep at 4x saves the 0.75s that separates them.
    assert slow - fast == pytest.approx(0.75, abs=0.3)


def test_speed_leaves_the_typing_animation_alone(tmp_path: pathlib.Path):
    # Typing is synthesized at `type_speed`, not measured, so compressing a
    # command must not make its own name scroll past unreadably.
    raw = _run(
        _spec(
            instructions=[Tagged('Command', {'command': 'true', 'speed': 10})],
            type_speed='100ms',
        ),
        tmp_path,
    )

    assert _duration(raw) >= 0.4


def test_a_speed_token_scales_only_the_keys_that_follow_it(tmp_path: pathlib.Path):
    # `rbx time` is one interactive command: the dwell that lets a reader take
    # in the prompt and the dwell that waits out the compute must be paced
    # differently, and only a mid-command switch can do that.
    paced = _duration(
        _run(
            _spec(
                instructions=[
                    Tagged(
                        'Interactive',
                        {'command': 'cat', 'keys': ['1s', 'x10', '1s', '^D']},
                    )
                ],
                type_speed='0ms',
                # Before the token is understood it is typed at `cat`, whose
                # next `^D` then flushes that text instead of closing the
                # stream -- so an unimplemented feature hangs. Fail fast.
                timeout='20s',
            ),
            tmp_path,
        )
    )
    flat = _duration(
        _run(
            _spec(
                instructions=[
                    Tagged(
                        'Interactive', {'command': 'cat', 'keys': ['1s', '1s', '^D']}
                    )
                ],
                type_speed='0ms',
            ),
            tmp_path,
        )
    )

    # The second second plays in a tenth of the time; the first is untouched.
    assert flat - paced == pytest.approx(0.9, abs=0.3)


def test_a_speed_token_is_not_typed_into_the_command(tmp_path: pathlib.Path):
    # The token steers the recording, so it must never reach the program: a
    # literal `x10` would land in the middle of whatever was being typed.
    raw = _run(
        _spec(
            instructions=[
                Tagged(
                    'Interactive',
                    {'command': 'cat', 'keys': ['hi', 'x10', '^M', '^D']},
                )
            ],
            timeout='20s',
        ),
        tmp_path,
    )

    # `cat` echoes what it is fed, so a token that leaked through would show
    # up twice over -- once as the keystroke, once in the echoed line.
    assert 'x10' not in cast_text(raw)


# -- cropping the view ----------------------------------------------------


def test_an_instruction_can_run_in_a_smaller_terminal(tmp_path: pathlib.Path):
    # Each instruction gets its own pty, so a narrower view is a genuinely
    # narrower terminal rather than a crop applied after the fact -- which is
    # why rbx's own output reflows into it instead of being clipped.
    raw = _run(
        _spec(
            instructions=[Tagged('Command', {'command': 'echo $COLUMNS', 'width': 40})],
            width=100,
        ),
        tmp_path,
    )

    assert '40' in cast_text(raw)


def test_a_resized_instruction_emits_a_resize_event(tmp_path: pathlib.Path):
    # A cast header carries one size; the player follows `r` events for the
    # rest. Without one the smaller output would be drawn into the full frame.
    raw = _run(
        _spec(
            instructions=[
                Tagged('Command', {'command': 'true', 'width': 40, 'height': 10})
            ],
            width=100,
            height=30,
        ),
        tmp_path,
    )

    events = [json.loads(line) for line in raw.splitlines()[1:] if line.strip()]
    resizes = [event for event in events if event[1] == 'r']

    assert resizes[0][2] == '40x10'
    # ...and it goes back, so the next instruction is not left cropped.
    assert resizes[-1][2] == '100x30'


def test_an_unresized_instruction_emits_no_resize_event(tmp_path: pathlib.Path):
    # Every existing cast must keep byte-for-byte to what it recorded before,
    # so a spec that asks for nothing gets nothing.
    raw = _run(_spec(instructions=['echo hi']), tmp_path)

    events = [json.loads(line) for line in raw.splitlines()[1:] if line.strip()]

    assert [event for event in events if event[1] == 'r'] == []


def test_a_non_positive_speed_is_rejected(tmp_path: pathlib.Path):
    with pytest.raises(RecordingError, match='speed'):
        _run(
            _spec(instructions=[Tagged('Command', {'command': 'true', 'speed': 0})]),
            tmp_path,
        )
