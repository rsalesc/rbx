"""Tests for contest schema (ContestProblem aliases and uniqueness)."""

import pytest
from pydantic import ValidationError

from rbx.box.contest.schema import Contest, ContestProblem


class TestContestProblemAliases:
    def test_aliases_default_empty(self):
        p = ContestProblem(short_name='A')
        assert p.aliases == []
        assert p.all_identifiers() == {'a'}

    def test_aliases_in_all_identifiers(self):
        p = ContestProblem(short_name='A', aliases=['choco', 'apple'])
        assert p.all_identifiers() == {'a', 'choco', 'apple'}

    def test_alias_valid_pattern(self):
        p = ContestProblem(short_name='A', aliases=['choco', 'prob_1', 'x_y'])
        assert p.aliases == ['choco', 'prob_1', 'x_y']

    def test_alias_invalid_pattern_rejected(self):
        with pytest.raises(ValidationError) as exc:
            ContestProblem(short_name='A', aliases=['has space'])
        assert 'has space' in str(exc.value) or 'alias' in str(exc.value).lower()

        with pytest.raises(ValidationError):
            ContestProblem(short_name='A', aliases=[''])

        with pytest.raises(ValidationError):
            ContestProblem(short_name='A', aliases=['a' * 33])


class TestContestProblemIdentifiersUnique:
    def test_duplicate_short_name_rejected(self):
        with pytest.raises(ValidationError) as exc:
            Contest(
                name='Test',
                problems=[
                    ContestProblem(short_name='A'),
                    ContestProblem(short_name='A'),
                ],
            )
        err = str(exc.value)
        assert 'a' in err.lower() and (
            'identifier' in err.lower()
            or 'used by more' in err
            or 'problem' in err.lower()
        )

    def test_short_name_same_as_other_alias_rejected(self):
        with pytest.raises(ValidationError):
            Contest(
                name='Test',
                problems=[
                    ContestProblem(short_name='A'),
                    ContestProblem(short_name='B', aliases=['a']),
                ],
            )

    def test_duplicate_alias_across_problems_rejected(self):
        with pytest.raises(ValidationError):
            Contest(
                name='Test',
                problems=[
                    ContestProblem(short_name='A', aliases=['choco']),
                    ContestProblem(short_name='B', aliases=['choco']),
                ],
            )

    def test_case_insensitive_uniqueness(self):
        with pytest.raises(ValidationError):
            Contest(
                name='Test',
                problems=[
                    ContestProblem(short_name='A', aliases=['Choco']),
                    ContestProblem(short_name='B', aliases=['choco']),
                ],
            )

    def test_valid_unique_aliases_accepted(self):
        contest = Contest(
            name='Test',
            problems=[
                ContestProblem(short_name='A', aliases=['apple']),
                ContestProblem(short_name='B', aliases=['banana']),
            ],
        )
        assert len(contest.problems) == 2
        assert contest.problems[0].all_identifiers() == {'a', 'apple'}
        assert contest.problems[1].all_identifiers() == {'b', 'banana'}
