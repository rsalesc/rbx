#include <iostream>

#include "testlib.h"
#include "rbx.h"

int main(int argc, char *argv[]) {
  rbx::registerGraderInteraction(argc, argv);
  int n = inf.readInt();
  int x = inf.readInt();
  int limit = getVar<int>("Q");

  std::cout << n << std::endl;
  int queries = 0;
  while (true) {
    std::string op = ouf.readToken("[?!]", "op");
    int y = ouf.readInt(1, n, "y");
    if (op == "!") {
      if (y != x) {
        quitf(_wa, "guessed %d, the hidden number is %d", y, x);
      }
      quitf(_ok, "%d queries (group '%s', limit %d)", queries,
            rbx::getGroup().c_str(), limit);
    }
    if (++queries > limit) {
      quitf(_wa, "more than %d queries (group '%s')", limit,
            rbx::getGroup().c_str());
    }
    std::cout << (x < y ? -1 : x > y ? 1 : 0) << std::endl;
  }
}
