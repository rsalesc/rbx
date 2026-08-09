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
        # `loop` is deliberately off: the player restarts the instant the last
        # frame is drawn, and that frame -- the verdict table, the counterexample
        # -- is usually the point of the recording. We loop by hand instead,
        # after a fixed pause.
        #
        # The pause cannot live in the cast file. A trailing idle gap there is
        # first clamped to `idleTimeLimit` and then divided by `speed`, so a
        # recorded "3 second hold" plays as one second, or half of one at
        # `speed=2`. Pausing here is wall-clock and immune to both.
        options = json.dumps(
            {
                'autoPlay': True,
                'loop': False,
                'idleTimeLimit': idleness,
                'speed': speed,
                'fit': 'width',
            },
            sort_keys=True,
        )
        # The player bundle is injected via `extra_javascript`, which Material
        # places at the end of <body> -- after this inline script. Waiting for
        # DOMContentLoaded is what guarantees `AsciinemaPlayer` exists by the
        # time we call it.
        return f"""<div style="width: 90%; margin: 0 auto;">
<div id="{element_id}"></div>
<script>
  document.addEventListener('DOMContentLoaded', function () {{
    var player = AsciinemaPlayer.create('{src}', document.getElementById('{element_id}'), {options});
    var pending = null;
    player.addEventListener('ended', function () {{
      // `ended` can fire again while the restart is queued (a seek to the end,
      // a double-fire on some browsers); one pending restart is enough.
      if (pending !== null) {{
        return;
      }}
      pending = setTimeout(function () {{
        pending = null;
        player.seek(0);
        player.play();
      }}, {int(pause * 1000)});
    }});
  }});
</script>
</div>
"""
