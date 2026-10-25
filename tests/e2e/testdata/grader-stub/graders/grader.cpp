#include <cstdio>
#include <cstdlib>

#include "guess.h"

int ask(int y) {
  std::printf("? %d\n", y);
  std::fflush(stdout);
  int response;
  if (std::scanf("%d", &response) != 1) {
    std::exit(0);
  }
  return response;
}

int main() {
  int n;
  if (std::scanf("%d", &n) != 1) {
    return 0;
  }
  int guess = guess_number(n);
  std::printf("! %d\n", guess);
  std::fflush(stdout);
  return 0;
}
