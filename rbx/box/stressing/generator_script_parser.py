import ast
import pathlib
from typing import List, Optional

import lark

from rbx.box.generation_schema import GenerationInput, GeneratorScriptEntry
from rbx.box.schema import GeneratorCall, Testcase
from rbx.box.stressing import whitespace


class ScriptGeneratedInput(GenerationInput):
    """Input generated from a generator script with optional group annotation."""

    group: Optional[str] = None


LARK_GRAMMAR = r'''
start: _statement*

_statement: comment
          | copy_test
          | inline_input
          | testgroup
          | generator_call

// Comments (whole line only)
comment: COMMENT

// Generator call - name must be first token on line, consumes rest of line as args
generator_call: REST_OF_LINE

// Copy test
copy_test: COPY_KEYWORD REST_OF_LINE

// Inline input
inline_input: INPUT_KEYWORD string
            | INPUT_KEYWORD _LBRACE input_lines _RBRACE

string: TRIPLE_QUOTED_STRING | ESCAPED_STRING

// Content between braces
input_lines: BLOCK_CONTENT?

// Testgroup
testgroup: TESTGROUP_KEYWORD GROUP_NAME _LBRACE _statement* _RBRACE

// Tokens
COMMENT.3: /(\/\/|#)[^\n\r]*/
COPY_KEYWORD.3: "@copy"
INPUT_KEYWORD.3: "@input"
TESTGROUP_KEYWORD.3: "@testgroup"
# no ambiguity
REST_OF_LINE.2: /[^\s@\/#][^\n\r]*/
FILEPATH: /[A-Za-z0-9\.][\/A-Za-z0-9\-_\.]*/
GROUP_NAME: /[a-zA-Z0-9][a-zA-Z0-9\-_]*/

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
class TestPlanTransformer(lark.Transformer):
    """
    Transformer for parsing test plan files.

    Transforms the parse tree into a list of ScriptGeneratedInput objects.
    """

    def __init__(self, script_path: pathlib.Path):
        super().__init__()
        self.script_path = script_path

    @lark.v_args(inline=False, meta=True)
    def start(self, meta: lark.tree.Meta, statements) -> List[ScriptGeneratedInput]:
        """Return list of ScriptGeneratedInput objects, filtering out None values and flattening nested lists."""
        result = []
        for stmt in statements:
            if stmt is None:
                continue
            elif isinstance(stmt, list):
                # Testgroups return lists, so we need to flatten them
                result.extend(stmt)
            else:
                result.append(stmt)
        return result

    def comment(self, meta: lark.tree.Meta, token: lark.Token) -> None:
        """Comments are ignored and not returned."""
        return None

    def generator_call(
        self, meta: lark.tree.Meta, rest_of_line: str
    ) -> ScriptGeneratedInput:
        """Create ScriptGeneratedInput from a generator call."""
        rest_of_line = rest_of_line.strip()
        name, *arglist = rest_of_line.split(None, 1)
        args = ' '.join(arglist)
        if not args:
            args = None
        return ScriptGeneratedInput(
            generator_call=GeneratorCall(name=name, args=args),
            generator_script=GeneratorScriptEntry(
                path=self.script_path,
                line=meta.line,
            ),
        )

    def generator_name(self, meta: lark.tree.Meta, token: lark.Token) -> str:
        """Return the generator name as string."""
        return str(token)

    def args(self, meta: lark.tree.Meta, rest_of_line: lark.Token) -> str:
        """Return the args string, stripped of leading/trailing whitespace."""
        return str(rest_of_line).strip()

    def copy_test(
        self, meta: lark.tree.Meta, keyword: lark.Token, rest_of_line: str
    ) -> ScriptGeneratedInput:
        """Create ScriptGeneratedInput from a @copy directive."""
        if not rest_of_line.strip():
            raise ValueError('@copy directive requires a filepath')
        return ScriptGeneratedInput(
            copied_from=Testcase(inputPath=pathlib.Path(rest_of_line.strip())),
            generator_script=GeneratorScriptEntry(
                path=self.script_path,
                line=meta.line,
            ),
        )

    @lark.v_args(inline=False, meta=True)
    def inline_input(
        self, meta: lark.tree.Meta, children: List
    ) -> ScriptGeneratedInput:
        """Create ScriptGeneratedInput from an @input directive."""
        # children[0] is the INPUT_KEYWORD token
        # children[1] is either a string or input_lines content
        content = children[1] if len(children) > 1 else ''

        # For brace block syntax (input_lines), strip and ensure trailing newline
        # For string syntax, keep as-is
        # We can distinguish by checking if it's multiline or already processed
        # String syntax (both regular and triple-quoted) don't need modification
        # Brace blocks come from input_lines which already has newlines added per line

        return ScriptGeneratedInput(
            content=content,
            generator_script=GeneratorScriptEntry(
                path=self.script_path,
                line=meta.line,
            ),
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

    @lark.v_args(inline=False, meta=True)
    def testgroup(
        self, meta: lark.tree.Meta, children: List
    ) -> List[ScriptGeneratedInput]:
        """
        Process testgroup and return flattened list of ScriptGeneratedInput objects.

        Children are: TESTGROUP_KEYWORD, GROUP_NAME, statements...
        All statements get the group name assigned to them.
        """
        if len(children) < 2:
            return []

        # First child is TESTGROUP_KEYWORD (@testgroup), second is the group name
        group_name = str(children[1])

        # Rest are statements (can include nested testgroups)
        statements = children[2:]

        # Flatten and assign group name
        result = []
        for stmt in statements:
            if stmt is None:
                continue
            elif isinstance(stmt, list):
                # Nested testgroup returns a list
                for nested_stmt in stmt:
                    if nested_stmt.group is None:
                        nested_stmt.group = group_name
                    result.append(nested_stmt)
            elif isinstance(stmt, ScriptGeneratedInput):
                # Direct statement
                if stmt.group is None:
                    stmt.group = group_name
                result.append(stmt)

        return result


def parse(script: str) -> lark.ParseTree:
    """Parse a test plan script and return the parse tree."""
    return LARK_PARSER.parse(script)


def parse_and_transform(
    script: str, script_path: pathlib.Path
) -> List[ScriptGeneratedInput]:
    """Parse a test plan script and transform it into a list of ScriptGeneratedInput objects."""
    tree = parse(script)
    transformer = TestPlanTransformer(script_path)
    res = transformer.transform(tree)
    return res


if __name__ == '__main__':
    # Example usage
    test_script = """
// This is a comment
gens/generator --MAX_N=100 --MIN_N=30 abcdef

@copy test/in/disk.in

@input '123\\n456\\n789\\n'

@input "test\\ndata"

@input \"\"\"
123
456
789
\"\"\"

@input {
multiline
brace block
syntax
}

@testgroup my-group {
    // Comment inside group
    gens/generator2 --X=5
    gens/generator3 --Y=10 --Z=20 some more args
    @input 'inline in group'
}

@testgroup group_2 {
    gens/generator4 --A=1
}
"""

    # Parse and show tree
    tree = parse(test_script)
    print('Parse tree:')
    print(tree.pretty())
    print()

    # Transform to ScriptGeneratedInput objects
    script_path = pathlib.Path('test_script.txt')
    results = parse_and_transform(test_script, script_path)

    print(f'Generated {len(results)} test inputs:')
    for i, result in enumerate(results, 1):
        line_info = (
            f'Line {result.generator_script.line}'
            if result.generator_script
            else 'Unknown line'
        )
        print(f'\n{i}. {line_info}:')
        print(f'   Group: {result.group}')
        if result.generator_call:
            print(f'   Generator: {result.generator_call.name}')
            print(f'   Args: {result.generator_call.args}')
        if result.copied_from:
            print(f'   Copied from: {result.copied_from.inputPath}')
        if result.content:
            print(f'   Content: {repr(result.content)}')
