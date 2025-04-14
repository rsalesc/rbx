#!/bin/bash
exec 2>/tmp/stderrlog

mkfifo /tmp/fifo.in /tmp/fifo.out

# Solutions stderr is eaten in interactor problems.
$CMD </tmp/fifo.in >/tmp/fifo.out &
PIDSOLUTION=$!

/tmp/dir/interactor /tmp/in /tmp/out >/tmp/fifo.in </tmp/fifo.out 2>/tmp/interactor.log &
PIDINTERACTOR=$!

wait $PIDSOLUTION
EXITCODESOLUTION=$?

wait $PIDINTERACTOR
EXITCODEINTERACTOR=$?

echo "interactor $PIDINTERACTOR -> $EXITCODEINTERACTOR" >&2
echo "solution $PIDSOLUTION -> $EXITCODESOLUTION" >&2

cat /tmp/interactor.log >&2

if [[ $EXITCODEINTERACTOR -ge 1 ]] && [[ $EXITCODEINTERACTOR -le 4 ]]; then
  echo "interactor exitcode $EXITCODEINTERACTOR" >&2
  exit 0
fi

if [[ $EXITCODESOLUTION -ne 0 ]]; then
  exit $EXITCODESOLUTION
fi

if [[ $EXITCODEINTERACTOR -ne 0 ]]; then
  echo "interactor exitcode $EXITCODEINTERACTOR" >&2
  exit $EXITCODEINTERACTOR
fi

exit 0
