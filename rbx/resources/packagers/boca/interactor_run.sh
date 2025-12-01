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
# Also ensure the killing subshell does not inherit the file descriptor.
fd=$2
(exec {fd}>&-; sleep $1; kill -TERM -$$; sleep 5; kill -9 -$$) 2>/dev/null &
ulimit -v 1024000 && exec ./interactor.exe "stdin0" "stdout0"
exit $?
WRAPPERFOF
chmod 755 runit_wrapper.sh

# Execute the pipe program. This program will execute both solution and interactor
# and pass some pipes to them to catch through epoll events which process finished
# first.
./pipe.exe -i fifo.in -o fifo.out -e safeexec.sf.stderr -E interactor.stderr --\
  "$sf" -ofifo.out -ififo.in -D__FD__ "$@" 2>safeexec.sf.stderr\
  =\
  ./runit_wrapper.sh $ittime __FD__ >pipe.log 2>pipe.stderr

if [[ $? -ne 0 ]]; then
  echo "pipe failed" >>stderr0
  cat pipe.stderr >>stderr0
  exit 4
fi

# Parse pipe.log output:
# Line 1: first_tag (1=solution, 2=interactor)
# Line 2: solution_status
# Line 3: interactor_status
FIRST_TAG=$(sed -n '1p' pipe.log | tr -d '[:space:]')
ECSF=$(sed -n '2p' pipe.log | tr -d '[:space:]')
ECINT=$(sed -n '3p' pipe.log | tr -d '[:space:]')

EXITFIRST=none
if [[ $FIRST_TAG -eq 1 ]]; then
  EXITFIRST=solution
elif [[ $FIRST_TAG -eq 2 ]]; then
  EXITFIRST=interactor
fi

if [[ $EXITFIRST == none ]]; then
  # Should never happen.
  echo "pipe failed, returned exit first none" >>stderr0
  cat pipe.stderr >>stderr0
  echo "== <pipe log> ==" >>stderr0
  cat pipe.log >>stderr0
  exit 4
fi

echo "== <pipe stderr> ==" >>stderr0
cat pipe.stderr >>stderr0
echo "== </pipe stderr> ==" >>stderr0

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

is_testlib_exitcode() {
  local EC=$ECINT
  if [[ $EC -ge 0 ]] && [[ $EC -le 4 ]]; then
    true
    return
  fi
  false
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

# 1. Check if interactor crashed.
if [[ $EXITFIRST == "interactor" ]] && ! is_testlib_exitcode; then
  check_interactor
fi

# 2. Check for solution MLE or TLE.
if [[ $ECSF -eq 3 ]] || [[ $ECSF -eq 7 ]]; then
  finish $ECSF
fi

# 3. When interactor finished first, check for interactor errors.
if [[ $EXITFIRST == "interactor" ]]; then
  check_interactor
fi

# 4. Check for solution errors.
if [[ $ECSF -ne 0 ]]; then
  finish $ECSF
fi

# 5. Check for interactor errors again, regardless of the order of finish.
check_interactor

# 6. Finish with zero and later check output.
finish 0
