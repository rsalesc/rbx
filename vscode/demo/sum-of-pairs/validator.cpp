#include "rbx.h"
#include "testlib.h"

// Reads its bounds from the package `vars` rather than hardcoding them, which
// is what makes the constraint-coverage table worth looking at: every group
// overrides `A.max`/`B.max` to its own ceiling, so each group is validated
// against different numbers and gets its own column instead of being merged
// into one.
//
// The two names passed to readInt -- "A" and "B" -- are the row labels in that
// table. testlib reports which of each variable's bounds a testcase touched,
// and rbx merges those per group.
int main(int argc, char *argv[]) {
  registerValidation(argc, argv);

  int A_MIN = getVar<int>("A.min");
  int A_MAX = getVar<int>("A.max");
  int B_MIN = getVar<int>("B.min");
  int B_MAX = getVar<int>("B.max");

  inf.readInt(A_MIN, A_MAX, "A");
  inf.readSpace();
  inf.readInt(B_MIN, B_MAX, "B");
  inf.readEoln();
  inf.readEof();
}
