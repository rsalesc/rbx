"""
File for defining mkdocs macros.
"""

import itertools
import json
import pathlib
import re
import subprocess

import yaml

# asciinema.org url tokens are 25 chars of [A-Za-z0-9]. Anything else is the
# basename of a cast committed under docs/assets/casts.
_LEGACY_ID = re.compile(r'^[A-Za-z0-9]{25}$')

_counter = itertools.count()

_ROOT = pathlib.Path(__file__).parent.resolve()

# The problem half of the default preset -- what `rbx create` lays down, and
# what the first-steps tree is a picture of.
PRESET_PROBLEM_DIR = 'rbx/resources/presets/default/problem'

# Prose for the tree's numbered annotations, keyed by the path it annotates.
# Keyed rather than ordered on purpose: the numbering is derived from the walk,
# so a preset that gains a file renumbers everything without misaligning any of
# it. See docs/plans/2026-08-24-walkthrough-audit-design.md.
PRESET_TREE_ANNOTATIONS = 'docs/_data/preset-tree.yml'

# The name `rbx create` is given in the recording that plays right above the
# tree (casts/create-problem.yml). Keeping them equal means the folder the
# reader watches being created is the folder the tree describes.
PRESET_TREE_ROOT_NAME = 'sum-of-n'

# The contest half of the same preset -- what `rbx contest create` lays down,
# and what the contest-scaffolding tree is a picture of.
PRESET_CONTEST_DIR = 'rbx/resources/presets/default/contest'

CONTEST_TREE_ANNOTATIONS = 'docs/_data/contest-preset-tree.yml'

# Matches the contest created in casts/contest-scaffold.yml, for the same
# reason PRESET_TREE_ROOT_NAME matches casts/create-problem.yml.
CONTEST_TREE_ROOT_NAME = 'summer-cup'

# `{{ var }}` / `{{ a.b }}` inside annotation prose. mkdocs-macros renders a
# page once and does not re-scan what a macro returned, so these would reach
# the reader as literal text unless the macro resolves them itself.
_VAR = re.compile(r'\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}')


def _tracked_preset_files(preset_dir: str) -> list[pathlib.Path]:
    """Preset files as git knows them, relative to `preset_dir`.

    Deliberately not a filesystem walk. A preset directory that has ever been
    built in place carries `.box/`, `build/` and `.limits/` alongside the files
    that ship, and a walk would render several hundred cache blobs into the
    page. What the preset *ships* is exactly what is committed.
    """
    out = subprocess.run(
        ['git', 'ls-files', '-z', preset_dir],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    prefix = preset_dir + '/'
    return sorted(
        pathlib.Path(line[len(prefix) :])
        for line in out.split('\0')
        if line.startswith(prefix)
    )


def _tree_lines(paths: list[pathlib.Path]) -> list[tuple[str, str]]:
    """Render `paths` as box-drawing lines paired with the path each shows.

    The pairing is what lets annotations be keyed by path: the caller numbers
    the lines it finds prose for, without either side counting rows.

    Files sort before directories at every level, which is how the tree read
    when it was written by hand -- configuration first, then the folders you
    go on to open.
    """
    lines: list[tuple[str, str]] = []

    def walk(prefix: str, parent: pathlib.PurePath, entries: list[pathlib.Path]):
        files = sorted({e.parts[0] for e in entries if len(e.parts) == 1})
        dirs = sorted({e.parts[0] for e in entries if len(e.parts) > 1})
        names = files + dirs
        for i, name in enumerate(names):
            last = i == len(names) - 1
            branch = '└── ' if last else '├── '
            path = parent / name
            lines.append((f'{prefix}{branch}{name}', str(path)))
            if name in dirs:
                walk(
                    prefix + ('    ' if last else '│   '),
                    path,
                    [
                        pathlib.Path(*e.parts[1:])
                        for e in entries
                        if len(e.parts) > 1 and e.parts[0] == name
                    ],
                )

    walk('', pathlib.PurePath(), paths)
    return lines


def _list_item(number: int, prose: str) -> str:
    """One numbered annotation, indented so its nested blocks stay inside it.

    The marker is padded to a fixed width rather than followed by a fixed two
    spaces: `1.  x` starts its text at column 4 but `10. x` would start at
    column 5, and a continuation line indented to the wrong column drops the
    admonitions and fenced blocks out of the item.
    """
    indent = ' ' * 4
    marker = f'{number}.'.ljust(len(indent))
    lines = [f'{marker}{prose.splitlines()[0]}'] + [
        (indent + line).rstrip() for line in prose.splitlines()[1:]
    ]
    return '\n'.join(lines).rstrip()


def define_env(env):
    @env.macro
    def default_timing_formula() -> str:
        """The formula rbx estimates with when no strategy is configured.

        Read out of the code rather than restated in prose: a docs page that
        spells the formula out by hand is a copy that drifts the moment the
        default changes, and a reader following a stale formula is worse off
        than one who is told nothing.
        """
        from rbx.box.environment import DEFAULT_TIMING_FORMULA

        return DEFAULT_TIMING_FORMULA

    def _resolve_vars(text: str) -> str:
        """Expand `{{testlib}}` / `{{tags.accepted}}` against the mkdocs `extra`."""

        def lookup(match: re.Match) -> str:
            value = env.variables
            for part in match.group(1).split('.'):
                try:
                    value = value[part]
                except (KeyError, TypeError):
                    raise KeyError(
                        f'{PRESET_TREE_ANNOTATIONS} refers to {{{{ {match.group(1)} }}}}, '
                        'which is not defined under `extra` in mkdocs.yml'
                    ) from None
            return str(value)

        return _VAR.sub(lookup, text)

    def _render_preset_tree(
        preset_dir: str, annotations_path: str, root_name: str
    ) -> str:
        """One half of the default preset, walked rather than transcribed.

        The tree this replaces was hand-copied once and then drifted: it went on
        showing a `documents/` folder for several releases after statements v2
        renamed it to `statement/` and moved the LaTeX chrome up to the contest.
        Nothing read it, so nothing could notice.

        Emits the fenced tree *and* its numbered annotation list together. The
        numbers have to be assigned by whoever walks the directory -- leaving
        the list in the page would make it positional again, and a preset that
        gained a file near the top would slide every annotation down one row
        without failing anything.
        """
        annotations = yaml.safe_load((_ROOT / annotations_path).read_text())

        paths = _tracked_preset_files(preset_dir)
        known = {str(p) for p in paths} | {
            str(parent) for p in paths for parent in p.parents if str(parent) != '.'
        }
        stale = sorted(set(annotations) - known)
        if stale:
            raise KeyError(
                f'{annotations_path} annotates {stale}, which the preset at '
                f'{preset_dir} no longer ships. Drop the entries, or point '
                'them at the paths that replaced them.'
            )

        rendered = [root_name]
        notes: list[str] = []
        for line, path in _tree_lines(paths):
            prose = annotations.get(path)
            if prose is None:
                # Shown but not annotated -- the sample files, and anything the
                # page has no reason to stop on.
                rendered.append(line)
                continue
            notes.append(prose.rstrip())
            rendered.append(f'{line} # ({len(notes)})!')

        body = '\n'.join(rendered)
        items = '\n\n'.join(
            _list_item(i, _resolve_vars(prose))
            for i, prose in enumerate(notes, start=1)
        )
        return f'```bash\n{body}\n```\n\n{items}\n'

    @env.macro
    def preset_tree() -> str:
        """What `rbx create` lays down -- the first-steps tree."""
        return _render_preset_tree(
            PRESET_PROBLEM_DIR, PRESET_TREE_ANNOTATIONS, PRESET_TREE_ROOT_NAME
        )

    @env.macro
    def contest_preset_tree() -> str:
        """What `rbx contest create` lays down -- the contest-scaffolding tree."""
        return _render_preset_tree(
            PRESET_CONTEST_DIR, CONTEST_TREE_ANNOTATIONS, CONTEST_TREE_ROOT_NAME
        )

    @env.macro
    def asciinema(id: str, idleness: float = 1, speed: float = 1, pause: float = 3):
        # A hosted recording is played by the same vendored player, just from a
        # remote source (asciinema.org serves `.cast` with
        # `Access-Control-Allow-Origin: *`). The alternative -- their `<script>`
        # embed -- brings its own player, which only takes `data-loop` and so
        # restarts the instant the last frame is drawn. Going through our player
        # is what gives every recording in the docs the same loop pause.
        if _LEGACY_ID.match(id):
            src = f'https://asciinema.org/a/{id}.cast'
        else:
            src = f'/assets/casts/{id}.cast'

        element_id = f'cast-{id}-{next(_counter)}'
        options = json.dumps(
            {'idleTimeLimit': idleness, 'speed': speed},
            sort_keys=True,
        )
        # `rbxCast` (assets/casts-loop.js) creates the player and holds its
        # final frame before looping. Both this macro and the home page template
        # go through it; calling AsciinemaPlayer.create directly is what left
        # the home page restarting instantly when the pause was added here.
        #
        # Both files are injected via `extra_javascript`, which Material places
        # at the end of <body> -- after this inline script. Waiting for
        # DOMContentLoaded is what guarantees they have run by the time we call.
        return f"""<div style="width: 90%; margin: 0 auto;">
<div id="{element_id}"></div>
<script>
  document.addEventListener('DOMContentLoaded', function () {{
    rbxCast('{src}', '{element_id}', {options}, {int(pause * 1000)});
  }});
</script>
</div>
"""
