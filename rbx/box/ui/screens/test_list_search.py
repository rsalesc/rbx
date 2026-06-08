"""Shared fuzzy-search / goto behaviour for the test-list explorer screens.

Both ``TestExplorerScreen`` (built tests) and ``RunTestExplorerScreen`` (run
results) render a ``#test-list`` ``OptionList`` backed by a parallel
``_option_entries`` list (see ``get_entries_options`` and the #464 invariant).
This mixin docks a ``#test-search`` ``Input`` toggled by ``/`` that live
fuzzy-filters that list and doubles as a goto: Enter commits the jump, Esc
restores. It is screen-agnostic -- a screen plugs in by implementing
``_compute_options`` (its own ``get_entries_options`` call) and, optionally,
``_extra_predicate`` / ``_extra_filter_labels`` (e.g. the run screen's
failing-only filter).

Like ``VimNavMixin`` / ``HelpPanelMixin`` it subclasses ``DOMNode`` so Textual
merges its ``BINDINGS`` into the host screen.
"""

from typing import Any, Callable, List, Optional, Tuple

from textual.binding import Binding
from textual.dom import DOMNode
from textual.fuzzy import Matcher
from textual.widgets import Input, OptionList

from rbx.box.generation_schema import GenerationTestcaseEntry

EntryPredicate = Callable[[GenerationTestcaseEntry], bool]


class TestListSearchMixin(DOMNode):
    """Search box + goto for a ``#test-list`` OptionList. Mix in before ``Screen``."""

    BINDINGS = [
        Binding('slash', 'focus_search', 'Search', show=False),
        Binding('escape', 'cancel_search', 'Cancel search', show=False),
    ]

    # Backed by ``#test-list``; the host screen owns ``_option_entries``.
    _search_query: str = ''
    _option_entries: List[Optional[GenerationTestcaseEntry]]

    # --- Hooks for the host screen ------------------------------------------

    def _compute_options(
        self, predicate: Optional[EntryPredicate]
    ) -> Tuple[List[Any], List[Optional[GenerationTestcaseEntry]]]:
        """Build the (options, expanded_entries) pair for the current state.

        Implemented per screen as the screen's own ``get_entries_options`` call
        with ``predicate`` forwarded.
        """
        raise NotImplementedError

    def _extra_predicate(self) -> Optional[EntryPredicate]:
        """An extra, non-search filter to AND with the search (e.g. failing-only)."""
        return None

    def _extra_filter_labels(self) -> List[str]:
        """Labels for non-search filters, shown in the list border title."""
        return []

    # --- Search box lifecycle ------------------------------------------------

    def _search_input(self) -> Input:
        """The search ``Input`` to ``yield`` from the host screen's ``compose``."""
        return Input(id='test-search', placeholder='Search tests…')

    def _init_search_box(self) -> None:
        """Hide + title the search box. Call from the host screen's ``on_mount``."""
        search = self.query_one('#test-search', Input)
        search.display = False
        search.border_title = 'Search'

    # --- Predicate + rebuild -------------------------------------------------

    def _search_text(self, entry: GenerationTestcaseEntry) -> str:
        md = entry.metadata
        parts = [f'{entry.group_entry.group}/{entry.group_entry.index}']
        if md.generator_call is not None:
            parts.append(str(md.generator_call))
        if md.copied_from is not None:
            parts.append(str(md.copied_from.inputPath))
        if md.content is not None:
            parts.append(md.content)
        if md.generator_script is not None:
            parts.append(str(md.generator_script))
        return ' '.join(parts)

    def _search_predicate(self) -> Optional[EntryPredicate]:
        query = self._search_query.strip()
        if not query:
            return None

        numeric = int(query) if query.isdigit() else None
        matcher = Matcher(query) if numeric is None else None

        def predicate(entry: GenerationTestcaseEntry) -> bool:
            if numeric is not None:
                return entry.group_entry.index == numeric
            assert matcher is not None
            return matcher.match(self._search_text(entry)) > 0

        return predicate

    def _build_predicate(self) -> Optional[EntryPredicate]:
        search = self._search_predicate()
        extra = self._extra_predicate()
        if search is None and extra is None:
            return None

        def predicate(entry: GenerationTestcaseEntry) -> bool:
            if extra is not None and not extra(entry):
                return False
            if search is not None and not search(entry):
                return False
            return True

        return predicate

    def _list_title(self) -> str:
        bits = list(self._extra_filter_labels())
        if self._search_query.strip():
            bits.append('search')
        return 'Tests' + (f' ({", ".join(bits)})' if bits else '')

    def rebuild_test_list(self) -> None:
        options, self._option_entries = self._compute_options(self._build_predicate())
        option_list = self.query_one('#test-list', OptionList)
        option_list.clear_options()
        option_list.add_options(options)
        self.query_one('#test-list').border_title = self._list_title()

    # --- Highlight helpers ---------------------------------------------------

    def _first_selectable_index(self) -> Optional[int]:
        for i, entry in enumerate(self._option_entries):
            if entry is not None:
                return i
        return None

    def _highlight_best_match(self) -> None:
        option_list = self.query_one('#test-list', OptionList)
        query = self._search_query.strip()
        best_index = None
        if query and not query.isdigit():
            matcher = Matcher(query)
            best_score = 0.0
            for i, entry in enumerate(self._option_entries):
                if entry is None:
                    continue
                score = matcher.match(self._search_text(entry))
                if score > best_score:
                    best_score = score
                    best_index = i
        if best_index is None:
            best_index = self._first_selectable_index()
        if best_index is not None:
            option_list.highlighted = best_index

    def _highlighted_entry(self) -> Optional[GenerationTestcaseEntry]:
        option_list = self.query_one('#test-list', OptionList)
        index = option_list.highlighted
        if index is None or index >= len(self._option_entries):
            return None
        return self._option_entries[index]

    def _option_index_of(self, target: GenerationTestcaseEntry) -> Optional[int]:
        for i, entry in enumerate(self._option_entries):
            if entry is target:
                return i
        return None

    def _close_search(self) -> None:
        search = self.query_one('#test-search', Input)
        # Hide first so the Changed posted by clearing the value is ignored.
        search.display = False
        search.value = ''
        self._search_query = ''

    # --- Actions + events ----------------------------------------------------

    def action_focus_search(self) -> None:
        search = self.query_one('#test-search', Input)
        search.display = True
        search.focus()

    def action_cancel_search(self) -> None:
        search = self.query_one('#test-search', Input)
        if not (search.display or search.has_focus):
            return
        self._close_search()
        self.rebuild_test_list()
        self.query_one('#test-list', OptionList).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        # Only live-filter while the box is visible. Closing the box clears its
        # value, which posts a Changed asynchronously; the hidden-box guard keeps
        # that late event from clobbering a committed goto highlight.
        if event.input.id != 'test-search' or not event.input.display:
            return
        self._search_query = event.value
        self.rebuild_test_list()
        self._highlight_best_match()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != 'test-search':
            return
        event.stop()
        # Goto: jump to the matched test in the restored (non-search) list.
        target = self._highlighted_entry()
        self._close_search()
        self.rebuild_test_list()
        option_list = self.query_one('#test-list', OptionList)
        if target is not None:
            index = self._option_index_of(target)
            if index is not None:
                option_list.highlighted = index
        option_list.focus()
