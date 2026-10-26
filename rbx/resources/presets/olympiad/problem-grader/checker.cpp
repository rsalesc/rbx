#include "testlib.h"
#include "rbx.h"
// A testlib checker for a problem with a grader. Docs:
// https://rsalesc.github.io/rbx/setters/grading/graders/
//
// Include testlib.h BEFORE rbx.h: the grader helpers need testlib.

int main(int argc, char *argv[]) {
  // Reads the test past its hidden header and the grader's output past its
  // frames. Everything after this line is plain testlib.
  rbx::registerGraderChecker(argc, argv);

  long long expected = ans.readLong();
  long long got = ouf.readLong();
  if (expected != got) {
    quitf(_wa, "expected %lld, got %lld", expected, got);
  }
  quitf(_ok, "%lld", got);
}
