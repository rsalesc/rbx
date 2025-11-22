import ast
import pathlib
from enum import Enum
from typing import List, Optional, Union

import lark
from pydantic import BaseModel

from rbx.box.schema import ExpectedOutcome, ValidatorOutcome
from rbx.box.stressing import whitespace


class UnitTestMode(str, Enum):
    """Mode for parsing unit tests - determines expectation type."""

    CHECKER = 'checker'
    """Parse expectations as ExpectedOutcome (for checker/solution tests)."""

    VALIDATOR = 'validator'
    """Parse expectations as ValidatorOutcome (for validator tests)."""


class ParsedUnitTest(BaseModel):
    """Represents a parsed unit test with input and optional output/answer."""

    name: Optional[str] = None
    expectation: Union[ExpectedOutcome, ValidatorOutcome]
    input: str
    output: Optional[str] = None
    answer: Optional[str] = None
    script_path: pathlib.Path
    line: int


LARK_GRAMMAR = r'''
start: _statement*

_statement: comment
          | test_block
          | input_only_block

// Comments (whole line only)
comment: COMMENT

// Test block with @input, @output, @answer (expectation is required)
test_block: TEST_KEYWORD test_name expectation _LBRACE test_statements _RBRACE
          | TEST_KEYWORD expectation _LBRACE test_statements _RBRACE

test_name: NAME

expectation: NAME

test_statements: test_statement*

test_statement: comment
              | input_block
              | output_block
              | answer_block

// Input block (required in test)
input_block: INPUT_KEYWORD string
           | INPUT_KEYWORD _LBRACE input_lines _RBRACE

// Output block (optional)
output_block: OUTPUT_KEYWORD string
            | OUTPUT_KEYWORD _LBRACE input_lines _RBRACE

// Answer block (optional)
answer_block: ANSWER_KEYWORD string
            | ANSWER_KEYWORD _LBRACE input_lines _RBRACE

// Simplified input-only syntax (expectation is required)
input_only_block: INPUT_KEYWORD test_name expectation _LBRACE input_lines _RBRACE
                | INPUT_KEYWORD test_name expectation string
                | INPUT_KEYWORD expectation _LBRACE input_lines _RBRACE
                | INPUT_KEYWORD expectation string

string: TRIPLE_QUOTED_STRING | ESCAPED_STRING

// Input line content - matches any content between braces
input_lines: BLOCK_CONTENT?

// Tokens
TEST_KEYWORD.3: "@test"
INPUT_KEYWORD.3: "@input"
OUTPUT_KEYWORD.3: "@output"
ANSWER_KEYWORD.3: "@answer"
NAME: /[a-zA-Z0-9][a-zA-Z0-9\-_]*/
COMMENT.3: /(\/\/|#)[^\n\r]*/

// String literals - support both single and double quotes with escape sequences
// Negative lookahead (?!") prevents matching "" when it's part of """
ESCAPED_STRING: /'(?:[^'\\]|\\.)*'/ | /"(?:[^"\\]|\\.)*"(?!")/
// Triple-quoted strings (multiline)
TRIPLE_QUOTED_STRING: /"""[\s\S]*?"""/
// Content between braces
BLOCK_CONTENT: /[^\}]+/

_INDENT: /[ \t]+/
_S: /[ \t]+/
_WS: /\s+/
_LBRACE: "{"
_RBRACE: "}"
_NEWLINE: /\r?\n/

%ignore _WS
'''

LARK_PARSER = lark.Lark(LARK_GRAMMAR, propagate_positions=True)


@lark.v_args(inline=True, meta=True)
class UnitTestTransformer(lark.Transformer):
    """
    Transformer for parsing unit test files.

    Transforms the parse tree into a list of ParsedUnitTest objects.
    """

    def __init__(self, script_path: pathlib.Path, mode: UnitTestMode):
        super().__init__()
        self.script_path = script_path
        self.mode = mode

    def _parse_expectation(
        self, expectation_str: str
    ) -> Union[ExpectedOutcome, ValidatorOutcome]:
        """Parse expectation string into the appropriate outcome type based on mode."""
        if self.mode == UnitTestMode.CHECKER:
            try:
                return ExpectedOutcome(expectation_str)
            except ValueError:
                raise ValueError(
                    f'Invalid expectation "{expectation_str}" for checker mode. '
                    f'Valid values are: {", ".join(e.value for e in ExpectedOutcome)}'
                ) from None
        elif self.mode == UnitTestMode.VALIDATOR:
            try:
                return ValidatorOutcome(expectation_str)
            except ValueError:
                raise ValueError(
                    f'Invalid expectation "{expectation_str}" for validator mode. '
                    f'Valid values are: {", ".join(e.value for e in ValidatorOutcome)}'
                ) from None
        else:
            raise ValueError(f'Unknown mode: {self.mode}')

    @lark.v_args(inline=False, meta=True)
    def start(self, meta: lark.tree.Meta, statements) -> List[ParsedUnitTest]:
        """Return list of ParsedUnitTest objects, filtering out None values."""
        result = []
        for stmt in statements:
            if stmt is not None:
                result.append(stmt)
        return result

    def comment(self, meta: lark.tree.Meta, token: lark.Token) -> None:
        """Comments are ignored and not returned."""
        return None

    @lark.v_args(inline=False, meta=True)
    def test_block(self, meta: lark.tree.Meta, children: List) -> ParsedUnitTest:
        """Process test block and create ParsedUnitTest."""
        # Children can be:
        # - TEST_KEYWORD, test_name, expectation, test_statements
        # - TEST_KEYWORD, expectation, test_statements

        name = None
        expectation_str = None
        test_statements = []

        # Extract strings (name and/or expectation) and test_statements
        strings = []
        for child in children:
            if child is None:
                continue
            # Skip the TEST_KEYWORD token
            if isinstance(child, lark.Token):
                continue
            # Collect strings
            if isinstance(child, str):
                strings.append(child)
            # Lists are test_statements results
            elif isinstance(child, list):
                test_statements = child

        # Parse strings: if we have 2, first is name, second is expectation
        # If we have 1, it's just the expectation
        if len(strings) == 1:
            expectation_str = strings[0]
        elif len(strings) >= 2:
            name = strings[0]
            expectation_str = strings[1]

        if expectation_str is None:
            raise ValueError(
                f'@test block at line {meta.line} is missing required expectation'
            )

        # Parse the expectation
        expectation = self._parse_expectation(expectation_str)

        # Parse test statements to extract input, output, answer
        input_content = None
        output_content = None
        answer_content = None

        for stmt in test_statements:
            if stmt is None:
                continue
            if isinstance(stmt, dict):
                if 'input' in stmt:
                    input_content = stmt['input']
                elif 'output' in stmt:
                    output_content = stmt['output']
                elif 'answer' in stmt:
                    answer_content = stmt['answer']

        if input_content is None:
            raise ValueError(
                f'@test block at line {meta.line} is missing required @input'
            )

        return ParsedUnitTest(
            name=name,
            expectation=expectation,
            input=input_content,
            output=output_content,
            answer=answer_content,
            script_path=self.script_path,
            line=meta.line,
        )

    def test_name(self, meta: lark.tree.Meta, token: lark.Token) -> str:
        """Return the test name as string."""
        return str(token)

    def expectation(self, meta: lark.tree.Meta, token: lark.Token) -> str:
        """Return the expectation as string (will be parsed later)."""
        return str(token)

    @lark.v_args(inline=False, meta=True)
    def test_statements(self, meta: lark.tree.Meta, items: List) -> List:
        """Collect all test statements."""
        return [item for item in items if item is not None]

    @lark.v_args(inline=False, meta=True)
    def test_statement(self, meta: lark.tree.Meta, children: List):
        """Return the test statement (input/output/answer dict)."""
        for child in children:
            if child is not None:
                return child
        return None

    @lark.v_args(inline=False, meta=True)
    def input_block(self, meta: lark.tree.Meta, children: List) -> dict:
        """Process input block and return dict."""
        # children[0] is INPUT_KEYWORD, children[1] is content
        content = children[1] if len(children) > 1 else ''
        return {'input': content}

    @lark.v_args(inline=False, meta=True)
    def output_block(self, meta: lark.tree.Meta, children: List) -> dict:
        """Process output block and return dict."""
        # children[0] is OUTPUT_KEYWORD, children[1] is content
        content = children[1] if len(children) > 1 else ''
        return {'output': content}

    @lark.v_args(inline=False, meta=True)
    def answer_block(self, meta: lark.tree.Meta, children: List) -> dict:
        """Process answer block and return dict."""
        # children[0] is ANSWER_KEYWORD, children[1] is content
        content = children[1] if len(children) > 1 else ''
        return {'answer': content}

    @lark.v_args(inline=False, meta=True)
    def input_only_block(self, meta: lark.tree.Meta, children: List) -> ParsedUnitTest:
        """Process simplified input-only syntax."""
        # Can be:
        # - INPUT_KEYWORD, test_name, expectation, content
        # - INPUT_KEYWORD, expectation, content

        name = None
        expectation_str = None
        content = None

        # Collect all non-token, non-None children
        non_token_children = [
            c for c in children if not isinstance(c, lark.Token) and c is not None
        ]

        if len(non_token_children) == 2:
            # expectation, content
            expectation_str = non_token_children[0]
            content = non_token_children[1]
        elif len(non_token_children) >= 3:
            # name, expectation, content
            name = non_token_children[0]
            expectation_str = non_token_children[1]
            content = non_token_children[2]
        elif len(non_token_children) == 1:
            raise ValueError(
                f'@input block at line {meta.line} is missing required expectation and content'
            )

        if expectation_str is None:
            raise ValueError(
                f'@input block at line {meta.line} is missing required expectation'
            )

        if content is None:
            content = ''

        # Parse the expectation
        expectation = self._parse_expectation(expectation_str)

        return ParsedUnitTest(
            name=name,
            expectation=expectation,
            input=content,
            output=None,
            answer=None,
            script_path=self.script_path,
            line=meta.line,
        )

    def string(self, meta: lark.tree.Meta, token: lark.Token) -> str:
        """Parse string literal and return its content."""
        raw_string = str(token)

        # Check if it's a triple-quoted string
        if raw_string.startswith('"""') and raw_string.endswith('"""'):
            # Remove triple quotes and return content as-is
            return whitespace.normalize_trailing_lines_from_text(raw_string[3:-3])
        else:
            # Regular string (single or double quoted) - use ast.literal_eval to handle escapes
            return ast.literal_eval(raw_string)

    @lark.v_args(inline=False, meta=True)
    def input_lines(self, meta: lark.tree.Meta, children: List) -> str:
        """Collect all input lines and join them."""
        if not children or children[0] is None:
            return ''
        # children[0] is the BLOCK_CONTENT token
        content = children[0]
        return whitespace.normalize_lines_from_text(str(content))


def parse(script: str) -> lark.ParseTree:
    """Parse a unit test script and return the parse tree."""
    return LARK_PARSER.parse(script)


def parse_and_transform(
    script: str, script_path: pathlib.Path, mode: UnitTestMode
) -> List[ParsedUnitTest]:
    """Parse a unit test script and transform it into a list of ParsedUnitTest objects.

    Args:
        script: The unit test script content to parse.
        script_path: Path to the script file (for error reporting).
        mode: The parsing mode - determines whether expectations are parsed as
              ExpectedOutcome (checker mode) or ValidatorOutcome (validator mode).

    Returns:
        A list of ParsedUnitTest objects.
    """
    tree = parse(script)
    transformer = UnitTestTransformer(script_path, mode)
    res = transformer.transform(tree)
    return res


if __name__ == '__main__':
    # Example usage for checker mode
    checker_script = """
// This is a comment
@test test_name_1 accepted {
    @input {
1 2 3
    }
    @output {
5
    }
    @answer {
6
    }
}

@test wa {
    @input "simple string input"
    @output "expected output"
}

@input test_simple ac {
1 2 3
}

@input tle {
just input
no name
}

@input rte "inline string"
"""

    # Example usage for validator mode
    validator_script = """
@test valid_case valid {
    @input {
1 2 3
    }
}

@input invalid_case invalid {
-1 0
}

@input valid "5 10"
"""

    print('=== CHECKER MODE EXAMPLE ===\n')
    # Parse and show tree for checker mode
    tree = parse(checker_script)
    print('Parse tree:')
    print(tree.pretty())
    print()

    # Transform to ParsedUnitTest objects in checker mode
    script_path = pathlib.Path('checker_script.txt')
    results = parse_and_transform(checker_script, script_path, UnitTestMode.CHECKER)

    print(f'Generated {len(results)} unit tests:')
    for i, result in enumerate(results, 1):
        print(f'\n{i}. {result.script_path}:{result.line}')
        print(f'   Name: {result.name}')
        print(f'   Expectation: {result.expectation}')
        print(f'   Input: {repr(result.input)}')
        print(f'   Output: {repr(result.output)}')
        print(f'   Answer: {repr(result.answer)}')

    print('\n\n=== VALIDATOR MODE EXAMPLE ===\n')
    # Transform to ParsedUnitTest objects in validator mode
    script_path = pathlib.Path('validator_script.txt')
    results = parse_and_transform(validator_script, script_path, UnitTestMode.VALIDATOR)

    print(f'Generated {len(results)} unit tests:')
    for i, result in enumerate(results, 1):
        print(f'\n{i}. {result.script_path}:{result.line}')
        print(f'   Name: {result.name}')
        print(f'   Expectation: {result.expectation}')
        print(f'   Input: {repr(result.input)}')
