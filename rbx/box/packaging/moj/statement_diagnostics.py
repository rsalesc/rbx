"""What a MOJ statement may lose on the way to Markdown, said out loud.

Two sources feed one report per statement:

- **The validator** (``polygon_utils.validate_polygon_tex`` with
  ``markdown_export.markdown_tex_config()``) reads each block *before*
  conversion and names every construct outside what the Markdown path can show
  -- the Polygon TeX subset, plus what ``text_symbols`` translates and what
  pandoc converts on its own. It works from a fixed allowlist, so it can name a
  position.
- **pandoc itself** (``markdown_export.convert_tex_to_markdown``) reports each
  piece of TeX its reader dropped. It is the safety net for whatever the
  allowlist does not know, and is the stronger claim: the content really is
  gone from the package.

A construct both report in the same block is said once, as dropped. Repeats are
grouped (``\\textbar`` x6 in ``explanation_0``). Packaging carries on after the
report unless strict mode is on -- ``rbx package moj --strict-statement`` or
``extensions.moj.strictStatement`` -- which turns any finding into a non-zero
exit before a package (or an upload) exists.

Blocks arrive with their sourcemap tags already stripped, so positions are
within the block, not the setter's source file.
"""

import dataclasses
import enum
from typing import Dict, List, Optional, Tuple

import rich.markup

from rbx import console
from rbx.box.exception import RbxException
from rbx.box.statements import polygon_utils
from rbx.box.statements.markdown_export import PandocDiagnostic, markdown_tex_config
from rbx.box.statements.processing import tex_scan


class FindingKind(enum.Enum):
    # pandoc's reader dropped it: the content is not in the package.
    DROPPED = 'dropped'
    # Outside what the Markdown path supports; may render wrong or not at all.
    UNSUPPORTED = 'unsupported'
    # Any other pandoc warning, in pandoc's words.
    PANDOC_WARNING = 'pandoc-warning'


@dataclasses.dataclass(frozen=True)
class Finding:
    block: str
    kind: FindingKind
    construct: str
    # (line, column) within the block, when the source of the finding knows it.
    location: Optional[Tuple[int, int]] = None
    reason: Optional[str] = None


def explanation_block(index: int) -> str:
    """The block name a sample explanation is reported under."""
    return f'explanation_{index}'


def _command_name(snippet: str) -> Optional[str]:
    r"""The control sequence a dropped snippet starts with (``\foo{x}`` ->
    ``\foo``), or the environment it opens (``\begin{foo}`` -> ``\foo``, the
    validator's spelling)."""
    if not snippet.startswith('\\'):
        return None
    name, end = tex_scan.read_control_sequence(snippet, 0)
    if name == 'begin':
        parsed = tex_scan.read_environment_name(snippet, end)
        if parsed is not None:
            return '\\' + parsed[0]
    if name == 'end':
        return None
    return '\\' + name


class StatementDiagnostics:
    """The findings for one shipped statement, in the order they were met."""

    def __init__(self, label: str):
        # How the report names the statement, e.g. `pt (main)`.
        self.label = label
        self.findings: List[Finding] = []

    def validate_block(self, block: str, tex: str) -> None:
        """Run the validator over one block's TeX."""
        if not tex.strip():
            return
        try:
            errors = polygon_utils.validate_polygon_tex(tex, markdown_tex_config())
        except RbxException:
            # TexSoup could not parse it. pandoc may still read it fine, and
            # will say what it dropped if not; the validator has nothing more
            # specific to add.
            self.findings.append(
                Finding(
                    block=block,
                    kind=FindingKind.UNSUPPORTED,
                    construct='(the whole block)',
                    reason='rbx could not parse this TeX to validate it',
                )
            )
            return
        for error in errors:
            self.findings.append(
                Finding(
                    block=block,
                    kind=FindingKind.UNSUPPORTED,
                    construct=error.construct,
                    location=error.location,
                    reason=error.reason,
                )
            )

    def add_pandoc(self, block: str, diagnostics: List[PandocDiagnostic]) -> None:
        for diagnostic in diagnostics:
            if diagnostic.dropped:
                assert diagnostic.snippet is not None
                self.findings.append(
                    Finding(
                        block=block,
                        kind=FindingKind.DROPPED,
                        construct=diagnostic.snippet,
                    )
                )
            else:
                self.findings.append(
                    Finding(
                        block=block,
                        kind=FindingKind.PANDOC_WARNING,
                        construct=diagnostic.message,
                    )
                )

    def effective_findings(self) -> List[Finding]:
        """The findings worth printing: an unsupported construct pandoc also
        dropped in the same block is folded into the drop."""
        dropped_names = {
            (finding.block, _command_name(finding.construct))
            for finding in self.findings
            if finding.kind == FindingKind.DROPPED
        }
        return [
            finding
            for finding in self.findings
            if not (
                finding.kind == FindingKind.UNSUPPORTED
                and (finding.block, finding.construct) in dropped_names
            )
        ]

    def __bool__(self) -> bool:
        return bool(self.effective_findings())

    def report(self, *, strict: bool) -> None:
        """Print the findings grouped by block, as warnings or (strict) errors."""
        findings = self.effective_findings()
        if not findings:
            return
        style = 'error' if strict else 'warning'

        by_block: Dict[str, List[Finding]] = {}
        for finding in findings:
            by_block.setdefault(finding.block, []).append(finding)

        lines = [
            f'[{style}]The [item]{self.label}[/item] statement uses TeX that MOJ '
            f'may not show:[/{style}]'
        ]
        for block, block_findings in by_block.items():
            lines.append(f'  Block [item]{block}[/item]:')
            groups: Dict[Tuple[FindingKind, str], List[Finding]] = {}
            for finding in block_findings:
                groups.setdefault((finding.kind, finding.construct), []).append(finding)
            for (kind, construct), group in groups.items():
                lines.append('    - ' + _describe(kind, construct, group))
        lines.append(
            f'[{style}]Rewrite them, define a macro for them, or ask for a '
            'translation in rbx (`rbx/box/statements/processing/text_symbols.py`).'
            f'[/{style}]'
        )
        console.console.print('\n'.join(lines))


def _describe(kind: FindingKind, construct: str, group: List[Finding]) -> str:
    shown = rich.markup.escape(construct)
    count = f' x{len(group)}' if len(group) > 1 else ''
    if kind == FindingKind.DROPPED:
        return (
            f'[item]{shown}[/item]{count}: dropped by pandoc, missing from the package'
        )
    if kind == FindingKind.PANDOC_WARNING:
        return f'pandoc{count}: {shown}'
    locations = [
        f'{finding.location[0]}:{finding.location[1]}'
        for finding in group
        if finding.location is not None
    ]
    where = f' at {", ".join(locations)}' if locations else ''
    reason = group[0].reason
    if reason and reason.startswith('Unsupported command or environment'):
        reason = 'outside what the MOJ statement converter supports'
    suffix = f': {rich.markup.escape(reason)}' if reason else ''
    return f'[item]{shown}[/item]{count}{where}{suffix}'


def report_all(diagnostics: List[StatementDiagnostics], *, strict: bool) -> bool:
    """Print every statement's report; True when anything was found."""
    found = False
    for statement_diagnostics in diagnostics:
        if statement_diagnostics:
            statement_diagnostics.report(strict=strict)
            found = True
    return found
