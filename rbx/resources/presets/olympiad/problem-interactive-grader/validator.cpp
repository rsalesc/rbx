#include "rbx.h"
#include "testlib.h"
// A testlib validator. Docs: https://rsalesc.github.io/rbx/setters/testset/
//
// Validators run over the *interactor's* input file, not over what the
// solution reads from its stdin.

using namespace std;

int main(int argc, char *argv[]) {
  registerValidation(argc, argv);
  prepareOpts(argc, argv);

  int MIN_N = getVar<int>("N.min"); // Read from package vars.
  int MAX_N = getVar<int>("N.max");

  int N = inf.readInt(MIN_N, MAX_N, "N");
  inf.readSpace();
  inf.readInt(1, N, "S"); // The secret number lies in the search range.
  inf.readEoln();
  inf.readEof();
}
