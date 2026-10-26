#include "testlib.h"
#include "rbx.h"

int main(int argc, char *argv[]) {
  registerValidation(argc, argv);
  int n = inf.readInt(1, getVar<int>("N.max"), "n");
  inf.readEoln();
  for (int i = 0; i < n; i++) {
    inf.readLong(-1000000000LL, 1000000000LL, "a_i");
    if (i + 1 < n) inf.readSpace();
  }
  inf.readEoln();
  inf.readEof();
}
