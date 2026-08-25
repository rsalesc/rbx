import pathlib
import re
import sys
from enum import Enum
from typing import List, Tuple, Union, get_args, get_origin, get_type_hints

import mkdocs_gen_files
from click import Argument, Choice, Command, Group, Option
from typer.main import get_command

# Fix for shadowing 'packaging' library by 'rbx/box/packaging' directory
# when the script directory is in sys.path.
script_dir = str(pathlib.Path(__file__).parent.resolve())
if script_dir in sys.path:
    sys.path.remove(script_dir)

# Import the main app
from rbx import annotations  # noqa: E402
from rbx.box.cli import app as main_app  # noqa: E402
from rbx.box.completion.generate import (  # noqa: E402
    help_panel,
    materialize_lazy_commands,
)

# Title Typer/Click gives to commands that declare no `rich_help_panel`. It is
# always rendered first in `--help`, and we mirror that here.
DEFAULT_PANEL = 'Commands'


def unwrap_type(tp):
    origin = get_origin(tp)
    if origin is Union:
        args = get_args(tp)
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return unwrap_type(non_none[0])
        return tp

    # Handle Annotated
    if origin is not None and getattr(origin, '__name__', '') == 'Annotated':
        return unwrap_type(get_args(tp)[0])

    return tp


def get_enum_link(tp) -> Union[str, None]:
    try:
        if isinstance(tp, type) and issubclass(tp, Enum):
            return f'[{tp.__name__}][{tp.__module__}.{tp.__name__}]'
    except Exception:
        pass
    return None


def primary_name(name: str) -> str:
    """`'build, b'` -> `'build'`."""
    return name.split(',')[0].strip()


def display_name(name: str) -> str:
    """`'build, b'` -> `'build (b)'`."""
    parts = [p.strip() for p in name.split(',')]
    if len(parts) == 1:
        return parts[0]
    return f'{parts[0]} ({", ".join(parts[1:])})'


def anchor_for(lineage: List[str]) -> str:
    """A stable, unique anchor built from the full command path.

    Leaf names repeat all over the tree (five commands are called `build`), so
    anchoring on the leaf alone yields `#build-b_3`-style ids that shift
    whenever a command is added. The full path is unique by construction.
    """
    slug = '-'.join(primary_name(part) for part in lineage)
    return re.sub(r'[^a-z0-9]+', '-', slug.lower()).strip('-')


def short_help(command: Command) -> str:
    help_text = command.short_help or command.help or ''
    # Only the first paragraph, on a single line: this goes inside a table cell.
    first = help_text.strip().split('\n\n')[0]
    return ' '.join(first.split()) or '-'


def group_children(
    group: Group,
) -> List[Tuple[str, List[Tuple[str, Command]]]]:
    """Bucket a group's visible subcommands the way `--help` does.

    Panels come out in order of first appearance (with the default panel first,
    as Typer renders it) and commands are alphabetical within each panel.
    """
    materialize_lazy_commands(group)
    order: List[str] = []
    buckets: dict = {}
    for name, command in group.commands.items():
        if command.hidden:
            continue
        panel = help_panel(command) or DEFAULT_PANEL
        if panel not in buckets:
            buckets[panel] = []
            order.append(panel)
        buckets[panel].append((name, command))

    if DEFAULT_PANEL in buckets:
        order.remove(DEFAULT_PANEL)
        order.insert(0, DEFAULT_PANEL)

    for panel in order:
        buckets[panel].sort(key=lambda entry: primary_name(entry[0]))

    return [(panel, buckets[panel]) for panel in order]


class DocsGenerator:
    def __init__(self):
        self.content = []
        self.seen_enums = set()

    def render_index_table(
        self, entries: List[Tuple[str, Command]], lineage: List[str]
    ) -> None:
        """A `--help`-like table of commands, linking to their sections."""
        if not entries:
            return
        self.content.append('| Command | Description |')
        self.content.append('| :--- | :--- |')
        for name, command in entries:
            child_lineage = lineage + [name]
            path = ' '.join(primary_name(part) for part in child_lineage)
            link = f'[`{path}`](#{anchor_for(child_lineage)})'
            self.content.append(f'| {link} | {short_help(command)} |')
        self.content.append('')

    def render_command(self, command: Command, lineage: List[str]) -> str:
        """Renders a single command's prose, usage, arguments and options."""
        normalized_lineage = [primary_name(part) for part in lineage]

        hints = {}
        if command.callback:
            try:
                hints = get_type_hints(command.callback)
            except Exception:
                pass

        output = []

        # The docs-only explanation attached with `@annotations.docs`, if any;
        # otherwise the terminal help.
        explanation = (
            annotations.get_docs(command.callback) if command.callback else None
        )
        if explanation:
            output.append(explanation)
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

        output.append(f'```bash\n{" ".join(usage_pieces)} [OPTIONS]\n```')
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
                opt_type = (
                    opt.type.name.upper() if hasattr(opt.type, 'name') else 'TEXT'
                )
                desc = opt.help or '-'

                # Type resolution
                param_name = opt.name
                target_type = None
                if param_name:
                    target_type = hints.get(param_name) or hints.get(
                        param_name.replace('-', '_')
                    )

                enum_link = None

                # Special handling for VerificationLevel
                if param_name in ('verification', 'verification_level'):
                    from rbx.box.environment import VerificationLevel

                    self.seen_enums.add(VerificationLevel)
                    enum_link = f'INTEGER of [{VerificationLevel.__name__}][{VerificationLevel.__module__}.{VerificationLevel.__name__}]'
                elif target_type:
                    unwrapped = unwrap_type(target_type)
                    # Register enum if found
                    if isinstance(unwrapped, type) and issubclass(unwrapped, Enum):
                        self.seen_enums.add(unwrapped)
                    enum_link = get_enum_link(unwrapped)

                if enum_link:
                    opt_type = enum_link
                elif isinstance(opt.type, Choice):
                    desc += f' <br> **Choices:** {", ".join(f"`{c}`" for c in opt.type.choices)}'

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

    def process_command(self, command: Command, lineage: List[str], level: int):
        self.content.append(
            f'{"#" * level} {display_name(lineage[-1])} {{ #{anchor_for(lineage)} }}\n'
        )
        self.content.append(self.render_command(command, lineage))

        if not isinstance(command, Group):
            self.content.append('\n---\n')
            return

        panels = group_children(command)
        # Only surface panel headings where the CLI itself has more than one:
        # a single (usually default) panel adds a level of nesting for nothing.
        titled = len(panels) > 1

        if not titled:
            for _, entries in panels:
                self.render_index_table(entries, lineage)
        self.content.append('\n---\n')

        for panel, entries in panels:
            child_level = level + 1
            if titled:
                self.content.append(
                    f'{"#" * (level + 1)} {panel} '
                    f'{{ #{anchor_for(lineage + [panel])} }}\n'
                )
                self.render_index_table(entries, lineage)
                child_level = level + 2
            for name, child in entries:
                self.process_command(child, lineage + [name], min(child_level, 6))

    def render_enums(self):
        if not self.seen_enums:
            return

        self.content.append('# Generic Types\n')
        # Sort by name for stability
        sorted_enums = sorted(self.seen_enums, key=lambda e: e.__name__)
        for enum_cls in sorted_enums:
            self.content.append(f'::: {enum_cls.__module__}.{enum_cls.__name__}')
            self.content.append('    options:')
            self.content.append('      show_root_heading: true')
            self.content.append('      show_root_full_path: false')
            self.content.append('      heading_level: 3')
            self.content.append('      show_labels: false')
            self.content.append('      members_order: source')
            self.content.append('')


def generate():
    # Convert Typer app to Click command
    main_cmd = get_command(main_app)

    # We want to name the root command 'rbx'
    # typer sometimes names it 'main' or similar depending on function name

    generator = DocsGenerator()
    generator.process_command(main_cmd, ['rbx'], level=1)
    generator.render_enums()

    # Write to file
    with mkdocs_gen_files.open('setters/reference/cli.md', 'w') as f:
        f.write('\n'.join(generator.content))


generate()
