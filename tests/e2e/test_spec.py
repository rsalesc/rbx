import copy
import pathlib

import pytest
from pydantic import ValidationError

from rbx.box.schema import ExpectedOutcome
from tests.e2e.spec import load_spec, parse_spec


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


def test_unknown_verdict_error_includes_location_path():
    data = {
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
    with pytest.raises(ValidationError) as exc_info:
        parse_spec(data)
    errors = exc_info.value.errors()
    locs = [err['loc'] for err in errors]
    assert any(
        'scenarios' in loc
        and 0 in loc
        and 'steps' in loc
        and 'expect' in loc
        and 'solutions' in loc
        and 'sols/x.cpp' in loc
        for loc in locs
    ), f'expected location path through solutions/sols/x.cpp, got {locs!r}'


def test_parse_spec_does_not_mutate_input():
    data = {
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
    snapshot = copy.deepcopy(data)
    parse_spec(data)
    assert data == snapshot


def test_empty_solution_matcher_is_rejected():
    with pytest.raises(ValueError):
        parse_spec(
            {
                'scenarios': [
                    {
                        'name': 's',
                        'steps': [
                            {
                                'cmd': 'run',
                                'expect': {'solutions': {'sols/main.cpp': {}}},
                            }
                        ],
                    }
                ]
            }
        )


def test_markers_default_empty():
    spec = parse_spec({'scenarios': [{'name': 's', 'steps': []}]})
    assert spec.scenarios[0].markers == []


def test_markers_slow_parses():
    spec = parse_spec({'scenarios': [{'name': 's', 'markers': ['slow'], 'steps': []}]})
    assert spec.scenarios[0].markers == ['slow']


def test_markers_slow_and_docker_parses():
    spec = parse_spec(
        {'scenarios': [{'name': 's', 'markers': ['slow', 'docker'], 'steps': []}]}
    )
    assert spec.scenarios[0].markers == ['slow', 'docker']


def test_markers_unknown_rejected():
    with pytest.raises(ValueError) as exc_info:
        parse_spec({'scenarios': [{'name': 's', 'markers': ['bogus'], 'steps': []}]})
    assert 'bogus' in str(exc_info.value)


def test_load_spec_against_simple_ac():
    path = (
        pathlib.Path(__file__).resolve().parent
        / 'testdata'
        / 'simple-ac'
        / 'e2e.rbx.yml'
    )
    spec = load_spec(path)
    assert [s.name for s in spec.scenarios] == ['smoke']
    assert spec.scenarios[0].steps[0].cmd == 'build'
    assert spec.scenarios[0].steps[0].expect_exit == 0
