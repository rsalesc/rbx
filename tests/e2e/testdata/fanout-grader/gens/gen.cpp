#include "testlib.h"
#include <cstdlib>

int main(int argc, char *argv[]) {
  registerGen(argc, argv, 1);
  int k = std::atoi(argv[1]);
  println(k);
  for (int i = 0; i < k; i++) println(rnd.next(0, 1000000000));
}
