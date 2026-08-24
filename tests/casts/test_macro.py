import pathlib
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


def test_the_default_formula_macro_serves_the_value_the_code_defines():
    # The profiling docs render this instead of restating the formula, so the
    # page cannot drift away from what rbx estimates with.
    from rbx.box.environment import DEFAULT_TIMING_FORMULA

    env = _Env()
    define_env(env)

    assert env.macros['default_timing_formula']() == DEFAULT_TIMING_FORMULA


def test_the_profiling_docs_do_not_restate_the_default_formula():
    # The formula lives on the page that explains how a limit is computed; a
    # page that spelled it out by hand would drift the moment the default did.
    root = pathlib.Path(__file__).resolve().parents[2]
    page = (root / 'docs' / 'setters' / 'profiling' / 'computing.md').read_text()

    assert '{{ default_timing_formula() }}' in page


def test_local_name_renders_a_player_pointed_at_the_committed_cast():
    html = _asciinema()('run-basic')

    assert '/assets/casts/run-basic.cast' in html
    assert 'rbxCast(' in html
    assert 'asciinema.org' not in html


def test_player_init_waits_for_the_bundle_to_load():
    # extra_javascript lands at the end of <body>, after this inline script,
    # so calling rbxCast immediately throws ReferenceError.
    html = _asciinema()('run-basic')

    assert "document.addEventListener('DOMContentLoaded'" in html
    init = html.index('rbxCast(')
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

    assert '}, 3000);' in html


def test_the_macro_does_not_create_a_player_of_its_own():
    # The pause lives in `rbxCast`. A second call site that creates its own
    # player silently opts out of it -- which is exactly what happened to the
    # home page template.
    html = _asciinema()('run-basic')

    assert 'AsciinemaPlayer.create' not in html


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


def test_every_cast_on_the_site_is_created_through_rbx_cast():
    # The home page builds its own players from a template rather than through
    # the macro. It kept `loop: true` when the pause was added here, so the
    # casts a first-time visitor sees restarted instantly. Both call sites have
    # to go through the one helper that pauses.
    root = pathlib.Path(__file__).resolve().parents[2]
    home = (root / 'docs' / 'templates' / 'home.html').read_text()
    helper = root / 'docs' / 'assets' / 'casts-loop.js'
    config = (root / 'mkdocs.yml').read_text()

    assert helper.is_file()
    assert 'rbxCast(' in home
    assert 'AsciinemaPlayer.create(' not in home
    # The helper wraps the bundle, so it has to be loaded after it.
    assert config.index('assets/asciinema-player.min.js') < config.index(
        'assets/casts-loop.js'
    )


def test_a_legacy_asciinema_org_id_plays_through_the_vendored_player():
    # Their `<script>` embed brings its own player, which only takes
    # `data-loop` and restarts the instant the last frame is drawn. Pointing
    # our player at the hosted `.cast` (served with `Allow-Origin: *`) is what
    # gives a hosted recording the same loop pause as a committed one.
    html = _asciinema()(LEGACY_ID)

    assert f"rbxCast('https://asciinema.org/a/{LEGACY_ID}.cast'" in html
    assert f'asciinema.org/a/{LEGACY_ID}.js' not in html


def test_a_legacy_asciinema_org_id_gets_the_loop_pause_too():
    html = _asciinema()(LEGACY_ID)

    assert 'rbxCast(' in html
    assert '}, 3000);' in html


# --- The preset tree ----------------------------------------------------------
#
# `first-steps.md` used to print a hand-transcribed picture of the default
# preset. It went on showing a `documents/` folder for several releases after
# statements v2 renamed it to `statement/`, because nothing read the page. These
# tests are what reads it now. See
# docs/plans/2026-08-24-walkthrough-audit-design.md.


def _mkdocs_extra():
    """The `extra:` block, which annotation prose expands `{{...}}` against."""
    import yaml

    class Loader(yaml.SafeLoader):
        pass

    # mkdocs.yml carries `!!python/name:` tags for the emoji extensions. They
    # are irrelevant here, but SafeLoader refuses to parse the file with them.
    Loader.add_multi_constructor(
        'tag:yaml.org,2002:python/name', lambda loader, suffix, node: suffix
    )

    root = pathlib.Path(__file__).resolve().parents[2]
    return yaml.load((root / 'mkdocs.yml').read_text(), Loader=Loader)['extra']


def _preset_tree():
    env = _Env()
    env.variables = _mkdocs_extra()
    define_env(env)
    return env.macros['preset_tree']


def _tracked_preset_paths():
    from main import _tracked_preset_files

    return {str(p) for p in _tracked_preset_files()}


def test_the_first_steps_tree_is_rendered_rather_than_transcribed():
    root = pathlib.Path(__file__).resolve().parents[2]
    page = (root / 'docs' / 'setters' / 'first-steps.md').read_text()

    assert '{{ preset_tree() }}' in page
    # A hand-written copy would drift again the moment the preset moved. An
    # annotated tree line is the tell -- the page draws other trees (the `build`
    # layout), but only the preset's carries `# (n)!` markers.
    assert not re.search(r'^\s*[├└]── .*# \(\d+\)!', page, re.M), (
        'first-steps.md has regrown a hand-written preset tree; render it with '
        '{{ preset_tree() }} instead'
    )


def test_every_file_the_preset_ships_shows_up_in_the_tree():
    rendered = _preset_tree()()

    for path in _tracked_preset_paths():
        assert pathlib.Path(path).name in rendered, (
            f'the preset ships {path}, but the first-steps tree does not show it'
        )


def test_the_tree_shows_the_layout_the_preset_actually_ships():
    # The fence only. The prose below it mentions `icpc.sty` on purpose, to say
    # that a problem is not where you will find it.
    tree = _preset_tree()().split('```')[1]

    assert 'statement' in tree
    # The regression this whole mechanism exists to prevent.
    assert 'documents' not in tree
    # Statement chrome belongs to the contest under statements v2, so a problem
    # ships neither of these.
    assert 'icpc.sty' not in tree
    assert 'template.rbx.tex' not in tree


def test_an_annotation_for_a_path_the_preset_dropped_is_an_error():
    import main

    tracked = _tracked_preset_paths()
    assert 'statement/statement.rbx.tex' in tracked
    assert 'documents/statement.rbx.tex' not in tracked, (
        'the check below only means anything while `documents/` is gone'
    )

    original = main.PRESET_TREE_ANNOTATIONS
    try:
        main.PRESET_TREE_ANNOTATIONS = 'docs/_data/preset-tree.yml'
        # Sanity: the committed annotations all point at paths that exist.
        _preset_tree()()
    finally:
        main.PRESET_TREE_ANNOTATIONS = original


def test_annotations_resolve_the_mkdocs_variables_they_use():
    rendered = _preset_tree()()

    # `{{testlib}}` and friends would otherwise reach the reader as literal
    # text: mkdocs-macros renders a page once and never re-scans macro output.
    assert '{{' not in rendered
    assert 'codeforces.com/testlib' in rendered


def test_numbering_is_derived_from_the_walk_and_stays_aligned():
    rendered = _preset_tree()()

    markers = re.findall(r'# \((\d+)\)!', rendered)
    assert markers == [str(i) for i in range(1, len(markers) + 1)]

    # Every marker in the tree has a list item to match, and every item's
    # continuation lines are indented to the same column regardless of whether
    # the number is one or two digits.
    for n in markers:
        item = re.search(rf'^{n}\.( +)', rendered, re.M)
        assert item is not None, f'tree marker ({n}) has no annotation below it'
        # Text starts at column 4 whether the number is one digit or two, so a
        # continuation line indented by 4 stays inside its list item.
        assert item.end() - item.start() == 4
