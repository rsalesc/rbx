import json
import pathlib

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
    raw = _run(_spec(instructions=[Tagged('Marker', 'Chapter one')]), tmp_path)

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


# -- environment ----------------------------------------------------------


def test_build_env_pins_the_values_that_must_not_vary():
    env = build_env(_spec(), home='/tmp/h', base={'PATH': '/bin'})

    assert env['HOME'] == '/tmp/h'
    assert env['TERM'] == 'xterm-256color'
    assert env['COLUMNS'] == '80'
    assert env['LC_ALL'] == 'C.UTF-8'
    assert env['TZ'] == 'UTC'


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
