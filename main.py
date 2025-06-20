"""
File for defining mkdocs macros.
"""


def define_env(env):
    @env.macro
    def asciinema(id: str, idleness: float = 1, speed: float = 1):
        return f"""<div style="width: 90%; margin: 0 auto;">
<script src="https://asciinema.org/a/{id}.js" id="asciicast-{id}" async="true" data-autoplay data-loop data-idle-time-limit="{idleness}" data-speed="{speed}"></script>
</div>
"""
