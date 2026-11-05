import pytest

from rbx.box.statements.processing.figure_size import figure_options

NATURAL = (200.0, 100.0)


def _display(options, natural=NATURAL, scale=1.09):
    return figure_options(options, natural, scale=scale, inline=False)


def _inline(options, natural=NATURAL, scale=1.09):
    return figure_options(options, natural, scale=scale, inline=True)


def test_a_display_figure_gets_its_natural_width_scaled():
    assert _display(None) == 'width=218pt'


def test_an_inline_figure_gets_its_natural_height_scaled():
    assert _inline(None) == 'height=109pt'


def test_the_scale_is_whatever_the_target_asks_for():
    assert _display(None, scale=1.0) == 'width=200pt'
    assert _inline(None, scale=2.0) == 'height=200pt'


def test_no_natural_size_and_no_options_leaves_the_figure_alone():
    assert _display(None, natural=None) is None
    assert _display('', natural=None) is None


def test_a_degenerate_natural_size_counts_as_unknown():
    assert _display(None, natural=(0.0, 10.0)) is None


def test_graphicx_scale_multiplies_the_natural_size():
    assert _display('scale=0.5') == 'width=109pt'
    assert _inline('scale=0.5') == 'height=54.5pt'


def test_graphicx_scale_without_a_natural_size_leaves_the_figure_alone():
    assert _display('scale=0.5', natural=None) is None


@pytest.mark.parametrize(
    'options, expected',
    [
        ('width=100bp', 'width=109pt'),
        ('width=72.27pt', 'width=78.48pt'),
        ('width=1in', 'width=78.48pt'),
        ('width=2.54cm', 'width=78.48pt'),
        ('width=25.4mm', 'width=78.48pt'),
        ('width = {1in}', 'width=78.48pt'),
    ],
)
def test_an_absolute_width_is_converted_and_scaled(options, expected):
    assert _display(options, natural=None) == expected


def test_an_absolute_height_on_an_inline_figure_stays_a_height():
    assert _inline('height=10bp') == 'height=10.9pt'


def test_an_absolute_height_on_a_display_figure_becomes_a_width():
    # Through the aspect ratio, so `max-width: 100%` cannot distort it.
    assert _display('height=1in') == 'width=156.96pt'


def test_an_absolute_height_with_no_natural_size_stays_a_height():
    assert _display('height=1in', natural=None) == 'height=78.48pt'


def test_both_absolute_dimensions_are_both_scaled():
    assert _display('width=1in,height=2in,keepaspectratio') == (
        'width=78.48pt,height=156.96pt'
    )


@pytest.mark.parametrize(
    'options, expected',
    [
        (r'width=0.5\textwidth', r'width=0.5\textwidth'),
        (r'width=.8\linewidth', r'width=0.8\textwidth'),
        (r'width=\columnwidth', r'width=1\textwidth'),
        (r'width=0.25\hsize, height=3cm', r'width=0.25\textwidth'),
    ],
)
def test_a_line_width_fraction_is_left_to_the_column(options, expected):
    # `<f>\textwidth` is what pandoc turns into `width="<100f>%"`; the scale
    # does not apply, the fraction is relative to the column already.
    assert _display(options) == expected
    assert _inline(options) == expected


def test_a_font_relative_length_is_kept_as_written():
    assert _inline('height=1.2em') == 'height=1.2em'
    assert _display('width=3ex') == 'width=3ex'


def test_graphicx_scale_does_not_apply_on_top_of_an_explicit_size():
    assert _display('width=100bp,scale=3') == 'width=109pt'


@pytest.mark.parametrize(
    'options',
    [
        'angle=90',
        'width=1in,angle=90',
        'trim=1 2 3 4,clip',
        'page=2',
        r'width=\dimexpr\textwidth-1cm\relax',
        r'height=0.5\textheight',
        r'height=0.5\textwidth',
        'width=3',
        'scale=-1',
        'scale=half',
        'width={1in',
    ],
)
def test_options_it_cannot_reason_about_leave_the_figure_alone(options):
    assert _display(options) is None
