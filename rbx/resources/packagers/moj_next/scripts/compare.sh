#!/bin/bash
# scripts/compare.sh -- STUB. Emitted by rbx's moj-next packager; equivalent to what
# mojtools' testlib/install-checker.sh installs.
#
# The checker BRIDGE lives in MOJTOOLS (single source):
#   mojtools/testlib/checker-bridge.sh -- compiles THIS package's scripts/checker.cpp
#   on first comparison (cache outside scripts/, so it stays out of the tl-checksum)
#   and translates the testlib result to the judge's contract.
#
# This file is only the POINTER: do not edit it, and never copy the bridge here. A
# package carrying its own bridge copy is exactly what spread one bwrap bug across 198
# packages, where fixing mojtools reached none of them.
#
# MOJ contract:  compare.sh <team output> <expected> <input>
#                -> exit 4=AC  5=AC,PE  6=WA  (anything else = judge error)
set -u
_pkg="$(cd "$(dirname "$(readlink -f "$0")")/.." 2>/dev/null && pwd)"
_mt="${MOJTOOLS_DIR:-$PWD}"    # build-and-test.sh EXPORTS MOJTOOLS_DIR
_br="$_mt/testlib/checker-bridge.sh"
[[ -x "$_br" ]] || {
  echo "compare.sh: checker bridge not found at '$_br' (MOJTOOLS_DIR='${MOJTOOLS_DIR:-}')"
  exit 7
}
exec "$_br" --pkg "$_pkg" "$@"
