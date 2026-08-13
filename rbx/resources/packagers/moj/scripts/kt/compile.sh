#!/bin/bash
# Runs INSIDE the jail, in a writable /tmp/rwdir already holding the submission.
#
# Printing `BIN=<artifact>` on stdout is MANDATORY: without that line
# build-and-test.sh reports Compilation Error.
exec 2>/tmp/stderrlog > /tmp/out
cd /tmp/rwdir

SRC=$(ls *.kt 2>/dev/null | head -1)
[[ -n "$SRC" ]] || exit 1

# kotlinc bundles the runtime into the jar and points Main-Class at the source's
# `fun main()`, so run.sh only needs `java -jar`.
export JAVA_OPTS="-Xmx700M -Xms64M"
kotlinc "$SRC" -include-runtime -d prog.jar || exit 1
echo BIN=prog.jar
