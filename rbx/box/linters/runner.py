from typing import List, Optional

from rbx.box.environment import LinterConfig
from rbx.box.exception import RbxException
from rbx.box.linters import registry
from rbx.box.linters.asset_kind import AssetKind
from rbx.box.linters.linter import Linter, LinterMessage, LinterSeverity
from rbx.box.sanitizers import warning_stack
from rbx.box.schema import CodeItem


def _in_scope(linter: Linter, config: LinterConfig, kind: Optional[AssetKind]) -> bool:
    interface = linter.applies_to  # empty == all
    config_scope = set(config.applies_to) if config.applies_to else None
    effective = interface
    if config_scope is not None:
        effective = (interface & config_scope) if interface else config_scope
    if not effective:
        return True  # applies to all kinds
    if kind is None:
        return False  # restricted, but kind unknown -> skip
    return kind in effective


def run_linters_for_messages(
    configs: List[LinterConfig],
    linters: List[Linter],
    language_name: str,
    kind: Optional[AssetKind],
    code,
    source: str,
) -> List[LinterMessage]:
    out: List[LinterMessage] = []
    for config, linter in zip(configs, linters):
        if language_name not in linter.languages:
            with RbxException() as e:
                e.print(
                    f'[error]Linter [item]{linter.name}[/item] does not support '
                    f'language [item]{language_name}[/item][/error]'
                )
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
        language_name=language.name,
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
