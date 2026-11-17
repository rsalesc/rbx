#include "testlib.h"
#include "rbx.h"

// Each round the value visits processes 0..P-1 in order; process i must
// answer value + i + 1 (it learns i from argv[1]).
int main(int argc, char *argv[]) {
  rbx::registerFanoutInteraction(argc, argv);
  int p = rbx::fanout::count();
  int k = inf.readInt();
  for (int round = 0; round < k; round++) {
    long long v = inf.readLong();
    for (int i = 0; i < p; i++) {
      rbx::fanout::to(i) << v << std::endl;
      long long got = rbx::fanout::from(i).readLong();
      if (got != v + i + 1) {
        quitf(_wa, "round %d: process %d answered %lld to %lld, expected %lld",
              round, i, got, v, v + i + 1);
      }
      v = got;
    }
  }
  // Every process waits for its next value: -1 tells it to stop.
  for (int i = 0; i < p; i++) rbx::fanout::to(i) << -1 << std::endl;
  tout << "ok" << std::endl;
  quitf(_ok, "%d rounds through %d processes", k, p);
}
