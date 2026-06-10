#include "rbx.h"
#include "testlib.h"
// A testlib validator. Docs: https://rsalesc.github.io/rbx/setters/testset/

using namespace std;

int main(int argc, char *argv[]) {
  registerValidation(argc, argv);
  prepareOpts(argc, argv);

  int MIN_N = getVar<int>("N.min"); // Read from package vars.
  int MAX_N = getVar<int>("N.max");

  inf.readInt(MIN_N, MAX_N, "A");
  inf.readSpace();
  inf.readInt(MIN_N, MAX_N, "B");
  inf.readEoln();
  inf.readEof();
}