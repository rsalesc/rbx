#include <cstdio>
#include <cstdlib>
#include <ctime>

int main(int argc, char *argv[]) {
  int index = std::atoi(argv[1]);
  bool burnt = false;
  long long v;
  while (std::scanf("%lld", &v) == 1 && v != -1) {
    if (!burnt) {
      burnt = true;
      volatile unsigned long long sink = 0;
      std::clock_t start = std::clock();
      while (std::clock() - start < CLOCKS_PER_SEC * 4 / 10) sink += 1;
    }
    std::printf("%lld\n", v + index + 1);
    std::fflush(stdout);
  }
  return 0;
}
