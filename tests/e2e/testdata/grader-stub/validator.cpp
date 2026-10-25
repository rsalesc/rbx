#include "testlib.h"
#include "rbx.h"

int main(int argc, char *argv[]) {
  registerValidation(argc, argv);
  int n = inf.readInt(1, getVar<int>("N.max"), "n");
  inf.readSpace();
  inf.readInt(1, n, "x");
  inf.readEoln();
  inf.readEof();
}
