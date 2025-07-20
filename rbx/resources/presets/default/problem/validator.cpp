#include "rbx.h"
#include "testlib.h"

using namespace std;

int main(int argc, char *argv[]) {
  registerValidation(argc, argv);
  prepareOpts(argc, argv);

  int MIN_N = getVar<int>("MIN_N"); // Read from package vars.
  int MAX_N = getVar<int>("MAX_N");

  inf.readInt(MIN_N, MAX_N, "A");
  inf.readSpace();
  inf.readInt(MIN_N, MAX_N, "B");
  inf.readEoln();
  inf.readEof();
}