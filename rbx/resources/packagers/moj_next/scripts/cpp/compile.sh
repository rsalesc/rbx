#!/bin/bash
# Runs INSIDE the jail, in a writable /tmp/rwdir already holding the submission.
# mojtools does not exist in there, which is why this is a real copy and not a stub.
#
# Printing `BIN=<artifact>` on stdout is MANDATORY: without that line
# build-and-test.sh reports Compilation Error regardless of the compiler's exit code.
exec 2>/tmp/stderrlog > /tmp/out
cd /tmp/rwdir

SRC=$(ls *.cpp *.cc *.cxx 2>/dev/null | head -1)
[[ -n "$SRC" ]] || exit 1

g++ {{rbxFlags}} "$SRC" -o main || exit 1
echo BIN=main
