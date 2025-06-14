#!/bin/bash
# $1 is cdir
# $2 is sf

cdir=$1
shift
sf=$1
shift
ttime=$1
shift

# Add 1 second to the wall TL of the interactor to be safe.
ittime=$(($ttime + 1))

cd "$cdir"

# Ensure fifos are created and given access to.
mkfifo fifo.in fifo.out
chmod 666 fifo.in fifo.out
chown nobody fifo.in fifo.out

# Ensure interactor's side input and output can't be read by solution.
touch stdin0 stdout0 interactor.stderr
chmod 640 stdin0 stdout0 interactor.stderr

echo "Running solution with safeexec params $@" >&2

# Execute interactor in a memory-limited shell to ensure a misbehaved interactor
# doesn't starve the system.
cat >runit_wrapper.sh <<"WRAPPERFOF"
#!/bin/bash
# SIGTERM after ttime, SIGKILL after extra 5 seconds.
(sleep $1; kill -TERM -$$; sleep 5; kill -9 -$$) 2>/dev/null &
ulimit -v 1024000 && exec ./interactor.exe "stdin0" "stdout0"
exit $?
WRAPPERFOF
chmod 755 runit_wrapper.sh
./runit_wrapper.sh $ittime <fifo.out >fifo.in 2>interactor.stderr &
INTPID=$!

"$sf" -ofifo.out -ififo.in "$@" 2>safeexec.sf.stderr &
SFPID=$!

ECINT=0
ECSF=0

echo "interactor pid $INTPID" >>stderr0
echo "solution pid $SFPID" >>stderr0

wait -p EXITID -n $SFPID $INTPID
ECEXIT=$?
if [[ $ECEXIT -ne 0 ]]; then
  kill -SIGTERM $SFPID $INTPID 2>/dev/null
fi

EXITFIRST=none
if [[ $EXITID -eq $INTPID ]]; then
  # In case the interactor exits first, we can just wait for the solution to finish.
  # It will certainly finish at some point since it's running inside a constrained
  # safeexec environment.
  wait $SFPID
  ECSF=$?
  ECINT=$ECEXIT
  EXITFIRST=interactor
else
  # When solution exits first, we're sure that it ACTUALLY finished first.
  # So, in case of non-zero exit code, we probably already halted the interactor.
  # Otherwise, let's wait for it for a maximum of wall time and then halt it to ensure
  # a misbehaved interactor doesn't hang the entire judge.
  wait $INTPID
  ECINT=$?
  ECSF=$ECEXIT
  EXITFIRST=solution
fi

echo "interactor exitcode $ECINT" >>stderr0
echo "solution exitcode $ECSF" >>stderr0
echo "exit first $EXITFIRST" >>stderr0

# Recover permissions.
chmod 644 stdin0 stdout0

# SAFEEXEC STDERR
echo "== <safeexec solution stderr> ==" >>stderr0
cat safeexec.sf.stderr >>stderr0
echo "== </safeexec solution stderr> ==" >>stderr0

# INTERACTOR STDERR
echo "== <interactor stderr> ==" >>stderr0
cat interactor.stderr >>stderr0 2>/dev/null
echo "== </interactor stderr> ==" >>stderr0
###

JUDGE_ERROR=4
finish() {
  echo "exitting from runit.sh with exit code $1" >>stderr0
  rm -rf fifo.in fifo.out
  exit $1
}

# Solution RTE, for checking purposes, is defined as any safeexec non-zero exit code, except for TLE or MLE.
is_solution_rte() {
  if [[ $1 -eq 0 ]]; then
    false
    return
  fi

  # In case of TLE or MLE, we don't consider as RTE.
  if [[ $1 -eq 3 ]] || [[ $1 -eq 7 ]]; then
    false
    return
  fi
  true
}

# Interactor RTE, for checking purposes, is defined as any non-zero exit code, except for SIGTERM or SIGPIPE, or exit codes
# reserved for testlib.
is_interactor_rte() {
  if [[ $1 -eq 0 ]] || [[ $1 -eq 143 ]] || [[ $1 -eq 141 ]]; then
    false
    return
  fi

  if [[ $1 -ge 1 ]] && [[ $1 -le 4 ]]; then
    false
    return
  fi

  true
}

# Check for interactor errors.
check_interactor() {
  local EC=$ECINT
  if [[ $EC -eq 0 ]]; then
    return
  fi

  if [[ $EC -ge 1 ]] && [[ $EC -le 4 ]]; then
    echo "testlib returned WA-like exitcode $EC" >>stderr0
    echo "testlib exitcode $EC" >stdout0
    finish 0
  fi

  finish $JUDGE_ERROR
}

# 0. Interactor has crashed?
if is_interactor_rte $ECINT; then
  echo "interactor EXITED WITH NON-ZERO CODE $ECINT" >>stderr0
  finish $JUDGE_ERROR
fi

# 1. Solution has exceed limits?
if [[ $ECSF -eq 3 ]] || [[ $ECSF -eq 7 ]]; then
  finish $ECSF
fi

# 2. Check for interactor errors.
# TODO: Maybe one day get rid of "wrong output format" check with extra fifos.
if ([[ $EXITFIRST == "interactor" ]] || is_solution_rte $ECSF) && ! cat stderr0 | grep -q "wrong output format Unexpected end of file"; then
  check_interactor
fi

# 3. Check for solution errors.
if [[ $ECSF -ne 0 ]]; then
  finish $ECSF
fi

# 4. Check for interactor without looking at solution output.
check_interactor

# 5. Finish with zero and later check output.
finish 0
