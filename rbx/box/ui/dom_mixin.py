"""The ``DOMNode`` base our screen/app mixins share.

A mixin that wants to contribute ``BINDINGS`` to the ``Screen`` or ``App`` it is
combined with has to be a ``DOMNode``: Textual's ``_merge_bindings`` walks the
MRO but only collects from ``DOMNode`` subclasses. That is why
``VimNavMixin``, ``HelpPanelMixin`` and ``TestListSearchMixin`` all subclass it.

``DOMNode._css_bases`` -- which decides a node's CSS type names, whose
``DEFAULT_CSS`` applies to it, and which ``COMPONENT_CLASSES`` it inherits --
does *not* walk the MRO. It follows the **first** ``DOMNode`` base of each class
and stops there, so ``class TestExplorerScreen(TestListSearchMixin, Screen)``
walks ``TestExplorerScreen -> TestListSearchMixin -> DOMNode`` and never reaches
``Screen`` at all. The screen silently loses everything ``Screen`` defines.

That cost us ``Screen.COMPONENT_CLASSES``, whose only member backs the text
selection highlight -- so the first mouse move over a selection in one of those
screens crashed the app with::

    KeyError: "No 'screen--selection' key in COMPONENT_CLASSES"

``RbxDOMMixin`` walks the MRO instead, so whatever ``Screen``/``App`` sits behind
the mixin keeps everything Textual would give a plain subclass of it.
"""

from typing import List, Sequence, Type

from textual.dom import DOMNode


class RbxDOMMixin(DOMNode):
    """A ``DOMNode`` mixin that stays transparent to Textual's CSS base walk."""

    @classmethod
    def _css_bases(cls, base: Type[DOMNode]) -> Sequence[Type[DOMNode]]:
        bases: List[Type[DOMNode]] = []
        for klass in base.__mro__:
            if not issubclass(klass, DOMNode):
                # `Generic`, `MessagePump` and `object` carry no CSS.
                continue
            bases.append(klass)
            if not klass._inherit_css:  # noqa: SLF001
                break
        return bases
