#undef main

// ---------------------------------------------------------------------------
// rbx MOJ arbiter, EXPERIMENTAL supervisor (`rbx package moj --experimental`).
//
// mojtools' driver runs the arbiter between two FIFOs and decides the verdict
// from text files afterwards. With this epilogue, rbx's own run.sh execs the
// arbiter instead, as
//
//     arbitro <input> -- <contestant command...>
//
// and the arbiter starts both sides itself, the way BOCA's pipe.c does: the
// contestant (exec'd, in a process group of its own) and the interactor (this
// file's testlib code, in a forked child), crossed by two pipes. As the parent
// of both, it knows exactly how each one ended, and decides by CAUSE rather than
// by which one it happened to reap first -- a dying contestant closes its pipes
// before it is reapable, so the interactor's EOF can beat it to the reaper:
//
//   1. the interactor failed (crash, _fail, _points) -> judge error, unless the
//      contestant had already failed first (then RE)
//   2. the interactor rejected for any reason but EOF -> WA, and a contestant
//      still running is killed on the spot, so it cannot turn the WA into a TLE
//      (rsalesc/rbx#894)
//   3. the contestant failed (non-zero exit, or a signal other than SIGPIPE) ->
//      RE, whether the interactor then accepted or only complained about the
//      EOF the contestant left behind (rsalesc/rbx#895)
//   4. otherwise, the interactor's verdict.
//
// An EOF rejection waits a moment for the contestant before killing it: that
// rejection is the contestant leaving, and how it left is the verdict.
//
// It speaks MOJ's protocol: the verdict line goes to /tmp/out (`WRONG ...` is
// WA, any other line AC, nothing at all a judge error), and exit code 3 is a
// Runtime Error. Every judge-side failure exits 0 with /tmp/out empty, since a
// non-zero exit would blame the contestant. Limits (TLE, MLE) stay the
// judge's: build-and-test.sh decides them before it reads any of this.
// ---------------------------------------------------------------------------
#include <cerrno>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>
#include <fcntl.h>
#include <sys/resource.h>
#include <sys/time.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

namespace rbx_moj_supervisor {

// Overridable only so the supervisor can be exercised outside MOJ's jail.
static std::string path_of(const char *env, const char *fallback) {
  const char *value = std::getenv(env);
  return value != nullptr && *value != '\0' ? value : fallback;
}

static std::string read_file(const std::string &path) {
  std::string into;
  if (FILE *f = std::fopen(path.c_str(), "rb")) {
    char buf[1 << 16];
    size_t n;
    while ((n = std::fread(buf, 1, sizeof(buf), f)) > 0)
      into.append(buf, n);
    std::fclose(f);
  }
  return into;
}

// The last non-empty line of `text`, flattened so it survives MOJ's
// "last line" protocol.
static std::string last_line(const std::string &text) {
  std::string last, cur;
  for (char c : text + "\n") {
    if (c == '\n') {
      if (cur.find_first_not_of(" \t\r") != std::string::npos)
        last = cur;
      cur.clear();
    } else {
      cur += (c == '\r' ? ' ' : c);
    }
  }
  return last;
}

// The last `max_lines` lines of `text`.
static std::string tail(const std::string &text, int max_lines) {
  size_t end = text.size();
  if (end > 0 && text[end - 1] == '\n')
    end--;
  size_t start = end;
  for (int i = 0; i < max_lines && start > 0; i++) {
    size_t nl = text.rfind('\n', start - 1);
    start = nl == std::string::npos ? 0 : nl;
  }
  if (start > 0)
    start++;
  return text.substr(start, end - start);
}

static void redirect(int fd, const std::string &path) {
  int f = open(path.c_str(), O_WRONLY | O_CREAT | O_TRUNC, 0644);
  if (f >= 0) {
    dup2(f, fd);
    close(f);
  }
}

// /tmp/out is a bind mount of a file outside the jail: truncate it, never
// re-create it.
static void write_result(const std::string &line) {
  std::string out = path_of("RBX_MOJ_OUT", "/tmp/out");
  int fd = open(out.c_str(), O_WRONLY | O_TRUNC);
  if (fd < 0)
    fd = open(out.c_str(), O_WRONLY | O_CREAT | O_TRUNC, 0644);
  if (fd < 0)
    return;
  std::string text = line + "\n";
  ssize_t ignored = write(fd, text.data(), text.size());
  (void)ignored;
  close(fd);
}

static std::string describe(int status) {
  char buf[96];
  if (WIFSIGNALED(status)) {
    std::snprintf(buf, sizeof(buf), "killed by signal %d (%s)", WTERMSIG(status),
                  strsignal(WTERMSIG(status)));
  } else {
    std::snprintf(buf, sizeof(buf), "exited with code %d", WEXITSTATUS(status));
  }
  return buf;
}

static pid_t g_contestant = -1;
static pid_t g_interactor = -1;

// The time limit: the judge sends TERM to the jail. Take both sides down; the
// verdict is the judge's TLE, decided from the wall clock.
static void on_term(int) {
  if (g_contestant > 0)
    kill(-g_contestant, SIGKILL);
  if (g_interactor > 0)
    kill(g_interactor, SIGKILL);
  _exit(0);
}

// A failure on the judge's side: no result, exit 0, so compare.sh reports a
// judge error instead of blaming the contestant.
[[noreturn]] static void judge_error(const std::string &why) {
  std::fprintf(stderr, "DRIVER(rbx): judge error: %s\n", why.c_str());
  std::fflush(stderr);
  _exit(0);
}

// _exit, not return: testlib's static finalize guard must not get a say.
[[noreturn]] static void finish(int code, const char *verdict) {
  std::fprintf(stderr, "DRIVER(rbx): -> %s\n", verdict);
  std::fflush(nullptr);
  _exit(code);
}

enum InteractorVerdict { ACCEPTS, REJECTS, FAILS };

static InteractorVerdict classify(int status) {
  if (!WIFEXITED(status))
    return FAILS;
  switch (WEXITSTATUS(status)) {
  case 0: // _ok
    return ACCEPTS;
  case 1: // _wa
  case 2: // _pe
  case 4: // _dirt
  case 8: // _unexpected_eof
    return REJECTS;
  default: // _fail (3), _points (7), anything else
    return FAILS;
  }
}

// Whether a rejection only says the contestant's output ended: the same test
// rbx applies locally (`checkers._is_testlib_eof`).
static bool is_eof_rejection(int status, const std::string &message) {
  return (WIFEXITED(status) && WEXITSTATUS(status) == 8) ||
         message.find("Unexpected end of file") != std::string::npos;
}

// How long an EOF rejection waits for the contestant to finish dying.
static const int kEofGraceMs = 500;

// Reap `pid` if it ends within `ms` milliseconds.
static bool reap_within(pid_t pid, int ms, int *status, struct rusage *usage) {
  for (int waited = 0;; waited += 5) {
    pid_t got = wait4(pid, status, WNOHANG, usage);
    if (got == pid)
      return true;
    if (got < 0 && errno != EINTR)
      return false;
    if (waited >= ms)
      return false;
    usleep(5000);
  }
}

} // namespace rbx_moj_supervisor

int main(int argc, char *argv[]) {
  using namespace rbx_moj_supervisor;
  if (argc < 4 || std::strcmp(argv[2], "--") != 0)
    judge_error(std::string("usage: ") + argv[0] + " <input> -- <command...>");

  std::string tmp = path_of("RBX_MOJ_TMP", "/tmp");
  std::string interactor_err = tmp + "/rbx-interactor.err";
  std::string contestant_err = tmp + "/rbx-contestant.err";

  int to_contestant[2], to_interactor[2], exec_error[2];
  if (pipe(to_contestant) != 0 || pipe(to_interactor) != 0 || pipe(exec_error) != 0)
    judge_error(std::string("pipe: ") + std::strerror(errno));
  fcntl(exec_error[1], F_SETFD, FD_CLOEXEC);
  std::fflush(nullptr);

  g_contestant = fork();
  if (g_contestant < 0)
    judge_error(std::string("fork: ") + std::strerror(errno));
  if (g_contestant == 0) {
    // A group of its own, so a kill reaches whatever it spawned too.
    setpgid(0, 0);
    std::signal(SIGPIPE, SIG_DFL);
    dup2(to_contestant[0], 0);
    dup2(to_interactor[1], 1);
    redirect(2, contestant_err);
    close(to_contestant[0]);
    close(to_contestant[1]);
    close(to_interactor[0]);
    close(to_interactor[1]);
    close(exec_error[0]);
    execvp(argv[3], argv + 3);
    // Only reached when exec failed: tell the parent, which treats it as the
    // judge's problem rather than a contestant that exited 127.
    int err = errno;
    ssize_t ignored = write(exec_error[1], &err, sizeof(err));
    (void)ignored;
    _exit(127);
  }
  setpgid(g_contestant, g_contestant);
  close(exec_error[1]);

  g_interactor = fork();
  if (g_interactor < 0) {
    kill(-g_contestant, SIGKILL);
    judge_error(std::string("fork: ") + std::strerror(errno));
  }
  if (g_interactor == 0) {
    // A contestant that closes its end must surface as a testlib read error,
    // not kill the interactor.
    std::signal(SIGPIPE, SIG_IGN);
    dup2(to_interactor[0], 0);
    dup2(to_contestant[1], 1);
    redirect(2, interactor_err);
    close(to_contestant[0]);
    close(to_contestant[1]);
    close(to_interactor[0]);
    close(to_interactor[1]);
    close(exec_error[0]);
    // MOJ hands the arbiter only the input; testlib's output file goes nowhere.
    char out_path[] = "/dev/null";
    char *interactor_argv[] = {argv[0], argv[1], out_path, nullptr};
    int code;
    try {
      code = rbx_interactor_main(3, interactor_argv);
    } catch (exit_exception &e) {
      code = e.getExitCode();
    }
    std::cout.flush();
    std::fflush(nullptr);
    // _exit: testlib's static finalize guard must not get a say.
    _exit(code);
  }

  close(to_contestant[0]);
  close(to_contestant[1]);
  close(to_interactor[0]);
  close(to_interactor[1]);
  std::signal(SIGTERM, on_term);

  int exec_errno = 0;
  bool exec_failed = read(exec_error[0], &exec_errno, sizeof(exec_errno)) ==
                     (ssize_t)sizeof(exec_errno);
  close(exec_error[0]);

  int contestant_status = 0, interactor_status = 0;
  bool contestant_done = false, interactor_done = false;
  bool interactor_first = false, killed_by_us = false;
  struct rusage contestant_usage {};
  while (!contestant_done || !interactor_done) {
    int status;
    struct rusage usage {};
    pid_t pid = wait4(-1, &status, 0, &usage);
    if (pid < 0) {
      if (errno == EINTR)
        continue;
      break;
    }
    if (pid == g_contestant) {
      contestant_done = true;
      contestant_status = status;
      contestant_usage = usage;
      // Anything it left behind still holds the pipes open.
      kill(-g_contestant, SIGKILL);
    } else if (pid == g_interactor) {
      interactor_done = true;
      interactor_status = status;
      if (contestant_done)
        continue;
      interactor_first = true;
      InteractorVerdict early = classify(status);
      if (early == ACCEPTS)
        continue; // the contestant may still crash, or overrun the limit
      if (early == REJECTS &&
          is_eof_rejection(status, last_line(read_file(interactor_err))) &&
          reap_within(g_contestant, kEofGraceMs, &contestant_status, &contestant_usage)) {
        contestant_done = true;
        kill(-g_contestant, SIGKILL);
        continue;
      }
      // The interactor has decided; nothing the contestant does from here on
      // may change that (#894).
      kill(-g_contestant, SIGKILL);
      killed_by_us = true;
    }
  }
  if (exec_failed)
    judge_error(std::string("cannot run ") + argv[3] + ": " +
                std::strerror(exec_errno));
  if (!contestant_done || !interactor_done)
    judge_error("lost track of a process");

  // -- report: everything below lands in MOJ's per-test log ------------------
  std::string interactor_text = read_file(interactor_err);
  std::string contestant_text = read_file(contestant_err);
  std::string message = last_line(interactor_text);
  if (!interactor_text.empty())
    std::fprintf(stderr, "%s\n", interactor_text.c_str());
  if (!contestant_text.empty())
    std::fprintf(stderr, "======== contestant stderr (last 40 lines)\n%s\n",
                 tail(contestant_text, 40).c_str());
  double cpu = contestant_usage.ru_utime.tv_sec + contestant_usage.ru_stime.tv_sec +
               (contestant_usage.ru_utime.tv_usec + contestant_usage.ru_stime.tv_usec) / 1e6;
  std::fprintf(stderr, "Contestant CPU time (s): %.3f\n", cpu);
  std::fprintf(stderr, "Contestant peak memory (KB): %ld\n", contestant_usage.ru_maxrss);
  std::fprintf(stderr, "DRIVER(rbx): %s ended first; interactor %s; contestant %s%s\n",
               interactor_first ? "interactor" : "contestant",
               describe(interactor_status).c_str(), describe(contestant_status).c_str(),
               killed_by_us ? " (killed by the driver)" : "");

  // -- verdict -----------------------------------------------------------------
  InteractorVerdict verdict = classify(interactor_status);
  // A contestant killed by SIGPIPE wrote into a pipe the interactor had already
  // left: that write is no failure, the interactor's verdict stands.
  bool sigpiped = WIFSIGNALED(contestant_status) && WTERMSIG(contestant_status) == SIGPIPE;
  bool contestant_failed =
      !killed_by_us && !sigpiped &&
      (WIFSIGNALED(contestant_status) ||
       (WIFEXITED(contestant_status) && WEXITSTATUS(contestant_status) != 0));

  if (verdict == FAILS) {
    if (!interactor_first && contestant_failed)
      finish(3, "Runtime Error");
    judge_error("the interactor failed: " + message);
  }
  if (verdict == REJECTS && !is_eof_rejection(interactor_status, message)) {
    write_result("WRONG " + message);
    finish(0, "Wrong Answer");
  }
  if (contestant_failed)
    finish(3, "Runtime Error");
  if (verdict == REJECTS) {
    write_result("WRONG " + message);
    finish(0, "Wrong Answer");
  }
  write_result("OK " + message);
  finish(0, "Accepted");
}
