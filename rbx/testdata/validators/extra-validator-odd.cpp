#include "testlib.h"

int main(int argc, char *argv[]) {
  registerValidation(argc, argv);
  int x = inf.readInt();
  ensuref(x % 2 != 0, "x is even");
  inf.readEoln();
  inf.readEof();
  return 0;
}