#include "testlib.h"

using namespace std;

int main(int argc, char *argv[]) {
  registerValidation(argc, argv);
  prepareOpts(argc, argv);

  int MAX_N = opt<int>("MAX_N"); // Read from package vars.

  inf.readInt(1, MAX_N, "A");
  inf.readSpace();
  inf.readInt(1, MAX_N, "B");
  inf.readEoln();
  inf.readEof();
}