#!/bin/bash

exec &>/tmp/stderrlog

#ulimit -a

cd /tmp/dir
source binfile.sh

export CLASSPATH=$PWD
CMD="java -Xmx{{rbxMaxMemory}}M -Xss256M $(basename $BIN .class)"

if [[ -e interactor_run.sh ]]; then
  source interactor_run.sh
fi

exec $CMD </tmp/in >/tmp/out
