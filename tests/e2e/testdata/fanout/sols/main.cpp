#include <cstdio>
#include <cstdlib>

int main(int argc, char *argv[]) {
  int index = std::atoi(argv[1]);
  long long v;
  while (std::scanf("%lld", &v) == 1 && v != -1) {
    std::printf("%lld\n", v + index + 1);
    std::fflush(stdout);
  }
  return 0;
}
