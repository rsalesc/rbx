#include "testlib.h"

#include <string>

// Usage: gen <n> <max value> <seed> [rand|max|zero]
//
// The seed argument only makes otherwise-identical lines distinct tests; testlib
// seeds its generator from the whole argument list.
int main(int argc, char *argv[]) {
  registerGen(argc, argv, 1);
  int n = atoi(argv[1]);
  int maxv = atoi(argv[2]);
  std::string mode = argc > 4 ? argv[4] : "rand";

  printf("%d\n", n);
  for (int i = 0; i < n; i++) {
    int v = mode == "max" ? maxv : mode == "zero" ? 0 : rnd.next(0, maxv);
    printf(i == 0 ? "%d" : " %d", v);
  }
  printf("\n");
}
