#include "testlib.h"
#include "rbx.h"

int main(int argc, char *argv[]) {
  rbx::registerGraderChecker(argc, argv);
  long long tol = getVar<long long>("TOL");
  long long expected = ans.readLong();
  long long got = ouf.readLong();
  if (std::llabs(expected - got) > tol) {
    quitf(_wa, "expected %lld, got %lld (group '%s', tolerance %lld)", expected,
          got, rbx::getGroup().c_str(), tol);
  }
  quitf(_ok, "group '%s', tolerance %lld", rbx::getGroup().c_str(), tol);
}
