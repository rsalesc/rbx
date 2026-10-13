# ---------------------------------------------------------------------------
# rbx's own interactive driver for MOJ.
#
# `rbx_interact <contestant command...>` runs the contestant against the
# interactor (/tmp/dir/arbitro, the problem's plain testlib interactor) through
# BOCA's pipe.c (/tmp/dir/pipe, built by prep.sh next to the arbiter), then
# decides the verdict the way rbx does locally -- by CAUSE, not only by which
# side ended first:
#
#   1. the interactor failed (crash, _fail, _points) -> judge error, unless the
#      contestant had already failed first (then RE)
#   2. the interactor rejected for any reason but EOF -> WA; pipe.c has already
#      stopped a contestant still running, so it cannot turn into TLE (#894)
#   3. the contestant failed (non-zero exit, or a signal other than SIGPIPE) ->
#      RE, whether the interactor then accepted or only complained about the EOF
#      the contestant left behind (#895)
#   4. otherwise, the interactor's verdict.
#
# MOJ's protocol: the verdict line goes to /tmp/out (`WRONG ...` is WA, any other
# line AC, nothing at all a judge error) and exit code 3 is RE. A judge-side
# failure exits 0 with /tmp/out empty, since a non-zero exit would blame the
# contestant. TLE and MLE stay build-and-test.sh's.
# ---------------------------------------------------------------------------
rbx_judge_error() {
  echo "DRIVER(rbx): judge error: $*"
  exit 0
}

rbx_interact() {
  trap 'exit 0' TERM # the time limit: the verdict is the judge's TLE
  [[ -x /tmp/dir/pipe ]] || rbx_judge_error "pipe was not built (see prep.sh)"
  rm -f /tmp/fifo.in /tmp/fifo.out
  mkfifo /tmp/fifo.in /tmp/fifo.out || rbx_judge_error "mkfifo failed"

  # Contestant: run from /tmp/dir, stdout opened before stdin so the two FIFO
  # rendezvous pair up with the interactor's in the same order. pipe starts the
  # interactor with SIGPIPE ignored, so a contestant that leaves early surfaces
  # as a testlib verdict instead of killing it.
  /tmp/dir/pipe -i /tmp/fifo.in -o /tmp/fifo.out \
    -e /tmp/rbx-contestant.err -E /tmp/rbx-interactor.err -- \
    /bin/bash -c 'cd /tmp/dir && exec "$@" >/tmp/fifo.out </tmp/fifo.in' rbx "$@" = \
    /tmp/dir/arbitro /tmp/in /dev/null \
    >/tmp/rbx-pipe.log 2>/tmp/rbx-pipe.err
  local pipe_rc=$?

  local first sol int
  { read -r first; read -r sol; read -r int; } </tmp/rbx-pipe.log
  local message
  message="$(tail -c 8192 /tmp/rbx-interactor.err 2>/dev/null | grep -v '^[[:space:]]*$' | tail -n1 | tr '\r' ' ')"

  # -- report: everything below lands in MOJ's per-test log -------------------
  tail -c 8192 /tmp/rbx-interactor.err 2>/dev/null
  if [[ -s /tmp/rbx-contestant.err ]]; then
    echo "======== contestant stderr (last 40 lines)"
    tail -c 8192 /tmp/rbx-contestant.err | tail -n 40
  fi
  echo "DRIVER(rbx): pipe: first=${first:-?} contestant=${sol:-?} interactor=${int:-?}"
  [[ $pipe_rc == 0 && "$first" =~ ^[12]$ && "$sol" =~ ^[0-9]+$ && "$int" =~ ^[0-9]+$ ]] \
    || { cat /tmp/rbx-pipe.err; rbx_judge_error "pipe failed"; }

  # -- verdict ------------------------------------------------------------------
  local interactor_first=0 verdict eof=0 failed=0
  [[ $first == 2 ]] && interactor_first=1
  case "$int" in
    0) verdict=accepts ;;
    1 | 2 | 4 | 8) verdict=rejects ;; # _wa, _pe, _dirt, _unexpected_eof
    *) verdict=fails ;;               # _fail, _points, a crash, pipe.c's SIGTERM
  esac
  [[ $int == 8 || "$message" == *"Unexpected end of file"* ]] && eof=1
  # 141: SIGPIPE, a write into a pipe the interactor had already left -- no
  # failure. 143 after the interactor rejected first: pipe.c's own SIGTERM.
  if [[ $sol != 0 && $sol != 141 ]] && ! ((interactor_first && int != 0 && sol == 143)); then
    failed=1
  fi

  if [[ $verdict == fails ]]; then
    ((!interactor_first && failed)) && { echo "DRIVER(rbx): -> Runtime Error"; exit 3; }
    rbx_judge_error "the interactor failed: $message"
  fi
  if [[ $verdict == rejects ]] && ((!eof)); then
    printf 'WRONG %s\n' "$message" >/tmp/out
    echo "DRIVER(rbx): -> Wrong Answer"
    exit 0
  fi
  ((failed)) && { echo "DRIVER(rbx): -> Runtime Error"; exit 3; }
  if [[ $verdict == rejects ]]; then
    printf 'WRONG %s\n' "$message" >/tmp/out
    echo "DRIVER(rbx): -> Wrong Answer"
    exit 0
  fi
  printf 'OK %s\n' "$message" >/tmp/out
  echo "DRIVER(rbx): -> Accepted"
  exit 0
}
