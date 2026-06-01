import pytest
from pydantic import ValidationError

from rbx.box.environment import (
    LanguageGroupFallback,
    TimingConfig,
)


def test_timing_config_defaults_to_no_groups():
    cfg = TimingConfig()
    assert cfg.groups == []


def test_language_group_with_when_empty_parses():
    cfg = TimingConfig.model_validate(
        {
            'groups': [
                {'languages': ['c', 'cpp']},
                {
                    'languages': ['java', 'kotlin'],
                    'whenEmpty': {'relativeTo': 'cpp', 'multiplier': 2.0},
                },
            ]
        }
    )
    assert cfg.groups[0].languages == ['c', 'cpp']
    assert cfg.groups[1].whenEmpty == LanguageGroupFallback(
        relativeTo='cpp', multiplier=2.0
    )


def test_language_cannot_appear_in_two_groups():
    with pytest.raises(ValidationError, match='cpp'):
        TimingConfig.model_validate(
            {'groups': [{'languages': ['c', 'cpp']}, {'languages': ['cpp']}]}
        )


def test_when_empty_requires_multiplier():
    with pytest.raises(ValidationError):
        LanguageGroupFallback.model_validate({'relativeTo': 'cpp'})
