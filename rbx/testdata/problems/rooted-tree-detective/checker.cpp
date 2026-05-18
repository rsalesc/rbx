#include "testlib.h"

// The interactor writes the number of queries the solution made to `tout`,
// which arrives here as `ouf`. `ans` carries the same value produced by the
// model solution. We enforce a global query limit.
int main(int argc, char *argv[]) {
  registerTestlibCmd(argc, argv);

  const int LIMIT = 200;

  int oufq = ouf.readInt();
  int ansq = ans.readInt();

  if (ansq > LIMIT)
    quitf(_fail, "model solution made %d queries, limit is %d", ansq, LIMIT);

  if (oufq > LIMIT)
    quitf(_wa, "solution made %d queries, limit is %d", oufq, LIMIT);

  int n = inf.readInt();
  quitf(_ok, "root of a %d-node tree found with %d queries", n, oufq);
}
