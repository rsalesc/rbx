#include "testlib.h"

int main(int argc, char *argv[]) {
  registerGen(argc, argv, 1);
  int n = atoi(argv[1]);
  println(n);
  std::vector<long long> a(n);
  for (auto &x : a) x = rnd.next(-1000000000LL, 1000000000LL);
  println(a);
}
