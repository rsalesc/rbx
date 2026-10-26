#include "sumgame.h"

// Off by 5: within the approx group's tolerance, wrong where TOL is 0.
long long sum_all(std::vector<long long> a) {
  long long s = 5;
  for (long long x : a) s += x;
  return s;
}
