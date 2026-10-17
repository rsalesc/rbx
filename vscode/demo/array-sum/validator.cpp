#include "testlib.h"

int main(int argc, char *argv[]) {
  registerValidation(argc, argv);

  int n = inf.readInt(1, 200000, "n");
  inf.readEoln();
  for (int i = 0; i < n; i++) {
    if (i > 0) {
      inf.readSpace();
    }
    inf.readInt(0, 1000000000, "a_i");
  }
  inf.readEoln();
  inf.readEof();
}
