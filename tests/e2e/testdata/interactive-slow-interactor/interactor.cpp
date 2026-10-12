#include "testlib.h"

#include <time.h>

#include <iostream>

// Spends `us` microseconds of its own CPU before each of `rounds` rounds, so the
// interaction is slow because of the interactor alone: the solution only waits
// (issue #893).
static void burn(long us) {
  timespec a, b;
  clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &a);
  volatile unsigned long long sink = 0;
  while (true) {
    for (int i = 0; i < 1000; i++) sink += i;
    clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &b);
    long elapsed =
        (b.tv_sec - a.tv_sec) * 1000000L + (b.tv_nsec - a.tv_nsec) / 1000;
    if (elapsed >= us) break;
  }
}

int main(int argc, char *argv[]) {
  registerInteraction(argc, argv);
  int rounds = inf.readInt();
  long us = inf.readInt();
  std::cout << rounds << std::endl;
  for (int r = 0; r < rounds; r++) {
    burn(us);
    int v = rnd.next(0, 1000000);
    std::cout << v << std::endl;
    if (ouf.readInt() != (v ^ 12345)) quitf(_wa, "round %d", r);
  }
  quitf(_ok, "%d rounds", rounds);
}
