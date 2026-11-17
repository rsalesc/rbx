#include <cstdio>
#include <cstdlib>
#include <string>

int main(int argc, char *argv[]) {
  int index = std::atoi(argv[1]);
  std::string noise(1000, 'x');
  long long v;
  while (std::scanf("%lld", &v) == 1 && v != -1) {
    std::fprintf(stderr, "process %d got %lld %s\n", index, v, noise.c_str());
    std::printf("%lld\n", v + index + 1);
    std::fflush(stdout);
  }
  return 0;
}
