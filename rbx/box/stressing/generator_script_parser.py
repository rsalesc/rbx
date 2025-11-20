import pathlib
from typing import List, Optional

import lark

from rbx.box.generation_schema import GenerationInput, GeneratorScriptEntry
from rbx.box.schema import GeneratorCall, Testcase


class ScriptGeneratedInput(GenerationInput):
    """Input generated from a generator script with optional group annotation."""

    group: Optional[str] = None


LARK_GRAMMAR = r"""
start: _statement*

_statement: _INDENT? comment
          | _INDENT? copy_test
          | _INDENT? testgroup
          | _INDENT? generator_call
          | _NEWLINE

// Comments (whole line only)
// _NEWLINE? allows statement to end with newline OR EOF
comment: COMMENT _NEWLINE?

// Generator call - name must be first token on line, consumes rest of line as args
// _NEWLINE? allows statement to end with newline OR EOF
generator_call: generator_name _WS args _NEWLINE?
              | generator_name _NEWLINE?

generator_name: FILEPATH
args: REST_OF_LINE

// Copy test
// _NEWLINE? allows statement to end with newline OR EOF
copy_test: COPY_KEYWORD _WS FILEPATH _NEWLINE?

// Testgroup
// _NEWLINE? allows statement to end with newline OR EOF
testgroup: TESTGROUP_KEYWORD _WS GROUP_NAME _WS? _LBRACE _statement* _INDENT? _RBRACE _NEWLINE?

// Tokens
COMMENT.3: /(\/\/|#)[^\n\r]*/
COPY_KEYWORD.3: "@copy"
TESTGROUP_KEYWORD.3: "@testgroup"
REST_OF_LINE.2: /[^\n\r]+/
FILEPATH: /[A-Za-z0-9@\.][\/A-Za-z0-9\-_\.@]*/
GROUP_NAME: /[a-zA-Z0-9][a-zA-Z0-9\-_]*/

_INDENT: /[ \t]+/
_WS: /[ \t]+/
_LBRACE: "{"
_RBRACE: "}"
_NEWLINE: /\r?\n/
"""

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
        self, meta: lark.tree.Meta, name: str, args: Optional[str] = None
    ) -> ScriptGeneratedInput:
        """Create ScriptGeneratedInput from a generator call."""
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
        self, meta: lark.tree.Meta, keyword: lark.Token, filepath: str
    ) -> ScriptGeneratedInput:
        """Create ScriptGeneratedInput from a @copy directive."""
        return ScriptGeneratedInput(
            copied_from=Testcase(inputPath=pathlib.Path(filepath)),
            generator_script=GeneratorScriptEntry(
                path=self.script_path,
                line=meta.line,
            ),
        )

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
    return transformer.transform(tree)


if __name__ == '__main__':
    # Example usage
    test_script = """
// This is a comment
gens/generator --MAX_N=100 --MIN_N=30 abcdef

@copy test/in/disk.in

@testgroup my-group {
    // Comment inside group
    gens/generator2 --X=5
    gens/generator3 --Y=10 --Z=20 some more args
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
