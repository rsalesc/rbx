from rbx.box.limits_info import build_limits_table_rows
from rbx.box.schema import LimitsProfile, TimingGroupOrigin, TimingGroupReport


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
