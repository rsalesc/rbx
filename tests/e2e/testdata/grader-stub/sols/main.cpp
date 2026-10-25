#include "guess.h"

int guess_number(int n) {
  int lo = 1, hi = n;
  while (true) {
    int mid = lo + (hi - lo) / 2;
    int r = ask(mid);
    if (r == 0) return mid;
    if (r < 0) hi = mid - 1;
    else lo = mid + 1;
  }
}
