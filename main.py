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
    def asciinema(id: str, idleness: float = 1, speed: float = 1):
        if _LEGACY_ID.match(id):
            return f"""<div style="width: 90%; margin: 0 auto;">
<script src="https://asciinema.org/a/{id}.js" id="asciicast-{id}" async="true" data-autoplay data-loop data-idle-time-limit="{idleness}" data-speed="{speed}"></script>
</div>
"""

        element_id = f'cast-{id}-{next(_counter)}'
        options = json.dumps(
            {
                'autoPlay': True,
                'loop': True,
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
    AsciinemaPlayer.create('/assets/casts/{id}.cast', document.getElementById('{element_id}'), {options});
  }});
</script>
</div>
"""
