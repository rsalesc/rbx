#include "testlib.h"

int main(int argc, char *argv[]) {
  registerValidation(argc, argv);
  inf.readInt();
  inf.readEoln();
  inf.readEof();
  return 0;
}