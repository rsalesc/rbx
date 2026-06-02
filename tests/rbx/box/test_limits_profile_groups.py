from rbx.box.schema import LimitsProfile, TimingGroupOrigin, TimingGroupReport


def test_limits_profile_groups_defaults_to_none():
    profile = LimitsProfile(timeLimit=1000)
    assert profile.groups is None


def test_limits_profile_round_trips_group_metadata():
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
                languages=['java', 'kotlin'],
                timeLimit=4000,
                origin=TimingGroupOrigin.MULTIPLIER,
                relativeToLanguage='cpp',
                multiplier=4.0,
            ),
        ],
    )
    reloaded = LimitsProfile.model_validate(profile.model_dump())
    assert reloaded.groups is not None
    assert reloaded.groups[1].origin == TimingGroupOrigin.MULTIPLIER
    assert reloaded.groups[1].relativeToLanguage == 'cpp'


def test_limits_profile_round_trips_is_leftover():
    profile = LimitsProfile(
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
    reloaded = LimitsProfile.model_validate(profile.model_dump())
    assert reloaded.groups is not None
    assert reloaded.groups[0].isLeftover is True


def test_limits_profile_groups_without_is_leftover_default_false():
    # Old saved files have no isLeftover key -> defaults to False, loads cleanly.
    raw = {
        'timeLimit': 2000,
        'groups': [
            {
                'languages': ['c', 'cpp'],
                'timeLimit': 1000,
                'origin': 'estimated',
                'solutionCount': 2,
            }
        ],
    }
    reloaded = LimitsProfile.model_validate(raw)
    assert reloaded.groups is not None
    assert reloaded.groups[0].isLeftover is False
