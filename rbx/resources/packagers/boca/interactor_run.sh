#!/bin/bash
mkfifo fifo.in fifo.out

echo "Running solution as $@" >&2

"$@" >fifo.out <fifo.in 2>/dev/null &
SFPID=$!

./interactor.exe "stdin0" "stdout0" <fifo.out >fifo.in 2>stderr0 &
INTPID=$!

ECINT=0
ECSF=0

wait -p EXITID -n $SFPID $INTPID
ECEXIT=$?
if [[ $ECEXIT -ne 0 ]]; then
  kill -SIGTERM $SFPID $INTPID 2>/dev/null
fi

EXITFIRST=none
if [[ $EXITID -eq $INTPID ]]; then
  wait $SFPID
  ECSF=$?
  ECINT=$ECEXIT
  EXITFIRST=interactor
else
  wait $INTPID
  ECINT=$?
  ECSF=$ECEXIT
  EXITFIRST=solution
fi

echo "interactor exitcode $ECINT" &>>stderr0
echo "solution exitcode $ECSF" &>>stderr0
echo "exit first $EXITFIRST" &>>stderr0

finish() {
  echo "exitting from runit.sh with exit code $1" &>>stderr0
  rm -rf fifo.in fifo.out
  exit $1
}

check_interactor() {
  if [[ $ECINT -ge 1 ]] && [[ $ECINT -le 4 ]]; then
    echo "testlib exitcode $ECINT" >stdout0
    finish 0
  elif [[ $ECINT -ne 0 ]]; then
    finish 9
  fi
}

# 1. Check for interactor errors.
if [[ $ECSF -eq -SIGPIPE ]] || [[ $ECSF -eq -SIGTERM ]] || [[ $ECSF -ne 0 ]] && ! cat stderr0 | grep -q "wrong output format Unexpected end of file"; then
  check_interactor
fi

# 2. Check for solution errors.
if [[ $ECSF -ne 0 ]]; then
  finish $ECSF
fi

# 3. Check for interactor without looking at solution output.
check_interactor

# 4. Finish with zero and later check output.
finish 0
