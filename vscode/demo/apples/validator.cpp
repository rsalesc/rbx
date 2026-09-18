#include "testlib.h"

// Deliberately plainer than problem A's: hardcoded bounds and no `vars`, so no
// group overrides them. With nothing group-specific in the package, rbx reports
// one merged set of hit bounds rather than a column per group -- which is the
// other half of the coverage table's behaviour, and the half that would go
// untested if both problems declared vars.
//
// `1..100` against inputs of 1, 7, 8, 42 and 58: the minimum is hit by the
// sample, the maximum by nothing.
int main(int argc, char *argv[]) {
  registerValidation(argc, argv);

  inf.readInt(1, 100, "a");
  inf.readSpace();
  inf.readInt(1, 100, "b");
  inf.readEoln();
  inf.readEof();
}
