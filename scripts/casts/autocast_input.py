"""Translation from a `RecordingSpec` into autocast's input schema."""

from typing import Any, Dict, List, Optional

from scripts.casts.spec import RecordingSpec, Tagged

SENTINEL_PROMPT = 'AUTOCAST_PROMPT'

# Forcing PS1 to a sentinel is how autocast detects that a command finished;
# disabling bracketed paste keeps stray escape sequences out of the cast.
_PROMPT_COMMAND = (
    f'PS1={SENTINEL_PROMPT}; unset PROMPT_COMMAND; '
    "bind 'set enable-bracketed-paste off'"
)


def _env_pairs(spec: RecordingSpec, home: Optional[str]) -> List[Dict[str, str]]:
    env = {
        'PROMPT_COMMAND': _PROMPT_COMMAND,
        'TERM': 'xterm-256color',
        'COLUMNS': str(spec.width),
        'LINES': str(spec.height),
        'LC_ALL': 'C.UTF-8',
        'LANG': 'C.UTF-8',
        'TZ': 'UTC',
    }
    if home is not None:
        env['HOME'] = home
    return [{'name': name, 'value': value} for name, value in env.items()]


def _hidden(command: str) -> Tagged:
    return Tagged('Command', {'command': command, 'hidden': True})


def build_autocast_input(
    spec: RecordingSpec, workdir: str, home: Optional[str] = None
) -> Dict[str, Any]:
    settings: Dict[str, Any] = {
        'width': spec.width,
        'height': spec.height,
        'type_speed': spec.type_speed,
        'timeout': spec.timeout,
        'prompt': '$ ',
        'secondary_prompt': '> ',
        'shell': {
            'program': 'bash',
            'args': ['--norc', '--noprofile'],
            'prompt': SENTINEL_PROMPT,
            'quit_command': 'exit',
        },
        'environment': _env_pairs(spec, home),
    }
    if spec.title is not None:
        settings['title'] = spec.title

    instructions: List[Any] = [_hidden(f'cd {workdir}')]
    instructions.extend(_hidden(command) for command in spec.setup)
    for instruction in spec.instructions:
        if isinstance(instruction, str):
            instructions.append(
                Tagged('Command', {'command': instruction, 'hidden': False})
            )
        else:
            instructions.append(instruction)

    return {'settings': settings, 'instructions': instructions}
