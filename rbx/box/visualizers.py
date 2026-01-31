import pathlib
import shlex
from typing import Dict, List, Optional

from pydantic import BaseModel

from rbx import console
from rbx.box import package
from rbx.box.code import SanitizationLevel, compile_item, run_item
from rbx.box.generation_schema import GenerationTestcaseEntry
from rbx.box.schema import CodeItem, Testcase, Visualizer
from rbx.grading.steps import (
    CompilationError,
    DigestHolder,
    DigestOrDest,
    DigestOrSource,
    GradingFileOutput,
)
from rbx.utils import StatusProgress


class VisualizationPaths(BaseModel):
    input: Optional[pathlib.Path] = None
    output: Optional[pathlib.Path] = None

    def has_input(self) -> bool:
        return self.input is not None and self.input.is_file()

    def has_output(self) -> bool:
        return self.output is not None and self.output.is_file()


def _compile_visualizer(visualizer: CodeItem) -> str:
    try:
        digest = compile_item(visualizer, sanitized=SanitizationLevel.PREFER)
    except CompilationError as e:
        e.print(f'[error]Failed compiling visualizer {visualizer.href()}[/error]')
        raise
    return digest


def get_visualization_stems(testcase: Testcase) -> VisualizationPaths:
    paths = VisualizationPaths()
    if testcase.inputPath is not None:
        paths.input = (
            testcase.inputPath.parent / 'visualization' / testcase.inputPath.stem
        )

    if testcase.outputPath is not None:
        paths.output = (
            testcase.outputPath.parent
            / 'output_visualization'
            / testcase.outputPath.stem
        )
    return paths


def compile_visualizers(
    visualizers: List[CodeItem],
    progress: Optional[StatusProgress] = None,
) -> Dict[str, str]:
    visualizers_to_compiled_digest = {}

    for visualizer in visualizers:
        if str(visualizer.path) in visualizers_to_compiled_digest:
            continue

        if progress:
            progress.update(f'Compiling visualizer {visualizer.href()}...')
        visualizers_to_compiled_digest[str(visualizer.path)] = _compile_visualizer(
            visualizer
        )

    return visualizers_to_compiled_digest


def compile_package_visualizers(
    progress: Optional[StatusProgress] = None,
) -> Dict[str, str]:
    pkg = package.find_problem_package_or_die()
    visualizers = []
    if pkg.visualizer is not None:
        visualizers.append(pkg.visualizer)
    if pkg.outputVisualizer is not None:
        visualizers.append(pkg.outputVisualizer)
    return compile_visualizers(visualizers, progress=progress)


def compile_visualizers_for_entries(
    entries: List[GenerationTestcaseEntry],
    progress: Optional[StatusProgress] = None,
) -> Dict[str, str]:
    visualizers = []

    for entry in entries:
        if entry.visualizer is not None:
            visualizers.append(entry.visualizer)
        if entry.output_visualizer is not None:
            visualizers.append(entry.output_visualizer)

    return compile_visualizers(visualizers, progress=progress)


async def run_visualizer(
    visualizer: Visualizer,
    visualizer_digest: str,
    visualization_stem: pathlib.Path,
    input_path: pathlib.Path,
    output_path: Optional[pathlib.Path] = None,
    answer_path: Optional[pathlib.Path] = None,
) -> Optional[pathlib.Path]:
    visualization_stem.parent.mkdir(parents=True, exist_ok=True)
    visualization_path = visualization_stem.with_suffix(visualizer.get_suffix())
    sandbox_path = pathlib.Path('visualization').with_suffix(visualizer.get_suffix())

    args = [str(sandbox_path), str(input_path)]
    if output_path is not None:
        args.append(str(output_path))
    if answer_path is not None:
        args.append(str(answer_path))

    # We don't capture stdout/stderr to files, but we could if we wanted to debug.
    # For now, let's just run it and check exit code.
    stderr_holder = DigestHolder()
    run_log = await run_item(
        visualizer,
        DigestOrSource.create(visualizer_digest),
        stderr=DigestOrDest.create(stderr_holder),
        extra_args=shlex.join(args) if args else None,
        outputs=[
            GradingFileOutput(
                src=sandbox_path,
                dest=visualization_path,
                optional=True,
            ),
        ],
    )

    if run_log is None or run_log.exitcode != 0:
        console.console.print(f'[error]Visualizer {visualizer.href()} failed.[/error]')
        if run_log is not None:
            console.console.print(f'[error]Summary:[/error] {run_log.get_summary()}')
            console.console.print(
                f'[error]Stderr:[/error] {package.get_digest_as_string(stderr_holder.value or "")}'
            )
        return None

    return visualization_path


async def run_input_visualizer_for_testcase(
    testcase: Testcase,
    visualizer: Visualizer,
    visualizer_digest: str,
) -> Optional[pathlib.Path]:
    input_path = testcase.inputPath
    if not input_path.is_file():
        console.console.print(
            f'[error]Visualization failed: input file [item]{input_path}[/item] does not exist.[/error]'
        )
        return None

    visualization_dir = input_path.parent / 'visualization'
    visualization_stem = visualization_dir / input_path.stem

    return await run_visualizer(
        visualizer,
        visualizer_digest,
        visualization_stem,
        input_path=input_path,
    )


async def run_output_visualizer_for_testcase(
    testcase: Testcase,
    visualizer: Visualizer,
    visualizer_digest: str,
    answer_path: Optional[pathlib.Path] = None,
) -> Optional[pathlib.Path]:
    input_path = testcase.inputPath
    output_path = testcase.outputPath

    if not input_path.is_file() or output_path is None or not output_path.is_file():
        console.console.print(
            f'[error]Visualization failed: input file [item]{input_path}[/item] or output file [item]{output_path}[/item] does not exist.[/error]'
        )
        return None

    visualization_dir = output_path.parent / 'output_visualization'
    visualization_stem = visualization_dir / output_path.stem

    return await run_visualizer(
        visualizer,
        visualizer_digest,
        visualization_stem,
        input_path=input_path,
        output_path=output_path,
        answer_path=answer_path,
    )


async def run_input_visualizers_for_entries(
    entries: List[GenerationTestcaseEntry],
    compiled_visualizers: Dict[str, str],
    progress: Optional[StatusProgress] = None,
):
    for entry in entries:
        if entry.visualizer is None:
            continue

        digest = compiled_visualizers.get(str(entry.visualizer.path))
        if digest is None:
            continue

        if progress:
            progress.update(f'Running input visualizer for {entry.group_entry}...')

        if not await run_input_visualizer_for_testcase(
            entry.metadata.copied_to,
            entry.visualizer,
            digest,
        ):
            console.console.print(
                f'[error]Input visualizer failed for [item]{entry.group_entry}[/item].[/error]'
            )


async def run_output_visualizers_for_entries(
    entries: List[GenerationTestcaseEntry],
    compiled_visualizers: Dict[str, str],
    progress: Optional[StatusProgress] = None,
):
    for entry in entries:
        if entry.output_visualizer is None:
            continue

        digest = compiled_visualizers.get(str(entry.output_visualizer.path))
        if digest is None:
            continue

        if progress:
            progress.update(f'Running output visualizer for {entry.group_entry}...')

        if not await run_output_visualizer_for_testcase(
            entry.metadata.copied_to,
            entry.output_visualizer,
            digest,
        ):
            console.console.print(
                f'[error]Output visualizer failed for [item]{entry.group_entry}[/item].[/error]'
            )


async def run_visualizers_for_entries(
    entries: List[GenerationTestcaseEntry],
    progress: Optional[StatusProgress] = None,
):
    compiled_visualizers = compile_visualizers_for_entries(entries, progress=progress)

    if not compiled_visualizers:
        return

    await run_input_visualizers_for_entries(
        entries, compiled_visualizers, progress=progress
    )
    await run_output_visualizers_for_entries(
        entries, compiled_visualizers, progress=progress
    )


async def run_visualizers_for_testcase(
    testcase: Testcase,
    answer_path: Optional[pathlib.Path] = None,
    progress: Optional[StatusProgress] = None,
    compiled_visualizers: Optional[Dict[str, str]] = None,
) -> VisualizationPaths:
    if compiled_visualizers is None:
        compiled_visualizers = compile_package_visualizers(progress=progress)

    pkg = package.find_problem_package_or_die()
    paths = VisualizationPaths()

    if progress:
        progress.update('Running visualizers...')

    if pkg.visualizer is not None:
        visualizer_digest = compiled_visualizers.get(str(pkg.visualizer.path))
        if visualizer_digest is not None:
            paths.input = await run_input_visualizer_for_testcase(
                testcase,
                pkg.visualizer,
                visualizer_digest,
            )

    if pkg.outputVisualizer is not None:
        visualizer_digest = compiled_visualizers.get(str(pkg.outputVisualizer.path))
        if visualizer_digest is not None:
            paths.output = await run_output_visualizer_for_testcase(
                testcase,
                pkg.outputVisualizer,
                visualizer_digest,
                answer_path,
            )

    return paths
