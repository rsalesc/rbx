#undef main

// ---------------------------------------------------------------------------
// rbx MOJ arbiter entry point.
// ---------------------------------------------------------------------------
#include <csignal>
#include <cstdio>
#include <iostream>
#include <string>
#include <fcntl.h>
#include <unistd.h>

namespace rbx_moj_arbiter {

static const char *kStderrLog = "/tmp/rbx-interactor.err";

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

static std::string read_file(const char *path) {
  std::string into;
  if (FILE *f = std::fopen(path, "rb")) {
    char buf[1 << 16];
    size_t n;
    while ((n = std::fread(buf, 1, sizeof(buf), f)) > 0)
      into.append(buf, n);
    std::fclose(f);
  }
  return into;
}

} // namespace rbx_moj_arbiter

int main(int argc, char *argv[]) {
  using namespace rbx_moj_arbiter;
  // The contestant may close its end at any time; a write to a dead FIFO must
  // surface as EPIPE (and so as a testlib verdict), not kill the arbiter.
  std::signal(SIGPIPE, SIG_IGN);
  if (argc < 2) {
    std::fprintf(stderr, "rbx: usage: %s <input>\n", argv[0]);
    _exit(1);
  }

  // Capture what testlib writes to stderr while the interactor runs, so its
  // message can be repeated on the verdict line. The real stderr is MOJ's
  // arbiter log, and is restored before anything is reported.
  int log_fd = dup(2);
  int capture = open(kStderrLog, O_WRONLY | O_CREAT | O_TRUNC, 0600);
  if (capture >= 0) {
    dup2(capture, 2);
    close(capture);
  }

  // MOJ hands the arbiter only the input. testlib wants an output file too;
  // nothing reads it, so it goes nowhere.
  char out_path[] = "/dev/null";
  char *interactor_argv[] = {argv[0], argv[1], out_path, nullptr};
  int code;
  try {
    code = rbx_interactor_main(3, interactor_argv);
  } catch (exit_exception &e) {
    code = e.getExitCode();
  }

  // _exit below skips static destructors, so flush the interactor's streams
  // here (an interactor may have turned off stdio sync).
  std::cout.flush();
  std::fflush(nullptr);
  if (log_fd >= 0) {
    dup2(log_fd, 2);
    close(log_fd);
  }
  std::string err = read_file(kStderrLog);
  if (!err.empty())
    std::fprintf(stderr, "%s\n", err.c_str());
  std::string message = last_line(err);

  int status = 0;
  switch (code) {
  case 0: // _ok
    std::fprintf(stderr, "OK %s\n", message.c_str());
    break;
  case 1: // _wa
  case 2: // _pe
  case 4: // _dirt
  case 8: // _unexpected_eof
    std::fprintf(stderr, "WRONG %s\n", message.c_str());
    break;
  default: // _fail (3), _points (7), anything else: a judge error.
    std::fprintf(stderr, "rbx: interactor failed with exit code %d: %s\n", code,
                 message.c_str());
    status = 1;
  }
  std::fflush(nullptr);
  // _exit, not return: testlib's static finalize guard must not get a say once
  // the verdict is out.
  _exit(status);
}
