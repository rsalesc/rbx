import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rbx.box import visualizers
from rbx.box.generation_schema import GenerationMetadata, GenerationTestcaseEntry
from rbx.box.schema import Testcase, Visualizer
from rbx.box.testcase_utils import TestcaseEntry
from rbx.grading.steps import CompilationError


@pytest.fixture
def mock_compile_item():
    with patch('rbx.box.visualizers.compile_item') as mock:
        mock.return_value = 'compiled_digest'
        yield mock


@pytest.fixture
def mock_run_item():
    with patch('rbx.box.visualizers.run_item', new_callable=AsyncMock) as mock:
        mock.return_value = MagicMock(exitcode=0)
        yield mock


def test_compile_visualizers_for_entries(mock_compile_item):
    visualizer = Visualizer(path=pathlib.Path('vis.py'), extension='svg')
    output_visualizer = Visualizer(path=pathlib.Path('output_vis.py'), extension='png')
    entries = [
        GenerationTestcaseEntry(
            group_entry=TestcaseEntry(group='g1', index=0),
            subgroup_entry=TestcaseEntry(group='g1', index=0),
            metadata=GenerationMetadata(
                copied_to=Testcase(inputPath=pathlib.Path('in'))
            ),
            visualizer=visualizer,
        ),
        GenerationTestcaseEntry(
            group_entry=TestcaseEntry(group='g1', index=1),
            subgroup_entry=TestcaseEntry(group='g1', index=1),
            metadata=GenerationMetadata(
                copied_to=Testcase(inputPath=pathlib.Path('in'))
            ),
            solution_visualizer=output_visualizer,
        ),
    ]

    compiled = visualizers.compile_visualizers_for_entries(entries)

    assert compiled['vis.py'] == 'compiled_digest'
    assert compiled['output_vis.py'] == 'compiled_digest'
    assert mock_compile_item.call_count == 2


@pytest.mark.asyncio
async def test_run_input_visualizers_for_entries(mock_run_item):
    visualizer = Visualizer(path=pathlib.Path('vis.py'), extension='svg')
    input_path = pathlib.Path('test.in')
    entries = [
        GenerationTestcaseEntry(
            group_entry=TestcaseEntry(group='g1', index=0),
            subgroup_entry=TestcaseEntry(group='g1', index=0),
            metadata=GenerationMetadata(copied_to=Testcase(inputPath=input_path)),
            visualizer=visualizer,
        ),
    ]
    compiled = {'vis.py': 'digest'}

    with patch.object(pathlib.Path, 'is_file', return_value=True):
        await visualizers.run_input_visualizers_for_entries(entries, compiled)

    mock_run_item.assert_called_once()
    args = mock_run_item.call_args
    # First arg is visualizer
    assert args[0][0] == visualizer
    # Second arg is digest
    assert args[0][1].digest.value == 'digest'

    # Check extra_args
    expected_args = f'visualization.svg {str(input_path)}'
    assert args[1]['extra_args'] == expected_args

    # Check outputs
    assert 'outputs' in args[1]
    outputs = args[1]['outputs']
    assert len(outputs) == 1
    # Check main output
    assert outputs[0].src == pathlib.Path('visualization.svg')
    assert outputs[0].dest == input_path.parent / 'visualization' / 'test.svg'


@pytest.mark.asyncio
async def test_run_output_visualizers_for_entries(mock_run_item):
    output_visualizer = Visualizer(path=pathlib.Path('output_vis.py'), extension='png')
    input_path = pathlib.Path('test.in')
    output_path = pathlib.Path('test.out')
    entries = [
        GenerationTestcaseEntry(
            group_entry=TestcaseEntry(group='g1', index=0),
            subgroup_entry=TestcaseEntry(group='g1', index=0),
            metadata=GenerationMetadata(
                copied_to=Testcase(inputPath=input_path, outputPath=output_path)
            ),
            solution_visualizer=output_visualizer,
        ),
    ]
    compiled = {'output_vis.py': 'digest'}

    with patch.object(pathlib.Path, 'is_file', return_value=True):
        await visualizers.run_solution_visualizers_for_entries(entries, compiled)

    mock_run_item.assert_called_once()
    args = mock_run_item.call_args

    expected_args = f'visualization.png {str(input_path)} {str(output_path)}'
    assert args[1]['extra_args'] == expected_args

    # Check outputs
    assert 'outputs' in args[1]
    outputs = args[1]['outputs']
    assert len(outputs) == 1
    # Check main output
    assert outputs[0].src == pathlib.Path('visualization.png')
    assert outputs[0].dest == output_path.parent / 'output_visualization' / 'test.png'


def test_get_visualization_stems():
    # Test with input only
    tc = Testcase(inputPath=pathlib.Path('dir/test.in'))
    stems = visualizers.get_visualization_stems(tc)
    assert stems.input == pathlib.Path('dir/visualization/test')
    assert stems.output is None

    # Test with both
    tc = Testcase(
        inputPath=pathlib.Path('dir/test.in'), outputPath=pathlib.Path('dir/test.out')
    )
    stems = visualizers.get_visualization_stems(tc)
    assert stems.input == pathlib.Path('dir/visualization/test')
    assert stems.output == pathlib.Path('dir/output_visualization/test')


def test_compile_package_visualizers(mock_compile_item):
    pkg_mock = MagicMock()
    pkg_mock.visualizer = Visualizer(path=pathlib.Path('vis.py'), extension='svg')
    pkg_mock.outputVisualizer = Visualizer(
        path=pathlib.Path('out_vis.py'), extension='png'
    )

    with patch(
        'rbx.box.visualizers.package.find_problem_package_or_die', return_value=pkg_mock
    ):
        compiled = visualizers.compile_package_visualizers()

    assert compiled['vis.py'] == 'compiled_digest'
    assert compiled['out_vis.py'] == 'compiled_digest'
    assert mock_compile_item.call_count == 2


@pytest.mark.asyncio
async def test_run_visualizers_for_testcase(mock_run_item):
    pkg_mock = MagicMock()
    pkg_mock.visualizer = Visualizer(path=pathlib.Path('vis.py'), extension='svg')
    pkg_mock.outputVisualizer = Visualizer(
        path=pathlib.Path('out_vis.py'), extension='png'
    )

    tc = Testcase(
        inputPath=pathlib.Path('test.in'), outputPath=pathlib.Path('test.out')
    )
    compiled = {'vis.py': 'digest1', 'out_vis.py': 'digest2'}

    with (
        patch(
            'rbx.box.visualizers.package.find_problem_package_or_die',
            return_value=pkg_mock,
        ),
        patch.object(pathlib.Path, 'is_file', return_value=True),
        patch('pathlib.Path.mkdir'),
    ):
        paths = await visualizers.run_visualizers_for_testcase(
            tc, compiled_visualizers=compiled
        )

    assert paths.input == pathlib.Path('visualization/test.svg')
    assert paths.output == pathlib.Path('output_visualization/test.png')
    assert mock_run_item.call_count == 2


@pytest.mark.asyncio
async def test_run_visualizer_failure(mock_run_item):
    visualizer = Visualizer(path=pathlib.Path('vis.py'), extension='svg')
    input_path = pathlib.Path('test.in')

    # Mock failure
    mock_run_item.return_value = MagicMock(exitcode=1, get_summary=lambda: 'Error')

    with patch('pathlib.Path.mkdir'):
        res = await visualizers.run_visualizer(
            visualizer, 'digest', pathlib.Path('visualization/test'), input_path
        )

    assert res is None


@pytest.mark.asyncio
async def test_run_input_visualizer_missing_input(mock_run_item):
    visualizer = Visualizer(path=pathlib.Path('vis.py'), extension='svg')
    tc = Testcase(inputPath=pathlib.Path('missing.in'))

    with patch.object(pathlib.Path, 'is_file', return_value=False):
        res = await visualizers.run_input_visualizer_for_testcase(
            tc, visualizer, 'digest'
        )

    assert res is None
    mock_run_item.assert_not_called()


@pytest.mark.asyncio
async def test_run_output_visualizer_missing_files(mock_run_item):
    visualizer = Visualizer(path=pathlib.Path('vis.py'), extension='png')
    tc = Testcase(
        inputPath=pathlib.Path('test.in'), outputPath=pathlib.Path('test.out')
    )

    # Test missing input
    with patch.object(pathlib.Path, 'is_file', side_effect=[False, True]):
        res = await visualizers.run_solution_visualizer_for_testcase(
            tc, visualizer, 'digest'
        )
    assert res is None

    # Test missing output
    with patch.object(pathlib.Path, 'is_file', side_effect=[True, False]):
        res = await visualizers.run_solution_visualizer_for_testcase(
            tc, visualizer, 'digest'
        )
    assert res is None

    mock_run_item.assert_not_called()


def test_compile_visualizers_failure():
    visualizer = Visualizer(path=pathlib.Path('vis.py'), extension='svg')

    with patch('rbx.box.visualizers.compile_item') as mock_compile:
        # Define a dummy exception that mocks CompilationError behavior
        # We need it to be caught by `except CompilationError`.
        # So it must be an instance of CompilationError.
        class MockCompilationError(CompilationError):
            def __init__(self):
                # We mock print, so that's enough
                pass

            def print(self, *args, **kwargs):
                self.print_called = True

        err = MockCompilationError()
        mock_compile.side_effect = err

        with pytest.raises(CompilationError):
            visualizers.compile_visualizers([visualizer])

        assert getattr(err, 'print_called', False)
