"""This module provides a template-rendering function for Jinja2
that overrides Jinja2 defaults to make it work more seamlessly
with Latex.
"""

import pathlib
import re
import typing
from typing import Any, Dict, Optional, Tuple, Union

import jinja2
import jinja2.runtime
import rich.pretty
import typer

from rbx import console

######################################################################
# J2_ARGS
#   Constant was borrowed from Marc Brinkmann's
#   latex repository (mbr/latex on github)
######################################################################
J2_ARGS = {
    'block_start_string': r'\BLOCK{',
    'block_end_string': '}',
    'variable_start_string': r'\VAR{',
    'variable_end_string': '}',
    'comment_start_string': r'\#{',
    'comment_end_string': '}',
    'line_statement_prefix': '%-',
    'line_comment_prefix': '%#',
    'trim_blocks': True,
    'autoescape': False,
}

J2_MD_ARGS = {
    'trim_blocks': True,
    'autoescape': False,
}


######################################################################
# Latex escape regex constants
######################################################################

# Organize all latex escape characters in one list
# (EXCEPT FOR ( "\" ), which is handled separately)
# escaping those which are special characters in
# PERL regular expressions
ESCAPE_CHARS = [
    r'\&',
    '%',
    r'\$',
    '#',
    '_',
    r'\{',
    r'\}',
    '~',
    r'\^',
]

# For each latex escape character, create a regular expression
# that matches all of the following criteria
# 1) one or two characters
# 2) if two characters, the first character is NOT a backslash ( "\" )
# 3) if two characters, the second, if one, the first character
#       is one of the latex escape characters
REGEX_ESCAPE_CHARS = [
    (re.compile(r'(?<!\\)' + i), r'\\' + i.replace('\\', '')) for i in ESCAPE_CHARS
]

# Place escape characters in [] for "match any character" regex
ESCAPE_CHARS_OR = r'[{}\\]'.format(''.join(ESCAPE_CHARS))

# For the back slash, create a regular expression
# that matches all of the following criteria
# 1) one, two, or three characters
# 2) the first character is not a backslash
# 3) the second character is a backslash
# 4) the third character is none of the ESCAPE_CHARS,
#       and is also not a backslash
REGEX_BACKSLASH = re.compile(r'(?<!\\)\\(?!{})'.format(ESCAPE_CHARS_OR))


######################################################################
# Declare module functions
######################################################################
def escape_latex_str_if_str(value):
    """Escape a latex string"""
    if not isinstance(value, str):
        return value
    for regex, replace_text in REGEX_ESCAPE_CHARS:
        value = re.sub(regex, replace_text, value)
    value = re.sub(REGEX_BACKSLASH, r'\\textbackslash{}', value)
    return value


def _process_zeroes(value: int) -> Tuple[int, int, int]:
    cnt = 0

    acc = value
    while acc >= 10:
        acc //= 10
        cnt += 1
    return acc, cnt, value - acc * 10**cnt


def scientific_notation(
    value: Union[int, jinja2.Undefined], zeroes: int = 2
) -> Union[str, jinja2.Undefined]:
    if jinja2.is_undefined(value):
        return typing.cast(jinja2.Undefined, value)
    assert isinstance(value, int)
    assert zeroes >= 1
    if value == 0:
        return '0'
    if value < 0:
        return f'-{scientific_notation(-value, zeroes=zeroes)}'

    mult, exp, rest = _process_zeroes(value)
    if exp < zeroes:
        return str(value)
    res = '10' if exp == 1 else f'10^{{{exp}}}'
    if rest > 0 and len(str(rest)) + 1 >= len(str(value)):
        # Should not convert numbers like 532 to 5*10^2 + 32.
        return str(value)
    if mult > 1:
        res = f'{mult} \\times {res}'
    if rest > 0:
        res = f'{res} + {rest}'
    return res


def path_parent(path: pathlib.Path) -> pathlib.Path:
    return path.parent


def path_stem(path: pathlib.Path) -> str:
    return path.stem


@jinja2.pass_context
def test_var_truthy(ctx: jinja2.runtime.Context, value: Any):
    if isinstance(value, jinja2.Undefined):
        return False
    if value is None:
        return False
    return bool(value)


@jinja2.pass_context
def test_var_falsy(ctx: jinja2.runtime.Context, value: Any):
    return not test_var_truthy(ctx, value)


@jinja2.pass_context
def test_var_null(ctx: jinja2.runtime.Context, value: Any):
    if isinstance(value, jinja2.Undefined):
        return True
    if value is None:
        return True
    return False


@jinja2.pass_context
def test_var_nonnull(ctx: jinja2.runtime.Context, value: Any):
    return not test_var_null(ctx, value)


######################################################################
# Declare module functions
######################################################################


class StrictChainableUndefined(jinja2.StrictUndefined):
    def __getattr__(self, name: str) -> 'StrictChainableUndefined':
        # Raise AttributeError on requests for names that appear to be unimplemented
        # dunder methods to avoid confusing Python with truthy non-method objects that
        # do not implement the protocol being probed for. e.g., copy.copy(Undefined())
        # fails spectacularly if getattr(Undefined(), '__setstate__') returns an
        # Undefined object instead of raising AttributeError to signal that it does not
        # support that style of object initialization.
        if name[:2] == '__' and name[-2:] == '__':
            raise AttributeError(name)

        return self

    def __getitem__(self, _name: str) -> 'StrictChainableUndefined':  # type: ignore[override]
        return self


class VarWrapperUndefinedError(jinja2.UndefinedError):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def vars(self) -> Dict[str, Any]:
        return {}


class JinjaDictWrapper(dict):
    def __init__(
        self,
        *args,
        key='dict object',
        prefix='',
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.key = key
        self.prefix = prefix
        self.ancestor_d: Optional[Dict[str, Any]] = None

        slf = self

        class _AccessError(VarWrapperUndefinedError):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)

            def vars(self) -> Dict[str, Any]:
                return slf.ancestor_d or slf

        self.exc = _AccessError

    @classmethod
    def from_dict(cls, d: Dict[str, Any], wrapper_key: str) -> 'JinjaDictWrapper':
        res = cls(key=wrapper_key)
        for key, value in d.items():
            splits = key.split('.')
            prefix = ''
            acc = res
            for split in splits[:-1]:
                prefix = f'{prefix}.{split}'.strip('.')
                if split not in acc or not isinstance(acc[split], dict):
                    acc[split] = JinjaDictWrapper(key=wrapper_key, prefix=prefix)
                    acc[split].ancestor_d = res
                acc = acc[split]
            acc[splits[-1]] = value
        return res

    def __getitem__(self, key: str) -> Any:
        try:
            return super().__getitem__(key)
        except KeyError:
            final_key = f'{self.prefix}.{key}'.strip('.')
            return StrictChainableUndefined(
                hint=f'"{final_key}" was not found in "{self.key}"',
                exc=self.exc,
            )


def add_builtin_filters(j2_env: jinja2.Environment):
    j2_env.filters['escape'] = escape_latex_str_if_str
    j2_env.filters['sci'] = scientific_notation
    j2_env.filters['parent'] = path_parent
    j2_env.filters['stem'] = path_stem


def add_builtin_tests(j2_env: jinja2.Environment):
    j2_env.tests['truthy'] = test_var_truthy
    j2_env.tests['falsy'] = test_var_falsy
    j2_env.tests['null'] = test_var_null
    j2_env.tests['nonnull'] = test_var_nonnull


def _handle_rendering_undefined(
    err: jinja2.UndefinedError,
) -> str:
    console.console.print('[error]Error while rendering Jinja2 template:', end=' ')
    console.console.print(err)
    console.console.print(
        '[warning]This usually happens when accessing an undefined variable.[/warning]'
    )
    if isinstance(err, VarWrapperUndefinedError):
        vars = err.vars()
        if vars:
            console.console.print('[warning]Defined variables are[/warning] ', end='')
            console.console.print(rich.pretty.Pretty(vars))
    raise typer.Abort() from err


def render_latex_template(path_templates, template_filename, template_vars=None) -> str:
    """Render a latex template, filling in its template variables

    :param path_templates: the path to the template directory
    :param template_filename: the name, rooted at the path_template_directory,
        of the desired template for rendering
    :param template_vars: dictionary of key:val for jinja2 variables
        defaults to None for case when no values need to be passed
    """
    var_dict = template_vars if template_vars else {}
    j2_env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(path_templates),
        **J2_ARGS,
        undefined=StrictChainableUndefined,
    )
    add_builtin_filters(j2_env)
    add_builtin_tests(j2_env)
    template = j2_env.get_template(template_filename)
    try:
        return template.render(**var_dict)  # type: ignore
    except jinja2.UndefinedError as err:
        _handle_rendering_undefined(err)
        raise


def render_latex_template_blocks(
    path_templates, template_filename, template_vars=None
) -> Dict[str, str]:
    """Render a latex template, filling in its template variables

    :param path_templates: the path to the template directory
    :param template_filename: the name, rooted at the path_template_directory,
        of the desired template for rendering
    :param template_vars: dictionary of key:val for jinja2 variables
        defaults to None for case when no values need to be passed
    """
    var_dict = template_vars if template_vars else {}
    j2_env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(path_templates),
        **J2_ARGS,
        undefined=StrictChainableUndefined,
    )
    add_builtin_filters(j2_env)
    add_builtin_tests(j2_env)
    template = j2_env.get_template(template_filename)
    ctx = template.new_context(var_dict)  # type: ignore
    try:
        return {key: ''.join(value(ctx)) for key, value in template.blocks.items()}
    except jinja2.UndefinedError as err:
        _handle_rendering_undefined(err)
        raise


def render_markdown_template_blocks(
    path_templates, template_filename, template_vars=None
) -> Dict[str, str]:
    """Render a markdown template, filling in its template variables

    :param path_templates: the path to the template directory
    :param template_filename: the name, rooted at the path_template_directory,
        of the desired template for rendering
    :param template_vars: dictionary of key:val for jinja2 variables
        defaults to None for case when no values need to be passed
    """
    var_dict = template_vars if template_vars else {}
    j2_env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(path_templates),
        **J2_MD_ARGS,  # type: ignore
        undefined=StrictChainableUndefined,
    )
    add_builtin_filters(j2_env)
    add_builtin_tests(j2_env)
    template = j2_env.get_template(template_filename)
    ctx = template.new_context(var_dict)  # type: ignore
    try:
        return {key: ''.join(value(ctx)) for key, value in template.blocks.items()}
    except jinja2.UndefinedError as err:
        _handle_rendering_undefined(err)
        raise
