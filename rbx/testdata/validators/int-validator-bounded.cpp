#include "testlib.h"

int main(int argc, char *argv[]) {
  registerValidation(argc, argv);
  inf.readInt(1, 100, "x");
  inf.readEoln();
  inf.readEof();
  return 0;
}