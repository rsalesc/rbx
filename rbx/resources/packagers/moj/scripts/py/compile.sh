#!/bin/bash
# Runs INSIDE the jail, in a writable /tmp/rwdir already holding the submission.
#
# Printing `BIN=<artifact>` on stdout is MANDATORY: without that line
# build-and-test.sh reports Compilation Error.
exec 2>/tmp/stderrlog > /tmp/out
cd /tmp/rwdir

# BIN is chosen before py_compile runs, so the __pycache__ it creates cannot pollute
# the listing.
BINF=$(ls *.py *.py3 *.py2 2>/dev/null | head -1)
[[ -n "$BINF" ]] || exit 1

# pypy3 on a real judge (it lives in the rootfs), CPython in host/dev mode.
PY=python3; command -v pypy3 >/dev/null 2>&1 && PY=pypy3

# Syntax check, so a syntax error is a Compilation Error rather than a Runtime Error.
$PY -m py_compile "$BINF" || exit 1
# printf, not `echo BIN=$BINF`: this is the one BIN line here that is the contestant's own
# filename, and an unquoted expansion would collapse its whitespace before build-and-test.sh
# ever gets to escape it into binfile.sh.
printf 'BIN=%s\n' "$BINF"
