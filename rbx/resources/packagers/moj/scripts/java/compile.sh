#!/bin/bash

exec 2>/tmp/stderrlog > /tmp/out
cd /tmp/rwdir

export _JAVA_OPTIONS="-Xmx300M -Xms50M -Xss10M"
javac *java
RET=$?
#java -Xms10m -Xmx500m -Xss10m

echo BIN=$(ls *.class)
exit $RET
