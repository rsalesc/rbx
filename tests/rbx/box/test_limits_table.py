from rbx.box.limits_info import build_limits_table_rows
from rbx.box.schema import (
    LimitModifiers,
    LimitsProfile,
    TimingGroupOrigin,
    TimingGroupReport,
)


def test_rows_from_group_metadata():
    profile = LimitsProfile(
        timeLimit=2000,
        modifiers={'cpp': LimitModifiers(time=1000)},
        groups=[
            TimingGroupReport(
                languages=['c', 'cpp'],
                timeLimit=1000,
                origin=TimingGroupOrigin.ESTIMATED,
                solutionCount=2,
                fastest=280,
                slowest=600,
            ),
            TimingGroupReport(
                languages=['go'],
                timeLimit=2000,
                origin=TimingGroupOrigin.DEFAULTED,
            ),
        ],
    )
    rows = build_limits_table_rows(profile)
    assert rows[0].languages == 'c, cpp'
    assert rows[0].time_limit_ms == 1000
    assert rows[0].solutions == 2
    assert 'estimated' in rows[0].source.lower()
    assert rows[1].defaulted is True
    assert 'default' in rows[1].source.lower()


def test_multiplier_row_shows_reference():
    profile = LimitsProfile(
        timeLimit=2000,
        groups=[
            TimingGroupReport(
                languages=['java', 'kotlin'],
                timeLimit=4000,
                origin=TimingGroupOrigin.MULTIPLIER,
                relativeToLanguage='cpp',
                multiplier=4.0,
            ),
        ],
    )
    rows = build_limits_table_rows(profile)
    assert rows[0].languages == 'java, kotlin'
    assert rows[0].time_limit_ms == 4000
    assert 'cpp' in rows[0].source
    assert rows[0].defaulted is False


def test_rows_degrade_without_group_metadata():
    profile = LimitsProfile(
        timeLimit=2000, modifiers={'python': LimitModifiers(time=5000)}
    )
    rows = build_limits_table_rows(profile)
    langs = {r.languages for r in rows}
    assert 'python' in langs
    # there should be a base row too
    assert any('base' in r.source.lower() for r in rows)


def test_degraded_view_includes_time_multiplier_modifier():
    profile = LimitsProfile(
        timeLimit=1000,
        modifiers={'java': LimitModifiers(timeMultiplier=2.0)},
    )
    rows = build_limits_table_rows(profile)
    java_row = next(r for r in rows if r.languages == 'java')
    assert java_row.time_limit_ms == 2000
    assert '2.0' in java_row.source


def test_render_limits_table_highlights_defaulted(capsys):
    from rbx.box.limits_info import render_limits_table

    profile = LimitsProfile(
        timeLimit=2000,
        groups=[
            TimingGroupReport(
                languages=['go'],
                timeLimit=2000,
                origin=TimingGroupOrigin.DEFAULTED,
            )
        ],
    )
    render_limits_table(profile, title='Test limits')
    out = capsys.readouterr().out
    assert 'go' in out
    assert 'Test limits' in out


def test_build_limits_table_has_colored_columns():
    from rbx.box.limits_info import build_limits_table

    profile = LimitsProfile(
        timeLimit=2000,
        groups=[
            TimingGroupReport(
                languages=['c', 'cpp'],
                timeLimit=1000,
                origin=TimingGroupOrigin.ESTIMATED,
                solutionCount=2,
                fastest=280,
                slowest=600,
            ),
        ],
    )
    table = build_limits_table(profile)
    # Columns carry explicit (non-grey) styles. Structural styles use the
    # resolved literal values of the project theme names so they render on any
    # console (item -> 'bold blue', bstatus -> 'bold bright_white').
    styles = [c.style for c in table.columns]
    assert 'bold blue' in styles  # Languages column (theme: item)
    assert 'bold bright_white' in styles  # Time Limit column (theme: bstatus)
    assert table.header_style == 'bold bright_white'
    # No column is left at the default grey ('info' / bright_black).
    assert all(s not in (None, '', 'info', 'bright_black') for s in styles)


def test_source_markup_colors_by_origin():
    from rbx.box.limits_info import _source_markup

    assert _source_markup('estimated (fastest 1 / slowest 2)').startswith('[success]')
    assert _source_markup('×4.0 of cpp').startswith('[item]')
    assert _source_markup('base') == 'base'


def test_leftover_row_is_first_and_marked():
    profile = LimitsProfile(
        timeLimit=2000,
        groups=[
            TimingGroupReport(
                languages=['c', 'cpp'],
                timeLimit=1000,
                origin=TimingGroupOrigin.ESTIMATED,
                solutionCount=2,
                fastest=280,
                slowest=600,
            ),
            TimingGroupReport(
                languages=['go', 'java'],
                timeLimit=2000,
                origin=TimingGroupOrigin.DEFAULTED,
                isLeftover=True,
            ),
        ],
    )
    rows = build_limits_table_rows(profile)
    # leftover pulled to the top, marked with a leading asterisk
    assert rows[0].is_leftover is True
    assert rows[0].languages.startswith('* ')
    assert 'go, java' in rows[0].languages
    # the rest keep their original order
    assert rows[1].languages == 'c, cpp'


def test_no_asterisk_when_no_leftover():
    profile = LimitsProfile(
        timeLimit=2000,
        groups=[
            TimingGroupReport(
                languages=['c', 'cpp'],
                timeLimit=1000,
                origin=TimingGroupOrigin.ESTIMATED,
                solutionCount=2,
                fastest=280,
                slowest=600,
            ),
        ],
    )
    rows = build_limits_table_rows(profile)
    assert rows[0].is_leftover is False
    assert not rows[0].languages.startswith('*')


def test_caption_present_only_with_leftover():
    from rbx.box.limits_info import build_limits_table

    leftover_profile = LimitsProfile(
        timeLimit=2000,
        groups=[
            TimingGroupReport(
                languages=['go', 'java'],
                timeLimit=2000,
                origin=TimingGroupOrigin.DEFAULTED,
                isLeftover=True,
            ),
        ],
    )
    plain_profile = LimitsProfile(
        timeLimit=2000,
        groups=[
            TimingGroupReport(
                languages=['c', 'cpp'],
                timeLimit=1000,
                origin=TimingGroupOrigin.ESTIMATED,
                solutionCount=2,
                fastest=280,
                slowest=600,
            ),
        ],
    )
    assert 'leftover' in (build_limits_table(leftover_profile).caption or '')
    assert build_limits_table(plain_profile).caption is None
