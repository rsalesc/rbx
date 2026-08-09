import re

from main import define_env

LEGACY_ID = 'cqUTWgIRFA1P7VsV39uJTorKC'


class _Env:
    def __init__(self):
        self.macros = {}

    def macro(self, fn):
        self.macros[fn.__name__] = fn
        return fn


def _asciinema():
    env = _Env()
    define_env(env)
    return env.macros['asciinema']


def test_local_name_renders_a_player_pointed_at_the_committed_cast():
    html = _asciinema()('run-basic')

    assert '/assets/casts/run-basic.cast' in html
    assert 'AsciinemaPlayer.create' in html
    assert 'asciinema.org' not in html


def test_player_init_waits_for_the_bundle_to_load():
    # extra_javascript lands at the end of <body>, after this inline script,
    # so calling AsciinemaPlayer immediately throws ReferenceError.
    html = _asciinema()('run-basic')

    assert "document.addEventListener('DOMContentLoaded'" in html
    init = html.index('AsciinemaPlayer.create')
    guard = html.index('DOMContentLoaded')
    assert guard < init


def test_speed_and_idleness_map_onto_player_options():
    html = _asciinema()('run-basic', idleness=2, speed=1.5)

    assert '"speed": 1.5' in html
    assert '"idleTimeLimit": 2' in html


def test_the_player_pauses_before_looping_instead_of_restarting_at_once():
    # The final frame is usually the point of the recording, and the player's
    # own `loop` restarts on the very next tick after it is drawn.
    html = _asciinema()('run-basic')

    assert '"loop": false' in html
    assert "addEventListener('ended'" in html
    assert 'player.seek(0)' in html
    assert '}, 3000);' in html


def test_the_loop_pause_is_configurable():
    html = _asciinema()('run-basic', pause=1.5)

    assert '}, 1500);' in html


def test_the_loop_pause_is_wall_clock_and_survives_speed():
    # A hold baked into the cast would be divided by `speed`; this one is a
    # setTimeout, so it is the same three seconds at any playback rate.
    html = _asciinema()('run-basic', speed=2)

    assert '"speed": 2' in html
    assert '}, 3000);' in html


def test_each_player_gets_a_unique_container_id():
    macro = _asciinema()
    first = re.search(r'id="(cast-[^"]+)"', macro('run-basic')).group(1)
    second = re.search(r'id="(cast-[^"]+)"', macro('run-basic')).group(1)

    assert first != second


def test_a_legacy_asciinema_org_id_plays_through_the_vendored_player():
    # Their `<script>` embed brings its own player, which only takes
    # `data-loop` and restarts the instant the last frame is drawn. Pointing
    # our player at the hosted `.cast` (served with `Allow-Origin: *`) is what
    # gives a hosted recording the same loop pause as a committed one.
    html = _asciinema()(LEGACY_ID)

    assert f"AsciinemaPlayer.create('https://asciinema.org/a/{LEGACY_ID}.cast'" in html
    assert f'asciinema.org/a/{LEGACY_ID}.js' not in html


def test_a_legacy_asciinema_org_id_gets_the_loop_pause_too():
    html = _asciinema()(LEGACY_ID)

    assert '"loop": false' in html
    assert "addEventListener('ended'" in html
    assert '}, 3000);' in html
