#include "testlib.h"

#include <iostream>
#include <string>

// Writes `x`, then a line of `len` characters the solution may ignore, and
// only then reads the answer. A solution that answers early exits while this
// is still writing (issue #891).
int main(int argc, char *argv[]) {
  registerInteraction(argc, argv);
  int x = inf.readInt(), len = inf.readInt();
  std::cout << x << std::endl;
  std::cout << std::string(len, 'z') << std::endl;
  ouf.readToken("!", "op");
  int y = ouf.readInt();
  if (y != x + 1) quitf(_wa, "expected %d, got %d", x + 1, y);
  quitf(_ok, "ok");
}
