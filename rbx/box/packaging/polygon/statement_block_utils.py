import pathlib
import tempfile
from typing import Callable, List, Optional, Tuple

import typer

from rbx import console, utils
from rbx.box import package
from rbx.box.lang import code_to_langs, is_valid_lang_code
from rbx.box.statements import demacro_utils, polygon_utils
from rbx.box.statements.build_statements import get_statement_dir
from rbx.box.statements.builders import (
    StatementBlocks,
    TeX2PDFBuilder,
    rbxTeXBuilder,
)
from rbx.box.statements.demacro_utils import MacroDefinitions
from rbx.box.statements.schema import Statement, StatementType


def get_substituted_statement_blocks(statement: Statement) -> StatementBlocks:
    assert statement.type == StatementType.rbxTeX
    statement_dir = get_statement_dir(statement, builder_name=rbxTeXBuilder.name())
    substituted_blocks_path = statement_dir / 'blocks.sub.yml'
    if not substituted_blocks_path.is_file():
        console.console.print(
            f'Substituted blocks file [item]{substituted_blocks_path}[/item] does not exist. '
            'Please run the command to build the statement again.',
        )
        raise typer.Exit(1)

    statement_blocks = utils.model_from_yaml(
        StatementBlocks, substituted_blocks_path.read_text()
    )
    return statement_blocks


def get_processed_statement_blocks(statement: Statement) -> StatementBlocks:
    statement_blocks = get_substituted_statement_blocks(statement)
    macros_file = (
        get_statement_dir(statement, builder_name=TeX2PDFBuilder.name()) / 'macros.json'
    )
    if not macros_file.is_file():
        return statement_blocks

    # Get macros and additional macros from defs block.
    macros = MacroDefinitions.from_json_file(macros_file)
    if 'defs' in statement_blocks.blocks:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_file = pathlib.Path(temp_dir) / 'defs.tex'
            temp_file.write_text(statement_blocks.blocks['defs'])
            defs_macros = demacro_utils.collect_macro_definitions(temp_file)
            macros.merge(defs_macros)

    # Filter out commands that are accepted by Polygon.
    macros = macros.filter(polygon_utils.PolygonTeXConfig.default().allowed_commands)

    # Expand macros in statement blocks and explanations.
    statement_blocks.blocks = {
        block_name: demacro_utils.expand_macros(block_content, macros)
        for block_name, block_content in statement_blocks.blocks.items()
    }
    statement_blocks.explanations = {
        explanation_index: demacro_utils.expand_macros(explanation, macros)
        for explanation_index, explanation in statement_blocks.explanations.items()
    }

    # For last, try to convert to Polygon TeX.
    statement_blocks.blocks = {
        block_name: polygon_utils.convert_to_polygon_tex(block_content)
        for block_name, block_content in statement_blocks.blocks.items()
    }
    statement_blocks.explanations = {
        explanation_index: polygon_utils.convert_to_polygon_tex(explanation)
        for explanation_index, explanation in statement_blocks.explanations.items()
    }

    # Save polygon blocks for debugging.
    statement_dir = get_statement_dir(statement, builder_name='polygon')
    for block_name, block_content in statement_blocks.blocks.items():
        (statement_dir / f'{block_name}.tex').write_text(block_content)
    for explanation_index, explanation in statement_blocks.explanations.items():
        (statement_dir / f'explanation_{explanation_index}.tex').write_text(explanation)

    return statement_blocks


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
        blocks = get_processed_statement_blocks(statement)

        errors: List[Tuple[str, List[polygon_utils.PolygonInvalidConstruct]]] = []
        for block_name, block_content in blocks.blocks.items():
            block_errors = polygon_utils.validate_polygon_tex(block_content)
            if block_errors:
                errors.append((block_name, block_errors))
        for explanation_index, explanation in blocks.explanations.items():
            explanation_errors = polygon_utils.validate_polygon_tex(explanation)
            if explanation_errors:
                errors.append((f'explanation_{explanation_index}', explanation_errors))

        if errors:
            console.console.print(
                f'[error]Polygon unsupported TeX constructs found in statement [item]{statement.name}[/item] for language [item]{language}[/item]:[/error]'
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
