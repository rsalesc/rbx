import pathlib
import sys
from typing import Dict, List

import mkdocs_gen_files
import yaml
from click import Argument, Command, Group, Option
from typer.main import get_command

# Fix for shadowing 'packaging' library by 'rbx/box/packaging' directory
# when the script directory is in sys.path.
script_dir = str(pathlib.Path(__file__).parent.resolve())
if script_dir in sys.path:
    sys.path.remove(script_dir)

# Import the main app
from rbx.box.cli import app as main_app  # noqa: E402

# Path to custom explanations
EXPLANATIONS_PATH = pathlib.Path('docs/setters/reference/cli_explanations.yaml')


def load_explanations() -> Dict[str, str]:
    if not EXPLANATIONS_PATH.exists():
        return {}
    with open(EXPLANATIONS_PATH, 'r') as f:
        return yaml.safe_load(f) or {}


EXPLANATIONS = load_explanations()


def render_command(command: Command, lineage: List[str]) -> str:
    """Renders a single command to Markdown."""

    # Construct normalized path for explanation lookup
    # Normalize each part of lineage: "build, b" -> "build"
    normalized_lineage = [part.split(',')[0].strip() for part in lineage]
    full_path_normalized = ' '.join(normalized_lineage)

    # Header
    output = []

    # Fallback to normalized path string if get_command_help isn't updated?
    # Actually get_command_help expects string. We can update it or just call dict directly
    # since we did normalization here.
    # Let's just use EXPLANATIONS directly since we normalized it here correctly.
    custom_help = EXPLANATIONS.get(full_path_normalized)

    if custom_help:
        output.append(custom_help)
        output.append('')
    elif command.help:
        output.append(command.help)
        output.append('')

    # Usage
    output.append('**Usage:**')
    usage_pieces = normalized_lineage[:]  # Copy

    # Collect arguments and options for usage string
    params = command.params
    for param in params:
        if isinstance(param, Argument):
            usage_pieces.append(f'<{param.name.upper()}>')
        elif isinstance(param, Option):
            pass  # We typically don't list all options in the usage line for complex CLIs, but we can if relevant

    output.append(f"```bash\n{' '.join(usage_pieces)} [OPTIONS]\n```")
    output.append('')

    # Arguments
    arguments = [p for p in params if isinstance(p, Argument)]
    if arguments:
        output.append('**Arguments:**')
        output.append('')
        output.append('| Name | Description | Required |')
        output.append('| :--- | :--- | :--- |')
        for arg in arguments:
            desc = arg.help or '-'
            required = 'Yes' if arg.required else 'No'
            output.append(f'| `{arg.name.upper()}` | {desc} | {required} |')
        output.append('')

    # Options
    options = [p for p in params if isinstance(p, Option)]
    if options:
        output.append('| Name | Type | Description | Default |')
        output.append('| :--- | :--- | :--- | :--- |')
        for opt in options:
            opts = ', '.join(f'`{o}`' for o in opt.opts)
            opt_type = opt.type.name.upper() if hasattr(opt.type, 'name') else 'TEXT'
            desc = opt.help or '-'
            default = opt.default
            if callable(default):
                default = default()

            if default is not None and str(default) != '':
                default = f'`{default}`'
            else:
                default = '-'
            output.append(f'| {opts} | {opt_type} | {desc} | {default} |')
        output.append('')

    return '\n'.join(output)


# Refined approach:
# We will generate `setters/reference/cli.md` as the main file.
# We can also generate `setters/reference/cli/_generated.md` and include it, or just write content directly.


class DocsGenerator:
    def __init__(self):
        self.content = []

    def get_full_command_path(self, lineage: List[str]) -> str:
        return ' '.join(lineage)

    def process_command(self, command: Command, lineage: List[str]):
        name = lineage[-1]
        # Format name for display: "list, ls" -> "list (ls)"
        parts = [p.strip() for p in name.split(',')]
        primary_name = parts[0]
        aliases = parts[1:]

        display_name = primary_name
        if aliases:
            display_name += f" ({', '.join(aliases)})"

        # Section header
        level = min(len(lineage), 6)  # h1, h2, h3...

        # If it's the root 'rbx', we use h1
        # If 'rbx build', h2
        # etc.

        self.content.append(f"{'#' * level} {display_name}\n")
        self.content.append(render_command(command, lineage))
        self.content.append('\n---\n')

        if isinstance(command, Group):
            for sub_name, sub_cmd in command.commands.items():
                if sub_cmd.hidden:
                    continue
                self.process_command(sub_cmd, lineage + [sub_name])


def generate():
    # Convert Typer app to Click command
    main_cmd = get_command(main_app)

    # We want to name the root command 'rbx'
    # typer sometimes names it 'main' or similar depending on function name

    generator = DocsGenerator()
    generator.process_command(main_cmd, ['rbx'])

    # Write to file
    with mkdocs_gen_files.open('setters/reference/cli.md', 'w') as f:
        f.write('\n'.join(generator.content))


generate()
