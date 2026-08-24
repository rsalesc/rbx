#!/bin/bash
# Runs INSIDE the jail, in a writable /tmp/rwdir already holding the submission.
#
# Printing `BIN=<artifact>` on stdout is MANDATORY: without that line
# build-and-test.sh reports Compilation Error.
exec 2>/tmp/stderrlog > /tmp/out
cd /tmp/rwdir

SRC=$(ls *.java 2>/dev/null | head -1)
[[ -n "$SRC" ]] || exit 1

# javac is the only party here that insists a source file be named after the public
# type it declares. Neither rbx nor MOJ does: rbx names a solution file after the
# solution (`vinicius_fastIO.java` holding `public class Main`), and MOJ reads the
# name only to pick the language. Left alone, that mismatch is a hard compile error --
# for a packaged solution during calibration, and equally for a contestant who
# submitted a file whose name is not their class. So rename each source to the type it
# declares before javac ever sees it.
#
# Only a `public` declaration starting a line counts, which is the shape javac accepts
# anyway; a `public class` inside a comment or a string virtually never starts one.
for src in *.java; do
  klass=$(sed -n -E \
    's/^[[:space:]]*public[[:space:]]+([a-z]+[[:space:]]+)*(class|interface|enum|record)[[:space:]]+([A-Za-z_$][A-Za-z0-9_$]*).*/\3/p' \
    "$src" | head -1)
  [[ -n "$klass" ]] || continue
  [[ "$klass.java" != "$src" ]] || continue
  # A name already taken is a conflict only javac can explain; leave it to say so.
  [[ -e "$klass.java" ]] && continue
  mv -f "$src" "$klass.java" || exit 1
  [[ "$SRC" == "$src" ]] && SRC="$klass.java"
done

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
