#include "rbx.h"
#include "testlib.h"

using namespace std;

// The input is a single integer N, within the bounds declared in
// problem.rbx.yml.
int main(int argc, char *argv[]) {
  registerValidation(argc, argv);

  int MIN_N = getVar<int>("N.min");
  int MAX_N = getVar<int>("N.max");

  inf.readInt(MIN_N, MAX_N, "N");
  inf.readEoln();
  inf.readEof();
}
