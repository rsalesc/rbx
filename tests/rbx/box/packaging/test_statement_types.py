"""Every packager's `statement_types()` must name an output statements v2 can emit.

`statement_types()` is the list of **output** types `run_packager` builds each
statement into; it is passed straight to `execute_build_on_statements(output=...)`
and lands in `build_statements._emit_output`, which supports only pdf/tex/md.

The MOJ packager once returned `StatementType.rbxTeX` here -- a *source* type, and
a plausible-looking mistake, since a packager that consumes blocks rather than a PDF
really does want the rbxTeX build to run. It does not say so through this hook: what
declares "I consume blocks" is `statement_export_params()`, and the PDF build is what
produces the artifacts it asks for (both externalization and demacro live inside
`render.compile_pdf`). The mistake reached a real `rbx package moj` run because every
packaging test drives `packager.package()` directly and never goes through
`run_packager`, so `_emit_output` was never reached.
"""

from typing import List, Type

import pytest

from rbx.box.packaging.boca.packager import BocaPackager
from rbx.box.packaging.moj.packager import MojPackager
from rbx.box.packaging.packager import BasePackager
from rbx.box.packaging.pkg.packager import PkgPackager
from rbx.box.packaging.polygon.packager import PolygonPackager
from rbx.box.statements.schema import StatementType

# Kept in sync with `build_statements._emit_output` by hand: it branches on PDF and
# on `(TeX, Markdown)`, and errors on everything else. See #569 (S13).
EMITTABLE_OUTPUT_TYPES = {
    StatementType.PDF,
    StatementType.TeX,
    StatementType.Markdown,
}

ALL_PACKAGERS: List[Type[BasePackager]] = [
    BocaPackager,
    MojPackager,
    PkgPackager,
    PolygonPackager,
]


@pytest.mark.parametrize('packager_cls', ALL_PACKAGERS, ids=lambda c: c.name())
def test_statement_types_are_emittable(packager_cls: Type[BasePackager]) -> None:
    packager = packager_cls(testcase_entries=[])
    unsupported = set(packager.statement_types()) - EMITTABLE_OUTPUT_TYPES
    assert not unsupported, (
        f'{packager_cls.__name__}.statement_types() returns {unsupported}, which '
        'statements v2 cannot emit. It names the OUTPUT a statement is built into '
        '(pdf/tex/md), not the source format. A packager that consumes blocks '
        'declares that through statement_export_params() instead.'
    )


def test_moj_consumes_blocks_without_asking_for_a_source_output_type() -> None:
    """MOJ reads statement blocks, and says so the way Polygon does.

    It must NOT express that through `statement_types()`: the artifacts the bundle
    reads (`macros.json`, externalized TikZ PDFs) are written inside
    `render.compile_pdf`, so a TeX or Markdown output type would skip that call and
    leave nothing to read, while rbxTeX fails the build outright.
    """
    moj = MojPackager(testcase_entries=[])
    assert moj.statement_types() == [StatementType.PDF]
    assert moj.statement_export_params(), (
        'MOJ must force externalize+demacro; that is what populates the overlay.'
    )
