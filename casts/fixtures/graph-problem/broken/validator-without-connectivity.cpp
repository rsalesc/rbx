// A deliberately incomplete copy of the fixture's `validator.cpp`: it checks
// the format and the bounds, but never checks that the graph is connected.
//
// `unit-validator-failure` swaps this in before running `rbx unit`, so the
// recording shows what the docs promise -- `invalid_NOT_CONNECTED.in` sails
// through validation and the unit test reports VALID where INVALID was
// expected. Nothing else in the fixture uses it.
#include "testlib.h"
#include "rbx.h"

// The docs snippet leans on testlib pulling `std` into scope; with GCC 15 it
// does not, so the fixture spells the dependency out.
#include <vector>
using namespace std;

int main(int argc, char *argv[]) {
  registerValidation(argc, argv);
  int MIN_N = getVar<int>("N.min");
  int MAX_N = getVar<int>("N.max");

  int n = inf.readInt(MIN_N, MAX_N, "N");
  inf.readSpace();
  int m = inf.readInt(1, n * (n - 1) / 2, "M");
  inf.readEoln();

  vector<vector<int>> adj(n + 1);

  // Read all the M edges of the graph.
  for (int i = 0; i < m; i++) {
    int u = inf.readInt(1, n, "u");
    inf.readSpace();
    int v = inf.readInt(1, n, "v");
    inf.readEoln();

    adj[u].push_back(v);
    adj[v].push_back(u);
  }

  // The connectivity check that `validator.cpp` performs here is missing.

  inf.readEof();
}
