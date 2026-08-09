import pathlib
import shutil
import subprocess
from typing import Dict, List

import pytest

from rbx import config

# Imported as a module: a bare `TestcaseGroup` name makes pytest try to collect
# the Pydantic model as a test class.
from rbx.box import header, schema
from rbx.box.fields import RecVars
from rbx.box.testing import testing_package


class TestHeader:
    """Tests for the header.py module."""

    def test_generate_header_with_no_variables(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test generate_header with a package that has no variables."""
        # Generate header with no variables
        header.generate_header()

        # Check that rbx.h file was created
        rbx_header_path = pathlib.Path('rbx.h')
        assert rbx_header_path.exists()

        # Read the generated header
        generated_content = rbx_header_path.read_text()

        # Check that the header contains the expected structure
        assert (
            'std::optional<std::string> getStringVar(std::string name)'
            in generated_content
        )
        assert 'std::optional<int64_t> getIntVar(std::string name)' in generated_content
        assert 'std::optional<float> getFloatVar(std::string name)' in generated_content
        assert 'std::optional<bool> getBoolVar(std::string name)' in generated_content

        # Since there are no variables, the functions should only return nullopt
        assert 'return std::nullopt;' in generated_content

    def test_generate_header_with_string_variables(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test generate_header with string variables."""
        # Set some string variables
        testing_pkg.set_vars(
            {
                'str_var1': 'hello',
                'str_var2': 'world with spaces',
                'str_var3': 'special"chars',
            }
        )

        header.generate_header()

        rbx_header_path = pathlib.Path('rbx.h')
        generated_content = rbx_header_path.read_text()

        # Check that string variables are properly escaped and included
        assert (
            'if (name == "str_var1") {\n    return "hello";\n  }' in generated_content
        )
        assert (
            'if (name == "str_var2") {\n    return "world with spaces";\n  }'
            in generated_content
        )
        assert (
            'if (name == "str_var3") {\n    return "special\\"chars";\n  }'
            in generated_content
        )

    def test_generate_header_with_int_variables(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test generate_header with integer variables."""
        testing_pkg.set_vars(
            {
                'int_var1': 42,
                'int_var2': -100,
                'int_var3': 0,
            }
        )

        header.generate_header()

        rbx_header_path = pathlib.Path('rbx.h')
        generated_content = rbx_header_path.read_text()

        # Check that integer variables are properly included
        assert (
            'if (name == "int_var1") {\n    return static_cast<int64_t>(42);\n  }'
            in generated_content
        )
        assert (
            'if (name == "int_var2") {\n    return static_cast<int64_t>(-100);\n  }'
            in generated_content
        )
        assert (
            'if (name == "int_var3") {\n    return static_cast<int64_t>(0);\n  }'
            in generated_content
        )

    def test_generate_header_with_float_variables(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test generate_header with float variables."""
        testing_pkg.set_vars(
            {
                'float_var1': 3.14,
                'float_var2': -2.5,
                'float_var3': 0.0,
            }
        )

        header.generate_header()

        rbx_header_path = pathlib.Path('rbx.h')
        generated_content = rbx_header_path.read_text()

        # Check that float variables are properly included
        assert 'if (name == "float_var1") {\n    return 3.14;\n  }' in generated_content
        assert 'if (name == "float_var2") {\n    return -2.5;\n  }' in generated_content
        assert 'if (name == "float_var3") {\n    return 0.0;\n  }' in generated_content

    def test_generate_header_with_bool_variables(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test generate_header with boolean variables."""
        testing_pkg.set_vars(
            {
                'bool_var1': True,
                'bool_var2': False,
            }
        )

        header.generate_header()

        rbx_header_path = pathlib.Path('rbx.h')
        generated_content = rbx_header_path.read_text()

        # Check that boolean variables are properly included
        assert 'if (name == "bool_var1") {\n    return true;\n  }' in generated_content
        assert 'if (name == "bool_var2") {\n    return false;\n  }' in generated_content

    def test_generate_header_with_mixed_variables(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test generate_header with variables of different types."""
        testing_pkg.set_vars(
            {
                'str_var': 'test',
                'int_var': 123,
                'float_var': 45.67,
                'bool_var': True,
            }
        )

        header.generate_header()

        rbx_header_path = pathlib.Path('rbx.h')
        generated_content = rbx_header_path.read_text()

        # Check that all variable types are included in their respective functions
        assert 'if (name == "str_var") {\n    return "test";\n  }' in generated_content
        assert (
            'if (name == "int_var") {\n    return static_cast<int64_t>(123);\n  }'
            in generated_content
        )
        assert 'if (name == "float_var") {\n    return 45.67;\n  }' in generated_content
        assert 'if (name == "bool_var") {\n    return true;\n  }' in generated_content

    def test_generate_header_with_override_file(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test generate_header with an override file."""
        override_content = '// This is an override header\n'
        override_path = pathlib.Path('rbx.override.h')
        override_path.write_text(override_content)

        header.generate_header()

        rbx_header_path = pathlib.Path('rbx.h')
        generated_content = rbx_header_path.read_text()

        # Should use the override content exactly
        assert generated_content == override_content

    def test_get_header_creates_and_returns_path(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test get_header function creates the header and returns the path."""
        result = header.get_header()

        assert isinstance(result, pathlib.Path)
        assert result.name == 'rbx.h'
        assert result.exists()

    def test_get_header_caching(self, testing_pkg: testing_package.TestingPackage):
        """Test that get_header is cached properly."""
        # First call should create the file
        result1 = header.get_header()

        # Modify the file to test caching
        result1.write_text('modified content')

        # Second call should return the same path (cached)
        result2 = header.get_header()

        assert result1 == result2
        assert result2.read_text() == 'modified content'

    def test_check_int_bounds_valid_values(self):
        """Test _check_int_bounds with valid integer values."""
        # These should not raise exceptions
        header.check_int_bounds(0)
        header.check_int_bounds(100)
        header.check_int_bounds(-100)
        header.check_int_bounds(2**63 - 1)  # Max int64_t
        header.check_int_bounds(-(2**63))  # Min int64_t

    def test_check_int_bounds_too_large(self):
        """Test _check_int_bounds with values that are too large."""
        with pytest.raises(
            ValueError, match='too large to fit in a C\\+\\+ 64-bit integer'
        ):
            header.check_int_bounds(2**64)

    def test_check_int_bounds_too_small(self):
        """Test _check_int_bounds with values that are too small."""
        with pytest.raises(
            ValueError, match='too small to fit in a C\\+\\+ 64-bit signed integer'
        ):
            header.check_int_bounds(-(2**63) - 1)

    def test_generate_header_with_large_int_fails(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that generate_header fails with integers that are too large."""
        testing_pkg.set_vars(
            {
                'large_int': 2**64,  # Too large for int64_t
            }
        )

        with pytest.raises(
            ValueError, match='too large to fit in a C\\+\\+ 64-bit integer'
        ):
            header.generate_header()

    def test_generate_header_with_small_int_fails(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that generate_header fails with integers that are too small."""
        testing_pkg.set_vars(
            {
                'small_int': -(2**63) - 1,  # Too small for int64_t
            }
        )

        with pytest.raises(
            ValueError, match='too small to fit in a C\\+\\+ 64-bit signed integer'
        ):
            header.generate_header()

    def test_generate_header_deterministic_order(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that generate_header produces variables in deterministic order."""
        testing_pkg.set_vars(
            {
                'z_var': 'last',
                'a_var': 'first',
                'm_var': 'middle',
            }
        )

        header.generate_header()

        rbx_header_path = pathlib.Path('rbx.h')
        generated_content = rbx_header_path.read_text()

        # Variables should be in alphabetical order
        a_pos = generated_content.find('if (name == "a_var")')
        m_pos = generated_content.find('if (name == "m_var")')
        z_pos = generated_content.find('if (name == "z_var")')

        assert a_pos < m_pos < z_pos

    def test_string_repr_escaping(self, testing_pkg: testing_package.TestingPackage):
        """Test that string variables with special characters are properly escaped in generated header."""
        # Set variables with various special characters that need escaping
        testing_pkg.set_vars(
            {
                'simple_string': 'simple',
                'string_with_spaces': 'with spaces',
                'string_with_quotes': 'with"quotes',
                'string_with_backslash': 'with\\backslash',
                'string_with_newline': 'with\nnewline',
                'string_with_tab': 'with\ttab',
                'string_with_return': 'with\rreturn',
            }
        )

        header.generate_header()

        rbx_header_path = pathlib.Path('rbx.h')
        generated_content = rbx_header_path.read_text()

        # Check that all string variables are properly escaped in the generated header
        assert (
            'if (name == "simple_string") {\n    return "simple";\n  }'
            in generated_content
        )
        assert (
            'if (name == "string_with_spaces") {\n    return "with spaces";\n  }'
            in generated_content
        )
        assert (
            'if (name == "string_with_quotes") {\n    return "with\\"quotes";\n  }'
            in generated_content
        )
        assert (
            'if (name == "string_with_backslash") {\n    return "with\\\\backslash";\n  }'
            in generated_content
        )
        assert (
            'if (name == "string_with_newline") {\n    return "with\\nnewline";\n  }'
            in generated_content
        )
        assert (
            'if (name == "string_with_tab") {\n    return "with\\ttab";\n  }'
            in generated_content
        )
        assert (
            'if (name == "string_with_return") {\n    return "with\\rreturn";\n  }'
            in generated_content
        )

    def test_generate_header_bool_as_int_in_int_block(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Test that bool variables are handled correctly in int context."""
        testing_pkg.set_vars(
            {
                'bool_true': True,
                'bool_false': False,
            }
        )

        header.generate_header()

        rbx_header_path = pathlib.Path('rbx.h')
        generated_content = rbx_header_path.read_text()

        # Booleans should appear in both bool and int blocks
        # In int block, they should be converted to 1/0
        assert (
            'if (name == "bool_true") {\n    return static_cast<int64_t>(1);\n  }'
            in generated_content
        )
        assert (
            'if (name == "bool_false") {\n    return static_cast<int64_t>(0);\n  }'
            in generated_content
        )

        # In bool block, they should be true/false
        assert 'if (name == "bool_true") {\n    return true;\n  }' in generated_content
        assert (
            'if (name == "bool_false") {\n    return false;\n  }' in generated_content
        )


_GET_VAR_MAIN = """
#include "rbx.h"
#include <cassert>
#include <cstdio>
#include <string>

int main() {
  assert(getVar<int>("N.max") == 100);
  assert(getVar<int>("N", "max") == 100);
  assert(getVar<int64_t>("N", "max") == 100);
  assert(getVar<std::string>("deep", "nested", "name") == "hello");
  assert(getVar<std::string>("deep.nested", "name") == "hello");
  assert(getVar<std::string>("deep", "nested.name") == "hello");

  // Segments can also be std::string values.
  std::string first = "N";
  std::string second = "max";
  assert(getVar<int>(first, second) == 100);

  // Missing variables report the joined name.
  try {
    getVar<int>("N", "missing");
    return 1;
  } catch (const std::runtime_error &e) {
    assert(std::string(e.what()).find("N.missing") != std::string::npos);
  }

  printf("ok");
  return 0;
}
"""


class TestGetVarWrapper:
    """Tests for the variadic getVar() wrapper exposed by rbx.h."""

    def test_get_var_accepts_dotted_name_and_segments(
        self, testing_pkg: testing_package.TestingPackage
    ):
        gpp = _require_gpp()

        testing_pkg.set_vars(
            {
                'N': {'max': 100},
                'deep': {'nested': {'name': 'hello'}},
            }
        )

        header.generate_header()
        pathlib.Path('main.cpp').write_text(_GET_VAR_MAIN)

        subprocess.run(
            [gpp, '-std=c++17', '-Wall', '-Werror', '-o', 'main', 'main.cpp'],
            check=True,
        )
        result = subprocess.run(['./main'], check=True, capture_output=True, text=True)
        assert result.stdout == 'ok'


_GET_GROUP_MAIN = """
#include "rbx.h"
#include <cstdio>
#include <string>

// Resolved before main() runs, to prove no call from main() is needed.
static const std::string kEarly = rbx::getGroup();

int main() {
  std::printf("early=[%s]\\n", kEarly.c_str());
  std::printf("late=[%s]\\n", rbx::getGroup().c_str());
  return 0;
}
"""

# Includes rbx.h BEFORE testlib.h.
_TESTLIB_BEFORE_MAIN = """
#include "rbx.h"
#include "testlib.h"
#include <cstdio>

int main(int argc, char *argv[]) {
  registerValidation(argc, argv);
  inf.readEof();
  std::printf("rbx=[%s]\\n", rbx::getGroup().c_str());
  std::printf("testlib=[%s]\\n", getGroup().c_str());
  return 0;
}
"""

# Includes rbx.h AFTER testlib.h.
_TESTLIB_AFTER_MAIN = """
#include "testlib.h"
#include "rbx.h"
#include <cstdio>

int main(int argc, char *argv[]) {
  registerValidation(argc, argv);
  inf.readEof();
  std::printf("rbx=[%s]\\n", rbx::getGroup().c_str());
  std::printf("testlib=[%s]\\n", getGroup().c_str());
  return 0;
}
"""


# Reads a blob from stdin and prints how rbx.h splits it. Exercises the
# /proc/self/cmdline splitter on every platform, not just Linux.
_SPLIT_CMDLINE_MAIN = """
#include "rbx.h"
#include <cstdio>
#include <string>

int main() {
  std::string blob;
  char buffer[4096];
  std::size_t read;
  while ((read = std::fread(buffer, 1, sizeof(buffer), stdin)) > 0) {
    blob.append(buffer, read);
  }
  for (const std::string &arg : rbx::detail::splitCmdline(blob)) {
    std::printf("[%s]\\n", arg.c_str());
  }
  return 0;
}
"""


def _require_gpp() -> str:
    gpp = shutil.which('g++')
    if gpp is None:
        pytest.skip('g++ is not available')
    return gpp


def _compile(gpp: str, source: str, name: str, extra_args: List[str]) -> None:
    pathlib.Path(f'{name}.cpp').write_text(source)
    subprocess.run(
        [gpp, '-std=c++20', '-O2', '-Wall', '-Werror', '-o', name, f'{name}.cpp']
        + extra_args,
        check=True,
    )


class TestGetGroup:
    """Tests for rbx::getGroup(), which parses --group out of argv."""

    @pytest.mark.parametrize(
        ('argv', 'expected'),
        [
            (['--group', 'sub2'], 'sub2'),
            (['--group=sub2'], 'sub2'),
            (['--AB.min=-200', '--group', 'sub2', '--other', 'x'], 'sub2'),
            ([], ''),
            (['--group'], ''),
            (['--groups', 'sub2'], ''),
        ],
    )
    def test_get_group_parses_argv(
        self,
        testing_pkg: testing_package.TestingPackage,
        argv: List[str],
        expected: str,
    ):
        gpp = _require_gpp()

        header.generate_header()
        _compile(gpp, _GET_GROUP_MAIN, 'main', [])

        result = subprocess.run(
            ['./main'] + argv, check=True, capture_output=True, text=True
        )
        assert result.stdout == f'early=[{expected}]\nlate=[{expected}]\n'

    @pytest.mark.parametrize(
        ('blob', 'expected'),
        [
            # NUL-separated args, as the kernel writes them.
            (b'./validator\x00--group\x00sub2\x00', ['./validator', '--group', 'sub2']),
            # A trailing NUL terminates the last arg, it does not add a phantom one.
            (b'a\x00b\x00', ['a', 'b']),
            # ... and a missing trailing NUL still yields the last arg.
            (b'a\x00b', ['a', 'b']),
            # A single arg with no trailing NUL.
            (b'solo', ['solo']),
            # An empty blob yields no args at all.
            (b'', []),
            # An embedded empty arg is representable and preserved.
            (b'a\x00\x00b\x00', ['a', '', 'b']),
        ],
    )
    def test_split_cmdline(
        self,
        testing_pkg: testing_package.TestingPackage,
        blob: bytes,
        expected: List[str],
    ):
        """The /proc/self/cmdline splitter, tested on every platform."""
        gpp = _require_gpp()

        header.generate_header()
        _compile(gpp, _SPLIT_CMDLINE_MAIN, 'split', [])

        result = subprocess.run(
            ['./split'], check=True, capture_output=True, input=blob
        )
        assert result.stdout.decode() == ''.join(f'[{arg}]\n' for arg in expected)

    def test_header_does_not_depend_on_testlib(
        self, testing_pkg: testing_package.TestingPackage
    ):
        header.generate_header()

        header_content = pathlib.Path('rbx.h').read_text()
        assert 'testlib' not in header_content.lower()
        assert '_TESTLIB_H_' not in header_content

    @pytest.mark.parametrize(
        ('source', 'name'),
        [
            (_TESTLIB_BEFORE_MAIN, 'rbx_first'),
            (_TESTLIB_AFTER_MAIN, 'testlib_first'),
        ],
    )
    def test_get_group_coexists_with_testlib(
        self, testing_pkg: testing_package.TestingPackage, source: str, name: str
    ):
        """rbx::getGroup() must not collide with testlib's global getGroup()."""
        gpp = _require_gpp()

        header.generate_header()
        testlib = config.get_resources_file(pathlib.Path('predownloaded/testlib.h'))
        pathlib.Path('testlib.h').write_text(testlib.read_text())

        # testlib.h is not warning-clean under -Wall -Werror, so relax it here;
        # the point of this test is the name collision, not warnings.
        _compile(gpp, source, name, ['-Wno-error', '-w'])

        result = subprocess.run(
            [f'./{name}', '--group', 'sub2'],
            check=True,
            capture_output=True,
            text=True,
            input='',
        )
        assert result.stdout == 'rbx=[sub2]\ntestlib=[sub2]\n'


# Prints one var of each type, so a group arm wired for only some of the four
# accessors is caught.
_GROUP_VARS_MAIN = """
#include "rbx.h"
#include <cstdio>
#include <string>

int main() {
  std::printf("AB.min=%lld\\n", (long long)getVar<int64_t>("AB.min"));
  std::printf("AB.max=%lld\\n", (long long)getVar<int64_t>("AB.max"));
  std::printf("name=%s\\n", getVar<std::string>("name").c_str());
  std::printf("ratio=%.2f\\n", getVar<double>("ratio"));
  std::printf("flag=%d\\n", (int)getVar<bool>("flag"));
  return 0;
}
"""

# Reports, per type, whether a var declared only by a group is visible.
_GROUP_ONLY_VARS_MAIN = """
#include "rbx.h"
#include <cstdio>
#include <stdexcept>
#include <string>

template <typename T> void report(const char *label, const std::string &name) {
  try {
    T value = getVar<T>(name);
    (void)value;
    std::printf("%s=ok\\n", label);
  } catch (const std::runtime_error &e) {
    (void)e;
    std::printf("%s=threw\\n", label);
  }
}

int main() {
  report<int64_t>("maxOps", "maxOps");
  report<std::string>("label", "label");
  report<double>("eps", "eps");
  // Not report<bool>: getVar<bool> falls back to getIntVar and, on a missing
  // var, that fallback yields true instead of throwing -- a pre-existing quirk
  // of the template that is out of scope here. The accessor itself is exact.
  std::printf("strict=%s\\n", getBoolVar("strict").has_value() ? "ok" : "threw");
  return 0;
}
"""

# A group override that changes a var's type must not leave the package's value
# of the old type reachable under that group.
_CROSS_TYPE_MAIN = """
#include "rbx.h"
#include <cstdio>
#include <stdexcept>
#include <string>

int main() {
  try {
    std::printf("int=%lld\\n", (long long)getVar<int64_t>("x"));
  } catch (const std::runtime_error &e) {
    (void)e;
    std::printf("int=threw\\n");
  }
  std::printf("string=%s\\n", getVar<std::string>("x").c_str());
  return 0;
}
"""

_UNSUPPORTED_PLATFORM_GUARD = (
    '#if !defined(__linux__) && !defined(__APPLE__) && !defined(_WIN32)'
)

_PACKAGE_VARS: RecVars = {
    'AB': {'min': -200, 'max': 200},
    'name': 'pkg',
    'ratio': 1.5,
    'flag': True,
}


def _set_group_vars(
    testing_pkg: testing_package.TestingPackage, groups: Dict[str, RecVars]
) -> None:
    testing_pkg.yml.testcases = [
        schema.TestcaseGroup(name=name, vars=vars) for name, vars in groups.items()
    ]
    testing_pkg.save()


class TestGroupVars:
    """Tests for per-group `vars` overrides baked into rbx.h."""

    def test_getvar_resolves_group_override(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """getVar returns the group's value under --group, the package's otherwise."""
        gpp = _require_gpp()

        testing_pkg.set_vars(dict(_PACKAGE_VARS))
        _set_group_vars(
            testing_pkg,
            {
                'sub2': {
                    'AB': {'min': 0},
                    'name': 'sub2name',
                    'ratio': 2.5,
                    'flag': False,
                },
                'sub3': {'AB': {'max': 0}},
                'sub4': {},
            },
        )

        header.generate_header()
        _compile(gpp, _GROUP_VARS_MAIN, 'groupvars', ['-Wextra'])

        package_expected = 'AB.min=-200\nAB.max=200\nname=pkg\nratio=1.50\nflag=1\n'
        cases = [
            (
                ['--group', 'sub2'],
                'AB.min=0\nAB.max=200\nname=sub2name\nratio=2.50\nflag=0\n',
            ),
            (
                ['--group', 'sub3'],
                'AB.min=-200\nAB.max=0\nname=pkg\nratio=1.50\nflag=1\n',
            ),
            (['--group', 'sub4'], package_expected),
            (['--group', 'unknown'], package_expected),
            ([], package_expected),
        ]
        for argv, expected in cases:
            result = subprocess.run(
                ['./groupvars'] + argv, check=True, capture_output=True, text=True
            )
            assert result.stdout == expected, argv

    def test_group_only_var_is_visible_in_its_group_and_throws_outside(
        self, testing_pkg: testing_package.TestingPackage
    ):
        gpp = _require_gpp()

        _set_group_vars(
            testing_pkg,
            {
                'sub2': {
                    'maxOps': 5,
                    'label': 'small',
                    'eps': 0.5,
                    'strict': True,
                },
            },
        )

        header.generate_header()
        # The package declares no vars of its own, so the accessors' `name`
        # parameter goes unused in the package-level block.
        _compile(
            gpp,
            _GROUP_ONLY_VARS_MAIN,
            'grouponly',
            ['-Wextra', '-Wno-unused-parameter'],
        )

        result = subprocess.run(
            ['./grouponly', '--group', 'sub2'],
            check=True,
            capture_output=True,
            text=True,
        )
        assert result.stdout == 'maxOps=ok\nlabel=ok\neps=ok\nstrict=ok\n'

        result = subprocess.run(
            ['./grouponly'], check=True, capture_output=True, text=True
        )
        assert result.stdout == 'maxOps=threw\nlabel=threw\neps=threw\nstrict=threw\n'

    def test_group_override_changing_a_var_type_hides_the_package_value(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """A group arm answers on its own; it never falls through to the package."""
        gpp = _require_gpp()

        testing_pkg.set_vars({'x': 1})
        _set_group_vars(testing_pkg, {'sub2': {'x': 'one'}})

        header.generate_header()
        # `name` goes unused in the float and bool accessors: neither the
        # package nor the group declares a var of those types.
        _compile(
            gpp, _CROSS_TYPE_MAIN, 'crosstype', ['-Wextra', '-Wno-unused-parameter']
        )

        result = subprocess.run(
            ['./crosstype', '--group', 'sub2'],
            check=True,
            capture_output=True,
            text=True,
        )
        assert result.stdout == 'int=threw\nstring=one\n'

        result = subprocess.run(
            ['./crosstype'], check=True, capture_output=True, text=True
        )
        assert result.stdout == 'int=1\nstring=1\n'

    def test_package_without_group_vars_generates_no_group_arms(
        self, testing_pkg: testing_package.TestingPackage
    ):
        """Existing packages stay byte-stable apart from Task 2's getGroup block."""
        testing_pkg.set_vars(dict(_PACKAGE_VARS))
        _set_group_vars(testing_pkg, {'sub1': {}, 'sub2': {}})

        header.generate_header()

        generated_content = pathlib.Path('rbx.h').read_text()
        assert 'if (group ==' not in generated_content

    def test_guard_is_emitted_only_when_a_group_declares_vars(
        self, testing_pkg: testing_package.TestingPackage
    ):
        testing_pkg.set_vars(dict(_PACKAGE_VARS))
        _set_group_vars(testing_pkg, {'sub1': {}})

        header.generate_header()
        assert _UNSUPPORTED_PLATFORM_GUARD not in pathlib.Path('rbx.h').read_text()

        _set_group_vars(testing_pkg, {'sub1': {'AB': {'min': 0}}})

        header.generate_header()
        assert _UNSUPPORTED_PLATFORM_GUARD in pathlib.Path('rbx.h').read_text()

    @pytest.mark.parametrize('with_group_vars', [False, True])
    def test_header_is_warning_clean(
        self, testing_pkg: testing_package.TestingPackage, with_group_vars: bool
    ):
        """The header is compiled into every validator; it must not warn."""
        gpp = _require_gpp()

        testing_pkg.set_vars(dict(_PACKAGE_VARS))
        if with_group_vars:
            _set_group_vars(testing_pkg, {'sub2': {'AB': {'min': 0}}})

        header.generate_header()
        _compile(gpp, _GROUP_VARS_MAIN, 'warnings', ['-Wextra'])
