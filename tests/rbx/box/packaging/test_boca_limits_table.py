from rbx.box import limits_info, timing
from rbx.box.limits_info import build_limits_table_rows
from rbx.box.schema import LimitsProfile, TimingGroupOrigin, TimingGroupReport
from rbx.box.testing import testing_package
from rbx.utils import model_to_yaml


def test_boca_table_flags_defaulted_language():
    profile = LimitsProfile(
        timeLimit=2000,
        groups=[
            TimingGroupReport(
                languages=['java'],
                timeLimit=2000,
                origin=TimingGroupOrigin.DEFAULTED,
            )
        ],
    )
    rows = build_limits_table_rows(profile)
    assert rows[0].defaulted is True


def test_inherit_display_profile_shows_real_package_base(
    testing_pkg: testing_package.TestingPackage,
):
    # testing_pkg defaults to timeLimit=1000 ms in problem.rbx.yml.
    assert testing_pkg.yml.timeLimit == 1000

    # Write a boca profile that inherits from the package (raw timeLimit=None).
    timing.inherit_time_limits(profile='boca')

    saved = limits_info.get_saved_limits_profile('boca')
    assert saved is not None
    assert saved.inheritFromPackage is True
    assert saved.timeLimit is None

    display = limits_info.get_display_limits_profile('boca')
    assert display is not None
    # Display profile must resolve to the real package base, not None/0.
    assert display.timeLimit == 1000
    # No group metadata when inheriting (degraded view), preserved from saved.
    assert display.groups is None

    rows = build_limits_table_rows(display)
    base_row = rows[0]
    assert base_row.languages == '(base)'
    assert base_row.time_limit_ms == 1000


def test_display_profile_preserves_group_metadata(
    testing_pkg: testing_package.TestingPackage,
):
    estimated = LimitsProfile(
        timeLimit=2000,
        groups=[
            TimingGroupReport(
                languages=['cpp'],
                timeLimit=2000,
                origin=TimingGroupOrigin.ESTIMATED,
                fastest=400,
                slowest=900,
            )
        ],
    )
    limits_path = testing_pkg.root / '.limits' / 'boca.yml'
    limits_path.parent.mkdir(parents=True, exist_ok=True)
    limits_path.write_text(model_to_yaml(estimated))

    display = limits_info.get_display_limits_profile('boca')
    assert display is not None
    assert display.timeLimit == 2000
    assert display.groups is not None
    assert display.groups[0].languages == ['cpp']
    assert display.groups[0].origin == TimingGroupOrigin.ESTIMATED
