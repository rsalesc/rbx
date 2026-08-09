"""
File for defining mkdocs macros.
"""

import itertools
import json
import re

# asciinema.org url tokens are 25 chars of [A-Za-z0-9]. Anything else is the
# basename of a cast committed under docs/assets/casts.
_LEGACY_ID = re.compile(r'^[A-Za-z0-9]{25}$')

_counter = itertools.count()


def define_env(env):
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
