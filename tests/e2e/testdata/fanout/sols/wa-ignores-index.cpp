#include <cstdio>

int main() {
  long long v;
  while (std::scanf("%lld", &v) == 1 && v != -1) {
    std::printf("%lld\n", v + 1);
    std::fflush(stdout);
  }
  return 0;
}
