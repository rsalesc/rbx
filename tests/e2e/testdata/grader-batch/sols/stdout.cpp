#include <cstdio>

#include "sumgame.h"

// Correct, but writes to stdout: the grader's framing catches it.
long long sum_all(std::vector<long long> a) {
  long long s = 0;
  for (long long x : a) s += x;
  std::printf("%lld\n", s);
  return s;
}
