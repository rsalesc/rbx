import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rbx.box import visualizers
from rbx.box.generation_schema import GenerationMetadata, GenerationTestcaseEntry
from rbx.box.schema import Testcase, Visualizer
from rbx.box.testcase_schema import TestcaseEntry
from rbx.grading.steps import CompilationError


@pytest.fixture(autouse=True)
def clear_visualizer_caches():
    """Clear the alru_cache on compile_visualizers_for_entries between tests."""
    visualizers.compile_visualizers_for_entries.cache_clear()
    yield
    visualizers.compile_visualizers_for_entries.cache_clear()


@pytest.fixture
def mock_compile_item():
    with patch('rbx.box.visualizers.compile_item', new_callable=AsyncMock) as mock:
        mock.return_value = 'compiled_digest'
        yield mock


@pytest.fixture
def mock_run_item():
    with patch('rbx.box.visualizers.run_item', new_callable=AsyncMock) as mock:
        mock.return_value = MagicMock(exitcode=0)
        yield mock


def _make_entry(
    input_path: pathlib.Path = pathlib.Path('test.in'),
    output_path: pathlib.Path | None = None,
    visualizer: Visualizer | None = None,
    solution_visualizer: Visualizer | None = None,
    index: int = 0,
) -> GenerationTestcaseEntry:
    return GenerationTestcaseEntry(
        group_entry=TestcaseEntry(group='g1', index=index),
        subgroup_entry=TestcaseEntry(group='g1', index=index),
        metadata=GenerationMetadata(
            copied_to=Testcase(inputPath=input_path, outputPath=output_path)
        ),
        visualizer=visualizer,
        solution_visualizer=solution_visualizer,
    )


# ---------------------------------------------------------------------------
# get_visualization_stems
# ---------------------------------------------------------------------------


def test_get_visualization_stems_input_only():
    tc = Testcase(inputPath=pathlib.Path('dir/test.in'))
    stems = visualizers.get_visualization_stems(tc)
    assert stems.input == pathlib.Path('dir/visualization/test')
    assert stems.output is None


def test_get_visualization_stems_with_output():
    tc = Testcase(
        inputPath=pathlib.Path('dir/test.in'), outputPath=pathlib.Path('dir/test.out')
    )
    stems = visualizers.get_visualization_stems(tc)
    assert stems.input == pathlib.Path('dir/visualization/test')
    assert stems.output == pathlib.Path('dir/output_visualization/test')


# ---------------------------------------------------------------------------
# compile_visualizers / compile_package_visualizers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compile_visualizers_dedupes_by_path(mock_compile_item):
    visualizer = Visualizer(path=pathlib.Path('vis.py'), extension='svg')
    other = Visualizer(path=pathlib.Path('out_vis.py'), extension='png')

    compiled = await visualizers.compile_visualizers([visualizer, visualizer, other])

    assert compiled == {
        'vis.py': 'compiled_digest',
        'out_vis.py': 'compiled_digest',
    }
    assert mock_compile_item.call_count == 2


@pytest.mark.asyncio
async def test_compile_package_visualizers(mock_compile_item):
    pkg_mock = MagicMock()
    pkg_mock.visualizer = Visualizer(path=pathlib.Path('vis.py'), extension='svg')
    pkg_mock.solutionVisualizer = Visualizer(
        path=pathlib.Path('out_vis.py'), extension='png'
    )

    with patch(
        'rbx.box.visualizers.package.find_problem_package_or_die', return_value=pkg_mock
    ):
        compiled = await visualizers.compile_package_visualizers()

    assert compiled == {
        'vis.py': 'compiled_digest',
        'out_vis.py': 'compiled_digest',
    }
    assert mock_compile_item.call_count == 2


@pytest.mark.asyncio
async def test_compile_package_visualizers_falls_back_to_input_for_solution(
    mock_compile_item,
):
    pkg_mock = MagicMock()
    pkg_mock.visualizer = Visualizer(path=pathlib.Path('vis.py'), extension='svg')
    pkg_mock.solutionVisualizer = None

    with patch(
        'rbx.box.visualizers.package.find_problem_package_or_die', return_value=pkg_mock
    ):
        compiled = await visualizers.compile_package_visualizers()

    assert compiled == {'vis.py': 'compiled_digest'}
    # Called once: the input visualizer is reused as solution visualizer and dedupes.
    assert mock_compile_item.call_count == 1


@pytest.mark.asyncio
async def test_compile_visualizers_failure_prints_and_reraises():
    visualizer = Visualizer(path=pathlib.Path('vis.py'), extension='svg')

    class _MockCompilationError(CompilationError):
        def __init__(self):
            self.print_called = False

        def print(self, *args, **kwargs):
            self.print_called = True

    err = _MockCompilationError()

    with patch(
        'rbx.box.visualizers.compile_item',
        new_callable=AsyncMock,
        side_effect=err,
    ):
        with pytest.raises(CompilationError):
            await visualizers.compile_visualizers([visualizer])

    assert err.print_called


# ---------------------------------------------------------------------------
# run_visualizer (low-level)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_visualizer_passes_sandbox_args_and_outputs(mock_run_item):
    visualizer = Visualizer(path=pathlib.Path('vis.py'), extension='svg')
    input_path = pathlib.Path('test.in')
    stem = pathlib.Path('visualization/test')

    with patch('pathlib.Path.mkdir'):
        result = await visualizers.run_visualizer(
            visualizer,
            'digest',
            stem,
            input_path,
        )

    assert result == pathlib.Path('visualization/test.svg')
    mock_run_item.assert_called_once()
    args, kwargs = mock_run_item.call_args
    # Positional: visualizer, DigestOrSource(digest='digest')
    assert args[0] == visualizer
    assert args[1].digest.value == 'digest'

    # Sandbox paths are fixed (input.txt etc.), not the host paths.
    assert kwargs['extra_args'] == 'visualization.svg input.txt'

    # Single output: visualization.svg → host stem with extension.
    outputs = kwargs['outputs']
    assert len(outputs) == 1
    assert outputs[0].src == pathlib.Path('visualization.svg')
    assert outputs[0].dest == pathlib.Path('visualization/test.svg')

    # Single input: host input file mapped onto sandbox `input.txt`.
    inputs = kwargs['inputs']
    assert len(inputs) == 1
    assert inputs[0].src == input_path
    assert inputs[0].dest == pathlib.Path('input.txt')


@pytest.mark.asyncio
async def test_run_visualizer_with_output_path(mock_run_item):
    visualizer = Visualizer(path=pathlib.Path('vis.py'), extension='png')
    input_path = pathlib.Path('test.in')
    output_path = pathlib.Path('test.out')
    stem = pathlib.Path('output_visualization/test')

    with patch('pathlib.Path.mkdir'):
        await visualizers.run_visualizer(
            visualizer,
            'digest',
            stem,
            input_path,
            output_path=output_path,
        )

    _, kwargs = mock_run_item.call_args
    assert kwargs['extra_args'] == 'visualization.png input.txt output.txt'
    inputs = kwargs['inputs']
    assert [str(i.dest) for i in inputs] == ['input.txt', 'output.txt']


@pytest.mark.asyncio
async def test_run_visualizer_failure_raises(mock_run_item):
    visualizer = Visualizer(path=pathlib.Path('vis.py'), extension='svg')
    mock_run_item.return_value = MagicMock(
        exitcode=1, get_summary=lambda: 'failed', stderr_absolute_path=None
    )

    with patch('pathlib.Path.mkdir'):
        with pytest.raises(visualizers.VisualizationError):
            await visualizers.run_visualizer(
                visualizer,
                'digest',
                pathlib.Path('visualization/test'),
                pathlib.Path('test.in'),
            )


@pytest.mark.asyncio
async def test_run_visualizer_special_exit_code_skips(mock_run_item):
    visualizer = Visualizer(path=pathlib.Path('vis.py'), extension='svg')
    mock_run_item.return_value = MagicMock(exitcode=visualizers.SPECIAL_CODE)

    with patch('pathlib.Path.mkdir'):
        result = await visualizers.run_visualizer(
            visualizer,
            'digest',
            pathlib.Path('visualization/test'),
            pathlib.Path('test.in'),
        )

    assert result is None


# ---------------------------------------------------------------------------
# run_input_visualizer_for_testcase / run_solution_visualizer_for_testcase
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_input_visualizer_for_testcase_missing_input(mock_run_item):
    visualizer = Visualizer(path=pathlib.Path('vis.py'), extension='svg')
    tc = Testcase(inputPath=pathlib.Path('missing.in'))

    with patch.object(pathlib.Path, 'is_file', return_value=False):
        with pytest.raises(visualizers.VisualizationError):
            await visualizers.run_input_visualizer_for_testcase(
                tc, visualizer, 'digest'
            )

    mock_run_item.assert_not_called()


@pytest.mark.asyncio
async def test_run_solution_visualizer_for_testcase_missing_files(mock_run_item):
    visualizer = Visualizer(path=pathlib.Path('vis.py'), extension='png')
    tc = Testcase(
        inputPath=pathlib.Path('test.in'), outputPath=pathlib.Path('test.out')
    )

    # Missing input.
    with patch.object(pathlib.Path, 'is_file', side_effect=[False, True]):
        with pytest.raises(visualizers.VisualizationError):
            await visualizers.run_solution_visualizer_for_testcase(
                tc, visualizer, 'digest'
            )

    # Missing output.
    with patch.object(pathlib.Path, 'is_file', side_effect=[True, False]):
        with pytest.raises(visualizers.VisualizationError):
            await visualizers.run_solution_visualizer_for_testcase(
                tc, visualizer, 'digest'
            )

    mock_run_item.assert_not_called()


# ---------------------------------------------------------------------------
# *_for_entries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_input_visualizers_for_entries_invokes_run_visualizer(mock_run_item):
    visualizer = Visualizer(path=pathlib.Path('vis.py'), extension='svg')
    entries = [_make_entry(visualizer=visualizer)]
    compiled = {'vis.py': 'digest'}

    with (
        patch.object(pathlib.Path, 'is_file', return_value=True),
        patch('pathlib.Path.mkdir'),
    ):
        await visualizers.run_input_visualizers_for_entries(entries, compiled)

    mock_run_item.assert_called_once()
    args, kwargs = mock_run_item.call_args
    assert args[0] == visualizer
    assert args[1].digest.value == 'digest'
    assert kwargs['extra_args'] == 'visualization.svg input.txt'


@pytest.mark.asyncio
async def test_run_solution_visualizers_for_entries_invokes_run_visualizer(
    mock_run_item,
):
    output_visualizer = Visualizer(path=pathlib.Path('out_vis.py'), extension='png')
    entries = [
        _make_entry(
            input_path=pathlib.Path('test.in'),
            output_path=pathlib.Path('test.out'),
            solution_visualizer=output_visualizer,
        )
    ]
    compiled = {'out_vis.py': 'digest'}

    with (
        patch.object(pathlib.Path, 'is_file', return_value=True),
        patch('pathlib.Path.mkdir'),
    ):
        await visualizers.run_solution_visualizers_for_entries(entries, compiled)

    mock_run_item.assert_called_once()
    _, kwargs = mock_run_item.call_args
    assert kwargs['extra_args'] == 'visualization.png input.txt output.txt'


@pytest.mark.asyncio
async def test_run_input_visualizers_for_entries_skips_when_no_digest(mock_run_item):
    visualizer = Visualizer(path=pathlib.Path('vis.py'), extension='svg')
    entries = [_make_entry(visualizer=visualizer)]

    await visualizers.run_input_visualizers_for_entries(
        entries, compiled_visualizers={}
    )

    mock_run_item.assert_not_called()


# ---------------------------------------------------------------------------
# run_visualizers_for_testcase
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_visualizers_for_testcase_returns_input_path(mock_run_item):
    pkg_mock = MagicMock()
    pkg_mock.visualizer = Visualizer(path=pathlib.Path('vis.py'), extension='svg')
    pkg_mock.solutionVisualizer = None

    tc = Testcase(inputPath=pathlib.Path('test.in'))
    compiled = {'vis.py': 'digest'}

    with (
        patch(
            'rbx.box.visualizers.package.find_problem_package_or_die',
            return_value=pkg_mock,
        ),
        patch.object(pathlib.Path, 'is_file', return_value=True),
        patch('pathlib.Path.mkdir'),
    ):
        result = await visualizers.run_visualizers_for_testcase(
            tc, compiled_visualizers=compiled
        )

    # Return is the host-side visualization path.
    assert result == pathlib.Path('visualization/test.svg')
    mock_run_item.assert_called_once()
