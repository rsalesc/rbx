from typing import Callable, List, Optional, Tuple

import typer

from rbx import console
from rbx.box import package
from rbx.box.exception import RbxException
from rbx.box.lang import code_to_langs, is_valid_lang_code
from rbx.box.statements import polygon_utils

# Transitional re-export: `upload.py` still imports these two from here. Drop it
# once `upload.py` imports them from `rbx.box.statements.export` directly, so this
# does not calcify into permanent indirection.
from rbx.box.statements.export import (  # noqa: F401
    get_processed_statement_blocks,
    get_substituted_statement_blocks,
)
from rbx.box.statements.schema import Statement, StatementType


def _statement_label(statement: Statement) -> str:
    """A human-readable id for a problem statement (which has no ``name`` in v2 —
    it is identified by ``(language, variant)``)."""
    return f'{statement.language}/{statement.variant}'


def _get_statement_for_language(language: str) -> Optional[Statement]:
    pkg = package.find_problem_package_or_die()
    for statement in pkg.expanded_statements:
        if statement.language == language:
            return statement
    return None


def process_statements(
    main_language: Optional[str],
    upload_as_english: bool,
    callable: Callable[[Statement, str, str], None],
):
    pkg = package.find_problem_package_or_die()

    lang_list = []
    languages = set()
    for statement in pkg.expanded_statements:
        if not is_valid_lang_code(statement.language):
            continue
        languages.add(statement.language)
        lang_list.append(statement.language)
    uploaded_languages = set()

    if main_language is None:
        main_language = lang_list[0]

    # Put the main language first.
    lang_list = list(languages)
    for i in range(len(lang_list)):
        if lang_list[i] == main_language:
            lang_list[i], lang_list[0] = lang_list[0], lang_list[i]
            break

    # Prioritize English statements.
    for language in lang_list:
        statement = _get_statement_for_language(language)
        if statement is None:
            continue
        if statement.type != StatementType.rbxTeX:
            continue
        statement_lang = code_to_langs([language])[0]
        uploaded_language = statement_lang
        if main_language == language:
            if not upload_as_english:
                console.console.print(
                    '[warning]By default, Polygon statements are uploaded respecting their original language.\n'
                    'Codeforces does not work well with statements in other languages. If you want a better experience, '
                    'use the [item]--upload-as-english[/item] option to force the main statement to be uploaded in English.[/warning]'
                )
            else:
                uploaded_language = 'english'
        if uploaded_language in uploaded_languages:
            continue
        uploaded_languages.add(uploaded_language)
        callable(statement, language, uploaded_language)


def validate_statements(main_language: Optional[str], upload_as_english: bool):
    def validate_statement(statement: Statement, language: str, uploaded_language: str):
        console.console.print(
            f'Validating statement [item]{_statement_label(statement)}[/item] for language [item]{language}[/item]...'
        )
        blocks = get_processed_statement_blocks(statement)

        errors: List[Tuple[str, List[polygon_utils.PolygonInvalidConstruct]]] = []
        for block_name, block_content in blocks.blocks.items():
            try:
                block_errors = polygon_utils.validate_polygon_tex(block_content)
            except RbxException as err:
                err.print(
                    f'[error]Failed to validate block [item]{block_name}[/item].[/error]'
                )
                raise err
            if block_errors:
                errors.append((block_name, block_errors))
        for explanation_index, explanation in blocks.explanations.items():
            explanation_errors = polygon_utils.validate_polygon_tex(explanation)
            if explanation_errors:
                errors.append((f'explanation_{explanation_index}', explanation_errors))

        if errors:
            console.console.print(
                f'[error]Polygon unsupported TeX constructs found in statement [item]{_statement_label(statement)}[/item] for language [item]{language}[/item]:[/error]'
            )
            for block_name, block_errors in errors:
                console.console.print(
                    f'[error]  - Block [item]{block_name}[/item]:[/error]'
                )
                for error in block_errors:
                    console.console.print(
                        f'[error]    - [item]{error.construct}[/item] at [item]{error.location}[/item]: [item]{error.reason}[/item][/error]'
                    )
            raise typer.Exit(1)

    process_statements(main_language, upload_as_english, validate_statement)
