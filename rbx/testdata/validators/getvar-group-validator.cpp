#include "rbx.h"
#include "testlib.h"

// Validates a single int against the bounds of the current test group.
//
// The bounds are read twice: from the tables generated into rbx.h (getVar) and
// from the command line rbx passes to the validator (opt). Both must resolve to
// the same group-effective values, otherwise the validation fails loudly.
//
// The no-default `opt<T>(key)` form is load-bearing: `opt(key, default)` (like
// `has_opt`) arms testlib's unused-opt check, which would then turn every var
// rbx injects and this validator does not read into a hard failure.

int main(int argc, char *argv[]) {
  registerValidation(argc, argv);
  prepareOpts(argc, argv);

  int minN = getVar<int>("N.min");
  int maxN = getVar<int>("N.max");

  int optMinN = opt<int>("N.min");
  int optMaxN = opt<int>("N.max");

  ensuref(minN == optMinN && maxN == optMaxN,
          "getVar bounds [%d, %d] disagree with command-line bounds [%d, %d]",
          minN, maxN, optMinN, optMaxN);

  inf.readInt(minN, maxN, "N");
  inf.readEoln();
  inf.readEof();
}
