#!/bin/bash

exec &>/tmp/stderrlog

#ulimit -a

cd /tmp/dir
source binfile.sh

CMD="python ./$BIN"

if [[ -e interactor_run.sh ]]; then
  source interactor_run.sh
fi

exec $CMD </tmp/in >/tmp/out
