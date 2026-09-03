"""Patch testlib.h to speak the DOMjudge/Kattis output validator protocol.

DOMjudge runs output validators with argv = ``<input> <answer> <feedbackdir>``,
team output on stdin, exit code 42 for AC and 43 for rejection, and judge/team
messages written into the feedback directory. Vanilla testlib speaks the
Codeforces protocol instead, so the bundled testlib.h is patched at package
time. The patch is ported from pol2dom, which in turn copied it from
https://github.com/cn-xcpc-tools/testlib-for-domjudge.
"""

import re
from typing import List

_HEADER_COMMENT = """\
// Modified by rbx to work with DOMjudge.
// Differences with the standard testlib.h:
// - The values of some exit codes.
// - The functions registerInteraction and registerTestlibCmd.
"""

_NEW_EXIT_CODES = {
    'OK_EXIT_CODE': 42,
    'WA_EXIT_CODE': 43,
    'PE_EXIT_CODE': 43,
    'DIRT_EXIT_CODE': 43,
    'UNEXPECTED_EOF_EXIT_CODE': 43,
}

_NEW_REGISTER_INTERACTION = """\
void registerInteraction(int argc, char *argv[]) {
    __testlib_ensuresPreconditions();
    TestlibFinalizeGuard::registered = true;

    testlibMode = _interactor;
    __testlib_set_binary(stdin);

    if (argc > 1 && !strcmp("--help", argv[1]))
        __testlib_help();
    if (argc == 3) {
        resultName = "";
        appesMode = false;
    }

    if (argc == 4) {
        resultName = std::string(argv[3]) + "/judgemessage.txt";
        tout.open(std::string(argv[3]) + "/teammessage.txt",
                  std::ios_base::out);
        if (tout.fail() || !tout.is_open())
            quit(_fail, "Can not write to the test-output-file '" +
                        std::string(argv[2]) + "'");
        appesMode = false;
    }

    inf.init(argv[1], _input);

    ouf.init(stdin, _output);
    if (argc >= 3)
        ans.init(argv[2], _answer);
    else
        ans.name = "unopened answer stream";
}"""

_NEW_REGISTER_TESTLIB_CMD = """\
void registerTestlibCmd(int argc, char *argv[]) {
    __testlib_ensuresPreconditions();
    TestlibFinalizeGuard::registered = true;

    testlibMode = _checker;
    __testlib_set_binary(stdin);

    if (argc > 1 && !strcmp("--help", argv[1]))
        __testlib_help();

    appesMode = false;

    if (argc == 3) {
        resultName = "";
        appesMode = false;
    }

    if (argc == 4) {
        resultName = std::string(argv[3]) + "/judgemessage.txt";
        appesMode = false;
    }

    inf.init(argv[1], _input);
    ouf.init(stdin, _output);
    ans.init(argv[2], _answer);
}"""


def _replace_exit_code(lines: List[str], name: str, value: int) -> List[str]:
    pattern = re.compile(r'(# *define +%s +)[a-zA-Z0-9]+( *)' % name)
    replaced = False
    for i, line in enumerate(lines):
        match = pattern.fullmatch(line)
        if match:
            lines[i] = match.group(1) + str(value) + match.group(2)
            replaced = True
    if not replaced:
        raise ValueError(
            f'Could not patch testlib.h for DOMjudge: no `#define {name}` found.'
        )
    return lines


def _replace_function(lines: List[str], function: str) -> List[str]:
    begin = function.splitlines()[0]
    end = function.splitlines()[-1]

    state = 0
    new_lines = []
    for line in lines:
        if line == begin:
            if state != 0:
                raise ValueError(
                    f'Could not patch testlib.h for DOMjudge: duplicate `{begin}`.'
                )
            state += 1
        if state != 1:
            new_lines.append(line)
        if state == 1 and line == end:
            state += 1
            new_lines.append(function)
    if state != 2:
        raise ValueError(
            f'Could not patch testlib.h for DOMjudge: `{begin}` not found.'
        )
    return new_lines


def patch_testlib_for_domjudge(content: str) -> str:
    """Return ``content`` patched for DOMjudge; raises ValueError if any patch
    anchor is missing (e.g. after a testlib upgrade)."""
    lines = content.splitlines()
    for name, value in _NEW_EXIT_CODES.items():
        lines = _replace_exit_code(lines, name, value)
    lines = _replace_function(lines, _NEW_REGISTER_INTERACTION)
    lines = _replace_function(lines, _NEW_REGISTER_TESTLIB_CMD)
    # skipBom seeks the stream, which fails when reading team output from a
    # stdin pipe.
    lines = [
        line for line in lines if line.strip() not in ('skipBom();', 'ouf.skipBom();')
    ]
    return '\n'.join([_HEADER_COMMENT] + lines) + '\n'
