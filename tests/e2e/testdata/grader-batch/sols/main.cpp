#include "sumgame.h"

long long sum_all(std::vector<long long> a) {
  long long s = 0;
  for (long long x : a) s += x;
  return s;
}
