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


def test_each_player_gets_a_unique_container_id():
    macro = _asciinema()
    first = re.search(r'id="(cast-[^"]+)"', macro('run-basic')).group(1)
    second = re.search(r'id="(cast-[^"]+)"', macro('run-basic')).group(1)

    assert first != second


def test_a_legacy_asciinema_org_id_still_renders_the_old_embed():
    html = _asciinema()(LEGACY_ID)

    assert f'asciinema.org/a/{LEGACY_ID}.js' in html
    assert 'AsciinemaPlayer.create' not in html
