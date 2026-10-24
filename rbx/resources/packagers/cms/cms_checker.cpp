// Runs an rbx/testlib checker as the last step of a CMS Communication
// manager (see cms_manager.cpp), reporting its verdict the way CMS expects.
//
// Called as `checker <input> <interactor output> <answer>`, exactly how rbx
// runs a legacy interactor's checker, with stdout and stderr still CMS's.
// Expects the problem's checker next to it as `check.cpp`.
#include "rbx_cms_report.h"
#include "testlib.h"

int rbx_checker_main(int argc, char *argv[]);

namespace rbx_cms_checker {

void report_at_exit() {
  std::string line = rbx_cms::read_verdict();
  rbx_cms::finish(rbx_cms::classify(line), line);
}

}  // namespace rbx_cms_checker

int main(int argc, char *argv[]) {
  rbx_cms::capture_verdict();
  atexit(rbx_cms_checker::report_at_exit);
  int code = rbx_checker_main(argc, argv);
  rbx_cms::returned = true;
  rbx_cms::return_code = code;
  exit(code);
}

#define main rbx_checker_main
#include "check.cpp"
#undef main
