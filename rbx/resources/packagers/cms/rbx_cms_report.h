// Turns a testlib program's verdict into a CMS manager result.
//
// CMS reads the outcome (a float in [0, 1]) from the first line of the
// manager's stdout and the message shown to the contestant from the first line
// of its stderr, and treats any non-zero exit as a judge error. testlib reports
// its verdict as a line on stderr, so that line is captured here and translated
// when the testlib program exits.
#pragma once

#include <fcntl.h>
#include <unistd.h>

#include <cstdio>
#include <string>

namespace rbx_cms {

inline int real_stdout = -1;
inline int real_stderr = -1;
inline int verdict_pipe[2] = {-1, -1};
// Set when the testlib program's main returns instead of calling quit().
inline bool returned = false;
inline int return_code = 0;

// Points stderr at a pipe, keeping the real stdout and stderr for the result.
// Must run before anything else takes over fds 1 and 2.
inline void capture_verdict() {
  real_stdout = dup(1);
  real_stderr = dup(2);
  if (pipe(verdict_pipe) == 0) {
    // Non-blocking: a verdict longer than the pipe must not hang the exit.
    fcntl(verdict_pipe[1], F_SETFL, O_NONBLOCK);
    dup2(verdict_pipe[1], 2);
  }
}

// The first line the testlib program wrote to stderr, e.g. "ok 3 queries".
inline std::string read_verdict() {
  fflush(stderr);
  close(2);
  close(verdict_pipe[1]);
  std::string text;
  char buf[4096];
  ssize_t k;
  while ((k = read(verdict_pipe[0], buf, sizeof buf)) > 0) text.append(buf, k);
  return text.substr(0, text.find('\n'));
}

enum class Verdict { kAccepted, kRejected, kJudgeError };

inline bool starts_with(const std::string &s, const char *prefix) {
  return s.rfind(prefix, 0) == 0;
}

// testlib's verdict lines: "ok", "wrong answer", "wrong output format",
// "unexpected eof", "FAIL" and "points". Partial points have no rbx meaning
// for interactive problems, so they are a judge error like FAIL.
inline Verdict classify(const std::string &line) {
  if (line.empty()) {
    return returned && return_code == 0 ? Verdict::kAccepted
                                        : Verdict::kJudgeError;
  }
  if (starts_with(line, "ok")) return Verdict::kAccepted;
  if (starts_with(line, "wrong answer") ||
      starts_with(line, "wrong output format") ||
      starts_with(line, "unexpected eof")) {
    return Verdict::kRejected;
  }
  return Verdict::kJudgeError;
}

// Writes the CMS result and exits. The contestant only ever sees CMS's stock
// messages: a checker comment can give away the answer.
[[noreturn]] inline void finish(Verdict verdict, const std::string &line) {
  if (verdict == Verdict::kJudgeError) {
    dprintf(real_stderr, "%s\n",
            line.empty() ? "testlib program gave no verdict" : line.c_str());
    _exit(1);
  }
  bool accepted = verdict == Verdict::kAccepted;
  dprintf(real_stdout, "%s\n", accepted ? "1.0" : "0.0");
  dprintf(real_stderr, "%s\n",
          accepted ? "translate:success" : "translate:wrong");
  _exit(0);
}

}  // namespace rbx_cms
