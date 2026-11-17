#include "testlib.h"

int main(int argc, char *argv[]) {
  registerValidation(argc, argv);
  int k = inf.readInt(1, 200000, "K");
  inf.readEoln();
  for (int i = 0; i < k; i++) {
    inf.readInt(0, 1000000000, "v");
    inf.readEoln();
  }
  inf.readEof();
}
