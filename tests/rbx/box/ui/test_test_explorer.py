"""Behavioral tests for the search box in ``TestExplorerScreen`` (#548).

The built-test explorer reuses ``TestListSearchMixin``: ``/`` opens a fuzzy
search box that live-filters the test list and doubles as a goto (Enter commits,
Esc restores). There is no failing-only filter here (built tests have no
verdicts). These mount the screen bare by mocking the package lookup and the
testcase extractor, mirroring the fixture style in ``test_run_test_explorer.py``.
"""

import contextlib
from unittest import mock

from textual.widgets import Input, OptionList

from rbx.box.generation_schema import GenerationMetadata, GenerationTestcaseEntry
from rbx.box.schema import GeneratorCall, TaskType, Testcase
from rbx.box.testcase_schema import TestcaseEntry


@contextlib.contextmanager
def _all(*patches):
    with contextlib.ExitStack() as stack:
        for patch in patches:
            stack.enter_context(patch)
        yield


def _built_entry(tmp_path, group, index, *, generator_call=None, content=None):
    inp = tmp_path / f'{group}-{index}.in'
    out = tmp_path / f'{group}-{index}.out'
    inp.write_text('')
    out.write_text('')
    te = TestcaseEntry(group=group, index=index)
    md = GenerationMetadata(
        copied_to=Testcase(inputPath=inp, outputPath=out),
        generator_call=generator_call,
        content=content,
    )
    return GenerationTestcaseEntry(group_entry=te, subgroup_entry=te, metadata=md)


def _mounted_test_explorer(tmp_path, monkeypatch, entries):
    from rbx.box.ui.screens import test_explorer

    monkeypatch.chdir(tmp_path)
    pkg = mock.Mock()
    pkg.type = TaskType.BATCH
    patches = _all(
        mock.patch.object(
            test_explorer.package, 'find_problem_package_or_die', return_value=pkg
        ),
        mock.patch.object(
            test_explorer,
            'extract_generation_testcases_from_groups',
            new=mock.AsyncMock(return_value=entries),
        ),
    )
    return test_explorer.TestExplorerScreen(), patches


def _row_texts(screen):
    option_list = screen.query_one('#test-list', OptionList)
    return [
        str(option_list.get_option_at_index(i).prompt)
        for i in range(option_list.option_count)
    ]


async def test_slash_opens_and_focuses_search_box(tmp_path, monkeypatch):
    from rbx.box.ui.main import rbxApp

    entries = [_built_entry(tmp_path, 'g1', 0)]
    screen, patches = _mounted_test_explorer(tmp_path, monkeypatch, entries)
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


async def test_search_filters_by_generator_call(tmp_path, monkeypatch):
    from rbx.box.ui.main import rbxApp

    entries = [
        _built_entry(
            tmp_path, 'g1', 0, generator_call=GeneratorCall(name='gen_small', args='1')
        ),
        _built_entry(
            tmp_path, 'g1', 1, generator_call=GeneratorCall(name='gen_huge', args='9')
        ),
    ]
    screen, patches = _mounted_test_explorer(tmp_path, monkeypatch, entries)
    with patches:
        async with rbxApp().run_test() as pilot:
            await pilot.app.push_screen(screen)
            await pilot.pause()
            await pilot.press('slash')
            screen.query_one('#test-search', Input).value = 'huge'
            await pilot.pause()

            texts = ' '.join(_row_texts(screen))
            assert 'g1/1' in texts
            assert 'g1/0' not in texts


async def test_numeric_query_matches_group_index(tmp_path, monkeypatch):
    from rbx.box.ui.main import rbxApp

    entries = [
        _built_entry(tmp_path, 'g1', 0),
        _built_entry(tmp_path, 'g1', 1),
        _built_entry(tmp_path, 'g2', 1),
    ]
    screen, patches = _mounted_test_explorer(tmp_path, monkeypatch, entries)
    with patches:
        async with rbxApp().run_test() as pilot:
            await pilot.app.push_screen(screen)
            await pilot.pause()
            await pilot.press('slash')
            screen.query_one('#test-search', Input).value = '1'
            await pilot.pause()

            texts = ' '.join(_row_texts(screen))
            assert 'g1/1' in texts and 'g2/1' in texts
            assert 'g1/0' not in texts


async def test_enter_commits_goto_restores_list_and_keeps_match(tmp_path, monkeypatch):
    from rbx.box.ui.main import rbxApp

    entries = [
        _built_entry(
            tmp_path, 'g1', 0, generator_call=GeneratorCall(name='gen_small', args='1')
        ),
        _built_entry(
            tmp_path, 'g1', 1, generator_call=GeneratorCall(name='gen_huge', args='9')
        ),
    ]
    screen, patches = _mounted_test_explorer(tmp_path, monkeypatch, entries)
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
            assert 'g1/0' in ' '.join(_row_texts(screen))  # full list restored
            assert option_list.highlighted is not None
            prompt = str(
                option_list.get_option_at_index(option_list.highlighted).prompt
            )
            assert 'g1/1' in prompt  # matched test highlighted
            assert option_list.has_focus


async def test_escape_restores_list_without_jumping(tmp_path, monkeypatch):
    from rbx.box.ui.main import rbxApp

    entries = [_built_entry(tmp_path, 'g1', 0), _built_entry(tmp_path, 'g1', 1)]
    screen, patches = _mounted_test_explorer(tmp_path, monkeypatch, entries)
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
