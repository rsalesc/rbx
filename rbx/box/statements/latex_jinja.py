"""This module provides a template-rendering function for Jinja2
that overrides Jinja2 defaults to make it work more seamlessly
with Latex.
"""

import enum
import functools
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
# Filter targets
######################################################################
class FilterTarget(enum.Enum):
    """What a filter is formatting for.

    The *rules* a filter applies -- when `sci` abbreviates, when it declines --
    are a property of the value and never vary. Only the spelling does: a PDF
    wants `2 \\times 10^{5}`, a VS Code inlay hint wants `2×10⁵` because it
    cannot typeset maths.

    MARKDOWN maps to the LaTeX formatter and is not redundant: a Markdown
    statement puts its constraints in `$...$` math, so LaTeX is what `sci` and
    `rsci` should emit there. Naming it separately means the day that stops
    being correct is a one-line change rather than an archaeology exercise.

    That claim covers `sci`/`rsci` only. The target also picks `escape`, and
    under MARKDOWN that is still the inherited LaTeX escaping (`a_b` -> `a\\_b`,
    a backslash -> `\\textbackslash{}`), which nobody has examined against a
    Markdown body outside math. Whether it is right there is out of scope here.
    """

    LATEX = 'latex'
    MARKDOWN = 'markdown'
    TEXT = 'text'


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


def _no_escape(value: Any) -> Any:
    """The `escape` filter for output that is not embedded in a markup document."""
    return value


def _process_zeroes(value: int) -> Tuple[int, int, int]:
    cnt = 0

    acc = value
    while acc >= 10:
        acc //= 10
        cnt += 1
    return acc, cnt, value - acc * 10**cnt


def _decide_scientific_notation(
    value: int,
    zeroes: int,
    rest: bool,
) -> Optional[Tuple[int, int, int]]:
    """Decide how to abbreviate a positive integer, or decline.

    Returns the `(mult, exp, rem)` of `mult * 10^exp + rem`, or None when the
    number should be printed as-is. These are the rules of the value, shared by
    every target; only the spelling of the answer varies.
    """
    mult, exp, rem = _process_zeroes(value)
    if exp < zeroes:
        return None
    if not rest and rem > 0:
        # Should not convert numbers like 100007 to 10^5 + 7,
        # unless rest is true.
        return None
    if rem > 0 and len(str(rem)) + 1 >= len(str(value)):
        # Should not convert numbers like 532 to 5*10^2 + 32.
        return None
    return mult, exp, rem


def _format_scientific_latex(mult: int, exp: int) -> str:
    """Spell `mult * 10^exp` as maths. The ` + rem` tail is added by the caller."""
    res = '10' if exp == 1 else f'10^{{{exp}}}'
    if mult > 1:
        res = f'{mult} \\times {res}'
    return res


_SUPERSCRIPT_DIGITS = str.maketrans('0123456789', '⁰¹²³⁴⁵⁶⁷⁸⁹')


def _format_scientific_text(mult: int, exp: int) -> str:
    """Spell `mult * 10^exp` as plain text. The ` + rem` tail is added by the caller."""
    res = '10' if exp == 1 else '10' + str(exp).translate(_SUPERSCRIPT_DIGITS)
    if mult > 1:
        # Tight, where the LaTeX spelling is `2 \times 10^{5}`. Not an
        # inconsistency: math mode discards source spaces and `\times` sets its
        # own, so the PDF shows the same tightness either way. Here `×` is the
        # glyph, and every space around it would be shown.
        res = f'{mult}×{res}'
    return res


def scientific_notation(
    value: Union[int, jinja2.Undefined],
    zeroes: int = 4,
    rest: bool = False,
    *,
    target: FilterTarget = FilterTarget.LATEX,
) -> Union[str, jinja2.Undefined]:
    if jinja2.is_undefined(value):
        return typing.cast(jinja2.Undefined, value)
    assert isinstance(value, int)
    assert zeroes >= 1
    if value == 0:
        return '0'
    if value < 0:
        # `rest` is not forwarded, so `rsci(-100007)` is `-100007` rather than
        # the negation of `10^{5} + 7`. That asymmetry is pre-existing, and it
        # is kept bug-for-bug because this refactor's one constraint is that
        # shipped statement output does not move. Changing it is a fine thing
        # to want; it belongs in its own commit, with its own golden row and a
        # changelog line.
        return f'-{scientific_notation(-value, zeroes=zeroes, target=target)}'

    decision = _decide_scientific_notation(value, zeroes=zeroes, rest=rest)
    if decision is None:
        return str(value)
    mult, exp, rem = decision
    if target is FilterTarget.TEXT:
        res = _format_scientific_text(mult, exp)
    else:
        res = _format_scientific_latex(mult, exp)
    if rem > 0:
        # Target-independent: every target spells the remainder the same way.
        res = f'{res} + {rem}'
    return res


def rest_scientific_notation(
    value: Union[int, jinja2.Undefined],
    zeroes: int = 4,
    *,
    target: FilterTarget = FilterTarget.LATEX,
) -> Union[str, jinja2.Undefined]:
    return scientific_notation(value, zeroes=zeroes, rest=True, target=target)


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


class JinjaDictGetter(dict):
    def __init__(self, name: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = name

    def __getitem__(self, key: str) -> Any:
        try:
            return super().__getitem__(key)
        except KeyError:
            return StrictChainableUndefined(
                hint=f'"{key}" was not found in "{self.name}"',
            )


class JinjaGroupsGetter(JinjaDictGetter):
    """A name-keyed accessor whose iteration yields values in insertion order.

    Used to expose testgroups to statement templates so that ``for g in groups``
    naturally iterates over group objects, while ``groups['subtask1']`` and
    ``groups.subtask1`` still resolve by name.
    """

    def __iter__(self):
        return iter(self.values())


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


def add_builtin_filters(
    j2_env: jinja2.Environment,
    target: FilterTarget = FilterTarget.LATEX,
):
    # TEXT output is not embedded in a markup document, so there is nothing to
    # escape for.
    j2_env.filters['escape'] = (
        _no_escape if target is FilterTarget.TEXT else escape_latex_str_if_str
    )
    j2_env.filters['sci'] = functools.partial(scientific_notation, target=target)
    j2_env.filters['rsci'] = functools.partial(rest_scientific_notation, target=target)
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
    add_builtin_filters(j2_env, target=FilterTarget.LATEX)
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
    add_builtin_filters(j2_env, target=FilterTarget.LATEX)
    add_builtin_tests(j2_env)
    template = j2_env.get_template(template_filename)
    ctx = template.new_context(var_dict)  # type: ignore
    try:
        # Prime the template first.
        for _ in template.root_render_func(ctx):
            pass
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
    add_builtin_filters(j2_env, target=FilterTarget.MARKDOWN)
    add_builtin_tests(j2_env)
    template = j2_env.get_template(template_filename)
    ctx = template.new_context(var_dict)  # type: ignore
    try:
        # Prime the template first.
        for _ in template.root_render_func(ctx):
            pass
        return {key: ''.join(value(ctx)) for key, value in template.blocks.items()}
    except jinja2.UndefinedError as err:
        _handle_rendering_undefined(err)
        raise
