import pathlib
import shutil
import subprocess

import pytest

from rbx.box.packaging.cms import testlib_cms
from rbx.config import get_app_file

# Reads the answer the input asks for; `quitp`s the number the contestant printed.
_CHECKER = r"""
#include "testlib.h"
int main(int argc, char *argv[]) {
    registerTestlibCmd(argc, argv);
    std::string want = ans.readToken();
    std::string got = ouf.readToken();
    if (got == "FAIL") quitf(_fail, "broken");
    if (got == "PC") quitf(_pc(10), "half");
    if (got == want) quitf(_ok, "fine");
    if (got[0] >= '0' && got[0] <= '9') quitp(atof(got.c_str()), "got %s", got.c_str());
    quitf(_wa, "expected %s", want.c_str());
}
"""


def test_patch_refuses_an_unknown_testlib():
    with pytest.raises(ValueError):
        testlib_cms.patch('// not testlib')


@pytest.fixture(scope='module')
def cms_checker(tmp_path_factory) -> pathlib.Path:
    if shutil.which('g++') is None:
        pytest.skip('g++ not available')
    root = tmp_path_factory.mktemp('cms_checker')
    testlib = get_app_file(pathlib.Path('testlib.h'), predownloaded=True)
    (root / 'testlib.h').write_text(testlib_cms.patch(testlib.read_text()))
    (root / 'check.cpp').write_text(_CHECKER)
    subprocess.run(
        ['g++', '-std=gnu++17', '-O0', '-DRBX_CMS', '-o', 'check', 'check.cpp'],
        cwd=root,
        check=True,
    )
    return root / 'check'


@pytest.mark.parametrize(
    'output,stdout,stderr,exitcode',
    [
        ('OK', '1.0000000000', 'fine', 0),
        ('NO', '0.0000000000', 'expected OK', 0),
        ('82.5', '0.8250000000', 'got 82.5', 0),
        ('100', '1.0000000000', 'got 100', 0),
        ('150', '', 'FAIL', 1),
        ('PC', '', 'FAIL', 1),
        ('FAIL', '', 'FAIL', 1),
    ],
)
def test_cms_checker_speaks_cms(
    cms_checker, tmp_path, output, stdout, stderr, exitcode
):
    (tmp_path / 'input').write_text('\n')
    (tmp_path / 'correct').write_text('OK\n')
    (tmp_path / 'contestant').write_text(output + '\n')

    # CMS's argument order: input, correct output, contestant output.
    run = subprocess.run(
        [str(cms_checker), 'input', 'correct', 'contestant'],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert run.returncode == exitcode
    assert run.stdout.strip() == stdout
    assert run.stderr.splitlines()[0].startswith(stderr)
