"""Tests for how package vars are rendered onto the validator command line.

Kept apart from `validators_test.py` on purpose: this is pure argv
construction, with no package, no compilation and no sandbox involved.
"""

from rbx.box.validators import _get_var_args


class TestGetVarArgs:
    def test_bools_are_rendered_as_one_and_zero(self):
        """testlib's `opt<bool>` and jngen's `getOpt<bool>` both read `1`/`0`.

        Python's `str()` would emit `True`/`False`, which neither can read.
        """
        assert _get_var_args({'flag': True, 'other': False}) == [
            '--flag=1',
            '--other=0',
        ]

    def test_bools_are_not_rendered_with_python_or_cpp_spelling(self):
        assert '--flag=True' not in _get_var_args({'flag': True})
        assert '--flag=true' not in _get_var_args({'flag': True})
        assert '--flag=False' not in _get_var_args({'flag': False})
        assert '--flag=false' not in _get_var_args({'flag': False})

    def test_numbers_and_strings_are_unaffected(self):
        assert _get_var_args(
            {'MAX_N': 100, 'MIN_X': -5, 'EPS': 0.5, 'MODE': 'fast'}
        ) == [
            '--MAX_N=100',
            '--MIN_X=-5',
            '--EPS=0.5',
            '--MODE=fast',
        ]

    def test_dotted_keys_are_kept_verbatim(self):
        assert _get_var_args({'AB.min': 1, 'AB.flag': True}) == [
            '--AB.min=1',
            '--AB.flag=1',
        ]

    def test_no_vars_yields_no_args(self):
        assert _get_var_args({}) == []
