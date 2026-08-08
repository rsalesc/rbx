#include "rbx.h"
#include "testlib.h"

using namespace std;

int main(int argc, char *argv[]) {
  registerValidation(argc, argv);
  prepareOpts(argc, argv);

  // Read from package vars.
  int MIN_N = getVar<int>("N.min");
  int MAX_N = getVar<int>("N.max");
  int MIN_A = getVar<int>("A.min");
  int MAX_A = getVar<int>("A.max");

  int n = inf.readInt(MIN_N, MAX_N, "N");
  inf.readEoln();
  for (int i = 0; i < n; i++) {
    if (i) inf.readSpace();
    inf.readInt(MIN_A, MAX_A, "A_i");
  }
  inf.readEoln();
  inf.readEof();
}
