#include <cstdio>

static int calls = 0;

int main() {
  long long v;
  while (std::scanf("%lld", &v) == 1 && v != -1) {
    int role = calls++ % 3;
    std::printf("%lld\n", v + role + 1);
    std::fflush(stdout);
  }
  return 0;
}
