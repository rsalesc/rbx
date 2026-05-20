"""Tests for Vim-style hjkl navigation in the Textual TUI (rbx.box.ui.vim_nav)."""

from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer
from textual.widgets import DataTable, Input, OptionList, Static

from rbx.box.ui.vim_nav import VimNavMixin


class _ListApp(VimNavMixin, App):
    def compose(self) -> ComposeResult:
        yield OptionList('a', 'b', 'c')

    def on_mount(self) -> None:
        self.query_one(OptionList).focus()


async def test_j_moves_down_and_k_moves_up():
    app = _ListApp()
    async with app.run_test() as pilot:
        option_list = app.query_one(OptionList)
        start = option_list.highlighted or 0

        await pilot.press('j')
        assert option_list.highlighted == start + 1

        await pilot.press('j')
        assert option_list.highlighted == start + 2

        await pilot.press('k')
        assert option_list.highlighted == start + 1


async def test_h_and_l_are_noops_on_plain_list():
    app = _ListApp()
    async with app.run_test() as pilot:
        option_list = app.query_one(OptionList)
        await pilot.press('j')  # move off the first row first
        before = option_list.highlighted

        await pilot.press('l')
        assert option_list.highlighted == before

        await pilot.press('h')
        assert option_list.highlighted == before


class _InputApp(VimNavMixin, App):
    def compose(self) -> ComposeResult:
        yield Input()

    def on_mount(self) -> None:
        self.query_one(Input).focus()


async def test_typing_hjkl_into_input_is_not_hijacked():
    app = _InputApp()
    async with app.run_test() as pilot:
        await pilot.press('h', 'j', 'k', 'l')
        assert app.query_one(Input).value == 'hjkl'


class _TableApp(VimNavMixin, App):
    def compose(self) -> ComposeResult:
        yield DataTable()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = 'cell'
        table.add_columns('x', 'y')
        table.add_rows([('1', '2'), ('3', '4')])
        table.focus()


async def test_datatable_hjkl_moves_cell_cursor():
    app = _TableApp()
    async with app.run_test() as pilot:
        table = app.query_one(DataTable)
        assert table.cursor_coordinate == (0, 0)

        await pilot.press('l')
        assert table.cursor_coordinate == (0, 1)

        await pilot.press('h')
        assert table.cursor_coordinate == (0, 0)

        await pilot.press('j')
        assert table.cursor_coordinate == (1, 0)

        await pilot.press('k')
        assert table.cursor_coordinate == (0, 0)


class _ScrollApp(VimNavMixin, App):
    def compose(self) -> ComposeResult:
        # ScrollableContainer scrolls on both axes (VerticalScroll forces
        # overflow-x: hidden, so horizontal scrolling is impossible there). The
        # child is sized larger than the viewport on both axes so there is real
        # content to scroll into.
        with ScrollableContainer():
            wide_line = 'x' * 200
            content = Static('\n'.join(wide_line for _ in range(200)))
            content.styles.width = 200
            content.styles.height = 200
            yield content

    def on_mount(self) -> None:
        self.query_one(ScrollableContainer).focus()


async def test_j_and_l_scroll_a_scroll_container():
    app = _ScrollApp()
    async with app.run_test(size=(20, 10)) as pilot:
        container = app.query_one(ScrollableContainer)
        assert container.scroll_offset == (0, 0)

        for _ in range(5):
            await pilot.press('j')
        await pilot.pause()
        assert container.scroll_offset.y > 0

        for _ in range(5):
            await pilot.press('l')
        await pilot.pause()
        assert container.scroll_offset.x > 0


async def test_main_menu_app_supports_vim_nav():
    from rbx.box.ui.main import rbxApp

    async with rbxApp().run_test() as pilot:
        option_list = pilot.app.query_one(OptionList)
        start = option_list.highlighted or 0

        await pilot.press('j')
        assert option_list.highlighted == start + 1
