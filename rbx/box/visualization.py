"""``rbx visualize`` -- run a visualizer for a single testcase, on demand.

The engine lives in :mod:`rbx.box.visualizers`; this module is only a command
surface over it. It exists because an editor integration needs to visualize
*one* testcase -- in particular a *solution's* output, which no build flag
reaches: ``rbx build --visualize`` visualizes the testset's inputs and expected
answers, while a solution's output is produced by ``rbx run`` and lives under
the cache, per solution.

The protocol is exit codes plus one line of stdout, so a caller needs no parser:

=====  ================================================
0      artifact produced; its absolute path on stdout
42     visualizer ran interactively and produced no file
3      cache-format skew; refused, nothing touched
1      failure; a rich message on stderr
=====  ================================================

42 is :data:`rbx.box.visualizers.SPECIAL_CODE` promoted to this command's own
exit code, so the visualizer's contract and the command's contract are the same
number.
"""

import pathlib
from typing import Annotated, List, Optional

import syncer
import typer

from rbx import annotations, console, utils
from rbx.annotations import PackagePath
from rbx.box import package, visualizers
from rbx.box.exception import RbxException
from rbx.box.schema import Testcase, Visualizer
from rbx.grading import grading_context

app = typer.Typer(no_args_is_help=True, cls=annotations.AliasGroup)

#: Ran interactively and wrote nothing. Not a failure -- see ``SPECIAL_CODE``.
EXIT_INTERACTIVE = visualizers.SPECIAL_CODE

#: This rbx's cache format differs from the one that built the package.
#
# Raised by `cli._refuse_incompatible_cache`, NOT here. The clear-on-mismatch it
# guards against happens in the root app callback, which runs before any
# sub-command, so a guard in this module would always find the cache -- and the
# build tree -- already gone.
EXIT_CACHE_SKEW = 3


@app.callback()
def callback():
    """Visualize a single testcase (sub-command)."""
    # Without an explicit callback Typer would collapse a multi-command app
    # differently than the rest of the CLI presents its sub-apps.


def _require(path: Optional[pathlib.Path], what: str) -> pathlib.Path:
    if path is None or not path.is_file():
        console.stderr_console.print(
            f'[error]{what} [item]{path}[/item] does not exist.[/error]'
        )
        raise typer.Exit(1)
    return path


def _report(visualization_path: Optional[pathlib.Path]) -> None:
    """Emit the protocol described in the module docstring."""
    if visualization_path is None or not visualization_path.is_file():
        # The visualizer said it interacted with the user instead of writing a
        # file. That is a success with nothing to open.
        raise typer.Exit(EXIT_INTERACTIVE)

    # Plain `print`, not the rich console: this line is the machine-readable
    # half of the protocol and must not carry markup, wrapping or highlighting.
    print(utils.abspath(visualization_path))


def _compiled(visualizer: Visualizer, compiled: dict) -> str:
    digest = compiled.get(str(visualizer.path))
    if digest is None:
        console.stderr_console.print(
            f'[error]Visualizer {visualizer.href()} was not compiled.[/error]'
        )
        raise typer.Exit(1)
    return digest


def _stderr_of(path: pathlib.Path) -> pathlib.Path:
    return path.with_suffix('.err')


@app.command('input', help='Visualize a testcase input.')
@annotations.docs("""
    Run the *input* visualizer for one testcase and print where it landed.

    Addressing is by path: `--input` is the testcase's input file, and the
    optional `--output` is an output to hand the visualizer alongside it.
""")
@package.within_problem
@syncer.sync
async def visualize_input(
    input_path: Annotated[
        pathlib.Path,
        PackagePath,
        typer.Option('--input', help='Path to the testcase input to visualize.'),
    ],
    output_path: Annotated[
        Optional[pathlib.Path],
        PackagePath,
        typer.Option('--output', help='Optional output to pass to the visualizer.'),
    ] = None,
    dest: Annotated[
        Optional[pathlib.Path],
        PackagePath,
        typer.Option(
            '--dest',
            help='Where to write the visualization, WITHOUT an extension. '
            'The visualizer decides the extension, and the final path is printed.',
        ),
    ] = None,
    use_stderr: bool = typer.Option(
        False,
        '--use-stderr',
        help="Shorthand for passing the sibling '.err' file instead of the output.",
    ),
):
    input_path = _require(input_path, 'Input')
    if use_stderr:
        output_path = _stderr_of(output_path or input_path)

    visualizer, _ = await visualizers.resolve_visualizers_for_input(input_path)
    if visualizer is None:
        console.stderr_console.print('[error]No input visualizer declared.[/error]')
        raise typer.Exit(1)

    with grading_context.cache_level(grading_context.CacheLevel.CACHE_COMPILATION):
        compiled = await visualizers.compile_visualizers([visualizer])
        try:
            visualization_path = await visualizers.run_input_visualizer_for_testcase(
                Testcase(inputPath=input_path, outputPath=output_path),
                visualizer,
                _compiled(visualizer, compiled),
                answer_from=visualizers.get_answer_from_with_digest(
                    visualizer, compiled
                ),
                interactive=True,
                visualization_stem=dest,
            )
        except RbxException as e:
            console.stderr_console.print(e.plain())
            raise typer.Exit(1) from e

    _report(visualization_path)


@app.command('output', help="Visualize a solution's output for a testcase.")
@annotations.docs("""
    Run the *solution* visualizer for one testcase's output.

    `--output` is the output to visualize -- a solution's output from a run, or
    the testset's expected answer, or any other file. `--answer` is an optional
    second output to compare it against.
""")
@package.within_problem
@syncer.sync
async def visualize_output(
    input_path: Annotated[
        pathlib.Path,
        PackagePath,
        typer.Option('--input', help='Path to the testcase input.'),
    ],
    output_path: Annotated[
        pathlib.Path,
        PackagePath,
        typer.Option('--output', help='Path to the output to visualize.'),
    ],
    answer_path: Annotated[
        Optional[pathlib.Path],
        PackagePath,
        typer.Option('--answer', help='Optional answer to compare the output against.'),
    ] = None,
    dest: Annotated[
        Optional[pathlib.Path],
        PackagePath,
        typer.Option(
            '--dest',
            help='Where to write the visualization, WITHOUT an extension. '
            'The visualizer decides the extension, and the final path is printed.',
        ),
    ] = None,
    use_stderr: bool = typer.Option(
        False,
        '--use-stderr',
        help="Shorthand for visualizing the sibling '.err' file instead. "
        'Prefer passing the stderr file to --output directly: on a communication '
        "task the solution's stderr is '.sol.err', which this cannot name.",
    ),
):
    input_path = _require(input_path, 'Input')
    if use_stderr:
        output_path = _stderr_of(output_path)
    output_path = _require(output_path, 'Output')

    _, visualizer = await visualizers.resolve_visualizers_for_input(input_path)
    if visualizer is None:
        console.stderr_console.print('[error]No solution visualizer declared.[/error]')
        raise typer.Exit(1)

    with grading_context.cache_level(grading_context.CacheLevel.CACHE_COMPILATION):
        compiled = await visualizers.compile_visualizers([visualizer])
        answer_from = visualizers.get_answer_from_with_digest(visualizer, compiled)
        try:
            visualization_path = await visualizers.run_solution_visualizer_for_testcase(
                Testcase(inputPath=input_path, outputPath=output_path),
                visualizer,
                _compiled(visualizer, compiled),
                answer_path,
                output_from=answer_from,
                answer_from=answer_from if answer_path is not None else None,
                interactive=True,
                visualization_stem=dest,
            )
        except RbxException as e:
            console.stderr_console.print(e.plain())
            raise typer.Exit(1) from e

    _report(visualization_path)


__all__: List[str] = ['app', 'EXIT_INTERACTIVE', 'EXIT_CACHE_SKEW']
