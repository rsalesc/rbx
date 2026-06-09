"""Fast completion entry point. Imported and called by main.py BEFORE the heavy CLI.

Must import nothing heavy: only stdlib + (lazily) the engine/spec/click.
"""

import os
import sys

COMPLETE_VAR = '_RBX_COMPLETE'
_INSTRUCTIONS = ('complete', 'source')


def _parse_instruction(value: str):
    """Split the `_RBX_COMPLETE` value into (instruction, shell).

    Accepts BOTH orderings used in the wild: Typer's `complete_bash` /
    `source_zsh` (instruction first) and Click's `bash_complete` / `zsh_source`
    (shell first). This lets completion work regardless of which shell source
    script is installed -- including the one our own `source` instruction emits.
    """
    parts = value.split('_')
    if parts and parts[0] in _INSTRUCTIONS:
        return parts[0], '_'.join(parts[1:])
    if parts and parts[-1] in _INSTRUCTIONS:
        return parts[-1], '_'.join(parts[:-1])
    return parts[0] if parts else '', ''


def handle_completion() -> bool:
    """If this process is a completion request, serve it and return True.

    Returns False when not completing, so the caller proceeds with normal startup.
    Never raises and never imports the heavy app: on any error it emits a shell
    'file' directive so the shell falls back to its own (filename) completion.
    """
    instruction = os.environ.get(COMPLETE_VAR)
    if not instruction:
        return False
    try:
        kind, shell = _parse_instruction(instruction)
        from rbx.box.completion import engine

        if kind == 'complete':
            from rbx.box.completion import _spec, registry

            registry.register_all(_spec.COMPLETERS)
            sys.stdout.write(engine.complete_to_string(shell, _spec.SPEC))
        elif kind == 'source':
            sys.stdout.write(engine.source_to_string(shell))
        # Unknown instruction: emit nothing (the shell shows no completions).
    except Exception:
        sys.stdout.write('file,\n')  # never break the shell; let it default-complete
    return True
