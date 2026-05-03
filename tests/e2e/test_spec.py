import pytest

from rbx.box.schema import ExpectedOutcome
from tests.e2e.spec import parse_spec


def test_minimal():
    spec = parse_spec({'scenarios': [{'name': 's', 'steps': [{'cmd': 'build'}]}]})
    assert spec.scenarios[0].steps[0].expect_exit == 0
    assert spec.scenarios[0].steps[0].cmd == 'build'


def test_rejects_unknown_keys_in_step():
    with pytest.raises(ValueError):
        parse_spec({'scenarios': [{'name': 's', 'steps': [{'cmd': 'x', 'typo': 1}]}]})


def test_rejects_unknown_keys_in_scenario():
    with pytest.raises(ValueError):
        parse_spec({'scenarios': [{'name': 's', 'steps': [], 'bogus': True}]})


def test_rejects_unknown_keys_at_root():
    with pytest.raises(ValueError):
        parse_spec({'scenarios': [], 'extra': 1})


def test_rejects_unknown_keys_in_expect():
    with pytest.raises(ValueError):
        parse_spec(
            {
                'scenarios': [
                    {
                        'name': 's',
                        'steps': [{'cmd': 'x', 'expect': {'unknown_matcher': 1}}],
                    }
                ]
            }
        )


def test_rejects_duplicate_scenario_names():
    with pytest.raises(ValueError):
        parse_spec(
            {
                'scenarios': [
                    {'name': 's', 'steps': []},
                    {'name': 's', 'steps': []},
                ]
            }
        )


def test_missing_required_name_field():
    with pytest.raises(ValueError):
        parse_spec({'scenarios': [{'steps': []}]})


def test_missing_required_cmd_field():
    with pytest.raises(ValueError):
        parse_spec({'scenarios': [{'name': 's', 'steps': [{}]}]})


def test_empty_scenarios_list():
    spec = parse_spec({'scenarios': []})
    assert spec.scenarios == []


def test_expect_exit_nonzero():
    spec = parse_spec(
        {
            'scenarios': [
                {
                    'name': 's',
                    'steps': [{'cmd': 'build', 'expect_exit': 2}],
                }
            ]
        }
    )
    assert spec.scenarios[0].steps[0].expect_exit == 2


def test_solutions_bare_verdict_parses_as_star_map():
    spec = parse_spec(
        {
            'scenarios': [
                {
                    'name': 's',
                    'steps': [
                        {
                            'cmd': 'run',
                            'expect': {'solutions': {'sols/main.cpp': 'ac'}},
                        }
                    ],
                }
            ]
        }
    )
    matcher = spec.scenarios[0].steps[0].expect.solutions['sols/main.cpp']
    assert matcher.star == ExpectedOutcome.ACCEPTED
    assert matcher.entries == {}


def test_solutions_star_only():
    spec = parse_spec(
        {
            'scenarios': [
                {
                    'name': 's',
                    'steps': [
                        {
                            'cmd': 'run',
                            'expect': {
                                'solutions': {'sols/main.cpp': {'*': 'accepted'}}
                            },
                        }
                    ],
                }
            ]
        }
    )
    matcher = spec.scenarios[0].steps[0].expect.solutions['sols/main.cpp']
    assert matcher.star == ExpectedOutcome.ACCEPTED
    assert matcher.entries == {}


def test_solutions_full_form():
    spec = parse_spec(
        {
            'scenarios': [
                {
                    'name': 's',
                    'steps': [
                        {
                            'cmd': 'run',
                            'expect': {
                                'solutions': {
                                    'sols/wa.cpp': {
                                        '*': 'wa',
                                        'samples': 'ac',
                                        'main_tests/edge': 'ac',
                                    }
                                }
                            },
                        }
                    ],
                }
            ]
        }
    )
    m = spec.scenarios[0].steps[0].expect.solutions['sols/wa.cpp']
    assert m.star == ExpectedOutcome.WRONG_ANSWER
    assert m.entries == {
        'samples': ExpectedOutcome.ACCEPTED,
        'main_tests/edge': ExpectedOutcome.ACCEPTED,
    }


def test_outcome_aliases_accepted():
    for raw in ['ac', 'AC', 'accepted', 'correct']:
        spec = parse_spec(
            {
                'scenarios': [
                    {
                        'name': 's',
                        'steps': [
                            {
                                'cmd': 'run',
                                'expect': {'solutions': {'sols/m.cpp': raw}},
                            }
                        ],
                    }
                ]
            }
        )
        matcher = spec.scenarios[0].steps[0].expect.solutions['sols/m.cpp']
        assert matcher.star == ExpectedOutcome.ACCEPTED, raw


def test_outcome_aliases_other_verdicts():
    cases = {
        'wa': ExpectedOutcome.WRONG_ANSWER,
        'tle': ExpectedOutcome.TIME_LIMIT_EXCEEDED,
        'rte': ExpectedOutcome.RUNTIME_ERROR,
        'mle': ExpectedOutcome.MEMORY_LIMIT_EXCEEDED,
    }
    for raw, expected in cases.items():
        spec = parse_spec(
            {
                'scenarios': [
                    {
                        'name': 's',
                        'steps': [
                            {
                                'cmd': 'run',
                                'expect': {'solutions': {'sols/m.cpp': raw}},
                            }
                        ],
                    }
                ]
            }
        )
        matcher = spec.scenarios[0].steps[0].expect.solutions['sols/m.cpp']
        assert matcher.star == expected, raw


def test_unknown_verdict_bare():
    with pytest.raises(ValueError):
        parse_spec(
            {
                'scenarios': [
                    {
                        'name': 's',
                        'steps': [
                            {
                                'cmd': 'run',
                                'expect': {'solutions': {'sols/x.cpp': 'BOGUS'}},
                            }
                        ],
                    }
                ]
            }
        )


def test_unknown_verdict_in_full_form():
    with pytest.raises(ValueError):
        parse_spec(
            {
                'scenarios': [
                    {
                        'name': 's',
                        'steps': [
                            {
                                'cmd': 'run',
                                'expect': {
                                    'solutions': {
                                        'sols/x.cpp': {
                                            '*': 'ac',
                                            'samples': 'NOPE',
                                        }
                                    }
                                },
                            }
                        ],
                    }
                ]
            }
        )
