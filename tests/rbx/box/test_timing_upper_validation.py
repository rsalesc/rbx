"""The limits profile records what phase 2 learned about each slow solution."""

from rbx.box import schema


def test_upper_validation_defaults_to_absent():
    report = schema.TimingGroupReport(
        languages=['cpp'], timeLimit=1000, origin=schema.TimingGroupOrigin.ESTIMATED
    )
    assert report.upperValidation is None


def test_upper_validation_round_trips():
    validation = schema.TimingGroupUpperValidation(
        confirmed=['sols/slow.cpp'],
        violating=[schema.TimingBound(value=1200, solution='sols/nearly.cpp')],
        skipped=['sols/unrun.cpp'],
    )
    report = schema.TimingGroupReport(
        languages=['cpp'],
        timeLimit=1000,
        origin=schema.TimingGroupOrigin.ESTIMATED,
        upperValidation=validation,
    )
    assert (
        schema.TimingGroupReport.model_validate(report.model_dump()).upperValidation
        == validation
    )


def test_a_profile_written_before_the_split_still_parses():
    # `droppedUpper` is deprecated but must not make an existing
    # `.limits/<profile>.yml` unparseable.
    report = schema.TimingGroupReport.model_validate(
        {
            'languages': ['cpp'],
            'timeLimit': 1000,
            'origin': 'estimated',
            'droppedUpper': ['sols/slow.cpp'],
        }
    )
    assert report.upperValidation is None


def test_the_deprecated_field_is_never_written_back():
    report = schema.TimingGroupReport.model_validate(
        {
            'languages': ['cpp'],
            'timeLimit': 1000,
            'origin': 'estimated',
            'droppedUpper': ['sols/slow.cpp'],
        }
    )
    assert 'droppedUpper' not in report.model_dump()
