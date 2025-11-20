import ast
import pathlib
from typing import List, Optional

import lark
from pydantic import BaseModel


class ParsedUnitTest(BaseModel):
    """Represents a parsed unit test with input and optional output/answer."""

    name: Optional[str] = None
    input: str
    output: Optional[str] = None
    answer: Optional[str] = None
    script_path: pathlib.Path
    line: int


LARK_GRAMMAR = r'''
start: _statement*

_statement: _INDENT? comment
          | _INDENT? test_block
          | _INDENT? input_only_block
          | _NEWLINE

// Comments (whole line only)
comment: COMMENT _NEWLINE?

// Test block with @input, @output, @answer
test_block: TEST_KEYWORD _WS test_name _WS? _LBRACE test_statements _INDENT? _RBRACE _NEWLINE?
          | TEST_KEYWORD _WS? _LBRACE test_statements _INDENT? _RBRACE _NEWLINE?

test_name: NAME

test_statements: test_statement*

test_statement: _INDENT? comment
              | _INDENT? input_block
              | _INDENT? output_block
              | _INDENT? answer_block
              | _NEWLINE

// Input block (required in test)
input_block: INPUT_KEYWORD _WS string _NEWLINE?
           | INPUT_KEYWORD _WS? _LBRACE input_lines _INDENT? _RBRACE _NEWLINE?

// Output block (optional)
output_block: OUTPUT_KEYWORD _WS string _NEWLINE?
            | OUTPUT_KEYWORD _WS? _LBRACE input_lines _INDENT? _RBRACE _NEWLINE?

// Answer block (optional)
answer_block: ANSWER_KEYWORD _WS string _NEWLINE?
            | ANSWER_KEYWORD _WS? _LBRACE input_lines _INDENT? _RBRACE _NEWLINE?

// Simplified input-only syntax
input_only_block: INPUT_KEYWORD _WS test_name _WS? _LBRACE input_lines _INDENT? _RBRACE _NEWLINE?
                | INPUT_KEYWORD _WS test_name _WS string _NEWLINE?
                | INPUT_KEYWORD _WS? _LBRACE input_lines _INDENT? _RBRACE _NEWLINE?
                | INPUT_KEYWORD _WS string _NEWLINE?

string: ESCAPED_STRING | TRIPLE_QUOTED_STRING

// Input line content - matches any line content (excluding newline)
input_lines: (_NEWLINE | input_line)*

input_line: INPUT_LINE_CONTENT _NEWLINE?

// Tokens
TEST_KEYWORD.3: "@test"
INPUT_KEYWORD.3: "@input"
OUTPUT_KEYWORD.3: "@output"
ANSWER_KEYWORD.3: "@answer"
NAME: /[a-zA-Z0-9][a-zA-Z0-9\-_]*/
COMMENT.3: /(\/\/|#)[^\n\r]*/

// String literals - support both single and double quotes with escape sequences
ESCAPED_STRING: /'(?:[^'\\]|\\.)*'/ | /"(?:[^"\\]|\\.)*"/
// Triple-quoted strings (multiline)
TRIPLE_QUOTED_STRING: /"""[\s\S]*?"""/
// Input line content
INPUT_LINE_CONTENT: /[^\r\n]+/

_INDENT: /[ \t]+/
_WS: /[ \t]+/
_LBRACE: "{"
_RBRACE: "}"
_NEWLINE: /\r?\n/
'''

LARK_PARSER = lark.Lark(LARK_GRAMMAR, propagate_positions=True)


@lark.v_args(inline=True, meta=True)
class UnitTestTransformer(lark.Transformer):
    """
    Transformer for parsing unit test files.

    Transforms the parse tree into a list of ParsedUnitTest objects.
    """

    def __init__(self, script_path: pathlib.Path):
        super().__init__()
        self.script_path = script_path

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
        # - TEST_KEYWORD, test_name, test_statements
        # - TEST_KEYWORD, test_statements

        name = None
        test_statements = []

        for child in children:
            if child is None:
                continue
            # Skip the TEST_KEYWORD token
            if isinstance(child, lark.Token):
                continue
            # First string is the name
            if isinstance(child, str) and name is None:
                name = child
            # Lists are test_statements results
            elif isinstance(child, list):
                test_statements = child

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
            input=input_content,
            output=output_content,
            answer=answer_content,
            script_path=self.script_path,
            line=meta.line,
        )

    def test_name(self, meta: lark.tree.Meta, token: lark.Token) -> str:
        """Return the test name as string."""
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
        # - INPUT_KEYWORD, test_name, content
        # - INPUT_KEYWORD, content

        name = None
        content = None

        for child in children:
            if child is None:
                continue
            # Skip the INPUT_KEYWORD token
            if isinstance(child, lark.Token):
                continue
            # First non-token string could be name or content
            if isinstance(child, str):
                if content is None and name is None:
                    # Could be either name or content
                    # We need to check if there's another child
                    # If this is the only child, it's content
                    # If there's another child, this is name
                    continue
                else:
                    content = child

        # Determine which is which
        non_token_children = [
            c for c in children if not isinstance(c, lark.Token) and c is not None
        ]

        if len(non_token_children) == 1:
            # Only content, no name
            content = non_token_children[0]
        elif len(non_token_children) >= 2:
            # First is name, second is content
            name = non_token_children[0]
            content = non_token_children[1]

        if content is None:
            content = ''

        return ParsedUnitTest(
            name=name,
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
            return raw_string[3:-3]
        else:
            # Regular string (single or double quoted) - use ast.literal_eval to handle escapes
            return ast.literal_eval(raw_string)

    @lark.v_args(inline=False, meta=True)
    def input_lines(self, meta: lark.tree.Meta, items: List) -> str:
        """Collect all input lines and join them."""
        result = []
        for item in items:
            if item is not None and item != '\n':
                result.append(item)
        return ''.join(result)

    def input_line(self, meta: lark.tree.Meta, content: lark.Token) -> str:
        """Return the line content with newline."""
        return str(content) + '\n'


def parse(script: str) -> lark.ParseTree:
    """Parse a unit test script and return the parse tree."""
    return LARK_PARSER.parse(script)


def parse_and_transform(script: str, script_path: pathlib.Path) -> List[ParsedUnitTest]:
    """Parse a unit test script and transform it into a list of ParsedUnitTest objects."""
    tree = parse(script)
    transformer = UnitTestTransformer(script_path)
    res = transformer.transform(tree)
    return res


if __name__ == '__main__':
    # Example usage
    test_script = """
// This is a comment
@test test_name_1 {
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

@test {
    @input "simple string input"
    @output "expected output"
}

@input test_simple {
1 2 3
}

@input {
just input
no name
}

@input "inline string"
"""

    # Parse and show tree
    tree = parse(test_script)
    print('Parse tree:')
    print(tree.pretty())
    print()

    # Transform to ParsedUnitTest objects
    script_path = pathlib.Path('test_script.txt')
    results = parse_and_transform(test_script, script_path)

    print(f'Generated {len(results)} unit tests:')
    for i, result in enumerate(results, 1):
        print(f'\n{i}. {result.script_path}:{result.line}')
        print(f'   Name: {result.name}')
        print(f'   Input: {repr(result.input)}')
        print(f'   Output: {repr(result.output)}')
        print(f'   Answer: {repr(result.answer)}')
