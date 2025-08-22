# flake8: noqa
from typing import Any, Optional, Union
import typing

import random
import lark

LARK_GRAMMAR = r"""
start: args

// A bunch of args
args: (arg (_WS arg)*)?

// Argument shlex
arg: _block | random_hex

// Blocks
_block: (TEXT | _ticked | _expr)+

// Expression
_expr: var | range | select

// Ticked
_ticked: "`" _expr "`"

// Variables
var: "<" RECNAME ">"

// Select
select: "(" select_value ("|" select_value)* ")"
select_value: _block

// Ranges
range: "[" range_value ".." range_value "]"
range_value: range | var | int | float | char
int: SIGNED_INT
float: SIGNED_FLOAT
char: "'" /./ "'"

// Random hex
random_hex.1: "@"

// Rest, strings, etc
TEXT: (/[^ \t\f\r\n\[\]\(\)\<\>\|\`]/ | ESCAPED_STRING)+

// Whitespace
_WS: WS

RECNAME: /[a-zA-Z0-9_]/+ /(\.[a-zA-Z0-9_]+)/*

%import common.WS
%import common.CNAME
%import common.SIGNED_INT
%import common.SIGNED_FLOAT
%import common.ESCAPED_STRING
"""

LARK_PARSER = lark.Lark(LARK_GRAMMAR)

Primitive = Union[int, float, str]


class GeneratorParsingError(Exception):
    pass


class RandomInt:
    def __init__(self, min: int, max: int):
        self.min = min
        self.max = max

    def get(self) -> int:
        if self.max < self.min:
            raise GeneratorParsingError(
                f'Found int range with invalid bounds [{self.min}..{self.max}].'
            )
        return random.randint(self.min, self.max)


class RandomChar:
    def __init__(self, min: str, max: str):
        self.min = min
        self.max = max

    def get(self) -> str:
        if len(self.min) != 1 or len(self.max) != 1:
            raise GeneratorParsingError(
                f"Found char range with invalid bounds ['{self.min}'..'{self.max}']"
            )
        mn = ord(self.min)
        mx = ord(self.max)
        if mx < mn:
            raise GeneratorParsingError(
                f"Found char range with invalid bounds ['{self.min}'..'{self.max}']"
            )
        return chr(random.randint(mn, mx))


class RandomHex:
    len: int

    def __init__(self, len: int = 8):
        self.len = len

    def get(self) -> str:
        return ''.join(random.choice('0123456789abcdef') for _ in range(self.len))


def parse(args: str) -> lark.ParseTree:
    tree = LARK_PARSER.parse(args)
    (args_root,) = tree.find_data('args')
    return args_root


def _var_as_str(var: Any) -> str:
    if isinstance(var, float):
        return f'{var:.6f}'
    return str(var)


def _down(node: lark.ParseTree) -> Union[lark.Token, lark.ParseTree]:
    return node.children[0]


def _down_tree(node: lark.ParseTree) -> lark.ParseTree:
    downed = _down(node)
    return typing.cast(lark.ParseTree, downed)


def _down_token(node: lark.ParseTree) -> lark.Token:
    downed = _down(node)
    return typing.cast(lark.Token, downed)


def _is_primitive(x: Primitive) -> bool:
    return isinstance(x, (int, float, str))


def _get_casting_type(a: Primitive, b: Primitive) -> Optional[str]:
    if isinstance(a, int) and isinstance(b, int):
        return 'int'
    if isinstance(a, float) or isinstance(b, float):
        if isinstance(a, (int, float)) or isinstance(b, (int, float)):
            return 'float'
    if isinstance(a, str) and isinstance(b, str):
        return 'char'
    return None


class Generator:
    def __init__(self, vars):
        self.vars = vars

    def handle_var(self, expr: lark.ParseTree) -> Any:
        name = typing.cast(lark.Token, _down(expr))
        if name.value not in self.vars:
            raise GeneratorParsingError(
                f'Error parsing generator expression: variable {name.value} is not defined'
            )
        value = self.vars[name.value]
        if not _is_primitive(value):
            raise GeneratorParsingError(
                f'Variable {name.value} has type {type(value)}, which is not supported by the Generator expression parser.'
            )
        return value

    def handle_range_value(self, range_value: lark.ParseTree) -> Primitive:
        tp = _down_tree(range_value)
        if tp.data == 'int':
            return int(_down_token(tp).value)
        if tp.data == 'float':
            return float(_down_token(tp).value)
        if tp.data == 'char':
            return str(_down_token(tp).value)
        if tp.data == 'var':
            return self.handle_var(tp)
        return self.handle_range(tp)

    def handle_range(self, range: lark.ParseTree) -> Primitive:
        value_a, value_b = range.children[:2]

        item_a = self.handle_range_value(typing.cast(lark.ParseTree, value_a))
        item_b = self.handle_range_value(typing.cast(lark.ParseTree, value_b))

        casting_type = _get_casting_type(item_a, item_b)
        if casting_type is None:
            raise GeneratorParsingError(
                f'Types in range are uncompatible: {type(item_a)} != {type(item_b)}'
            )

        if casting_type == 'int':
            return RandomInt(int(item_a), int(item_b)).get()
        if casting_type == 'float':
            return random.uniform(float(item_a), float(item_b))
        if casting_type == 'char':
            return RandomChar(str(item_a), str(item_b)).get()

        raise GeneratorParsingError(
            f'Types in range are not supported: {type(item_a)}, {type(item_b)}'
        )

    def handle_select_value(self, select_value: lark.ParseTree) -> str:
        items = []
        for item in select_value.children:
            items.append(self.handle_block(item))
        return ''.join(items)

    def handle_select(self, select: lark.ParseTree) -> str:
        options = []
        for select_value in select.children:
            options.append(
                self.handle_select_value(typing.cast(lark.ParseTree, select_value))
            )
        return options[RandomInt(0, len(options) - 1).get()]

    def handle_expr(self, expr: lark.ParseTree) -> str:
        if expr.data == 'var':
            return _var_as_str(self.handle_var(expr))
        if expr.data == 'range':
            return _var_as_str(self.handle_range(expr))
        if expr.data == 'select':
            return self.handle_select(expr)
        raise GeneratorParsingError(
            f'Internal error: found invalid AST node in Generator parsing, {expr.data}'
        )

    def handle_block(self, block: Union[lark.ParseTree, lark.Token]) -> str:
        if isinstance(block, lark.Token):
            return block.value

        return self.handle_expr(block)

    def generate_arg(self, arg: lark.ParseTree) -> str:
        items = []
        for arg_item in arg.children:
            if hasattr(arg_item, 'data'):
                data_item = typing.cast(lark.ParseTree, arg_item)
                if data_item.data == 'random_hex':
                    items.append(RandomHex().get())
                    continue
            items.append(self.handle_block(arg_item))
        return ''.join(items)

    def generate(self, args: lark.ParseTree) -> str:
        args_list = []

        for arg in args.children:
            args_list.append(self.generate_arg(typing.cast(lark.ParseTree, arg)))

        return ' '.join(args_list)


if __name__ == '__main__':
    tree = parse(
        """--MAX_N="allow me" --int=[1..<MAX_N>] --float=[1.0..<MAX_N>] --char=['a'..'a'] --selection="(a|b|(c|<MAX_N>))" --select=("a"|"b"|"c") @ --r2=[1..[8..15]]"""
    )
    print(tree)

    generator = Generator({'MAX_N': 10})
    print(generator.generate(tree))
