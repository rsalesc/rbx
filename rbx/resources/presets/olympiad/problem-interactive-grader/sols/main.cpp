#include "guessing.h"

int find_secret(int n) {
  // Binary search: each guess either hits the secret number or halves the
  // remaining range, so at most ceil(log2(n + 1)) guesses are needed.
  int lo = 1, hi = n;
  while (true) {
    int mid = lo + (hi - lo) / 2;
    int r = guess(mid);
    if (r == 0) {
      return mid;
    } else if (r > 0) {
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
}
