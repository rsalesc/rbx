"""Behavioral tests for ``RunTestExplorerScreen`` (issue #404).

The run-mode test explorer used to pop a blocking modal for testcase metadata
(``g``). It now docks a toggleable ``#test-metadata`` footer like the non-run
``TestExplorerScreen``: ``m`` toggles that footer, ``r`` toggles the per-side
run/eval metadata box, and ``g`` is unbound (no modal).

These mount the screen bare by mocking ``find_problem_package_or_die`` (so
``on_mount`` reports a non-COMMUNICATION package) over an in-memory skeleton,
mirroring the fixture style in ``test_run_ui.py``.
"""

import contextlib
import pathlib
from unittest import mock

from textual.widgets import Input, OptionList

from rbx.box.environment import VerificationLevel
from rbx.box.generation_schema import (
    GenerationMetadata,
    GenerationTestcaseEntry,
    GeneratorScriptEntry,
)
from rbx.box.schema import (
    ExpectedOutcome,
    GeneratorCall,
    ScoreType,
    Solution,
    TaskType,
    Testcase,
)
from rbx.box.solutions import SolutionReportSkeleton, SolutionSkeleton
from rbx.box.testcase_schema import TestcaseEntry
from rbx.box.ui.widgets.rich_log_box import RichLogBox
from rbx.grading.limits import Limits
from rbx.grading.steps import (
    CheckerResult,
    Evaluation,
    Outcome,
    TestcaseIO,
    TestcaseLog,
)


def _make_skeleton(tmp_path: pathlib.Path):
    inputs_dir = tmp_path / 'tests'
    inputs_dir.mkdir(parents=True, exist_ok=True)
    input_path = inputs_dir / '1-gen-000.in'
    input_path.write_text('')

    entry = TestcaseEntry(group='main', index=0)
    gen_entry = GenerationTestcaseEntry(
        group_entry=entry,
        subgroup_entry=entry,
        metadata=GenerationMetadata(copied_to=Testcase(inputPath=input_path)),
    )
    solution = Solution(path=pathlib.Path('sol.cpp'), outcome=ExpectedOutcome.ACCEPTED)
    sol_skel = SolutionSkeleton(**solution.model_dump(), runs_dir=tmp_path / 'runs')
    skeleton = SolutionReportSkeleton(
        solutions=[sol_skel],
        entries=[gen_entry],
        groups=[],
        limits={'cpp': Limits(time=1000, memory=256, profile=None, isDoubleTL=False)},
        compiled_solutions={'sol.cpp': 'digest'},
        verification=VerificationLevel.FULL,
    )
    return skeleton, sol_skel, gen_entry


@contextlib.contextmanager
def _all(*patches):
    with contextlib.ExitStack() as stack:
        for patch in patches:
            stack.enter_context(patch)
        yield


def _mounted_run_test_explorer(tmp_path: pathlib.Path, monkeypatch, main_solution=None):
    """Mount ``RunTestExplorerScreen`` bare for behavioral key/footer tests.

    ``on_mount`` and selection reach the real package and on-disk build layout
    (``_is_interactive``, ``get_main_solution``, per-test verdict option labels,
    and package-build-relative prefix paths), none of which exists outside a
    built package. We stub those data-loading collaborators -- the package as a
    plain BATCH task with no main solution, a single test row, and tmp prefix
    paths -- leaving the footer/keybinding behavior under test untouched.

    ``main_solution`` overrides the stubbed ``get_main_solution`` so the MAIN
    title marker can be exercised.
    """
    from rbx.box.ui.screens import run_test_explorer

    # FileLog renders paths relative to cwd, so the synthetic tmp paths must
    # live under it.
    monkeypatch.chdir(tmp_path)
    skeleton, solution, gen_entry = _make_skeleton(tmp_path)

    pkg = mock.Mock()
    pkg.type = TaskType.BATCH
    run_prefix = tmp_path / 'runs' / 'main' / '1-gen-000'
    build_prefix = tmp_path / 'tests' / '1-gen-000'
    patches = _all(
        mock.patch.object(
            run_test_explorer.package,
            'find_problem_package_or_die',
            return_value=pkg,
        ),
        mock.patch.object(
            run_test_explorer.package, 'get_main_solution', return_value=main_solution
        ),
        mock.patch.object(
            run_test_explorer,
            'get_entries_options',
            return_value=(['main/0'], [gen_entry]),
        ),
        mock.patch.object(
            run_test_explorer.SolutionReportSkeleton,
            'get_solution_entry_prefix',
            return_value=run_prefix,
        ),
        mock.patch.object(TestcaseEntry, 'get_prefix_path', return_value=build_prefix),
    )
    screen = run_test_explorer.RunTestExplorerScreen(skeleton, solution)
    return screen, patches


def _gen_entry(
    group,
    index,
    *,
    generator_call=None,
    content=None,
    script=None,
    copied_from=None,
):
    te = TestcaseEntry(group=group, index=index)
    md = GenerationMetadata(
        copied_to=Testcase(inputPath=pathlib.Path(f'{group}-{index}.in')),
        generator_call=generator_call,
        content=content,
        generator_script=script,
        copied_from=copied_from,
    )
    return GenerationTestcaseEntry(group_entry=te, subgroup_entry=te, metadata=md)


def _eval(outcome):
    return Evaluation(
        result=CheckerResult(outcome=outcome),
        log=TestcaseLog(),
        testcase=TestcaseIO(index=0),
    )


def _make_multi_skeleton(tmp_path, entries):
    solution = Solution(path=pathlib.Path('sol.cpp'), outcome=ExpectedOutcome.ACCEPTED)
    sol_skel = SolutionSkeleton(**solution.model_dump(), runs_dir=tmp_path / 'runs')
    skeleton = SolutionReportSkeleton(
        solutions=[sol_skel],
        entries=entries,
        groups=[],
        limits={'cpp': Limits(time=1000, memory=256, profile=None, isDoubleTL=False)},
        compiled_solutions={'sol.cpp': 'digest'},
        verification=VerificationLevel.FULL,
    )
    return skeleton, sol_skel


def _mounted_filterable(tmp_path, monkeypatch, entries, outcomes):
    """Mount the screen with REAL ``get_entries_options`` filtering.

    ``outcomes`` is a list aligned with ``entries`` (an ``Outcome`` or ``None``
    per entry); it drives the precomputed outcome map the failing-only predicate
    consults. ``get_solution_entry_prefix`` is stubbed so the detail pane never
    reads missing files when a row is highlighted.
    """
    from rbx.box.ui.screens import run_test_explorer

    monkeypatch.chdir(tmp_path)
    # FileLog renders the input path relative to cwd, so make each entry's input
    # an absolute file under tmp_path.
    for entry in entries:
        abs_input = tmp_path / entry.metadata.copied_to.inputPath.name
        abs_input.write_text('')
        entry.metadata.copied_to.inputPath = abs_input
    skeleton, solution = _make_multi_skeleton(tmp_path, entries)

    pkg = mock.Mock()
    pkg.type = TaskType.BATCH
    evals = [(_eval(o) if o is not None else None) for o in outcomes]
    patches = _all(
        mock.patch.object(
            run_test_explorer.package,
            'find_problem_package_or_die',
            return_value=pkg,
        ),
        mock.patch.object(
            run_test_explorer.package, 'get_main_solution', return_value=None
        ),
        mock.patch.object(
            run_test_explorer.package, 'get_scoring', return_value=ScoreType.BINARY
        ),
        mock.patch.object(run_test_explorer, 'get_solution_evals', return_value=evals),
        mock.patch.object(
            run_test_explorer.SolutionReportSkeleton,
            'get_solution_entry_prefix',
            return_value=tmp_path / 'runs' / 'prefix',
        ),
        mock.patch.object(
            TestcaseEntry, 'get_prefix_path', return_value=tmp_path / 'tests' / 'prefix'
        ),
    )
    screen = run_test_explorer.RunTestExplorerScreen(skeleton, solution)
    return screen, patches


def _row_texts(screen):
    option_list = screen.query_one('#test-list', OptionList)
    return [
        str(option_list.get_option_at_index(i).prompt)
        for i in range(option_list.option_count)
    ]


async def test_f_filters_to_failing_tests_and_drops_ac_and_empty_headers(
    tmp_path, monkeypatch
):
    from rbx.box.ui.main import rbxApp

    entries = [_gen_entry('g1', 0), _gen_entry('g1', 1), _gen_entry('g2', 0)]
    outcomes = [Outcome.ACCEPTED, Outcome.WRONG_ANSWER, Outcome.ACCEPTED]
    screen, patches = _mounted_filterable(tmp_path, monkeypatch, entries, outcomes)
    with patches:
        async with rbxApp().run_test() as pilot:
            await pilot.app.push_screen(screen)
            await pilot.pause()

            await pilot.press('f')
            await pilot.pause()

            texts = ' '.join(_row_texts(screen))
            # Only the WA test in g1 survives; g2 (all AC) header is gone.
            assert 'g1/1' in texts
            assert 'g1/0' not in texts
            assert 'g2' not in texts
            assert 'failing only' in str(screen.query_one('#test-list').border_title)

            await pilot.press('f')  # toggle back
            await pilot.pause()
            texts = ' '.join(_row_texts(screen))
            assert 'g1/0' in texts and 'g2/0' in texts
            assert str(screen.query_one('#test-list').border_title) == 'Tests'


async def test_slash_opens_and_focuses_search_box(tmp_path, monkeypatch):
    from rbx.box.ui.main import rbxApp

    entries = [_gen_entry('g1', 0)]
    screen, patches = _mounted_filterable(
        tmp_path, monkeypatch, entries, [Outcome.ACCEPTED]
    )
    with patches:
        async with rbxApp().run_test() as pilot:
            await pilot.app.push_screen(screen)
            await pilot.pause()

            search = screen.query_one('#test-search', Input)
            assert search.display is False

            await pilot.press('slash')
            await pilot.pause()
            assert search.display is True
            assert search.has_focus


async def test_search_filters_by_generator_call_and_highlights_best(
    tmp_path, monkeypatch
):
    from rbx.box.ui.main import rbxApp

    entries = [
        _gen_entry('g1', 0, generator_call=GeneratorCall(name='gen_small', args='1')),
        _gen_entry('g1', 1, generator_call=GeneratorCall(name='gen_huge', args='999')),
    ]
    screen, patches = _mounted_filterable(
        tmp_path, monkeypatch, entries, [Outcome.ACCEPTED, Outcome.ACCEPTED]
    )
    with patches:
        async with rbxApp().run_test() as pilot:
            await pilot.app.push_screen(screen)
            await pilot.pause()

            await pilot.press('slash')
            search = screen.query_one('#test-search', Input)
            search.value = 'huge'
            await pilot.pause()

            texts = ' '.join(_row_texts(screen))
            assert 'g1/1' in texts
            assert 'g1/0' not in texts


async def test_search_matches_inline_content_and_script_location(tmp_path, monkeypatch):
    from rbx.box.ui.main import rbxApp

    entries = [
        _gen_entry('g1', 0, content='alpha beta gamma'),
        _gen_entry(
            'g1',
            1,
            script=GeneratorScriptEntry(path=pathlib.Path('gen.txt'), line=42),
        ),
    ]
    screen, patches = _mounted_filterable(
        tmp_path, monkeypatch, entries, [Outcome.ACCEPTED, Outcome.ACCEPTED]
    )
    with patches:
        async with rbxApp().run_test() as pilot:
            await pilot.app.push_screen(screen)
            await pilot.pause()
            await pilot.press('slash')
            search = screen.query_one('#test-search', Input)

            search.value = 'gamma'
            await pilot.pause()
            assert 'g1/0' in ' '.join(_row_texts(screen))
            assert 'g1/1' not in ' '.join(_row_texts(screen))

            search.value = 'gen.txt'
            await pilot.pause()
            assert 'g1/1' in ' '.join(_row_texts(screen))
            assert 'g1/0' not in ' '.join(_row_texts(screen))


async def test_numeric_query_matches_group_index(tmp_path, monkeypatch):
    from rbx.box.ui.main import rbxApp

    entries = [_gen_entry('g1', 0), _gen_entry('g1', 1), _gen_entry('g2', 1)]
    screen, patches = _mounted_filterable(
        tmp_path, monkeypatch, entries, [Outcome.ACCEPTED] * 3
    )
    with patches:
        async with rbxApp().run_test() as pilot:
            await pilot.app.push_screen(screen)
            await pilot.pause()
            await pilot.press('slash')
            search = screen.query_one('#test-search', Input)
            search.value = '1'
            await pilot.pause()

            texts = ' '.join(_row_texts(screen))
            assert 'g1/1' in texts and 'g2/1' in texts
            assert 'g1/0' not in texts


async def test_enter_commits_goto_restores_list_and_keeps_match(tmp_path, monkeypatch):
    from rbx.box.ui.main import rbxApp

    entries = [
        _gen_entry('g1', 0, generator_call=GeneratorCall(name='gen_small', args='1')),
        _gen_entry('g1', 1, generator_call=GeneratorCall(name='gen_huge', args='9')),
    ]
    screen, patches = _mounted_filterable(
        tmp_path, monkeypatch, entries, [Outcome.ACCEPTED, Outcome.ACCEPTED]
    )
    with patches:
        async with rbxApp().run_test() as pilot:
            await pilot.app.push_screen(screen)
            await pilot.pause()
            await pilot.press('slash')
            screen.query_one('#test-search', Input).value = 'huge'
            await pilot.pause()
            await pilot.press('enter')
            await pilot.pause()

            search = screen.query_one('#test-search', Input)
            option_list = screen.query_one('#test-list', OptionList)
            assert search.display is False
            # Full list restored (both rows present)...
            assert 'g1/0' in ' '.join(_row_texts(screen))
            # ...and the matched test (g1/1) is highlighted.
            assert option_list.highlighted is not None
            prompt = str(
                option_list.get_option_at_index(option_list.highlighted).prompt
            )
            assert 'g1/1' in prompt
            assert option_list.has_focus


async def test_escape_restores_list_without_jumping(tmp_path, monkeypatch):
    from rbx.box.ui.main import rbxApp

    entries = [_gen_entry('g1', 0), _gen_entry('g1', 1)]
    screen, patches = _mounted_filterable(
        tmp_path, monkeypatch, entries, [Outcome.ACCEPTED, Outcome.ACCEPTED]
    )
    with patches:
        async with rbxApp().run_test() as pilot:
            await pilot.app.push_screen(screen)
            await pilot.pause()
            await pilot.press('slash')
            screen.query_one('#test-search', Input).value = '1'
            await pilot.pause()
            await pilot.press('escape')
            await pilot.pause()

            search = screen.query_one('#test-search', Input)
            assert search.display is False
            assert search.value == ''
            assert 'g1/0' in ' '.join(_row_texts(screen))
            assert str(screen.query_one('#test-list').border_title) == 'Tests'


async def test_search_and_failing_only_compose(tmp_path, monkeypatch):
    from rbx.box.ui.main import rbxApp

    entries = [
        _gen_entry('g1', 0, generator_call=GeneratorCall(name='gen_x', args='1')),
        _gen_entry('g1', 1, generator_call=GeneratorCall(name='gen_x', args='2')),
    ]
    # index 0 AC, index 1 WA -> failing-only keeps index 1; both match 'gen_x'.
    screen, patches = _mounted_filterable(
        tmp_path, monkeypatch, entries, [Outcome.ACCEPTED, Outcome.WRONG_ANSWER]
    )
    with patches:
        async with rbxApp().run_test() as pilot:
            await pilot.app.push_screen(screen)
            await pilot.pause()
            await pilot.press('f')
            await pilot.press('slash')
            screen.query_one('#test-search', Input).value = 'gen_x'
            await pilot.pause()

            texts = ' '.join(_row_texts(screen))
            assert 'g1/1' in texts
            assert 'g1/0' not in texts  # filtered by failing-only despite matching


async def test_metadata_footer_hidden_by_default(tmp_path, monkeypatch):
    from rbx.box.ui.main import rbxApp

    screen, patches = _mounted_run_test_explorer(tmp_path, monkeypatch)
    with patches:
        async with rbxApp().run_test() as pilot:
            await pilot.app.push_screen(screen)
            await pilot.pause()

            metadata = screen.query_one('#test-metadata', RichLogBox)
            assert metadata.display is False


async def test_m_toggles_metadata_footer(tmp_path, monkeypatch):
    from rbx.box.ui.main import rbxApp

    screen, patches = _mounted_run_test_explorer(tmp_path, monkeypatch)
    with patches:
        async with rbxApp().run_test() as pilot:
            await pilot.app.push_screen(screen)
            await pilot.pause()

            metadata = screen.query_one('#test-metadata', RichLogBox)
            assert metadata.display is False

            await pilot.press('m')
            await pilot.pause()
            assert metadata.display is True

            await pilot.press('m')
            await pilot.pause()
            assert metadata.display is False


async def test_metadata_footer_shows_selected_test_metadata(tmp_path, monkeypatch):
    from rbx.box.ui.main import rbxApp

    screen, patches = _mounted_run_test_explorer(tmp_path, monkeypatch)
    with patches:
        async with rbxApp().run_test() as pilot:
            await pilot.app.push_screen(screen)
            await pilot.pause()

            # Make the footer visible so its content is rendered, then select
            # the (only) test to populate it.
            await pilot.press('m')
            option_list = screen.query_one('#test-list', OptionList)
            option_list.highlighted = None
            await pilot.pause()
            option_list.highlighted = 0
            await pilot.pause()

            metadata = screen.query_one('#test-metadata', RichLogBox)
            text = '\n'.join(strip.text for strip in metadata.lines)
            # Testcase generation metadata leads with "<group> / <index>".
            assert 'main' in text


async def test_r_toggles_run_metadata_box(tmp_path, monkeypatch):
    from rbx.box.ui.main import rbxApp

    screen, patches = _mounted_run_test_explorer(tmp_path, monkeypatch)
    with patches:
        async with rbxApp().run_test() as pilot:
            await pilot.app.push_screen(screen)
            await pilot.pause()

            run_metadata = screen.query_one(
                '#test-box-1 #test-box-metadata', RichLogBox
            )
            assert run_metadata.display is False

            await pilot.press('r')
            await pilot.pause()
            assert run_metadata.display is True

            await pilot.press('r')
            await pilot.pause()
            assert run_metadata.display is False


async def test_g_does_not_open_modal(tmp_path, monkeypatch):
    from rbx.box.ui.main import rbxApp

    screen, patches = _mounted_run_test_explorer(tmp_path, monkeypatch)
    with patches:
        async with rbxApp().run_test() as pilot:
            await pilot.app.push_screen(screen)
            await pilot.pause()

            # Select a test: the old modal action only fired when a test was
            # highlighted, so we must highlight one for this to be meaningful.
            screen.query_one('#test-list', OptionList).highlighted = 0
            await pilot.pause()
            assert pilot.app.screen is screen

            await pilot.press('g')
            await pilot.pause()

            # `g` is unbound now: no modal should be pushed on top of the screen.
            assert pilot.app.screen is screen


async def test_title_is_prefixed_with_main_marker_for_main_solution(
    tmp_path, monkeypatch
):
    from rbx.box.ui.main import rbxApp

    # ``is_main_solution`` matches on path; the mounted screen's solution is
    # ``sol.cpp``.
    main = Solution(path=pathlib.Path('sol.cpp'), outcome=ExpectedOutcome.ACCEPTED)
    screen, patches = _mounted_run_test_explorer(
        tmp_path, monkeypatch, main_solution=main
    )
    with patches:
        async with rbxApp().run_test() as pilot:
            await pilot.app.push_screen(screen)
            await pilot.pause()

            assert screen.title.startswith('[MAIN]')
            assert 'sol.cpp' in screen.title


async def test_title_has_no_main_marker_for_non_main_solution(tmp_path, monkeypatch):
    from rbx.box.ui.main import rbxApp

    # No main solution -> no marker.
    screen, patches = _mounted_run_test_explorer(tmp_path, monkeypatch)
    with patches:
        async with rbxApp().run_test() as pilot:
            await pilot.app.push_screen(screen)
            await pilot.pause()

            assert '[MAIN]' not in screen.title
            assert screen.title == 'sol.cpp'
