"""Mouse text selection must not crash the screens that use our DOM mixins.

Textual resolves a node's CSS bases by walking only the *first* `DOMNode` base
of each class, not the MRO. A `DOMNode`-derived mixin listed ahead of `Screen`
(or `App`) therefore hides everything behind it: the screen stops inheriting
`Screen.COMPONENT_CLASSES`, and the first mouse move over a selection in a `Log`
blows up with ``KeyError: "No 'screen--selection' key in COMPONENT_CLASSES"``.
"""

import contextlib
from unittest import mock

from textual.app import App
from textual.geometry import Offset
from textual.screen import Screen
from textual.selection import Selection
from textual.widgets import Log

from rbx.box.generation_schema import GenerationMetadata, GenerationTestcaseEntry
from rbx.box.schema import TaskType, Testcase
from rbx.box.testcase_schema import TestcaseEntry
from rbx.box.ui.main import rbxApp


def _screen_classes():
    # Imported inside the tests: pytest tries to *collect* a module-level name
    # starting with `Test`, and warns when it cannot.
    from rbx.box.ui.screens.run_test_explorer import RunTestExplorerScreen
    from rbx.box.ui.screens.test_explorer import TestExplorerScreen

    return (TestExplorerScreen, RunTestExplorerScreen)


@contextlib.contextmanager
def _all(*patches):
    with contextlib.ExitStack() as stack:
        for patch in patches:
            stack.enter_context(patch)
        yield


def _built_entry(tmp_path, group, index):
    inp = tmp_path / f'{group}-{index}.in'
    out = tmp_path / f'{group}-{index}.out'
    inp.write_text('')
    out.write_text('')
    te = TestcaseEntry(group=group, index=index)
    md = GenerationMetadata(copied_to=Testcase(inputPath=inp, outputPath=out))
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


def test_every_screen_inherits_the_selection_component_class():
    """Every screen must keep the component class the selection highlight uses."""
    for screen_cls in _screen_classes():
        assert 'screen--selection' in screen_cls._get_component_classes(), (  # noqa: SLF001
            f'{screen_cls.__name__} lost Screen.COMPONENT_CLASSES'
        )


def test_screens_keep_screen_among_their_textual_css_bases():
    """A mixin ahead of `Screen` must not hide it from the CSS base walk."""
    for screen_cls in _screen_classes():
        assert Screen in screen_cls._css_bases(screen_cls), (  # noqa: SLF001
            f'{screen_cls.__name__} lost Screen from its CSS bases'
        )


def test_apps_keep_app_among_their_textual_css_bases():
    """The same trap applies to the app-level mixins mixed in ahead of `App`."""
    from rbx.box.ui.command_app import rbxCommandApp

    for app_cls in (rbxApp, rbxCommandApp):
        assert App in app_cls._css_bases(app_cls), (  # noqa: SLF001
            f'{app_cls.__name__} lost App from its CSS bases'
        )


async def test_selecting_text_in_the_file_log_renders(tmp_path, monkeypatch):
    """A selection over the test explorer's file log must render, not crash."""
    entries = [_built_entry(tmp_path, 'g1', 0)]
    screen, patches = _mounted_test_explorer(tmp_path, monkeypatch, entries)
    with patches:
        async with rbxApp().run_test() as pilot:
            await pilot.app.push_screen(screen)
            await pilot.pause()

            log = screen.query(Log).first()
            log.write('alpha beta gamma')
            await pilot.pause()

            screen.selections = {log: Selection(Offset(0, 0), Offset(5, 0))}
            await pilot.pause()

            # This is what a mouse move over the selection ends up doing.
            strip = log.render_line(0)

            assert 'alpha' in strip.text
