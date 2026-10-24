// A CMS Communication manager around an rbx/testlib interactor.
//
// CMS runs the manager as `manager <fifo from user> <fifo to user>`, with the
// test input in input.txt. The manager must speak through the fifos, print the
// outcome on stdout and exit 0 (see rbx_cms_report.h). It runs in a sandbox
// that allows a single process, so the interactor runs in this very process:
// its source, `interactor.cpp`, is compiled in below, called the way rbx calls
// it (`interactor <input> <output>`), and its verdict translated at exit.
//
// A legacy interactor's output is then graded by the problem's checker. When
// compiled with -DRBX_CMS_CHECKER="<path>", the checker runner built from
// cms_checker.cpp is embedded, and once the interactor accepts, this process
// becomes it (fexecve), with `checker <input> <interactor output> <answer>`.
// CMS never gives the manager the answer, so the stored test input carries it
// (see split_input).
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>

#include <csignal>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>

#include "rbx_cms_report.h"
#include "testlib.h"

#ifdef RBX_CMS_CHECKER
extern "C" const char rbx_cms_checker_start[];
extern "C" const char rbx_cms_checker_end[];
__asm__(
    ".section .rodata\n"
    ".global rbx_cms_checker_start\n"
    "rbx_cms_checker_start:\n"
    ".incbin \"" RBX_CMS_CHECKER "\"\n"
    ".global rbx_cms_checker_end\n"
    "rbx_cms_checker_end:\n"
    ".previous\n");
#endif

int rbx_interactor_main(int argc, char *argv[]);

namespace rbx_cms_manager {

const char kHeader[] = "RBX-CMS-INPUT ";

std::string input_path;
std::string output_path;
std::string answer_path;

int memfd_with(const char *name, const std::string &data) {
  int fd = memfd_create(name, 0);
  if (fd < 0) {
    perror("memfd_create");
    _exit(1);
  }
  size_t done = 0;
  while (done < data.size()) {
    ssize_t k = write(fd, data.data() + done, data.size() - done);
    if (k <= 0) {
      perror("write");
      _exit(1);
    }
    done += k;
  }
  return fd;
}

// testlib opens files by path, and an in-memory file is reachable by one.
std::string path_of(int fd) { return "/proc/self/fd/" + std::to_string(fd); }

// input.txt is either the test input as is, or, for problems with a checker,
// `RBX-CMS-INPUT <n> <m>\n` followed by n bytes of input and m of answer.
void split_input(std::string &input, std::string &answer) {
  std::ifstream file("input.txt", std::ios::binary);
  std::stringstream buffer;
  buffer << file.rdbuf();
  std::string data = buffer.str();
  answer.clear();
  if (data.rfind(kHeader, 0) != 0) {
    input = data;
    return;
  }
  size_t eol = data.find('\n');
  size_t n = 0, m = 0;
  if (eol == std::string::npos ||
      sscanf(data.c_str() + sizeof kHeader - 1, "%zu %zu", &n, &m) != 2 ||
      eol + 1 + n + m != data.size()) {
    dprintf(2, "malformed rbx test input header\n");
    _exit(1);
  }
  input = data.substr(eol + 1, n);
  answer = data.substr(eol + 1 + n, m);
}

void report_at_exit() {
  std::cout.flush();
  fflush(stdout);
  if (tout.is_open()) tout.close();
  // From here on the contestant reads EOF.
  close(0);
  close(1);
  std::string line = rbx_cms::read_verdict();
  rbx_cms::Verdict verdict = rbx_cms::classify(line);
#ifdef RBX_CMS_CHECKER
  if (verdict == rbx_cms::Verdict::kAccepted) {
    dup2(rbx_cms::real_stdout, 1);
    dup2(rbx_cms::real_stderr, 2);
    int checker = memfd_with(
        "checker", std::string(rbx_cms_checker_start,
                               rbx_cms_checker_end - rbx_cms_checker_start));
    char name[] = "checker";
    char *args[] = {name, input_path.data(), output_path.data(),
                    answer_path.data(), nullptr};
    fexecve(checker, args, environ);
    perror("fexecve");
    _exit(1);
  }
#endif
  rbx_cms::finish(verdict, line);
}

}  // namespace rbx_cms_manager

int main(int argc, char *argv[]) {
  using namespace rbx_cms_manager;
  if (argc < 3) {
    fprintf(stderr, "usage: %s <fifo from user> <fifo to user>\n", argv[0]);
    return 1;
  }
  // The contestant may leave early; that is a verdict, not a crash.
  signal(SIGPIPE, SIG_IGN);

  std::string input, answer;
  split_input(input, answer);
  input_path = path_of(memfd_with("input", input));
  output_path = path_of(memfd_with("output", ""));
  answer_path = path_of(memfd_with("answer", answer));

  // The contestant opens its stdin first, so the fifo to it must be opened
  // first too, or both sides block forever.
  int to_user = open(argv[2], O_WRONLY);
  int from_user = open(argv[1], O_RDONLY);
  if (to_user < 0 || from_user < 0) {
    perror("open fifo");
    return 1;
  }
  rbx_cms::capture_verdict();
  dup2(from_user, 0);
  dup2(to_user, 1);
  close(from_user);
  close(to_user);

  atexit(report_at_exit);
  char name[] = "interactor";
  char *args[] = {name, input_path.data(), output_path.data(), nullptr};
  int code = rbx_interactor_main(3, args);
  rbx_cms::returned = true;
  rbx_cms::return_code = code;
  exit(code);
}

#define main rbx_interactor_main
#include "interactor.cpp"
#undef main
