from typing import List, Optional

from rbx.box.environment import LinterConfig
from rbx.box.exception import RbxException
from rbx.box.linters import registry
from rbx.box.linters.asset_kind import AssetKind
from rbx.box.linters.linter import Linter, LinterMessage, LinterSeverity
from rbx.box.sanitizers import warning_stack
from rbx.box.schema import CodeItem


def _in_scope(linter: Linter, config: LinterConfig, kind: Optional[AssetKind]) -> bool:
    # An empty `applies_to` (interface or config) means "no restriction".
    interface = linter.applies_to or None
    config_scope = set(config.applies_to) if config.applies_to else None
    if interface is None and config_scope is None:
        return True  # unrestricted on both sides -> applies to all kinds
    if interface is None:
        effective = config_scope
    elif config_scope is None:
        effective = interface
    else:
        # Both restrict: the linter only applies to the intersection, which may
        # be empty (disjoint scopes) -> the linter never applies.
        effective = interface & config_scope
    if not effective:
        return False
    if kind is None:
        return False  # restricted, but kind unknown -> skip
    return kind in effective


def run_linters_for_messages(
    configs: List[LinterConfig],
    linters: List[Linter],
    kind: Optional[AssetKind],
    code,
    source: str,
) -> List[LinterMessage]:
    out: List[LinterMessage] = []
    for config, linter in zip(configs, linters):
        if not _in_scope(linter, config, kind):
            continue
        out.extend(linter.lint(code, source))
    return out


async def run_linters(code: CodeItem, kind: Optional[AssetKind]) -> None:
    """Run configured linters for `code` and route results.

    Called from compile_item.
    """
    from rbx.box import code as code_module  # avoid import cycle

    language = code_module.find_language(code)
    configs = language.linters
    if not configs:
        return
    linters = [registry.get_linter(c.name) for c in configs]
    source = code.path.read_text()
    messages = run_linters_for_messages(
        configs=configs,
        linters=linters,
        kind=kind,
        code=code,
        source=source,
    )
    warnings = [m for m in messages if m.severity is LinterSeverity.WARNING]
    errors = [m for m in messages if m.severity is LinterSeverity.ERROR]
    if warnings:
        warning_stack.get_warning_stack().add_linter_warning(code, warnings)
    if errors:
        with RbxException() as e:
            e.print(f'[error]Linter errors in {code.href()}[/error]')
            for m in errors:
                loc = f'{m.line}:{m.col} ' if m.line else ''
                e.print(f'- {loc}{m.message}')
