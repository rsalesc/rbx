#!/bin/bash
# Runs INSIDE the jail, in a writable /tmp/rwdir already holding the submission.
#
# Printing `BIN=<artifact>` on stdout is MANDATORY: without that line
# build-and-test.sh reports Compilation Error.
exec 2>/tmp/stderrlog > /tmp/out
cd /tmp/rwdir

SRC=$(ls *.java 2>/dev/null | head -1)
[[ -n "$SRC" ]] || exit 1
klass=$(basename "$SRC" .java)
[[ -n "$klass" ]] || klass=Main

export _JAVA_OPTIONS="-Xmx700M -Xms64M"
javac *.java || exit 1

# Name the entry point in the jar manifest so run.sh is just `java -jar`. Electing the
# class at runtime -- grep the sources for a main declaration, else `ls *.class` -- is
# locale-dependent once javac emits nested `Main$X.class` files, because '$' sorts
# before '.' in the C collation.
printf 'Main-Class: %s\n' "$klass" > Manifest.txt
jar cfm prog.jar Manifest.txt *.class || exit 1
echo BIN=prog.jar
