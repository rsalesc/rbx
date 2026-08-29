import jinja2
import pytest

from rbx.box.statements.latex_jinja import (
    FilterTarget,
    add_builtin_filters,
    rest_scientific_notation,
    scientific_notation,
)

# (value, LaTeX sci, LaTeX rsci, TEXT sci, TEXT rsci)
GOLDEN = [
    (0, '0', '0', '0', '0'),
    (1, '1', '1', '1', '1'),
    (10, '10', '10', '10', '10'),
    (532, '532', '532', '532', '532'),
    (9999, '9999', '9999', '9999', '9999'),
    (10000, '10^{4}', '10^{4}', '10⁴', '10⁴'),
    (100000, '10^{5}', '10^{5}', '10⁵', '10⁵'),
    (100007, '100007', '10^{5} + 7', '100007', '10⁵ + 7'),
    (200000, r'2 \times 10^{5}', r'2 \times 10^{5}', '2×10⁵', '2×10⁵'),
    (250000, '250000', '250000', '250000', '250000'),
    (1000000007, '1000000007', '10^{9} + 7', '1000000007', '10⁹ + 7'),
    (
        10**18 + 7,
        '1000000000000000007',
        '10^{18} + 7',
        '1000000000000000007',
        '10¹⁸ + 7',
    ),
    (-100000, '-10^{5}', '-10^{5}', '-10⁵', '-10⁵'),
    (10**21, '10^{21}', '10^{21}', '10²¹', '10²¹'),
]


@pytest.mark.parametrize(('value', 'sci', 'rsci', 'text_sci', 'text_rsci'), GOLDEN)
def test_latex_scientific_notation_is_unchanged(value, sci, rsci, text_sci, text_rsci):
    assert scientific_notation(value) == sci
    assert rest_scientific_notation(value) == rsci
    assert scientific_notation(value, target=FilterTarget.LATEX) == sci
    assert rest_scientific_notation(value, target=FilterTarget.LATEX) == rsci


@pytest.mark.parametrize(('value', 'sci', 'rsci', 'text_sci', 'text_rsci'), GOLDEN)
def test_text_scientific_notation(value, sci, rsci, text_sci, text_rsci):
    assert scientific_notation(value, target=FilterTarget.TEXT) == text_sci
    assert rest_scientific_notation(value, target=FilterTarget.TEXT) == text_rsci


@pytest.mark.parametrize(('value', 'sci', 'rsci', 'text_sci', 'text_rsci'), GOLDEN)
def test_text_and_latex_agree_on_whether_to_abbreviate(
    value, sci, rsci, text_sci, text_rsci
):
    """The rules are the value's; only the spelling is the medium's."""
    latex_declined = sci == str(value)
    text_declined = scientific_notation(value, target=FilterTarget.TEXT) == str(value)
    assert latex_declined == text_declined

    latex_rest_declined = rsci == str(value)
    text_rest_declined = rest_scientific_notation(
        value, target=FilterTarget.TEXT
    ) == str(value)
    assert latex_rest_declined == text_rest_declined


def test_markdown_target_formats_as_latex():
    assert scientific_notation(200000, target=FilterTarget.MARKDOWN) == (
        r'2 \times 10^{5}'
    )
    assert rest_scientific_notation(100007, target=FilterTarget.MARKDOWN) == (
        '10^{5} + 7'
    )


@pytest.mark.parametrize('target', list(FilterTarget))
def test_undefined_passes_through(target):
    undefined = jinja2.Undefined(name='N')
    assert jinja2.is_undefined(scientific_notation(undefined, target=target))
    assert jinja2.is_undefined(rest_scientific_notation(undefined, target=target))


def test_zeroes_stays_the_second_positional_parameter():
    assert scientific_notation(200000, 5) == r'2 \times 10^{5}'
    assert scientific_notation(200000, 6) == '200000'
    assert scientific_notation(200000, 5, target=FilterTarget.TEXT) == '2×10⁵'
    assert rest_scientific_notation(100007, 6) == '100007'


def _render(target: FilterTarget, source: str, **kwargs) -> str:
    env = jinja2.Environment(autoescape=False)
    add_builtin_filters(env, target=target)
    return env.from_string(source).render(**kwargs)


@pytest.mark.parametrize(
    ('target', 'expected'),
    [
        (FilterTarget.LATEX, r'2 \times 10^{5}'),
        (FilterTarget.MARKDOWN, r'2 \times 10^{5}'),
        (FilterTarget.TEXT, '2×10⁵'),
    ],
)
def test_sci_filter_is_installed_per_target(target, expected):
    assert _render(target, '{{ n | sci }}', n=200000) == expected
    assert _render(target, '{{ n | rsci }}', n=200000) == expected
    # The filter still accepts `zeroes` positionally.
    assert _render(target, '{{ n | sci(9) }}', n=200000) == '200000'


@pytest.mark.parametrize(
    ('target', 'expected'),
    [
        (FilterTarget.LATEX, r'a\_b'),
        (FilterTarget.MARKDOWN, r'a\_b'),
        (FilterTarget.TEXT, 'a_b'),
    ],
)
def test_escape_filter_is_installed_per_target(target, expected):
    assert _render(target, '{{ s | escape }}', s='a_b') == expected
