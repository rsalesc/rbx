#include "guess.h"

// Fine while the query limit is generous, too slow for the tight group.
int guess_number(int n) {
  for (int y = 1; y < n; y++) {
    if (ask(y) == 0) return y;
  }
  return n;
}
