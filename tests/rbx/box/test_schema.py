import os
from unittest import mock

import pytest
from pydantic import ValidationError

from rbx.box.schema import (
    RESERVED_VAR_NAMES,
    LimitModifiers,
    LimitsProfile,
)


class TestLimitsProfile:
    """Test LimitsProfile methods."""

    def test_timelimit_for_language_no_modifiers(self):
        """Test timelimit_for_language without any language-specific modifiers."""
        profile = LimitsProfile(
            timeLimit=2000,
            memoryLimit=256,
        )

        assert profile.timelimit_for_language() == 2000
        assert profile.timelimit_for_language('cpp') == 2000
        assert profile.timelimit_for_language('python') == 2000

    def test_timelimit_for_language_with_time_override(self):
        """Test timelimit_for_language with specific time override for a language."""
        profile = LimitsProfile(
            timeLimit=2000,
            memoryLimit=256,
            modifiers={
                'cpp': LimitModifiers(time=1500),
                'python': LimitModifiers(time=3000),
            },
        )

        # No language specified - use base time limit
        assert profile.timelimit_for_language() == 2000

        # Language with time override
        assert profile.timelimit_for_language('cpp') == 1500
        assert profile.timelimit_for_language('python') == 3000

        # Language without modifiers - use base time limit
        assert profile.timelimit_for_language('java') == 2000

    def test_timelimit_for_language_with_time_multiplier(self):
        """Test timelimit_for_language with time multiplier for a language."""
        profile = LimitsProfile(
            timeLimit=2000,
            memoryLimit=256,
            modifiers={
                'python': LimitModifiers(timeMultiplier=2.5),
                'java': LimitModifiers(timeMultiplier=1.5),
            },
        )

        # No language specified - use base time limit
        assert profile.timelimit_for_language() == 2000

        # Language with time multiplier
        assert profile.timelimit_for_language('python') == int(2000 * 2.5)  # 5000
        assert profile.timelimit_for_language('java') == int(2000 * 1.5)  # 3000

        # Language without modifiers - use base time limit
        assert profile.timelimit_for_language('cpp') == 2000

    def test_timelimit_for_language_time_override_takes_precedence(self):
        """Test that time override takes precedence over time multiplier."""
        profile = LimitsProfile(
            timeLimit=2000,
            memoryLimit=256,
            modifiers={
                'cpp': LimitModifiers(time=1200, timeMultiplier=3.0),
            },
        )

        # Time override should be used first, then multiplier applied to that
        expected = int(1200 * 3.0)  # 3600
        assert profile.timelimit_for_language('cpp') == expected

    @mock.patch.dict(os.environ, {'RBX_TIME_MULTIPLIER': '2.0'})
    def test_timelimit_for_language_with_env_multiplier(self):
        """Test timelimit_for_language with RBX_TIME_MULTIPLIER environment variable."""
        profile = LimitsProfile(
            timeLimit=1000,
            memoryLimit=256,
        )

        # Environment multiplier should be applied to final result
        assert profile.timelimit_for_language() == int(1000 * 2.0)  # 2000
        assert profile.timelimit_for_language('cpp') == int(1000 * 2.0)  # 2000

    @mock.patch.dict(os.environ, {'RBX_TIME_MULTIPLIER': '1.5'})
    def test_timelimit_for_language_env_multiplier_with_language_modifiers(self):
        """Test timelimit_for_language with both language modifiers and environment multiplier."""
        profile = LimitsProfile(
            timeLimit=1000,
            memoryLimit=256,
            modifiers={
                'cpp': LimitModifiers(time=800, timeMultiplier=2.0),
                'python': LimitModifiers(timeMultiplier=3.0),
            },
        )

        # For cpp: time override (800) * timeMultiplier (2.0) * env multiplier (1.5)
        expected_cpp = int(int(800 * 2.0) * 1.5)  # int(1600 * 1.5) = 2400
        assert profile.timelimit_for_language('cpp') == expected_cpp

        # For python: base time (1000) * timeMultiplier (3.0) * env multiplier (1.5)
        expected_python = int(int(1000 * 3.0) * 1.5)  # int(3000 * 1.5) = 4500
        assert profile.timelimit_for_language('python') == expected_python

        # For java (no modifiers): base time (1000) * env multiplier (1.5)
        expected_java = int(1000 * 1.5)  # 1500
        assert profile.timelimit_for_language('java') == expected_java

    def test_memorylimit_for_language_no_modifiers(self):
        """Test memorylimit_for_language without any language-specific modifiers."""
        profile = LimitsProfile(
            timeLimit=2000,
            memoryLimit=256,
        )

        assert profile.memorylimit_for_language() == 256
        assert profile.memorylimit_for_language('cpp') == 256
        assert profile.memorylimit_for_language('python') == 256

    def test_memorylimit_for_language_with_memory_override(self):
        """Test memorylimit_for_language with specific memory override for a language."""
        profile = LimitsProfile(
            timeLimit=2000,
            memoryLimit=256,
            modifiers={
                'cpp': LimitModifiers(memory=128),
                'java': LimitModifiers(memory=512),
            },
        )

        # No language specified - use base memory limit
        assert profile.memorylimit_for_language() == 256

        # Language with memory override
        assert profile.memorylimit_for_language('cpp') == 128
        assert profile.memorylimit_for_language('java') == 512

        # Language without modifiers - use base memory limit
        assert profile.memorylimit_for_language('python') == 256

    def test_memorylimit_for_language_ignores_time_modifiers(self):
        """Test that memorylimit_for_language ignores time-related modifiers."""
        profile = LimitsProfile(
            timeLimit=2000,
            memoryLimit=256,
            modifiers={
                'cpp': LimitModifiers(time=1500, timeMultiplier=2.0),
                'python': LimitModifiers(timeMultiplier=3.0, memory=128),
            },
        )

        # cpp has time modifiers but no memory modifier
        assert profile.memorylimit_for_language('cpp') == 256

        # python has both time and memory modifiers - only memory should be used
        assert profile.memorylimit_for_language('python') == 128

    def test_memorylimit_for_language_none_language(self):
        """Test memorylimit_for_language with None language parameter."""
        profile = LimitsProfile(
            timeLimit=2000,
            memoryLimit=256,
            modifiers={
                'cpp': LimitModifiers(memory=128),
            },
        )

        # None language should return base memory limit
        assert profile.memorylimit_for_language(None) == 256

    def test_memorylimit_for_language_nonexistent_language(self):
        """Test memorylimit_for_language with a language that has no modifiers."""
        profile = LimitsProfile(
            timeLimit=2000,
            memoryLimit=256,
            modifiers={
                'cpp': LimitModifiers(memory=128),
            },
        )

        # Language not in modifiers should return base memory limit
        assert profile.memorylimit_for_language('nonexistent') == 256

    def test_timelimit_assertion_failure(self):
        """Test that timelimit_for_language raises assertion error when timeLimit is None."""
        profile = LimitsProfile(
            memoryLimit=256,
        )

        with pytest.raises(AssertionError):
            profile.timelimit_for_language()

    def test_memorylimit_assertion_failure(self):
        """Test that memorylimit_for_language raises assertion error when memoryLimit is None."""
        profile = LimitsProfile(
            timeLimit=2000,
        )

        with pytest.raises(AssertionError):
            profile.memorylimit_for_language()

    @mock.patch.dict(os.environ, {'RBX_TIME_MULTIPLIER': '0.5'})
    def test_timelimit_for_language_fractional_env_multiplier(self):
        """Test timelimit_for_language with fractional environment multiplier."""
        profile = LimitsProfile(
            timeLimit=1000,
            memoryLimit=256,
        )

        # Should handle fractional multipliers properly
        assert profile.timelimit_for_language() == int(1000 * 0.5)  # 500

    def test_complex_scenario_all_modifiers(self):
        """Test a complex scenario with multiple types of modifiers."""
        profile = LimitsProfile(
            timeLimit=2000,
            memoryLimit=512,
            modifiers={
                'cpp': LimitModifiers(time=1500, memory=256),
                'python': LimitModifiers(timeMultiplier=2.0, memory=1024),
                'java': LimitModifiers(timeMultiplier=1.5),
                'go': LimitModifiers(memory=128),
            },
        )

        # Test time limits
        assert profile.timelimit_for_language('cpp') == 1500  # time override
        assert profile.timelimit_for_language('python') == int(2000 * 2.0)  # 4000
        assert profile.timelimit_for_language('java') == int(2000 * 1.5)  # 3000
        assert profile.timelimit_for_language('go') == 2000  # no time modifier

        # Test memory limits
        assert profile.memorylimit_for_language('cpp') == 256  # memory override
        assert profile.memorylimit_for_language('python') == 1024  # memory override
        assert profile.memorylimit_for_language('java') == 512  # no memory modifier
        assert profile.memorylimit_for_language('go') == 128  # memory override


class TestPackageTestcaseGroupUniqueness:
    def test_duplicate_top_level_group_names_are_rejected(self):
        from pydantic import ValidationError

        from rbx.box.schema import Package, TestcaseGroup

        with pytest.raises(
            ValidationError, match='Testcase group names must be unique'
        ):
            Package(
                name='dup',
                timeLimit=1000,
                memoryLimit=256,
                testcases=[
                    TestcaseGroup(name='samples'),
                    TestcaseGroup(name='samples'),
                ],
            )

    def test_unique_top_level_group_names_are_accepted(self):
        from rbx.box.schema import Package, ScoreType, TestcaseGroup

        package = Package(
            name='okay',
            timeLimit=1000,
            memoryLimit=256,
            scoring=ScoreType.POINTS,
            testcases=[
                TestcaseGroup(name='samples'),
                TestcaseGroup(name='subtask1', score=30),
                TestcaseGroup(name='subtask2', score=70),
            ],
        )

        assert [g.name for g in package.testcases] == [
            'samples',
            'subtask1',
            'subtask2',
        ]


class TestTestcaseGroupSubgroupUniqueness:
    def test_duplicate_subgroup_names_within_parent_are_rejected(self):
        from pydantic import ValidationError

        from rbx.box.schema import TestcaseGroup, TestcaseSubgroup

        with pytest.raises(
            ValidationError, match='Testcase subgroup names must be unique'
        ):
            TestcaseGroup(
                name='subtask1',
                subgroups=[
                    TestcaseSubgroup(name='small'),
                    TestcaseSubgroup(name='small'),
                ],
            )

    def test_duplicate_subgroup_names_across_parents_are_allowed(self):
        from rbx.box.schema import (
            Package,
            ScoreType,
            TestcaseGroup,
            TestcaseSubgroup,
        )

        package = Package(
            name='okay',
            timeLimit=1000,
            memoryLimit=256,
            scoring=ScoreType.POINTS,
            testcases=[
                TestcaseGroup(name='samples'),
                TestcaseGroup(
                    name='subtask1',
                    score=30,
                    subgroups=[TestcaseSubgroup(name='small')],
                ),
                TestcaseGroup(
                    name='subtask2',
                    score=70,
                    subgroups=[TestcaseSubgroup(name='small')],
                ),
            ],
        )

        assert [g.name for g in package.testcases] == [
            'samples',
            'subtask1',
            'subtask2',
        ]
        assert [sg.name for sg in package.testcases[1].subgroups] == ['small']
        assert [sg.name for sg in package.testcases[2].subgroups] == ['small']


class TestSolutionOutcomePerGroup:
    def test_no_per_group_outcomes_resolves_to_none(self):
        from rbx.box.schema import ExpectedOutcome, Solution

        solution = Solution(path='sol.cpp', outcome=ExpectedOutcome.ACCEPTED)

        assert solution.outcomePerGroup == {}
        assert solution.expected_outcome_for_group('group1') is None
        assert solution.all_expected_outcomes() == {ExpectedOutcome.ACCEPTED}

    def test_explicit_group_takes_precedence_over_wildcard(self):
        from rbx.box.schema import ExpectedOutcome, Solution

        solution = Solution(
            path='sol.cpp',
            outcome=ExpectedOutcome.INCORRECT,
            outcomePerGroup={
                '*': ExpectedOutcome.ACCEPTED,
                'group3': ExpectedOutcome.TIME_LIMIT_EXCEEDED,
            },
        )

        assert (
            solution.expected_outcome_for_group('group3')
            == ExpectedOutcome.TIME_LIMIT_EXCEEDED
        )
        # Everything else, samples included, falls back to the wildcard.
        assert (
            solution.expected_outcome_for_group('samples') == ExpectedOutcome.ACCEPTED
        )
        assert solution.expected_outcome_for_group('group1') == ExpectedOutcome.ACCEPTED
        assert solution.all_expected_outcomes() == {
            ExpectedOutcome.INCORRECT,
            ExpectedOutcome.ACCEPTED,
            ExpectedOutcome.TIME_LIMIT_EXCEEDED,
        }

    def test_without_wildcard_unlisted_groups_have_no_expectation(self):
        from rbx.box.schema import ExpectedOutcome, Solution

        solution = Solution(
            path='sol.cpp',
            outcome=ExpectedOutcome.INCORRECT,
            outcomePerGroup={'group2': ExpectedOutcome.WRONG_ANSWER},
        )

        assert (
            solution.expected_outcome_for_group('group2')
            == ExpectedOutcome.WRONG_ANSWER
        )
        assert solution.expected_outcome_for_group('group1') is None

    def test_outcome_names_are_parsed_from_yaml_aliases(self):
        from rbx.box.schema import ExpectedOutcome, Solution

        solution = Solution.model_validate(
            {
                'path': 'sol.cpp',
                'outcome': 'incorrect',
                'outcomePerGroup': {'*': 'ac', 'g': 'tle'},
            }
        )

        assert solution.outcomePerGroup == {
            '*': ExpectedOutcome.ACCEPTED,
            'g': ExpectedOutcome.TIME_LIMIT_EXCEEDED,
        }

    def test_unset_outcome_still_contributes_any_to_all_expected_outcomes(self):
        from rbx.box.schema import ExpectedOutcome, Solution

        solution = Solution(
            path='sol.cpp',
            outcomePerGroup={'g': ExpectedOutcome.TIME_LIMIT_EXCEEDED},
        )

        # `outcome` defaults to ANY, and that default is part of the pool: an ANY
        # solution keeps being counted as neither good nor merely passing.
        assert solution.outcome == ExpectedOutcome.ANY
        assert solution.all_expected_outcomes() == {
            ExpectedOutcome.ANY,
            ExpectedOutcome.TIME_LIMIT_EXCEEDED,
        }


class TestPackageOutcomePerGroupValidation:
    def _package(self, **solution_kwargs):
        from rbx.box.schema import ExpectedOutcome, Package, Solution, TestcaseGroup

        return Package(
            name='prob',
            timeLimit=1000,
            memoryLimit=256,
            testcases=[
                TestcaseGroup(name='samples'),
                TestcaseGroup(name='group1'),
                TestcaseGroup(name='group2'),
            ],
            solutions=[
                Solution(path='sols/main.cpp', outcome=ExpectedOutcome.ACCEPTED),
                Solution(path='sols/other.cpp', **solution_kwargs),
            ],
        )

    def test_unknown_group_key_is_rejected(self):
        from pydantic import ValidationError

        from rbx.box.schema import ExpectedOutcome

        with pytest.raises(ValidationError, match='typo') as excinfo:
            self._package(
                outcome=ExpectedOutcome.INCORRECT,
                outcomePerGroup={'typo': ExpectedOutcome.WRONG_ANSWER},
            )

        # The error renders with no `loc`, so the message is the whole diagnostic:
        # it has to say which names would have worked.
        assert 'Known groups: samples, group1, group2.' in str(excinfo.value)

    def test_unknown_group_is_reported_before_contradictions(self):
        from pydantic import ValidationError

        from rbx.box.schema import ExpectedOutcome

        # The key is both unknown and contradictory; the actionable error is the
        # unknown key, and no later validator may crash on it.
        with pytest.raises(ValidationError, match='not a testcase group'):
            self._package(
                outcome=ExpectedOutcome.ACCEPTED,
                outcomePerGroup={'typo': ExpectedOutcome.WRONG_ANSWER},
            )

    def test_known_group_and_wildcard_keys_are_accepted(self):
        from rbx.box.schema import ExpectedOutcome

        package = self._package(
            outcome=ExpectedOutcome.INCORRECT,
            outcomePerGroup={
                '*': ExpectedOutcome.ACCEPTED,
                'samples': ExpectedOutcome.ACCEPTED,
                'group2': ExpectedOutcome.WRONG_ANSWER,
            },
        )

        assert len(package.solutions) == 2

    def test_main_solution_cannot_expect_a_non_ac_group(self):
        from pydantic import ValidationError

        from rbx.box.schema import ExpectedOutcome, Package, Solution, TestcaseGroup

        with pytest.raises(ValidationError, match='first accepted solution'):
            Package(
                name='prob',
                timeLimit=1000,
                memoryLimit=256,
                testcases=[TestcaseGroup(name='samples'), TestcaseGroup(name='group1')],
                solutions=[
                    Solution(
                        path='sols/main.cpp',
                        outcome=ExpectedOutcome.ACCEPTED,
                        outcomePerGroup={'group1': ExpectedOutcome.WRONG_ANSWER},
                    ),
                ],
            )

    def test_accepted_solution_listed_after_another_one_is_rejected(self):
        from pydantic import ValidationError

        from rbx.box.schema import ExpectedOutcome, Package, Solution, TestcaseGroup

        # An ACCEPTED solution that is not listed first is rejected outright, so
        # `get_main_solution` never has to look past the first solution.
        with pytest.raises(ValidationError, match='must have the "ACCEPTED" outcome'):
            Package(
                name='prob',
                timeLimit=1000,
                memoryLimit=256,
                testcases=[TestcaseGroup(name='samples'), TestcaseGroup(name='group1')],
                solutions=[
                    Solution(path='sols/wa.cpp', outcome=ExpectedOutcome.INCORRECT),
                    Solution(
                        path='sols/main.cpp',
                        outcome=ExpectedOutcome.ACCEPTED,
                        outcomePerGroup={'group1': ExpectedOutcome.WRONG_ANSWER},
                    ),
                ],
            )

    def test_wildcard_default_is_not_reported_as_a_group_name(self):
        from pydantic import ValidationError

        from rbx.box.schema import ExpectedOutcome, Package, Solution, TestcaseGroup

        with pytest.raises(ValidationError, match='default for every group') as excinfo:
            Package(
                name='prob',
                timeLimit=1000,
                memoryLimit=256,
                testcases=[TestcaseGroup(name='samples'), TestcaseGroup(name='group1')],
                solutions=[
                    Solution(
                        path='sols/main.cpp',
                        outcome=ExpectedOutcome.ACCEPTED,
                        outcomePerGroup={'*': ExpectedOutcome.WRONG_ANSWER},
                    ),
                ],
            )

        assert 'on "*"' not in str(excinfo.value)

    def test_package_without_a_main_solution_is_not_held_to_accepted(self):
        from rbx.box.schema import ExpectedOutcome, Package, Solution, TestcaseGroup

        # Nothing generates the reference outputs here (they come from manual
        # `outputPath`s), so there is no solution to hold to ACCEPTED.
        package = Package(
            name='prob',
            timeLimit=1000,
            memoryLimit=256,
            testcases=[TestcaseGroup(name='samples'), TestcaseGroup(name='group1')],
            solutions=[
                Solution(
                    path='sols/slow.cpp',
                    outcome=ExpectedOutcome.INCORRECT,
                    outcomePerGroup={'group1': ExpectedOutcome.TIME_LIMIT_EXCEEDED},
                ),
            ],
        )

        assert package.solutions[0].outcomePerGroup == {
            'group1': ExpectedOutcome.TIME_LIMIT_EXCEEDED
        }

    def test_main_solution_may_pin_groups_to_accepted(self):
        from rbx.box.schema import ExpectedOutcome, Package, Solution, TestcaseGroup

        package = Package(
            name='prob',
            timeLimit=1000,
            memoryLimit=256,
            testcases=[TestcaseGroup(name='samples'), TestcaseGroup(name='group1')],
            solutions=[
                Solution(
                    path='sols/main.cpp',
                    outcome=ExpectedOutcome.ACCEPTED,
                    outcomePerGroup={'*': ExpectedOutcome.ACCEPTED},
                ),
            ],
        )

        assert package.solutions[0].outcomePerGroup == {'*': ExpectedOutcome.ACCEPTED}

    def test_group_expectation_contradicting_the_pooled_one_is_rejected(self):
        from pydantic import ValidationError

        from rbx.box.schema import ExpectedOutcome

        with pytest.raises(ValidationError, match='cannot be satisfied'):
            # Pooled ACCEPTED forbids any bad verdict, group2 demands a WA.
            self._package(
                outcome=ExpectedOutcome.ACCEPTED,
                outcomePerGroup={'group2': ExpectedOutcome.WRONG_ANSWER},
            )

    def test_disjoint_bad_expectations_are_rejected(self):
        from pydantic import ValidationError

        from rbx.box.schema import ExpectedOutcome

        with pytest.raises(ValidationError, match='cannot be satisfied'):
            # A WA on group2 would violate the pooled RTE expectation.
            self._package(
                outcome=ExpectedOutcome.RUNTIME_ERROR,
                outcomePerGroup={'group2': ExpectedOutcome.WRONG_ANSWER},
            )

    def test_all_groups_accepted_contradicts_a_bad_pooled_outcome(self):
        from pydantic import ValidationError

        from rbx.box.schema import ExpectedOutcome

        with pytest.raises(ValidationError, match='cannot be satisfied'):
            # Every group must be fully AC, yet the testset must fail somewhere.
            self._package(
                outcome=ExpectedOutcome.INCORRECT,
                outcomePerGroup={'*': ExpectedOutcome.ACCEPTED},
            )

    def test_unconstrained_group_can_host_the_bad_pooled_verdict(self):
        from rbx.box.schema import ExpectedOutcome

        # Without a `*`, group1 has no expectation at all, so it is free to be
        # the group where the pooled INCORRECT happens.
        package = self._package(
            outcome=ExpectedOutcome.INCORRECT,
            outcomePerGroup={'group2': ExpectedOutcome.ACCEPTED},
        )

        assert package.solutions[1].expected_outcome_for_group('group1') is None

    def test_package_without_groups_is_not_checked_for_satisfiability(self):
        from rbx.box.schema import ExpectedOutcome, Package, Solution

        # With no groups declared, `*` resolves to nothing, so it cannot make the
        # pooled expectation unsatisfiable on its own.
        package = Package(
            name='prob',
            timeLimit=1000,
            memoryLimit=256,
            solutions=[
                Solution(
                    path='sols/wa.cpp',
                    outcome=ExpectedOutcome.INCORRECT,
                    outcomePerGroup={'*': ExpectedOutcome.ACCEPTED},
                ),
            ],
        )

        assert package.testcases == []

    def test_default_pooled_outcome_never_contradicts_a_group(self):
        from rbx.box.schema import ExpectedOutcome

        # Declaring only `outcomePerGroup` leaves `outcome` at its ANY default,
        # which matches ACCEPTED and so imposes no existential requirement.
        package = self._package(
            outcomePerGroup={
                '*': ExpectedOutcome.ACCEPTED,
                'group2': ExpectedOutcome.WRONG_ANSWER,
            },
        )

        assert package.solutions[1].outcome == ExpectedOutcome.ANY

    def test_compatible_layers_are_accepted(self):
        from rbx.box.schema import ExpectedOutcome

        # group2 is the only group allowed to fail, and a TLE satisfies the pooled
        # INCORRECT: pins the satisfiable side of the every-group-pinned branch.
        package = self._package(
            outcome=ExpectedOutcome.INCORRECT,
            outcomePerGroup={
                '*': ExpectedOutcome.ACCEPTED,
                'group2': ExpectedOutcome.TIME_LIMIT_EXCEEDED,
            },
        )

        assert package.solutions[1].outcomePerGroup['group2'] == (
            ExpectedOutcome.TIME_LIMIT_EXCEEDED
        )


class TestPackageVarsPerGroup:
    def test_expanded_vars_for_group_applies_override(self):
        from rbx.box.schema import Package

        pkg = Package.model_validate(
            {
                'name': 'test',
                'timeLimit': 1000,
                'memoryLimit': 256,
                'vars': {'AB': {'min': -200, 'max': 200}},
                'testcases': [
                    {'name': 'sub2', 'vars': {'AB': {'min': 0}}},
                    {'name': 'sub4'},
                ],
            }
        )

        assert pkg.expanded_vars == {'AB.min': -200, 'AB.max': 200}
        assert pkg.expanded_vars_for_group('sub2') == {'AB.min': 0, 'AB.max': 200}
        assert pkg.expanded_vars_for_group('sub4') == {'AB.min': -200, 'AB.max': 200}
        # Unknown or absent group falls back to the package vars.
        assert pkg.expanded_vars_for_group('nope') == {'AB.min': -200, 'AB.max': 200}
        assert pkg.expanded_vars_for_group(None) == {'AB.min': -200, 'AB.max': 200}

    def test_overrides_feed_the_vars_derived_from_them(self):
        from rbx.box.schema import Package

        # The merge happens before expansion, so `M` is recomputed from the
        # group's `N`. Merging the two *expanded* var sets instead would leave
        # `M` at its package value of 20 and silently desync the constraints.
        pkg = Package.model_validate(
            {
                'name': 'test',
                'timeLimit': 1000,
                'memoryLimit': 256,
                'vars': {'N': 10, 'M': 'py`vars.N * 2`'},
                'testcases': [{'name': 'big', 'vars': {'N': 100}}],
            }
        )

        assert pkg.expanded_vars == {'N': 10, 'M': 20}
        assert pkg.expanded_vars_for_group('big') == {'N': 100, 'M': 200}


class TestFirstSolutionIsMain:
    def _package(self, *outcomes):
        from rbx.box.schema import Package, Solution, TestcaseGroup

        return Package(
            name='prob',
            timeLimit=1000,
            memoryLimit=256,
            testcases=[TestcaseGroup(name='samples')],
            solutions=[
                Solution(path=f'sols/sol{i}.cpp', outcome=outcome)
                for i, outcome in enumerate(outcomes)
            ],
        )

    def test_accepted_solution_after_a_non_accepted_one_is_rejected(self):
        from pydantic import ValidationError

        from rbx.box.schema import ExpectedOutcome

        # Regression: the guard used to compare the solution's `ExpectedOutcome`
        # against the grading `Outcome` enum, which never matches, so this
        # package was silently accepted.
        with pytest.raises(ValidationError, match='must have the "ACCEPTED" outcome'):
            self._package(
                ExpectedOutcome.WRONG_ANSWER,
                ExpectedOutcome.ACCEPTED,
            )

    def test_accepted_solution_coming_first_is_accepted(self):
        from rbx.box.schema import ExpectedOutcome

        package = self._package(
            ExpectedOutcome.ACCEPTED,
            ExpectedOutcome.WRONG_ANSWER,
        )

        assert package.solutions[0].outcome == ExpectedOutcome.ACCEPTED

    def test_package_without_accepted_solutions_is_not_checked(self):
        from rbx.box.schema import ExpectedOutcome

        package = self._package(
            ExpectedOutcome.WRONG_ANSWER,
            ExpectedOutcome.TIME_LIMIT_EXCEEDED,
        )

        assert len(package.solutions) == 2


class TestReservedVarNames:
    """Vars must not shadow the command-line flags testlib and rbx consume.

    Vars are flattened to dotted keys and passed to validators as
    `--<key>=<value>`, so a top-level var named `group` would emit
    `--group=<value>` and make `rbx::getGroup()` resolve a group that does not
    exist -- silently falling back to the package-level constraints.
    """

    def _package(self, **kwargs):
        from rbx.box.schema import Package

        return Package(name='problem', timeLimit=1000, memoryLimit=256, **kwargs)

    @pytest.mark.parametrize('name', sorted(RESERVED_VAR_NAMES))
    def test_reserved_top_level_package_var_is_rejected(self, name: str):
        with pytest.raises(ValidationError, match=f'"{name}" collides with'):
            self._package(vars={name: 1})

    @pytest.mark.parametrize('name', sorted(RESERVED_VAR_NAMES))
    def test_reserved_top_level_group_var_is_rejected(self, name: str):
        from rbx.box.schema import TestcaseGroup

        with pytest.raises(ValidationError, match=f'"{name}" collides with'):
            TestcaseGroup(name='main', vars={name: 1})

    def test_error_message_points_at_the_flag(self):
        with pytest.raises(ValidationError, match=r'--group=<value>'):
            self._package(vars={'group': 'oops'})

    def test_nested_reserved_name_is_accepted(self):
        # Flattens to `--AB.group=1`, which no flag parser matches.
        package = self._package(vars={'AB': {'group': 1}})

        assert package.expanded_vars == {'AB.group': 1}

    def test_nested_reserved_name_is_accepted_in_a_group(self):
        from rbx.box.schema import TestcaseGroup

        group = TestcaseGroup(name='main', vars={'AB': {'group': 1}})

        assert group.vars == {'AB': {'group': 1}}

    def test_top_level_reserved_name_holding_a_dict_is_accepted(self):
        # Flattens to `--group.min=1`, not `--group=...`.
        package = self._package(vars={'group': {'min': 1}})

        assert package.expanded_vars == {'group.min': 1}

    def test_ordinary_vars_still_validate(self):
        package = self._package(vars={'MAX_N': 100, 'AB': {'min': 1, 'max': 10}})

        assert package.expanded_vars == {'MAX_N': 100, 'AB.min': 1, 'AB.max': 10}
